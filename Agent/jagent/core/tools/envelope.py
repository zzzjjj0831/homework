"""工具返回值信封：成功/失败统一为 JSON，失败带可机读的错误码。

模型看到的是结构化 JSON（ok / error.code / error.message），
而不是裸异常字符串，便于它自己判断"是参数错了还是要换个工具"。
"""

from __future__ import annotations

import json
from typing import Any


def ok(**fields: Any) -> str:
    payload: dict[str, Any] = {"ok": True}
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False, default=str)


def error_json(code: str, message: str, **details: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return json.dumps(payload, ensure_ascii=False, default=str)


class ToolError(Exception):
    """工具层可预期的失败：带错误码，由各工具捕获后转成结构化 JSON。"""

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_json(self) -> str:
        return error_json(self.code, self.message, **self.details)
