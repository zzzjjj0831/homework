import asyncio
import concurrent.futures
import hashlib
import json
import logging
import re
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import (
        create_mcp_http_client,
        streamable_http_client,
    )

    MCP_AVAILABLE = True
    MCP_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - only hit when the SDK is missing
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    create_mcp_http_client = None  # type: ignore[assignment]
    streamable_http_client = None  # type: ignore[assignment]
    MCP_AVAILABLE = False
    MCP_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


LOGGER = logging.getLogger(__name__)
CONFIG_FILENAME = ".mcp.json"
DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_CALL_TIMEOUT = 60.0
DEFAULT_MAX_FUNCTION_NAME_LENGTH = 64


class MCPError(Exception):
    pass


class MCPTimeoutError(MCPError):
    pass


class MCPManager:
    """Loads .mcp.json, discovers tools and forwards tool calls to MCP servers."""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        config_path: Optional[Path] = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        max_function_name_length: int = DEFAULT_MAX_FUNCTION_NAME_LENGTH,
        enabled: bool = True,
    ):
        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else Path.cwd().resolve()
        )
        self.config_path = (
            Path(config_path).expanduser().resolve()
            if config_path is not None
            else self.project_root / CONFIG_FILENAME
        )
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.max_function_name_length = max(8, int(max_function_name_length))
        self.enabled = bool(enabled)

        self.servers: Dict[str, Dict[str, Any]] = {}
        self.errors: Dict[str, str] = {}
        self._tool_defs: List[Dict[str, Any]] = []
        self._tool_map: Dict[str, Tuple[str, str]] = {}
        self._server_tools: Dict[str, List[str]] = {}
        self._used_names: set[str] = set()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._loading = False
        self._closed = False
        self._lock = threading.RLock()

        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.is_file():
            return
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.errors["config"] = (
                f"failed to read {self.config_path}: {self._describe_exception(exc)}"
            )
            return
        if not isinstance(raw, dict):
            self.errors["config"] = f"{self.config_path} must contain a JSON object"
            return

        servers = raw.get("mcpServers", raw.get("servers"))
        if not isinstance(servers, dict):
            self.errors["config"] = (
                f"{self.config_path} is missing a valid 'mcpServers' object"
            )
            return

        for name, config in servers.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(config, dict):
                self.errors[name] = "server configuration must be a JSON object"
                continue
            if config.get("disabled") is True:
                continue
            self.servers[name] = config

    def start(self) -> None:
        with self._lock:
            if self._started or self._closed:
                return
            self._started = True
            self._loading = self.enabled

        if not self.enabled:
            LOGGER.info("MCP is disabled in configuration")
            self._loading = False
            self._report_errors()
            return

        if not self.servers:
            if "config" not in self.errors:
                LOGGER.info("No MCP servers configured in %s", self.config_path)
            self._loading = False
            self._report_errors()
            return

        if not MCP_AVAILABLE:
            message = f"MCP SDK is not available ({MCP_IMPORT_ERROR})"
            with self._lock:
                for name in self.servers:
                    self.errors[name] = message
            self._loading = False
            self._report_errors()
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="jagent-mcp-client",
            daemon=True,
        )
        self._thread.start()

        try:
            results = self._run(
                self._discover_all(), timeout=self.connect_timeout + 5.0
            )
        except Exception as exc:
            message = self._describe_exception(exc)
            with self._lock:
                for name in self.servers:
                    self.errors.setdefault(name, message)
            LOGGER.debug("MCP discovery failed: %s", message)
        else:
            for name, outcome in zip(list(self.servers), results):
                if isinstance(outcome, BaseException):
                    message = self._describe_exception(outcome)
                    with self._lock:
                        self.errors[name] = message
                    LOGGER.debug("MCP server %s failed: %s", name, message)
                else:
                    self._register_tools(name, outcome)
        finally:
            with self._lock:
                self._loading = False
            self._report_errors()

    def _run_event_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _report_errors(self) -> None:
        with self._lock:
            items = list(self.errors.items())
        for name, message in items:
            LOGGER.debug("MCP server '%s' unavailable: %s", name, message)

    async def _discover_all(self) -> List[Any]:
        tasks = [
            self._discover_one(name, config)
            for name, config in self.servers.items()
        ]
        if not tasks:
            return []
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _discover_one(self, name: str, config: Dict[str, Any]) -> List[Any]:
        try:
            return await asyncio.wait_for(
                self._discover_server(name, config), timeout=self.connect_timeout
            )
        except asyncio.TimeoutError as exc:
            raise MCPTimeoutError(
                f"operation timed out after {self.connect_timeout:g}s"
            ) from exc

    def _run(self, coro, timeout: float):
        if self._loop is None:
            coro.close()
            raise MCPError("MCP client event loop is not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise MCPTimeoutError(f"operation timed out after {timeout:g}s") from exc

    async def _discover_server(self, name: str, config: Dict[str, Any]) -> List[Any]:
        async with AsyncExitStack() as stack:
            session = await self._open_session(stack, name, config)
            return await self._list_all_tools(session)

    @staticmethod
    async def _list_all_tools(session) -> List[Any]:
        tools: List[Any] = []
        cursor: Optional[str] = None
        seen_cursors = set()
        while True:
            if cursor:
                try:
                    from mcp import types

                    result = await session.list_tools(
                        params=types.PaginatedRequestParams(cursor=cursor)
                    )
                except TypeError:
                    result = await session.list_tools()
            else:
                result = await session.list_tools()

            tools.extend(getattr(result, "tools", []) or [])
            cursor = getattr(result, "next_cursor", None)
            if not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        return tools

    async def _open_session(self, stack: AsyncExitStack, name: str, config: Dict[str, Any]):
        kind = self._server_kind(config)
        if kind == "stdio":
            command = config.get("command")
            if not isinstance(command, str) or not command.strip():
                raise MCPError("stdio server requires a non-empty 'command'")
            args = config.get("args") or []
            if not isinstance(args, list):
                raise MCPError("'args' must be a list of strings")
            env = config.get("env")
            if env is not None and not isinstance(env, dict):
                raise MCPError("'env' must be an object")
            cwd = config.get("cwd") or str(self.project_root)
            params = StdioServerParameters(
                command=command,
                args=[str(arg) for arg in args],
                env={str(key): str(value) for key, value in env.items()}
                if env
                else None,
                cwd=str(Path(cwd).expanduser()),
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params)
            )
        elif kind == "streamable_http":
            url = config.get("url")
            if not isinstance(url, str) or not url.strip():
                raise MCPError("streamable_http server requires a non-empty 'url'")
            headers = config.get("headers")
            if headers is not None and not isinstance(headers, dict):
                raise MCPError("'headers' must be an object")
            http_client = create_mcp_http_client(
                headers={str(k): str(v) for k, v in headers.items()}
                if headers
                else None
            )
            await stack.enter_async_context(http_client)
            read_stream, write_stream = await stack.enter_async_context(
                streamable_http_client(url, http_client=http_client)
            )
        else:
            raise MCPError(f"unsupported MCP transport type: {kind}")

        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        return session

    @staticmethod
    def _server_kind(config: Dict[str, Any]) -> str:
        raw = config.get("type") or config.get("transport") or ""
        kind = str(raw).strip().lower().replace("-", "_")
        if kind in ("streamable_http", "streamablehttp", "http"):
            return "streamable_http"
        if kind in ("stdio", "command"):
            return "stdio"
        if kind:
            return kind
        return "streamable_http" if config.get("url") else "stdio"

    def _register_tools(self, server_name: str, tools: List[Any]) -> None:
        with self._lock:
            for tool in tools:
                original_name = getattr(tool, "name", None)
                if not isinstance(original_name, str) or not original_name:
                    LOGGER.debug(
                        "Ignoring MCP tool without a name from %s", server_name
                    )
                    continue
                exposed_name = self._allocate_tool_name(server_name, original_name)
                schema = self._normalize_schema(getattr(tool, "input_schema", None))
                description = (
                    getattr(tool, "description", None)
                    or getattr(tool, "title", None)
                    or f"MCP tool '{original_name}' provided by server '{server_name}'"
                )
                self._tool_defs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": exposed_name,
                            "description": description,
                            "parameters": schema,
                        },
                    }
                )
                self._server_tools.setdefault(server_name, []).append(original_name)

    def _allocate_tool_name(self, server_name: str, tool_name: str) -> str:
        server_part = self._sanitize_name(server_name, "server")
        tool_part = self._sanitize_name(tool_name, "tool")
        candidate = f"{server_part}__{tool_part}"
        if len(candidate) > self.max_function_name_length:
            digest = hashlib.sha1(
                f"{server_name}\0{tool_name}".encode("utf-8")
            ).hexdigest()[:8]
            prefix = f"{server_part}__"
            keep = self.max_function_name_length - len(prefix) - len(digest) - 1
            candidate = f"{prefix}{tool_part[:max(keep, 1)]}_{digest}"

        if candidate in self._used_names:
            digest = hashlib.sha1(
                f"{server_name}\0{tool_name}\0duplicate".encode("utf-8")
            ).hexdigest()[:8]
            keep = self.max_function_name_length - len(digest) - 1
            candidate = f"{candidate[:keep]}_{digest}"

        self._used_names.add(candidate)
        self._tool_map[candidate] = (server_name, tool_name)
        return candidate

    @staticmethod
    def _sanitize_name(value: str, fallback: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or "")).strip("_")
        return sanitized or fallback

    @staticmethod
    def _normalize_schema(schema: Any) -> Dict[str, Any]:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}
        result = dict(schema)
        result.setdefault("type", "object")
        if result.get("type") == "object":
            properties = result.get("properties")
            if not isinstance(properties, dict):
                result["properties"] = {}
            if not isinstance(result.get("required"), list):
                result.pop("required", None)
        return result

    def get_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._tool_defs)

    def get_errors(self) -> Dict[str, str]:
        with self._lock:
            return dict(self.errors)

    def is_mcp_tool(self, name: str) -> bool:
        with self._lock:
            return name in self._tool_map

    def is_loading(self) -> bool:
        with self._lock:
            return self._loading

    def add_error(self, name: str, message: str) -> None:
        with self._lock:
            self.errors[name] = str(message)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            servers: Dict[str, Dict[str, Any]] = {}
            for name in self.servers:
                if not self.enabled:
                    status = "disabled"
                elif self.errors.get(name):
                    status = "error"
                elif self._loading or not self._started:
                    status = "loading"
                else:
                    status = "connected"
                servers[name] = {
                    "status": status,
                    "tools": list(self._server_tools.get(name, [])),
                    "error": self.errors.get(name, ""),
                }
            return {
                "enabled": self.enabled,
                "available": MCP_AVAILABLE,
                "started": self._started,
                "loading": self._loading,
                "servers": servers,
                "errors": dict(self.errors),
                "config_path": str(self.config_path),
            }

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        with self._lock:
            mapping = self._tool_map.get(name)
            if mapping is None:
                return json.dumps(
                    {"error": "unknown MCP tool", "tool": name}, ensure_ascii=False
                )
            server_name, tool_name = mapping
            config = self.servers.get(server_name)
            error = self.errors.get(server_name, "")
            reachable = server_name in self._reachable_servers()

        if config is None:
            return json.dumps(
                {
                    "error": f"MCP server is not configured: {server_name}",
                    "server": server_name,
                    "tool": tool_name,
                },
                ensure_ascii=False,
            )
        if error and not reachable:
            return json.dumps(
                {
                    "error": f"MCP server is unavailable: {server_name}",
                    "server": server_name,
                    "tool": tool_name,
                    "detail": error,
                },
                ensure_ascii=False,
            )

        args = arguments if isinstance(arguments, dict) else {}
        timeout = self._call_timeout_for(config)
        try:
            result = self._run(
                self._call_server(server_name, config, tool_name, args), timeout
            )
        except Exception as exc:
            return json.dumps(
                {
                    "error": f"MCP tool call failed: {tool_name}",
                    "server": server_name,
                    "tool": tool_name,
                    "detail": self._describe_exception(exc),
                },
                ensure_ascii=False,
            )
        return self._format_result(result, server_name, tool_name)

    def _reachable_servers(self) -> set[str]:
        return {
            server
            for server, _tool in self._tool_map.values()
            if not self.errors.get(server)
        }

    def _call_timeout_for(self, config: Dict[str, Any]) -> float:
        value = config.get("timeout")
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return self.call_timeout

    async def _call_server(
        self,
        server_name: str,
        config: Dict[str, Any],
        tool_name: str,
        arguments: Dict[str, Any],
    ):
        async with AsyncExitStack() as stack:
            session = await self._open_session(stack, server_name, config)
            return await session.call_tool(tool_name, arguments)

    def _format_result(self, result: Any, server_name: str, tool_name: str) -> str:
        is_error = bool(
            getattr(result, "is_error", getattr(result, "isError", False))
        )
        structured = getattr(
            result,
            "structured_content",
            getattr(result, "structuredContent", None),
        )
        contents = getattr(result, "content", None) or []

        text_parts: List[str] = []
        other_parts: List[Dict[str, Any]] = []
        for item in contents:
            item_type = getattr(item, "type", None)
            if item_type is None and isinstance(item, dict):
                item_type = item.get("type")
            if item_type == "text":
                text = getattr(item, "text", None)
                if text is None and isinstance(item, dict):
                    text = item.get("text")
                if text:
                    text_parts.append(str(text))
            elif item_type == "image":
                other_parts.append(
                    {
                        "type": "image",
                        "mimeType": self._get(item, "mime_type", "mimeType"),
                        "note": "image content omitted",
                    }
                )
            elif item_type == "audio":
                other_parts.append(
                    {
                        "type": "audio",
                        "mimeType": self._get(item, "mime_type", "mimeType"),
                        "note": "audio content omitted",
                    }
                )
            elif item_type == "resource":
                resource = self._get(item, "resource")
                text = self._get(resource, "text")
                if text:
                    text_parts.append(str(text))
                else:
                    other_parts.append(
                        {
                            "type": "resource",
                            "uri": self._get(resource, "uri"),
                            "mimeType": self._get(resource, "mime_type", "mimeType"),
                            "note": "binary resource content omitted",
                        }
                    )
            elif item_type == "resource_link":
                other_parts.append(
                    {
                        "type": "resource_link",
                        "uri": self._get(item, "uri"),
                        "name": self._get(item, "name"),
                        "description": self._get(item, "description"),
                    }
                )
            else:
                other_parts.append(self._to_jsonable(item))

        text = "\n".join(text_parts)
        if is_error:
            payload: Dict[str, Any] = {
                "error": text or "MCP tool returned an error",
                "server": server_name,
                "tool": tool_name,
                "isError": True,
            }
            if structured is not None:
                payload["structuredContent"] = structured
            if other_parts:
                payload["content"] = other_parts
            return json.dumps(payload, ensure_ascii=False, default=str)

        if structured is not None:
            if text:
                return json.dumps(
                    {"content": text, "structuredContent": structured},
                    ensure_ascii=False,
                    default=str,
                )
            return json.dumps(structured, ensure_ascii=False, default=str)
        if text:
            return text
        if other_parts:
            return json.dumps({"content": other_parts}, ensure_ascii=False, default=str)
        return json.dumps(
            {"content": [], "note": "MCP tool returned an empty result"},
            ensure_ascii=False,
        )

    @staticmethod
    def _get(obj: Any, *names: str) -> Any:
        if obj is None:
            return None
        for name in names:
            if isinstance(obj, dict) and name in obj:
                return obj[name]
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump(by_alias=True, exclude_none=True)
            except TypeError:
                return value.model_dump()
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @classmethod
    def _describe_exception(cls, exc: BaseException) -> str:
        if isinstance(exc, BaseExceptionGroup):
            details = "; ".join(
                cls._describe_exception(item) for item in exc.exceptions
            )
            return f"{type(exc).__name__}: {details}"
        message = str(exc).strip()
        if not message:
            message = repr(exc)
        return f"{type(exc).__name__}: {message}"

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._loading = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._loop is not None:
            self._loop.close()
        self._loop = None
        self._thread = None

