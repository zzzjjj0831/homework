"""宠物医院 MCP server。

把 PetHospitalServer 的 REST 接口封装成 MCP 工具：
- 传输：默认 Streamable HTTP（127.0.0.1:8000/mcp），可用 MCP_TRANSPORT=stdio 切到本地进程管道
- 契约：参数带类型/范围/枚举约束（由 MCP SDK 依据函数签名生成 JSON Schema）
- 错误：统一返回 {ok: false, error: {code, message, ...}}，不透传上游 HTML/裸异常
- 工程：连接与读超时、失败重试（指数退避）、结构化调用日志（写 stderr，避免污染 stdio）
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT = 10.0
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
MAX_PAGE_SIZE = 100

LOGGER = logging.getLogger("pet_hospital_mcp")

# 上游允许排序的字段（与 PetHospitalServer/README.md 的 /api/v1/pets 文档一致）
SortBy = Literal["totalCost", "visitCount", "name", "ageMonths"]
Order = Literal["asc", "desc"]


def _configure_logging() -> None:
    """把调用日志写到 stderr。

    stdio 传输下 stdout 属于协议通道，任何 print/log 到 stdout 都会破坏帧，
    因此这里固定 stderr，并输出 key=value 形式的结构化日志。
    """
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(os.environ.get("PET_HOSPITAL_LOG_LEVEL", "INFO").upper())
    LOGGER.propagate = False


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


BASE_URL = os.environ.get("PET_HOSPITAL_URL", DEFAULT_BASE_URL).rstrip("/")
TIMEOUT = _env_float("PET_HOSPITAL_TIMEOUT", DEFAULT_TIMEOUT)
CONNECT_TIMEOUT = _env_float("PET_HOSPITAL_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT)
RETRIES = _env_int("PET_HOSPITAL_RETRIES", DEFAULT_RETRIES)

mcp = MCPServer(
    "pet-hospital",
    instructions=(
        "宠物医院数据查询。先运行 PetHospitalServer/pethospital.exe（默认 http://127.0.0.1:8080）"
        "再使用本服务器的工具。所有错误都以结构化 JSON 返回，code 字段可用于判断失败原因。"
    ),
)

# 需要回给模型的字段（不含病历与收费明细，控制上下文体积）
SUMMARY_FIELDS = (
    "id",
    "name",
    "species",
    "breed",
    "gender",
    "ageMonths",
    "ownerName",
    "ownerPhone",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
)


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return payload


def _build_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=True,
    )


def fetch_pets(params: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
    """查询 /api/v1/pets。

    client 参数用于测试注入（httpx.MockTransport），生产环境走默认连接池。
    """
    url = f"{BASE_URL}/api/v1/pets"
    owns_client = client is None
    http = client or _build_client()
    last_error: dict[str, Any] | None = None
    attempts = RETRIES + 1

    try:
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                response = http.get(url, params=params)
            except httpx.TimeoutException:
                last_error = _error(
                    "UPSTREAM_TIMEOUT",
                    f"调用宠物医院服务超时（>{TIMEOUT:g}s）",
                    url=url,
                    attempt=attempt,
                )
            except httpx.HTTPError as exc:
                last_error = _error(
                    "UPSTREAM_UNAVAILABLE",
                    f"无法连接宠物医院服务：{type(exc).__name__}",
                    url=url,
                    attempt=attempt,
                    hint="请先启动 PetHospitalServer/pethospital.exe",
                )
            else:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if response.status_code >= 500:
                    last_error = _error(
                        "UPSTREAM_HTTP_ERROR",
                        f"上游服务返回 {response.status_code}",
                        url=url,
                        status_code=response.status_code,
                        attempt=attempt,
                        elapsed_ms=elapsed_ms,
                    )
                elif response.status_code >= 400:
                    # 4xx 是确定性错误，重试无意义，直接返回
                    LOGGER.warning(
                        "tool=list_pets outcome=http_error status=%s elapsed_ms=%s attempt=%s",
                        response.status_code,
                        elapsed_ms,
                        attempt,
                    )
                    return _error(
                        "UPSTREAM_REJECTED",
                        f"上游服务拒绝了请求（HTTP {response.status_code}）",
                        status_code=response.status_code,
                        url=url,
                        hint="检查筛选参数取值是否为上游支持的格式",
                    )
                else:
                    return _parse_payload(response, elapsed_ms)

            LOGGER.warning(
                "tool=list_pets outcome=%s attempt=%s/%s",
                last_error["error"]["code"],
                attempt,
                attempts,
            )
            if attempt < attempts:
                time.sleep(min(0.2 * attempt, 1.0))
    finally:
        if owns_client:
            http.close()

    return last_error or _error("UPSTREAM_UNAVAILABLE", "调用上游服务失败")


def _parse_payload(response: httpx.Response, elapsed_ms: int) -> dict[str, Any]:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        LOGGER.error("tool=list_pets outcome=bad_payload elapsed_ms=%s", elapsed_ms)
        return _error(
            "UPSTREAM_BAD_PAYLOAD",
            "上游返回的不是合法 JSON（可能是 HTML 错误页）",
            status_code=response.status_code,
            body_prefix=response.text[:200],
        )

    data = body.get("data") if isinstance(body, dict) else None
    business_code = body.get("code") if isinstance(body, dict) else None
    if isinstance(business_code, int) and business_code >= 400:
        LOGGER.error(
            "tool=list_pets outcome=business_error code=%s elapsed_ms=%s",
            business_code,
            elapsed_ms,
        )
        return _error(
            "UPSTREAM_REJECTED",
            f"上游业务错误（code={business_code}）：{body.get('message') or '未提供原因'}",
            status_code=response.status_code,
            business_code=business_code,
        )
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        LOGGER.error("tool=list_pets outcome=unexpected_schema elapsed_ms=%s", elapsed_ms)
        return _error(
            "UPSTREAM_UNEXPECTED_SCHEMA",
            "上游返回结构缺少 data.items",
            keys=sorted(body.keys())[:10] if isinstance(body, dict) else [],
        )

    items = []
    for item in data["items"]:
        if isinstance(item, dict):
            items.append({key: item.get(key) for key in SUMMARY_FIELDS})

    LOGGER.info(
        "tool=list_pets outcome=ok total=%s returned=%s elapsed_ms=%s",
        data.get("total"),
        len(items),
        elapsed_ms,
    )
    return {
        "ok": True,
        "total": data.get("total"),
        "page": data.get("page"),
        "pageSize": data.get("pageSize"),
        "totalPages": data.get("totalPages"),
        "items": items,
    }


@mcp.tool(
    description=(
        "查询宠物医院的宠物档案列表：支持关键词跨字段检索、种类/医生/就诊状态筛选、"
        "排序与分页。返回精简摘要（不含病历与收费明细）。失败时返回 ok=false 与 error.code。"
    )
)
def list_pets(
    q: Annotated[str, Field(max_length=64, description="关键词，跨字段检索（名称/主人/病名等）")] = "",
    species: Annotated[str, Field(max_length=16, description="种类，例如 犬 / 猫")] = "",
    doctor: Annotated[str, Field(max_length=32, description="主治医生姓名")] = "",
    status: Annotated[str, Field(max_length=16, description="就诊状态，例如 就诊中 / 住院 / 已治愈")] = "",
    sortBy: Annotated[SortBy, Field(description="排序字段：totalCost(总花费)/visitCount(就诊次数)/name/ageMonths")] = "totalCost",
    order: Annotated[Order, Field(description="排序方向：asc 升序 / desc 降序")] = "desc",
    page: Annotated[int, Field(ge=1, le=10000, description="页码，从 1 开始")] = 1,
    pageSize: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE, description=f"每页条数，1-{MAX_PAGE_SIZE}")] = 10,
) -> dict[str, Any]:
    """GET /api/v1/pets 的 MCP 封装。

    所有参数都带类型与范围约束，非法取值会在协议层被拒绝；
    业务失败（超时/5xx/非 JSON）以结构化错误返回，不会抛出裸异常。
    """
    params = {
        key: value.strip()
        for key, value in {
            "q": q,
            "species": species,
            "doctor": doctor,
            "status": status,
            "sortBy": sortBy,
            "order": order,
        }.items()
        if key not in ("sortBy", "order") and value.strip()
    }
    params.update({"sortBy": sortBy, "order": order, "page": page, "pageSize": pageSize})

    return fetch_pets(params)


def main() -> None:
    _configure_logging()
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http").strip().lower()
    LOGGER.info(
        "server=pet-hospital starting transport=%s upstream=%s retries=%s",
        transport,
        BASE_URL,
        RETRIES,
    )
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    port = _env_int("MCP_PORT", 8000) or 8000
    mcp.run(transport="streamable-http", port=port)


if __name__ == "__main__":
    main()
