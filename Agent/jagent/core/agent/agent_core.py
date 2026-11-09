import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import BadRequestError, OpenAI

from core.config.settings import Config
from core.context.manager import (
    ContextManager,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from core.mcp.manager import MCPManager
from core.session.manager import AGENTS_MD_MARKER, SessionManager, is_agents_message
from core.skills.manager import SkillManager
from core.tools.registry import ToolRegistry

COMPACTION_PROMPT_TEMPLATE = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 {target_tokens} Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


class AgentCore:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client: OpenAI = self.config.get_client()
        self.model = self.config.get_model()
        self.agent_name = self.config.get_agent_name()
        self.warning_ratio = self.config.get_warning_ratio()

        self.skill_manager = SkillManager(
            project_root=self.config.project_root,
            skills_dir=self.config.get_skills_dir(),
            max_name_length=self.config.get_skills_max_name_length(),
            max_description_length=self.config.get_skills_max_description_length(),
        )
        self.mcp_manager = MCPManager(
            project_root=self.config.project_root,
            config_path=self.config.get_mcp_config_path(),
            connect_timeout=self.config.get_mcp_connect_timeout(),
            call_timeout=self.config.get_mcp_call_timeout(),
            max_function_name_length=self.config.get_mcp_max_tool_name_length(),
            enabled=self.config.get_mcp_enabled(),
        )

        self.context_manager = ContextManager(
            project_root=self.config.project_root,
            archive_dir=self.config.get_archive_dir(),
            max_results=self.config.get_context_max_results(),
            max_chars=self.config.get_context_max_chars(),
            snippet_radius=self.config.get_context_snippet_radius(),
        )
        self.context_window, self.context_window_is_default = (
            self.config.get_context_window()
        )
        self._context_tokens = 0
        self._token_source = "estimate"
        self._context_blocked = False
        self._compacting = False
        self._compact_lock = threading.Lock()

        self.tools_registry = ToolRegistry(
            self.config,
            self.skill_manager,
            self.mcp_manager,
            context_manager=self.context_manager,
        )
        self.system_prompt = self._build_system_prompt()

        self.session_manager = SessionManager(
            project_root=self.config.project_root,
            sessions_dir=self.config.get_sessions_dir(),
            title_length=self.config.get_sessions_title_length(),
        )
        self.session_id = self.session_manager.new_session_id()
        self.session_title = ""
        self.agents_md_injected = False
        self.history: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        self.agents_md_injected = self._inject_agents_md()
        self._refresh_context_usage()

    def _build_system_prompt(self) -> str:
        skills = self.skill_manager.get_skills()
        lines = [
            f"You are {self.agent_name}, a helpful assistant. "
            "You are running inside a terminal user interface."
        ]
        if skills:
            lines.append("You have access to the following skills:")
            for skill in skills:
                lines.append(f"- `{skill.name}`: {skill.description}")
        else:
            lines.append("You currently have no skills available.")
        lines.append(
            "Use the `loadSkill` tool to load the full instructions of a skill when needed. "
            "You can also load additional files referenced by a skill."
        )
        lines.append(
            "Use the `createSkill` tool when the user asks you to create a new skill. "
            "Pass the complete SKILL.md content as `skillContext`; create auxiliary files "
            "such as references/ or scripts/ with the file operation tools afterwards."
        )
        if self.mcp_manager.servers:
            lines.append(
                "Tools provided by external MCP servers are available as well. Their "
                "names are prefixed with the MCP server name (server__tool) so they "
                "can coexist with local tools."
            )
        lines.append(
            "When a compacted summary lacks historical details, use the `recallContext` "
            "tool to search the archived original conversation."
        )
        return "\n".join(lines)

    def start_mcp(self) -> None:
        try:
            self.mcp_manager.start()
        except Exception as exc:
            self.mcp_manager.add_error("startup", f"{type(exc).__name__}: {exc}")

    def _inject_agents_md(self, position: Optional[int] = None) -> bool:
        if not self.config.get_agents_enabled():
            return False
        path = self.config.get_agents_path()
        if not path.is_file():
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        content = content.strip()
        if not content:
            return False
        message = {
            "role": "system",
            "content": (
                f"{AGENTS_MD_MARKER}\n"
                f"# 项目说明（AGENTS.md）\n\n"
                f"来源文件：{path}\n\n{content}"
            ),
        }
        if position is None:
            position = len(self.history)
        position = max(1, min(position, len(self.history)))
        self.history.insert(position, message)
        return True

    def get_agents_status(self) -> Dict[str, Any]:
        path = self.config.get_agents_path()
        return {
            "enabled": self.config.get_agents_enabled(),
            "path": str(path),
            "exists": path.is_file(),
            "injected": self.agents_md_injected,
        }

    def get_tools(self):
        return self.tools_registry.get_tools()

    def get_mcp_errors(self) -> Dict[str, str]:
        return self.mcp_manager.get_errors()

    def get_mcp_status(self) -> Dict[str, Any]:
        return self.mcp_manager.get_status()

    def get_context_status(self) -> Dict[str, Any]:
        window = max(1, int(self.context_window))
        tokens = max(0, int(self._context_tokens))
        percent = tokens / window * 100
        return {
            "tokens": tokens,
            "window": window,
            "percent": percent,
            "warning": percent >= self.warning_ratio * 100,
            "warning_ratio": self.warning_ratio,
            "blocked": self._context_blocked,
            "compacting": self._compacting,
            "window_is_default": self.context_window_is_default,
            "source": self._token_source,
        }

    def is_context_blocked(self) -> bool:
        return self._context_blocked

    def is_compacting(self) -> bool:
        return self._compacting

    def _estimate_context_tokens(self) -> int:
        tools = self.get_tools()
        tools_tokens = estimate_text_tokens(
            json.dumps(tools, ensure_ascii=False, default=str)
        )
        return estimate_messages_tokens(self.history) + tools_tokens

    def _refresh_context_usage(self) -> None:
        self._context_tokens = self._estimate_context_tokens()
        self._token_source = "estimate"
        self._update_context_block()

    def _apply_usage(self, response: Any) -> bool:
        usage = getattr(response, "usage", None)
        if usage is None:
            return False
        total = getattr(usage, "total_tokens", None)
        if total is None:
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or 0
            total = prompt + completion
        try:
            total = int(total)
        except (TypeError, ValueError):
            return False
        if total <= 0:
            return False
        self._context_tokens = total
        self._token_source = "api"
        self._update_context_block()
        return True

    def _update_context_block(self) -> None:
        ratio = self._context_tokens / max(1, int(self.context_window))
        self._context_blocked = ratio >= self.warning_ratio

    def run_turn(self, user_message: str):
        if self._compacting:
            yield "上下文压缩正在进行，请等待压缩完成后再继续。"
            return
        if self._context_blocked:
            yield (
                f"上下文使用量已达到 {self.warning_ratio * 100:.0f}%，"
                "请先执行 `/compact` 压缩上下文。"
            )
            return

        self.history.append({"role": "user", "content": user_message})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
            tools=self.get_tools(),
            tool_choice="auto",
        )
        usage_applied = self._apply_usage(response)
        message = response.choices[0].message
        if message.tool_calls:
            self.history.append(message)
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except Exception:
                    args = {}
                tool_result = self.tools_registry.call(name, args)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    }
                )

            stream = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                stream=True,
            )
            reply = ""
            stream_usage_applied = False
            for chunk in stream:
                if self._apply_usage(chunk):
                    stream_usage_applied = True
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    reply += delta
                    yield delta
            self.history.append({"role": "assistant", "content": reply})
            if not stream_usage_applied:
                self._refresh_context_usage()
        else:
            reply = message.content or ""
            self.history.append({"role": "assistant", "content": reply})
            if not usage_applied:
                self._refresh_context_usage()
            yield reply
        self._autosave_after_turn()

    def _autosave_after_turn(self) -> None:
        if not self.config.get_autosave_after_turn():
            return
        if not SessionManager.has_user_messages(self.history):
            return
        try:
            self.save_session(visible=True)
        except Exception:
            pass

    def new_session(self) -> Dict[str, Any]:
        saved = None
        if (
            self.config.get_autosave_on_new()
            and SessionManager.has_user_messages(self.history)
        ):
            saved = self.save_session(visible=True)
        self.session_id = self.session_manager.new_session_id()
        self.session_title = ""
        self.history = [{"role": "system", "content": self.system_prompt}]
        self.agents_md_injected = self._inject_agents_md()
        self._context_blocked = False
        self._refresh_context_usage()
        return {
            "saved": saved,
            "session_id": self.session_id,
            "agents_md_injected": self.agents_md_injected,
        }

    def save_session(
        self, title: Optional[str] = None, visible: bool = True
    ) -> Optional[Dict[str, Any]]:
        if not self.history:
            return None
        result = self.session_manager.save(
            self.session_id,
            self.history,
            title if title is not None else self.session_title,
            self.model,
            str(self.config.project_root),
            self.agents_md_injected,
            visible,
        )
        self.session_title = result["title"]
        return result

    def load_session(self, session_id: str) -> Dict[str, Any]:
        data = self.session_manager.load(session_id)
        history = data["messages"]
        if not history:
            raise ValueError(f"会话没有可恢复的消息: {session_id}")
        if not (
            isinstance(history[0], dict) and history[0].get("role") == "system"
        ):
            history.insert(0, {"role": "system", "content": self.system_prompt})
        self.history = history
        self.session_id = data["id"]
        self.session_title = data["title"]
        self.agents_md_injected = any(
            is_agents_message(message) for message in history
        )
        if not self.agents_md_injected:
            self.agents_md_injected = self._inject_agents_md(position=1)
        self._context_blocked = False
        self._refresh_context_usage()
        return data

    def list_sessions(self) -> List[Dict[str, Any]]:
        return self.session_manager.list_sessions()

    def session_info(self) -> Dict[str, Any]:
        return {
            "id": self.session_id,
            "title": self.session_title,
            "message_count": len(self.history),
            "agents_md_injected": self.agents_md_injected,
        }

    def compact(self) -> Dict[str, Any]:
        with self._compact_lock:
            if self._compacting:
                raise RuntimeError("上下文压缩正在进行中")
            self._compacting = True

        try:
            archive = self.context_manager.archive(self.history)
            summary = self._summarize_context(archive["transcript"])
            archive_note = self._archive_note(archive)
            summary_content = (
                "以下是此前会话的压缩摘要，请在后续任务中将其作为已存在的上下文继续工作。\n\n"
                f"{summary}\n\n{archive_note}"
            )
            compacted_system = (
                f"{self.system_prompt}\n\n"
                "# 历史会话压缩摘要\n\n"
                f"{summary_content}"
            )
            self.history = [{"role": "system", "content": compacted_system}]
            self._refresh_context_usage()
            self._context_blocked = False
            return {
                "archive_id": archive["id"],
                "archive_path": str(archive["path"]),
                "created_at": archive["created_at"],
                "original": archive["transcript"],
                "summary": summary_content,
                "tokens": self._context_tokens,
            }
        finally:
            self._compacting = False

    def _build_compaction_prompt(self) -> str:
        target = self.config.get_summary_target_tokens()
        return COMPACTION_PROMPT_TEMPLATE.format(target_tokens=f"{target:,}")

    def _summarize_context(self, transcript: str) -> str:
        messages = [
            {"role": "system", "content": self._build_compaction_prompt()},
            {
                "role": "user",
                "content": (
                    "以下是需要压缩的历史上下文。"
                    "请根据系统提示生成 Markdown 工作摘要：\n\n"
                    f"{transcript}"
                ),
            },
        ]
        effort = self.config.get_summary_reasoning_effort()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                reasoning_effort=effort or "none",
            )
        except (BadRequestError, TypeError):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
        summary = response.choices[0].message.content or ""
        summary = summary.strip()
        if not summary:
            raise RuntimeError("LLM 返回了空的压缩摘要")
        return summary

    @staticmethod
    def _archive_note(archive: Dict[str, Any]) -> str:
        created_at = archive["created_at"]
        if isinstance(created_at, datetime):
            time_text = created_at.strftime("%Y-%m-%d %H:%M:%S")
        else:
            time_text = str(created_at)
        return (
            f"此前上下文已于 {time_text} 完成压缩，原始上下文保存在编号为 "
            f"{archive['id']} 的归档文件中。如需查找历史信息，请使用 "
            "recallContext 工具。"
        )

    def close(self) -> None:
        self.mcp_manager.close()
