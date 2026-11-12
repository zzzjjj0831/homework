"""工具注册表：集中声明工具契约（JSON Schema）并分发到具体实现。

约定：
- 每个工具都有 type/description/parameters，参数带类型、范围、枚举与默认值，
  让模型能稳定选对工具、传对参数
- 分发统一经过 PathPolicy（文件边界）与耗时/结果日志
- 未知工具、内部异常都返回结构化 JSON，而不是抛出异常打断主循环
"""

from __future__ import annotations

import json
import logging
import time

from . import cli_ops, file_ops, web_ops
from .paths import PathPolicy

LOGGER = logging.getLogger("jagent.tools")


class ToolRegistry:
    def __init__(
        self,
        config=None,
        skill_manager=None,
        mcp_manager=None,
        context_manager=None,
    ):
        self.config = config
        self.skill_manager = skill_manager
        self.mcp_manager = mcp_manager
        self.context_manager = context_manager
        if config is not None:
            self.policy = PathPolicy(
                config.get_workspace_root(), config.get_allow_outside_workspace()
            )
        else:
            self.policy = PathPolicy()
        self.tools_def = [
            {
                "type": "function",
                "function": {
                    "name": "get_date",
                    "description": "获取当前电脑的日期与时间（本地时区，含星期与时区偏移）",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "is_leap_year",
                    "description": "判断给定年份是否为闰年（能被 4 整除，整百年需被 400 整除）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "year": {
                                "type": "integer",
                                "description": "要判断的年份",
                                "minimum": -4712,
                                "maximum": 9999,
                            }
                        },
                        "required": ["year"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_working_directory",
                    "description": "获取当前进程的工作目录路径",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "列出指定目录下的文件与子目录（含类型与大小），默认当前工作区根目录",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "目录路径，绝对路径或相对工作区根目录的路径",
                                "default": ".",
                            }
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_file_type",
                    "description": "判断路径是文件、目录还是链接，并返回扩展名",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件或目录路径"}
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_file_content",
                    "description": (
                        "读取 UTF-8 文本文件内容，支持分段读取：返回 content 与 next_offset，"
                        "文件过大时用 next_offset 继续读"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件路径"},
                            "offset": {
                                "type": "integer",
                                "description": "起始字符偏移，默认 0",
                                "minimum": 0,
                                "default": 0,
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "本次最多返回多少字符，默认 20000",
                                "minimum": 200,
                                "maximum": 200000,
                                "default": 20000,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_file",
                    "description": "创建文本文件；目标已存在时默认拒绝，需覆盖要显式传 overwrite=true",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dir_path": {
                                "type": "string",
                                "description": "目标目录（不存在会自动创建多级）",
                            },
                            "file_name": {
                                "type": "string",
                                "description": "纯文件名，不能包含路径分隔符",
                            },
                            "content": {"type": "string", "description": "文件内容", "default": ""},
                            "overwrite": {
                                "type": "boolean",
                                "description": "目标已存在时是否覆盖，默认 false",
                                "default": False,
                            },
                        },
                        "required": ["dir_path", "file_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "编辑文本文件：mode=replace 整体覆盖写入，mode=append 追加到末尾",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件路径"},
                            "content": {"type": "string", "description": "要写入的内容"},
                            "mode": {
                                "type": "string",
                                "enum": ["replace", "append"],
                                "description": "写入方式，默认 replace",
                                "default": "replace",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_directory",
                    "description": "创建目录（自动创建多级父目录）；已存在时返回 DIR_EXISTS",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "要创建的目录路径"}
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_directory",
                    "description": (
                        "删除目录：默认只能删空目录；recursive=true 递归删除非空目录；"
                        "必须带 confirm=true 表示已确认，否则返回 CONFIRM_REQUIRED"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "目录路径"},
                            "recursive": {
                                "type": "boolean",
                                "description": "是否递归删除非空目录，默认 false",
                                "default": False,
                            },
                            "confirm": {
                                "type": "boolean",
                                "description": "确认执行破坏性操作，默认 false",
                                "default": False,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_file",
                    "description": "删除文件；必须带 confirm=true 表示已确认，否则返回 CONFIRM_REQUIRED",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件路径"},
                            "confirm": {
                                "type": "boolean",
                                "description": "确认执行破坏性操作，默认 false",
                                "default": False,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rename_path",
                    "description": "重命名或移动文件/目录；目标已存在则拒绝；必须带 confirm=true",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "old_path": {"type": "string", "description": "原路径"},
                            "new_path": {"type": "string", "description": "新路径"},
                            "confirm": {
                                "type": "boolean",
                                "description": "确认执行破坏性操作，默认 false",
                                "default": False,
                            },
                        },
                        "required": ["old_path", "new_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "loadSkill",
                    "description": "按需加载指定 Skill 的完整说明（SKILL.md），或加载该 Skill 目录内的附件文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Skill 名称"},
                            "filename": {
                                "type": "string",
                                "description": "可选，Skill 目录内的附件相对路径",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "createSkill",
                    "description": (
                        "创建新的 Agent Skill：在 .agents/skills/ 下创建规范化名称的目录和带 YAML frontmatter 的 SKILL.md；"
                        "名称非法/重复/已存在时拒绝覆盖"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Skill 名称，小写字母/数字/连字符，例如 my-skill",
                                "maxLength": 64,
                            },
                            "skillContext": {
                                "type": "string",
                                "description": "SKILL.md 的完整内容（可含 YAML frontmatter；工具会保证 name/description 正确）",
                            },
                        },
                        "required": ["name", "skillContext"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "RunCli",
                    "description": "调用本地命令行程序，返回标准输出、标准错误与退出码（带超时与输出截断）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "程序名或路径，例如 python、git",
                            },
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "参数列表，例如 [\"--version\"]",
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fetchWeb",
                    "description": "抓取网页正文并转成 Markdown（自动去掉导航、广告、页脚）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "网页地址，仅支持 http/https",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "searchWeb",
                    "description": "调用百度千帆搜索 API 检索互联网信息，返回摘要与来源链接",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "搜索关键词，建议不超过 72 字符",
                                "maxLength": 200,
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "recallContext",
                    "description": "检索已压缩归档的历史对话原文（压缩摘要丢失细节时使用）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "可选，归档编号，例如 20261022-153000；不填检索全部归档",
                            },
                            "text": {
                                "type": "string",
                                "description": "要查找的关键词或文本片段",
                                "minLength": 1,
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
        ]

    def get_tools(self):
        tools = list(self.tools_def)
        if self.mcp_manager is not None:
            tools.extend(self.mcp_manager.get_tools())
        return tools

    # ------------------------------------------------------------------ #
    # 分发
    # ------------------------------------------------------------------ #
    def call(self, name: str, args: dict):
        args = args if isinstance(args, dict) else {}
        started = time.monotonic()
        try:
            result = self._dispatch(name, args)
        except Exception as exc:  # 兜底：任何工具异常都不能打断主循环
            LOGGER.exception("tool=%s outcome=exception", name)
            result = json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "TOOL_EXCEPTION",
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                },
                ensure_ascii=False,
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        outcome = "ok"
        if isinstance(result, str) and ('"ok": false' in result or '"error"' in result):
            outcome = "error"
        LOGGER.info(
            "tool=%s outcome=%s duration_ms=%s args=%s",
            name,
            outcome,
            elapsed_ms,
            sorted(args.keys()),
        )
        return result

    def _dispatch(self, name: str, args: dict):
        if self.mcp_manager is not None and self.mcp_manager.is_mcp_tool(name):
            return self.mcp_manager.call_tool(name, args)
        policy = self.policy
        if name == "get_date":
            return file_ops.get_date()
        if name == "is_leap_year":
            return file_ops.is_leap_year(args.get("year"))
        if name == "get_current_working_directory":
            return file_ops.get_current_working_directory()
        if name == "list_directory":
            return file_ops.list_directory(args.get("path") or ".", policy=policy)
        if name == "get_file_type":
            return file_ops.get_file_type(args.get("path") or "", policy=policy)
        if name == "get_file_content":
            return file_ops.get_file_content(
                args.get("path") or "",
                offset=int(args.get("offset") or 0),
                max_chars=int(args.get("max_chars") or file_ops.DEFAULT_READ_LIMIT),
                policy=policy,
            )
        if name == "create_file":
            return file_ops.create_file(
                args.get("dir_path") or ".",
                args.get("file_name") or "",
                args.get("content") or "",
                overwrite=bool(args.get("overwrite")),
                policy=policy,
            )
        if name == "edit_file":
            return file_ops.edit_file(
                args.get("path") or "",
                args.get("content") or "",
                mode=args.get("mode") or "replace",
                policy=policy,
            )
        if name == "create_directory":
            return file_ops.create_directory(args.get("path") or "", policy=policy)
        if name == "remove_directory":
            return file_ops.remove_directory(
                args.get("path") or "",
                recursive=bool(args.get("recursive")),
                confirm=bool(args.get("confirm")),
                policy=policy,
            )
        if name == "remove_file":
            return file_ops.remove_file(
                args.get("path") or "", confirm=bool(args.get("confirm")), policy=policy
            )
        if name == "rename_path":
            return file_ops.rename_path(
                args.get("old_path") or "",
                args.get("new_path") or "",
                confirm=bool(args.get("confirm")),
                policy=policy,
            )
        if name == "loadSkill":
            if self.skill_manager is None:
                return json.dumps(
                    {"ok": False, "error": {"code": "NOT_INITIALIZED", "message": "skill manager 未初始化"}},
                    ensure_ascii=False,
                )
            return self.skill_manager.load_skill(
                args.get("name") or "", args.get("filename")
            )
        if name == "createSkill":
            if self.skill_manager is None:
                return json.dumps(
                    {"ok": False, "error": {"code": "NOT_INITIALIZED", "message": "skill manager 未初始化"}},
                    ensure_ascii=False,
                )
            return self.skill_manager.create_skill(
                args.get("name") or "", args.get("skillContext") or ""
            )
        if name == "RunCli":
            options = {}
            if self.config is not None:
                options = {
                    "timeout": self.config.get_cli_timeout(),
                    "max_timeout": self.config.get_cli_max_timeout(),
                    "max_output_chars": self.config.get_cli_max_output_chars(),
                }
            return cli_ops.run_cli(
                args.get("command") or "", args.get("args") or [], **options
            )
        if name == "fetchWeb":
            options = {}
            if self.config is not None:
                options = {
                    "timeout": self.config.get_web_timeout(),
                    "connect_timeout": self.config.get_web_connect_timeout(),
                    "user_agent": self.config.get_user_agent(),
                }
            return web_ops.fetch_web(args.get("url") or "", **options)
        if name == "searchWeb":
            api_key = self.config.get_search_api_key() if self.config else ""
            options = {}
            if self.config is not None:
                options = {
                    "top_k": self.config.get_search_top_k(),
                    "timeout": self.config.get_search_timeout(),
                    "api_url": self.config.get_search_api_url(),
                    "max_summary_chars": self.config.get_web_max_summary_chars(),
                    "user_agent": self.config.get_user_agent(),
                }
            return web_ops.search_web(args.get("query") or "", api_key, **options)
        if name == "recallContext":
            if self.context_manager is None:
                return json.dumps(
                    {"ok": False, "error": {"code": "NOT_INITIALIZED", "message": "context manager 未初始化"}},
                    ensure_ascii=False,
                )
            return self.context_manager.search(
                args.get("text") or "", args.get("id")
            )
        return json.dumps(
            {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": f"未知工具：{name}"}},
            ensure_ascii=False,
        )
