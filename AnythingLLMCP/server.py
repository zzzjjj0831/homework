"""AnythingLLM MCP server。

把 AnythingLLM 的 HTTP API 封装成 MCP 工具，覆盖四类能力：
1. 工作区管理：list_workspaces / get_workspace / create_workspace
2. 文档接入：list_documents / upload_document / add_raw_text
3. 向量化：update_embeddings
4. 检索问答：chat / vector_search

约定：
- 密钥只从环境变量 ANYTHINGLLM_API_KEY 读取，缺配置时返回 CONFIG_MISSING，不内置任何 Key
- 服务地址 ANYTHINGLLM_URL 可配置（默认 http://127.0.0.1:3001）
- 传输可用 MCP_TRANSPORT=stdio 或 streamable-http（默认，端口 MCP_PORT=8091）
- 失败统一返回 {ok: false, error: {code, message, ...}}；列表类工具支持 offset/limit 分页
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

DEFAULT_BASE_URL = "http://127.0.0.1:3001"
DEFAULT_TIMEOUT = 30.0
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_RETRIES = 2
MAX_UPLOAD_BYTES = 32 * 1024 * 1024

LOGGER = logging.getLogger("anythingllm_mcp")

ChatMode = Literal["chat", "query"]


def _configure_logging() -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(os.environ.get("ANYTHINGLLM_LOG_LEVEL", "INFO").upper())
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


BASE_URL = os.environ.get("ANYTHINGLLM_URL", DEFAULT_BASE_URL).rstrip("/")
TIMEOUT = _env_float("ANYTHINGLLM_TIMEOUT", DEFAULT_TIMEOUT)
CONNECT_TIMEOUT = _env_float("ANYTHINGLLM_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT)
RETRIES = _env_int("ANYTHINGLLM_RETRIES", DEFAULT_RETRIES)

mcp = MCPServer(
    "anythingllm",
    instructions=(
        "AnythingLLM 工作区/文档/向量化/检索问答。先启动 AnythingLLM 并在其设置里生成 API Key，"
        "再以环境变量 ANYTHINGLLM_URL、ANYTHINGLLM_API_KEY 启动本服务器。"
    ),
)


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return payload


def _api_key() -> str | None:
    key = (os.environ.get("ANYTHINGLLM_API_KEY") or "").strip()
    return key or None


def _make_client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        timeout=httpx.Timeout(TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=True,
    )


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """发起一次 API 调用。

    返回 (payload, error)：成功时 error 为 None，失败时 payload 为 None。
    """
    key = _api_key()
    if not key:
        return None, _error(
            "CONFIG_MISSING",
            "缺少 ANYTHINGLLM_API_KEY：请先在 AnythingLLM 设置中生成 API Key 并注入环境变量",
            env="ANYTHINGLLM_API_KEY",
            base_url=BASE_URL,
        )

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    owns_client = client is None
    http = client or _make_client()
    last_error: dict[str, Any] | None = None
    attempts = RETRIES + 1

    try:
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                response = http.request(
                    method,
                    path,
                    json=json_body,
                    files=files,
                    data=data,
                    params=params,
                    headers=headers,
                )
            except httpx.TimeoutException:
                last_error = _error(
                    "UPSTREAM_TIMEOUT",
                    f"AnythingLLM 请求超时（>{TIMEOUT:g}s）",
                    path=path,
                    attempt=attempt,
                )
            except httpx.HTTPError as exc:
                last_error = _error(
                    "UPSTREAM_UNAVAILABLE",
                    f"无法连接 AnythingLLM：{type(exc).__name__}",
                    path=path,
                    base_url=BASE_URL,
                    hint="确认 AnythingLLM 已启动且 ANYTHINGLLM_URL 正确",
                )
            else:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if response.status_code in (401, 403):
                    LOGGER.warning("%s %s outcome=auth_failed status=%s", method, path, response.status_code)
                    return None, _error(
                        "AUTH_FAILED",
                        "AnythingLLM 拒绝了该 API Key",
                        status_code=response.status_code,
                        hint="在 AnythingLLM → Settings → API Keys 重新生成并注入 ANYTHINGLLM_API_KEY",
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = _error(
                        "UPSTREAM_HTTP_ERROR",
                        f"AnythingLLM 返回 {response.status_code}",
                        path=path,
                        status_code=response.status_code,
                        attempt=attempt,
                        elapsed_ms=elapsed_ms,
                    )
                elif response.status_code >= 400:
                    detail = _safe_detail(response)
                    LOGGER.warning(
                        "%s %s outcome=rejected status=%s", method, path, response.status_code
                    )
                    return None, _error(
                        "UPSTREAM_REJECTED",
                        f"AnythingLLM 拒绝了请求（HTTP {response.status_code}）：{detail}",
                        status_code=response.status_code,
                        path=path,
                    )
                else:
                    payload, parse_error = _parse(response)
                    if parse_error is not None:
                        return None, parse_error
                    LOGGER.info("%s %s outcome=ok elapsed_ms=%s", method, path, elapsed_ms)
                    return payload, None

            if attempt < attempts:
                time.sleep(min(0.2 * attempt, 1.0))
    finally:
        if owns_client:
            http.close()

    return None, last_error or _error("UPSTREAM_UNAVAILABLE", "请求 AnythingLLM 失败")


def _safe_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text[:200]
    if isinstance(body, dict):
        for key in ("error", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return str(body)[:300]


def _parse(response: httpx.Response) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return None, _error(
            "UPSTREAM_BAD_PAYLOAD",
            "AnythingLLM 返回的不是合法 JSON",
            status_code=response.status_code,
            body_prefix=response.text[:200],
        )
    if not isinstance(body, dict):
        return None, _error("UPSTREAM_BAD_PAYLOAD", "AnythingLLM 返回结构不是对象")
    return body, None


def _paginate(items: list[Any], offset: int, limit: int) -> dict[str, Any]:
    total = len(items)
    window = items[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "items": window,
    }


# --------------------------------------------------------------------------- #
# 1. 工作区管理
# --------------------------------------------------------------------------- #
@mcp.tool(description="列出 AnythingLLM 的全部工作区（名称、slug、创建时间），支持 offset/limit 分页")
def list_workspaces(
    offset: Annotated[int, Field(ge=0, description="跳过前 N 个")] = 0,
    limit: Annotated[int, Field(ge=1, le=100, description="本次返回条数，1-100")] = 20,
) -> dict[str, Any]:
    payload, error = _request("GET", "/api/v1/workspaces")
    if error:
        return error
    workspaces = payload.get("workspaces") if payload else None
    if not isinstance(workspaces, list):
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 workspaces 数组")
    items = [
        {
            "name": ws.get("name"),
            "slug": ws.get("slug"),
            "createdAt": ws.get("createdAt"),
            "chatProvider": ws.get("chatProvider"),
        }
        for ws in workspaces
        if isinstance(ws, dict) and ws.get("slug")
    ]
    return {"ok": True, **_paginate(items, offset, limit)}


@mcp.tool(description="读取单个工作区的详情（包含已挂载的文档名列表）")
def get_workspace(
    slug: Annotated[str, Field(min_length=1, max_length=128, description="工作区 slug")],
) -> dict[str, Any]:
    payload, error = _request("GET", f"/api/v1/workspace/{slug}")
    if error:
        return error
    workspace = payload.get("workspace") if payload else None
    if not isinstance(workspace, list) or not workspace or not isinstance(workspace[0], dict):
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 workspace 数组", slug=slug)
    info = workspace[0]
    documents = info.get("documents") or []
    return {
        "ok": True,
        "slug": info.get("slug", slug),
        "name": info.get("name"),
        "documentCount": len(documents) if isinstance(documents, list) else 0,
        "documents": [
            {"title": doc.get("title"), "docpath": doc.get("docpath")}
            for doc in documents
            if isinstance(doc, dict)
        ][:200],
    }


@mcp.tool(description="新建一个 AnythingLLM 工作区；名称重复时返回 UPSTREAM_REJECTED")
def create_workspace(
    name: Annotated[str, Field(min_length=1, max_length=64, description="新工作区名称")],
) -> dict[str, Any]:
    payload, error = _request("POST", "/api/v1/workspace/new", json_body={"name": name})
    if error:
        return error
    workspace = payload.get("workspace") if payload else None
    if not isinstance(workspace, dict):
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 workspace 对象", name=name)
    return {
        "ok": True,
        "name": workspace.get("name", name),
        "slug": workspace.get("slug"),
        "created": True,
    }


# --------------------------------------------------------------------------- #
# 2. 文档接入
# --------------------------------------------------------------------------- #
@mcp.tool(description="列出 AnythingLLM 已入库的文档（标题/来源/词数），支持 offset/limit 分页")
def list_documents(
    offset: Annotated[int, Field(ge=0, description="跳过前 N 个")] = 0,
    limit: Annotated[int, Field(ge=1, le=100, description="本次返回条数，1-100")] = 20,
) -> dict[str, Any]:
    payload, error = _request("GET", "/api/v1/documents")
    if error:
        return error
    local_files = (payload or {}).get("localFiles")
    if isinstance(local_files, dict):
        entries = [value for value in local_files.values() if isinstance(value, dict)]
    elif isinstance(local_files, list):
        entries = [value for value in local_files if isinstance(value, dict)]
    else:
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 localFiles")
    items = [
        {
            "title": entry.get("title") or entry.get("name"),
            "docSource": entry.get("docSource"),
            "wordCount": entry.get("wordCount"),
            "tokenEstimate": entry.get("token_count_estimate"),
        }
        for entry in entries
    ]
    return {"ok": True, **_paginate(items, offset, limit)}


@mcp.tool(
    description=(
        "把本地文件上传到 AnythingLLM 文档库（multipart）。上传后需再用 update_embeddings "
        "挂载到工作区才会被检索到。"
    )
)
def upload_document(
    file_path: Annotated[str, Field(min_length=1, description="本地文件绝对或相对路径")],
    add_to_workspaces: Annotated[str, Field(description="可选，逗号分隔的工作区 slug，上传后直接向量化")] = "",
) -> dict[str, Any]:
    path = Path(file_path).expanduser()
    if not path.is_file():
        return _error("INVALID_ARGUMENT", f"文件不存在：{file_path}", file_path=file_path)
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        return _error(
            "INVALID_ARGUMENT",
            f"文件过大（{size} 字节），上限 {MAX_UPLOAD_BYTES} 字节",
            file_path=file_path,
        )

    workspaces = [item.strip() for item in add_to_workspaces.split(",") if item.strip()]
    form = {"addToWorkspaces": ",".join(workspaces)} if workspaces else None
    try:
        with path.open("rb") as handle:
            files = {"file": (path.name, handle, "application/octet-stream")}
            payload, error = _request(
                "POST", "/api/v1/document/upload", files=files, data=form
            )
    except OSError as exc:
        return _error("IO_ERROR", f"读取文件失败：{exc}", file_path=file_path)

    if error:
        return error
    documents = (payload or {}).get("documents")
    if not isinstance(documents, list) or not documents:
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "上传响应缺少 documents 数组")
    return {
        "ok": True,
        "uploaded": len(documents),
        "documents": [
            {
                "title": doc.get("title") or doc.get("name"),
                "location": doc.get("location"),
                "wordCount": doc.get("wordCount"),
                "tokenEstimate": doc.get("token_count_estimate"),
            }
            for doc in documents
            if isinstance(doc, dict)
        ],
    }


@mcp.tool(description="直接把一段纯文本写入 AnythingLLM 文档库（无需先落盘成文件）")
def add_raw_text(
    text: Annotated[str, Field(min_length=1, max_length=200000, description="要入库的文本内容")],
    title: Annotated[str, Field(min_length=1, max_length=128, description="文档标题")] = "raw-text",
    add_to_workspaces: Annotated[str, Field(description="可选，逗号分隔的工作区 slug")] = "",
) -> dict[str, Any]:
    workspaces = [item.strip() for item in add_to_workspaces.split(",") if item.strip()]
    payload, error = _request(
        "POST",
        "/api/v1/document/raw-text",
        json_body={"textContent": text, "addToWorkspaces": ",".join(workspaces)},
    )
    if error:
        return error
    document = (payload or {}).get("document")
    if not isinstance(document, dict):
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 document 对象")
    return {
        "ok": True,
        "title": title,
        "location": document.get("location"),
        "wordCount": document.get("wordCount"),
    }


# --------------------------------------------------------------------------- #
# 3. 向量化
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "把文档挂载/卸载到指定工作区并触发向量化（adds 为上传返回的 location，"
        "deletes 为要移除的文档名）。"
    )
)
def update_embeddings(
    slug: Annotated[str, Field(min_length=1, max_length=128, description="工作区 slug")],
    adds: Annotated[str, Field(description="逗号分隔的文档 location（upload_document 的返回值）")] = "",
    deletes: Annotated[str, Field(description="逗号分隔的要移除的文档名")] = "",
) -> dict[str, Any]:
    added = [item.strip() for item in adds.split(",") if item.strip()]
    removed = [item.strip() for item in deletes.split(",") if item.strip()]
    if not added and not removed:
        return _error("INVALID_ARGUMENT", "adds 与 deletes 不能同时为空")
    payload, error = _request(
        "POST",
        f"/api/v1/workspace/{slug}/update-embeddings",
        json_body={"adds": added, "deletes": removed},
    )
    if error:
        return error
    workspace = (payload or {}).get("workspace")
    embedded = workspace.get("documents") if isinstance(workspace, dict) else None
    return {
        "ok": True,
        "slug": slug,
        "added": len(added),
        "deleted": len(removed),
        "workspaceDocumentCount": len(embedded) if isinstance(embedded, list) else None,
    }


# --------------------------------------------------------------------------- #
# 4. 检索问答
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "在指定工作区里对大模型提问。mode=chat 保留会话上下文，mode=query 只做单轮 RAG；"
        "返回回答正文、引用的来源片段与 sessionId。"
    )
)
def chat(
    slug: Annotated[str, Field(min_length=1, max_length=128, description="工作区 slug")],
    message: Annotated[str, Field(min_length=1, max_length=8000, description="用户问题")],
    mode: Annotated[ChatMode, Field(description="chat=保留会话上下文 / query=单轮检索问答")] = "chat",
    session_id: Annotated[str, Field(description="可选，续用已有会话以保持多轮上下文")] = "",
) -> dict[str, Any]:
    body: dict[str, Any] = {"message": message, "mode": mode}
    if session_id:
        body["sessionId"] = session_id
    payload, error = _request("POST", f"/api/v1/workspace/{slug}/chat", json_body=body)
    if error:
        return error

    text = (payload or {}).get("textResponse")
    if not isinstance(text, str):
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 textResponse 字段")
    sources = (payload or {}).get("sources") or []
    return {
        "ok": True,
        "slug": slug,
        "mode": mode,
        "text": text.strip(),
        "sessionId": (payload or {}).get("id"),
        "sources": [
            {
                "title": source.get("title"),
                "url": source.get("url"),
                "score": source.get("score"),
            }
            for source in sources
            if isinstance(source, dict)
        ][:20],
    }


@mcp.tool(
    description="在工作区里做纯向量检索（不经过大模型），返回最相关的文本分块与相似度分数"
)
def vector_search(
    slug: Annotated[str, Field(min_length=1, max_length=128, description="工作区 slug")],
    query: Annotated[str, Field(min_length=1, max_length=2000, description="检索语句")],
    top_n: Annotated[int, Field(ge=1, le=20, description="返回条数，1-20")] = 5,
    similarity_threshold: Annotated[float, Field(ge=0.0, le=1.0, description="最低相似度 0-1")] = 0.25,
) -> dict[str, Any]:
    payload, error = _request(
        "POST",
        f"/api/v1/workspace/{slug}/vector-search",
        json_body={"query": query, "topN": top_n, "similarityThreshold": similarity_threshold},
    )
    if error:
        return error
    results = (payload or {}).get("results")
    if not isinstance(results, list):
        return _error("UPSTREAM_UNEXPECTED_SCHEMA", "响应缺少 results 数组", slug=slug)
    chunks = []
    for item in results[:top_n]:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or ""
        chunks.append(
            {
                "score": item.get("score"),
                "text": text[:1200],
                "truncated": len(text) > 1200,
            }
        )
    return {"ok": True, "slug": slug, "query": query, "chunks": chunks}


def main() -> None:
    _configure_logging()
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http").strip().lower()
    LOGGER.info(
        "server=anythingllm starting transport=%s base_url=%s key_configured=%s",
        transport,
        BASE_URL,
        bool(_api_key()),
    )
    if not _api_key():
        LOGGER.warning(
            "ANYTHINGLLM_API_KEY 未设置：工具会返回 CONFIG_MISSING，请配置后重启"
        )
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    port = _env_int("MCP_PORT", 8091) or 8091
    mcp.run(transport="streamable-http", port=port)


if __name__ == "__main__":
    main()
