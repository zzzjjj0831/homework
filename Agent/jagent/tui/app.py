import time
from datetime import datetime
from typing import List, Optional

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from core.agent.agent_core import AgentCore
from core.config.settings import Config
from core.session.manager import SessionManager, is_agents_message
from tui.commands import COMMANDS, SlashCommand, resolve_command, suggest_commands


class ConfigCreatedModal(ModalScreen[Optional[bool]]):
    BINDINGS = [("escape", "continue_run", "继续")]

    CSS = """
    ConfigCreatedModal {
        align: center middle;
        background: $background 70%;
    }

    #config-dialog {
        width: 80%;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $warning;
    }

    #config-title {
        height: 1;
        text-style: bold;
        color: $warning;
    }

    #config-body {
        height: auto;
        margin: 1 0;
    }

    #config-buttons {
        height: 3;
        align: right middle;
    }

    #config-buttons Button {
        margin-left: 2;
    }
    """

    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        body = Text()
        body.append("没有找到 config.ini，已为你创建一份带 mock 配置的新文件。\n\n")
        body.append("配置文件：\n", style="bold")
        body.append(f"{self.config_path}\n\n", style="#7aa2f7")
        body.append(
            "请修改模型地址、模型名称、API Key、搜索 Key 以及 MCP 配置后，"
            "重新启动 jagent 才能正常工作。\n\n",
            style="#e0af68",
        )
        body.append(
            "如果现在继续，程序会使用 mock 配置运行，对话和联网功能可能不可用。",
            style="dim",
        )
        yield Vertical(
            Static("首次运行 · 已生成配置文件", id="config-title"),
            Static(body, id="config-body", markup=False),
            Horizontal(
                Button("继续运行", id="config-continue"),
                Button("退出程序", id="config-quit", variant="error"),
                id="config-buttons",
            ),
            id="config-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "config-quit")

    def action_continue_run(self) -> None:
        self.dismiss(False)


class SessionResumeModal(ModalScreen[Optional[str]]):
    BINDINGS = [("escape", "cancel", "取消")]

    CSS = """
    SessionResumeModal {
        align: center middle;
        background: $background 70%;
    }

    #resume-dialog {
        width: 92%;
        height: 80%;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }

    #resume-title {
        height: auto;
        margin-bottom: 1;
        text-style: bold;
        color: $accent;
    }

    #resume-list {
        height: 1fr;
    }
    """

    def __init__(self, sessions: List[dict]):
        super().__init__()
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        options = []
        for session in self.sessions:
            title = str(session.get("title") or "未命名会话")
            updated = str(session.get("updated_at") or "").replace("T", " ")
            count = int(session.get("message_count") or 0)
            preview = str(session.get("preview") or "")
            prompt = Text()
            prompt.append(title, style="bold #7aa2f7")
            prompt.append(f"  {updated}  ·  {count} 条消息\n", style="dim")
            if preview:
                prompt.append(preview, style="#a9b1d6")
            options.append(Option(prompt, id=session["id"]))

        yield Vertical(
            Static(
                "历史会话 · ↑/↓ 选择 · Enter 恢复 · ESC 取消",
                id="resume-title",
            ),
            OptionList(*options, id="resume-list"),
            id="resume-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#resume-list", OptionList).focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CompactionModal(ModalScreen):
    BINDINGS = [("escape", "close_modal", "关闭")]

    CSS = """
    CompactionModal {
        align: center middle;
        background: $background 60%;
    }

    #compact-dialog {
        width: 92%;
        height: 88%;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }

    #compact-title {
        height: 1;
        text-style: bold;
        color: $accent;
    }

    #compact-columns {
        height: 1fr;
        margin: 1 0;
    }

    .compact-column {
        width: 1fr;
        height: 100%;
        margin: 0 1;
        padding: 0 1;
        border: round $primary 40%;
    }

    .compact-heading {
        height: 1;
        text-style: bold;
        color: $text;
    }

    .compact-scroll {
        height: 1fr;
    }

    .compact-content {
        width: 100%;
    }

    #compact-close {
        width: 18;
        margin-top: 1;
    }
    """

    def __init__(self, original: str, summary: str, archive_id: str):
        super().__init__()
        self.original = original
        self.summary = summary
        self.archive_id = archive_id

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(
                f"上下文压缩完成 · 归档 {self.archive_id}",
                id="compact-title",
            ),
            Horizontal(
                Vertical(
                    Static("压缩前原文", classes="compact-heading"),
                    VerticalScroll(
                        Static(
                            self.original,
                            classes="compact-content",
                            markup=False,
                        ),
                        classes="compact-scroll",
                    ),
                    classes="compact-column",
                ),
                Vertical(
                    Static("压缩后摘要", classes="compact-heading"),
                    VerticalScroll(
                        Static(
                            Markdown(self.summary),
                            classes="compact-content",
                        ),
                        classes="compact-scroll",
                    ),
                    classes="compact-column",
                ),
                id="compact-columns",
            ),
            Button("关闭", id="compact-close", variant="primary"),
            id="compact-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "compact-close":
            self.dismiss()

    def action_close_modal(self) -> None:
        self.dismiss()


class CommandInput(Input):
    BINDINGS = Input.BINDINGS + [
        Binding("up", "completion_prev", "上一条补全", show=False),
        Binding("down", "completion_next", "下一条补全", show=False),
        Binding("tab", "completion_accept", "补全命令", show=False),
        Binding("escape", "completion_cancel", "关闭补全", show=False),
    ]

    def action_completion_prev(self) -> None:
        if self.app.completion_visible:
            self.app.move_completion(-1)

    def action_completion_next(self) -> None:
        if self.app.completion_visible:
            self.app.move_completion(1)

    def action_completion_accept(self) -> None:
        if self.app.completion_visible:
            self.app.accept_completion(execute=False)
        else:
            self.screen.focus_next()

    def action_completion_cancel(self) -> None:
        if self.app.completion_visible:
            self.app.hide_completions()

    async def action_submit(self) -> None:
        if self.app.completion_visible:
            self.app.accept_completion(execute=True)
            return
        await super().action_submit()


class JagAgentApp(App):
    TITLE = "jagent"
    SUB_TITLE = "本地大模型终端助手"

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+l", "clear_chat", "清屏"),
        ("f1", "show_help", "命令帮助"),
    ]

    CSS = """
    Screen {
        background: $background;
    }

    Header {
        background: $primary 20%;
        color: $text;
    }

    #body {
        height: 1fr;
    }

    #main {
        width: 1fr;
    }

    #context-bar {
        height: 1;
        margin: 0 2;
        padding: 0 1;
        background: $primary 15%;
        content-align: left middle;
    }

    #log {
        height: 1fr;
        margin: 1 2 0 2;
        padding: 1 2;
        background: $surface;
        border: round $primary 35%;
    }

    #stream-box {
        display: none;
        height: auto;
        max-height: 12;
        margin: 0 2;
        padding: 0 2;
        background: $panel;
        border: round $accent 60%;
    }

    #stream-box.visible {
        display: block;
    }

    #stream-text {
        height: auto;
        color: $text;
    }

    #command-panel {
        display: none;
        height: auto;
        max-height: 14;
        margin: 0 2;
        border: round $accent 60%;
        background: $panel;
    }

    #command-panel.visible {
        display: block;
    }

    #status {
        height: 1;
        margin: 0 2;
        content-align: left middle;
    }

    #input-bar {
        height: 3;
        margin: 1 2;
        padding: 0 1;
        align: left middle;
        background: $surface;
        border: round $accent 60%;
    }

    #input-bar:focus-within {
        border: round $success;
    }

    #prompt {
        width: 3;
        height: 1;
        content-align: center middle;
        color: $accent;
        text-style: bold;
    }

    #input {
        width: 1fr;
        height: 1;
        padding: 0;
        border: none;
        background: transparent;
    }

    #sidebar {
        width: 38;
        margin: 1 2 0 0;
        padding: 1;
        background: $surface;
        border: round $primary 35%;
    }

    #sidebar-title {
        height: 1;
        text-style: bold;
        color: $accent;
    }

    #sidebar-scroll {
        height: 1fr;
    }

    #sidebar-content {
        width: 100%;
    }

    Footer {
        background: $panel;
    }
    """

    def __init__(self, config: Optional[Config] = None):
        super().__init__()
        self.config = config or Config()
        self.theme = self.config.get_ui_theme()
        self.agent = AgentCore(self.config)
        self.title = self.config.get_ui_title()
        self.sub_title = f"{self.agent.model} · {self.config.get_ui_sub_title()}"
        self._busy = False
        self._compacting = False
        self._context_warned = False
        self._completion_visible = False
        self._command_matches: List[SlashCommand] = []
        self._command_index = 0
        self._mcp_errors_seen: set = set()
        self._quit_saved = False

    @property
    def completion_visible(self) -> bool:
        return self._completion_visible

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield Static(id="context-bar")
                yield RichLog(id="log", markup=True, auto_scroll=True)
                with VerticalScroll(id="stream-box"):
                    yield Static("", id="stream-text", markup=False)
                yield OptionList(id="command-panel")
                yield Static(id="status")
                with Horizontal(id="input-bar"):
                    yield Static("❯", id="prompt")
                    yield CommandInput(
                        placeholder="输入问题，Enter 发送；输入 / 查看命令补全...",
                        id="input",
                    )
            with Vertical(id="sidebar"):
                yield Static("MCP 概览", id="sidebar-title")
                with VerticalScroll(id="sidebar-scroll"):
                    yield Static("", id="sidebar-content", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.border_title = " 对话 "
        log.border_subtitle = " /help 查看命令 "
        self.query_one("#sidebar").styles.width = self.config.get_ui_sidebar_width()
        self.query_one("#command-panel", OptionList).display = False
        self._set_status("● 就绪", "italic #9ece6a")
        self._write_welcome()
        if self.agent.agents_md_injected:
            self._write_agents_notice()
        self._update_context_bar()
        self._refresh_sidebar()
        self.query_one("#input", CommandInput).focus()
        if self.config.was_created:
            self.call_after_refresh(self._show_config_notice)
        self.load_mcp()

    def on_unmount(self) -> None:
        if not self._quit_saved:
            self._autosave_current()
        try:
            self.agent.close()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "input":
            return
        self._refresh_completions(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return

        input_widget = self.query_one("#input", CommandInput)
        if user_text.startswith("/"):
            input_widget.value = ""
            self._execute_command(user_text)
            return

        if self._compacting:
            input_widget.value = ""
            self._write_block(
                Text(" 上下文压缩正在进行，请稍候...", style="#e0af68")
            )
            return
        if self._busy:
            input_widget.value = ""
            self._write_block(
                Text(" 请等待当前回复结束后再发送新消息。", style="#e0af68")
            )
            return

        if self.agent.is_context_blocked():
            input_widget.value = ""
            percent = self.agent.warning_ratio * 100
            self._write_block(
                Text(
                    f" 上下文使用量已达到 {percent:.0f}%，请先执行 /compact 压缩上下文。",
                    style="#f7768e",
                )
            )
            self._set_status("● 已暂停输入 · 请执行 /compact", "italic #f7768e")
            self._update_context_bar()
            return

        input_widget.value = ""
        self._write_user_message(user_text)
        self._busy = True
        self._begin_reply()
        self.stream_reply(user_text)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id == "command-panel":
            event.stop()
            self.hide_completions()
            self._execute_command(event.option.id or "")

    def _refresh_completions(self, value: str) -> None:
        if not self.config.get_ui_autocomplete_enabled():
            self.hide_completions()
            return
        matches = suggest_commands(value)
        if not matches:
            self.hide_completions()
            return

        max_items = self.config.get_ui_command_panel_max_items()
        self._command_matches = matches[:max_items]
        if self._command_index >= len(self._command_matches):
            self._command_index = 0

        options = []
        for command in self._command_matches:
            prompt = Text()
            prompt.append(command.name, style="bold #7aa2f7")
            if command.aliases:
                prompt.append(f"  ({', '.join(command.aliases)})", style="dim")
            prompt.append("\n")
            prompt.append(command.description, style="#a9b1d6")
            options.append(Option(prompt, id=command.name))

        panel = self.query_one("#command-panel", OptionList)
        panel.set_options(options)
        panel.highlighted = self._command_index
        panel.display = True
        panel.add_class("visible")
        self._completion_visible = True

    def hide_completions(self) -> None:
        self._completion_visible = False
        self._command_matches = []
        self._command_index = 0
        try:
            panel = self.query_one("#command-panel", OptionList)
            panel.remove_class("visible")
            panel.display = False
        except Exception:
            pass

    def move_completion(self, delta: int) -> None:
        if not self._completion_visible or not self._command_matches:
            return
        self._command_index = (
            self._command_index + delta
        ) % len(self._command_matches)
        panel = self.query_one("#command-panel", OptionList)
        panel.highlighted = self._command_index

    def accept_completion(self, execute: bool) -> None:
        if not self._command_matches:
            return
        command = self._command_matches[self._command_index]
        self.hide_completions()
        input_widget = self.query_one("#input", CommandInput)
        if execute:
            input_widget.value = ""
            input_widget.cursor_position = 0
            self._execute_command(command.name)
        else:
            input_widget.value = command.name
            input_widget.cursor_position = len(command.name)
            input_widget.focus()

    def _execute_command(self, text: str) -> None:
        command = resolve_command(text)
        input_widget = self.query_one("#input", CommandInput)
        if command is None:
            token = text.strip().split(maxsplit=1)[0]
            self._write_block(
                Panel(
                    Text(
                        f" 未知命令：{token}\n 输入 /help 查看所有可用命令。",
                        style="#f7768e",
                    ),
                    title=" 命令错误 ",
                    title_align="left",
                    border_style="#f7768e",
                    padding=(0, 1),
                )
            )
            self.hide_completions()
            input_widget.focus()
            return

        if (self._busy or self._compacting) and command.name not in (
            "/quit",
            "/help",
            "/context",
            "/mcp",
        ):
            self._write_block(
                Text(
                    " 当前有任务正在执行，请等待完成后再使用该命令。",
                    style="#e0af68",
                )
            )
            input_widget.focus()
            return

        handlers = {
            "/help": self._show_help,
            "/new": self._command_new,
            "/resume": self._command_resume,
            "/save": self._command_save,
            "/compact": self._start_compaction,
            "/context": self._show_context,
            "/clear": self.action_clear_chat,
            "/tools": self._show_tools,
            "/mcp": self._show_mcp,
            "/agents": self._show_agents,
            "/model": self._show_model,
            "/quit": self._quit_with_autosave,
        }
        handler = handlers.get(command.name)
        if handler is not None:
            handler()
        if (
            command.name != "/quit"
            and not input_widget.disabled
            and not isinstance(self.screen, ModalScreen)
        ):
            input_widget.focus()

    def _focus_input(self) -> None:
        self.query_one("#input", CommandInput).focus()

    def _command_new(self) -> None:
        result = self.agent.new_session()
        log = self.query_one("#log", RichLog)
        log.clear()
        self._context_warned = False
        self._write_welcome()
        if result["agents_md_injected"]:
            self._write_agents_notice()
        if result["saved"]:
            saved = result["saved"]
            message = (
                f" 已自动保存上一个会话：{saved['id']}\n"
                f" 标题：{saved['title']}\n\n"
                f" 新会话编号：{result['session_id']}"
            )
        else:
            message = (
                " 已开始新的会话（上一个会话没有用户消息，未保存）。\n"
                f" 新会话编号：{result['session_id']}"
            )
        self._write_block(
            Panel(
                Text(message, style="#9ece6a"),
                title=" /new ",
                title_align="left",
                border_style="#9ece6a",
                padding=(0, 1),
            )
        )
        self._update_context_bar()
        self._refresh_sidebar()

    def _command_resume(self) -> None:
        sessions = self.agent.list_sessions()
        if not sessions:
            self._write_block(
                Text(" 暂无历史会话可供恢复。", style="#e0af68")
            )
            return
        self.push_screen(SessionResumeModal(sessions), self._on_resume_selected)

    def _on_resume_selected(self, session_id: Optional[str]) -> None:
        if not session_id:
            self._focus_input()
            return
        try:
            data = self.agent.load_session(session_id)
        except Exception as exc:
            self._write_block(
                Panel(
                    Text(f" 恢复会话失败：{exc}", style="#f7768e"),
                    title=" /resume ",
                    title_align="left",
                    border_style="#f7768e",
                    padding=(0, 1),
                )
            )
            self._focus_input()
            return

        log = self.query_one("#log", RichLog)
        log.clear()
        self._context_warned = False
        self._render_history(data["messages"])
        self._write_block(
            Panel(
                Text(
                    (
                        f" 已恢复会话：{data['title']}\n"
                        f" 编号：{data['id']} · {data['message_count']} 条消息"
                    ),
                    style="#9ece6a",
                ),
                title=" /resume ",
                title_align="left",
                border_style="#9ece6a",
                padding=(0, 1),
            )
        )
        self._update_context_bar()
        self._refresh_sidebar()
        self._focus_input()

    def _render_history(self, messages: List[dict]) -> None:
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            role = message.get("role")
            if role == "system":
                if is_agents_message(message):
                    self._write_block(
                        Text(
                            " 已从会话日志恢复 AGENTS.md 项目上下文。",
                            style="dim #9ece6a",
                        )
                    )
                continue
            if role == "user":
                self._write_user_message(content)
            elif role == "assistant":
                self._write_agent_message(content)

    def _command_save(self) -> None:
        if not SessionManager.has_user_messages(self.agent.history):
            self._write_block(
                Text(" 当前会话还没有用户消息，暂不保存。", style="#e0af68")
            )
            return
        try:
            result = self.agent.save_session()
        except Exception as exc:
            self._write_block(
                Panel(
                    Text(f" 保存会话失败：{exc}", style="#f7768e"),
                    title=" /save ",
                    title_align="left",
                    border_style="#f7768e",
                    padding=(0, 1),
                )
            )
            return
        if result is None:
            self._write_block(
                Text(" 当前会话为空，未保存。", style="#e0af68")
            )
            return
        self._write_block(
            Panel(
                Text(
                    (
                        f" 会话已保存：{result['id']}\n"
                        f" 标题：{result['title']}\n"
                        f" 文件：{result['path']}"
                    ),
                    style="#9ece6a",
                ),
                title=" /save ",
                title_align="left",
                border_style="#9ece6a",
                padding=(0, 1),
            )
        )
        self._refresh_sidebar()

    def _show_help(self) -> None:
        body = Text()
        for command in COMMANDS:
            body.append(f"  {command.name:<10}", style="bold #7aa2f7")
            if command.aliases:
                body.append(f"({', '.join(command.aliases)}) ", style="dim")
            else:
                body.append("             ")
            body.append(f"{command.description}\n", style="#a9b1d6")
        body.append("\n")
        body.append("  Enter      ", style="bold #e0af68")
        body.append("发送消息 / 执行补全项\n", style="#a9b1d6")
        body.append("  ↑ / ↓     ", style="bold #e0af68")
        body.append("在命令补全面板中选择\n", style="#a9b1d6")
        body.append("  Tab        ", style="bold #e0af68")
        body.append("补全当前命令\n", style="#a9b1d6")
        body.append("  Ctrl+Q     ", style="bold #e0af68")
        body.append("保存并退出\n", style="#a9b1d6")
        body.append("  Ctrl+L     ", style="bold #e0af68")
        body.append("清空屏幕显示\n", style="#a9b1d6")
        self._write_block(
            Panel(
                body,
                title=" 命令帮助 ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(1, 2),
            )
        )

    def _show_context(self) -> None:
        status = self.agent.get_context_status()
        info = self.agent.session_info()
        tokens_k = status["tokens"] / 1024
        window_k = status["window"] / 1024
        default_text = "（默认值）" if status["window_is_default"] else ""
        body = Text()
        body.append(f" 上下文：{tokens_k:.1f}k / {window_k:.0f}k{default_text}\n")
        body.append(f" 已占用：{status['percent']:.1f}%\n")
        body.append(f" 警告阈值：{status['warning_ratio'] * 100:.0f}%\n")
        body.append(f" Token 来源：{status['source']}\n\n", style="dim")
        body.append(f" 会话编号：{info['id']}\n", style="#a9b1d6")
        body.append(
            f" 会话标题：{info['title'] or '未命名会话'}\n", style="#a9b1d6"
        )
        body.append(
            f" 消息数量：{info['message_count']}\n", style="#a9b1d6"
        )
        self._write_block(
            Panel(
                body,
                title=" /context ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(0, 1),
            )
        )

    def _show_tools(self) -> None:
        tools = self.agent.get_tools()
        body = Text()
        body.append(f" 共 {len(tools)} 个可用工具\n\n", style="bold #7aa2f7")
        for tool in tools:
            function = tool.get("function", {})
            name = function.get("name", "unknown")
            description = function.get("description", "")
            body.append(f"  {name}\n", style="bold #9ece6a")
            if description:
                body.append(f"    {description}\n", style="#a9b1d6")
        self._write_block(
            Panel(
                body,
                title=" /tools ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(0, 1),
            )
        )

    def _show_mcp(self) -> None:
        status = self.agent.get_mcp_status()
        body = Text()
        body.append(f" 配置路径：{status['config_path']}\n")
        body.append(f" SDK 可用：{'是' if status['available'] else '否'}\n")
        body.append(f" 启用状态：{'已启用' if status['enabled'] else '已禁用'}\n")
        body.append(
            f" 加载状态：{'加载中' if status['loading'] else '已完成'}\n\n"
        )
        if not status["servers"]:
            body.append(" 未配置 MCP 服务器。\n", style="dim")
        for name, server in status["servers"].items():
            state = server["status"]
            if state == "connected":
                body.append(f" ● {name}\n", style="bold #9ece6a")
                if server["tools"]:
                    for tool in server["tools"]:
                        body.append(f"    - {tool}\n", style="#a9b1d6")
                else:
                    body.append("    (该服务器未提供工具)\n", style="dim")
            elif state == "error":
                body.append(f" ✗ {name}\n", style="bold #f7768e")
                body.append(f"    {server['error']}\n", style="#f7768e")
            elif state == "disabled":
                body.append(f" ○ {name} · 已禁用\n", style="dim")
            else:
                body.append(f" ○ {name} · 等待加载\n", style="#e0af68")
        self._write_block(
            Panel(
                body,
                title=" /mcp ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(0, 1),
            )
        )
        self._refresh_sidebar()

    def _show_agents(self) -> None:
        info = self.agent.get_agents_status()
        body = Text()
        body.append(
            f" 启用状态：{'已启用' if info['enabled'] else '已禁用'}\n"
        )
        body.append(f" 文件路径：{info['path']}\n")
        body.append(f" 文件存在：{'是' if info['exists'] else '否'}\n")
        body.append(
            f" 当前会话注入：{'是' if info['injected'] else '否'}\n\n"
        )
        if not info["enabled"]:
            body.append(
                " AGENTS.md 注入已在配置中关闭。\n", style="#e0af68"
            )
        elif not info["exists"]:
            body.append(
                " 当前目录没有 AGENTS.md，新建会话时不会注入项目说明。\n",
                style="#e0af68",
            )
        else:
            body.append(
                " AGENTS.md 采用“一次注入，全程复用”策略：\n"
                " 会话首次加载时注入一次，并写入会话事件日志，后续轮次直接复用。\n",
                style="#a9b1d6",
            )
        self._write_block(
            Panel(
                body,
                title=" /agents ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(0, 1),
            )
        )

    def _show_model(self) -> None:
        status = self.agent.get_context_status()
        body = Text()
        body.append(f" 模型：{self.agent.model}\n")
        body.append(f" 接口：{self.config.get('llm', 'base_url')}\n")
        body.append(
            f" 上下文窗口：{'自动' if status['window_is_default'] else '配置值'}"
            f"（{status['window']}）\n"
        )
        body.append(f" 代理名称：{self.agent.agent_name}\n")
        body.append(f" 主题：{self.config.get_ui_theme()}\n")
        body.append(f" 配置文件：{self.config.config_path}\n")
        self._write_block(
            Panel(
                body,
                title=" /model ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(0, 1),
            )
        )

    def _show_config_notice(self) -> None:
        self.push_screen(
            ConfigCreatedModal(str(self.config.config_path)),
            self._on_config_notice,
        )

    def _on_config_notice(self, should_quit: Optional[bool]) -> None:
        if should_quit:
            self._quit_saved = True
            self.exit()
            return
        self._write_block(
            Panel(
                Text(
                    (
                        f" 配置文件已创建：{self.config.config_path}\n"
                        " 请修改配置后重新启动 jagent。当前仍在使用 mock 配置。"
                    ),
                    style="#e0af68",
                ),
                title=" 配置提醒 ",
                title_align="left",
                border_style="#e0af68",
                padding=(0, 1),
            )
        )
        self._focus_input()

    def _start_compaction(self) -> None:
        self._compacting = True
        self._write_block(
            Panel(
                Text(
                    " 正在生成上下文摘要，压缩期间不会执行其他工具...",
                    style="#e0af68",
                ),
                title=" /compact ",
                title_align="left",
                border_style="#e0af68",
                padding=(0, 1),
            )
        )
        self._set_status("● 正在压缩上下文...", "italic #e0af68")
        self.query_one("#input", CommandInput).disabled = True
        self._update_context_bar()
        self.compact_context()

    def _update_context_bar(self) -> None:
        status = self.agent.get_context_status()
        tokens_k = status["tokens"] / 1024
        window_k = status["window"] / 1024
        default_text = "（默认）" if status["window_is_default"] else ""
        warn_percent = status["warning_ratio"] * 100
        text = (
            f"上下文 {tokens_k:.1f}k / {window_k:.0f}k{default_text}"
            f"  ·  已占用 {status['percent']:.1f}%"
        )
        if self._compacting:
            text += "  ·  压缩中..."
            style = "bold #e0af68"
        elif status["warning"]:
            text += f"  ⚠ 已达 {warn_percent:.0f}%，请执行 /compact"
            style = "bold #f7768e"
        else:
            style = "bold #9ece6a"
        self.query_one("#context-bar", Static).update(Text(text, style=style))

        if status["warning"] and not self._compacting:
            if not self._context_warned:
                self._context_warned = True
                self._write_context_warning(status)
        elif not status["warning"]:
            self._context_warned = False

    def _write_context_warning(self, status: dict) -> None:
        tokens_k = status["tokens"] / 1024
        window_k = status["window"] / 1024
        warn_percent = status["warning_ratio"] * 100
        self._write_block(
            Panel(
                Text(
                    (
                        f"上下文已使用 {status['percent']:.1f}%"
                        f"（{tokens_k:.1f}k / {window_k:.0f}k），"
                        f"已达到 {warn_percent:.0f}% 阈值。\n"
                        "请执行 /compact 压缩上下文后再继续输入。"
                    ),
                    style="#e0af68",
                ),
                title=" 上下文警告 ",
                title_align="left",
                border_style="#e0af68",
                padding=(0, 1),
            )
        )

    def action_clear_chat(self) -> None:
        self.query_one("#log", RichLog).clear()
        self._set_status("● 就绪", "italic #9ece6a")
        self._focus_input()

    def action_quit(self) -> None:
        self._quit_with_autosave()

    def action_show_help(self) -> None:
        self._show_help()
        self._focus_input()

    def _quit_with_autosave(self) -> None:
        if not self._quit_saved:
            self._autosave_current()
            self._quit_saved = True
        self.exit()

    def _autosave_current(self) -> None:
        if not self.config.get_autosave_on_quit():
            return
        try:
            if SessionManager.has_user_messages(self.agent.history):
                self.agent.save_session()
        except Exception:
            pass

    def _set_status(self, text: str, style: str) -> None:
        self.query_one("#status", Static).update(Text(f"  {text}", style=style))

    def _write_block(self, renderable) -> None:
        log = self.query_one("#log", RichLog)
        log.write("")
        log.write(renderable)

    def _write_welcome(self) -> None:
        body = Text()
        body.append(f"欢迎使用 {self.config.get_ui_title()}\n", style="bold #7aa2f7")
        body.append("一个运行在终端里的本地大模型助手\n\n", style="#a9b1d6")
        body.append("  /        ", style="bold #e0af68")
        body.append("打开斜杠命令补全面板\n", style="#a9b1d6")
        body.append("  /help    ", style="bold #e0af68")
        body.append("查看全部命令\n", style="#a9b1d6")
        body.append("  /new     ", style="bold #e0af68")
        body.append("新建会话并自动保存当前会话\n", style="#a9b1d6")
        body.append("  /resume  ", style="bold #e0af68")
        body.append("恢复历史会话\n", style="#a9b1d6")
        body.append("  /save    ", style="bold #e0af68")
        body.append("保存当前会话\n", style="#a9b1d6")
        body.append("  /compact ", style="bold #e0af68")
        body.append("压缩上下文\n", style="#a9b1d6")
        body.append("  Ctrl+Q   ", style="bold #e0af68")
        body.append("保存并退出\n", style="#a9b1d6")
        body.append("  Ctrl+L   ", style="bold #e0af68")
        body.append("清屏\n", style="#a9b1d6")
        self._write_block(
            Panel(
                body,
                title=f" {self.config.get_ui_title()} ",
                title_align="left",
                border_style="#7aa2f7",
                padding=(1, 2),
            )
        )

    def _write_agents_notice(self) -> None:
        self._write_block(
            Text(
                " 已按“一次注入，全程复用”策略加载 AGENTS.md，并写入会话事件日志。",
                style="dim #9ece6a",
            )
        )

    def _refresh_sidebar(self) -> None:
        status = self.agent.get_mcp_status()
        info = self.agent.session_info()
        text = Text()
        text.append("会话\n", style="bold #7aa2f7")
        text.append(
            f"  {info['title'] or '未命名会话'}\n", style="#c0caf5"
        )
        text.append(f"  {info['id']}\n", style="dim")
        text.append(f"  {info['message_count']} 条消息\n\n", style="dim")

        text.append("MCP 服务器\n", style="bold #7aa2f7")
        if not status["enabled"]:
            text.append("  已禁用\n", style="dim")
        elif not status["servers"]:
            text.append("  未配置服务器\n", style="dim")
        else:
            if status["loading"]:
                text.append("  正在加载...\n", style="#e0af68")
            for name, server in status["servers"].items():
                state = server["status"]
                if state == "connected":
                    text.append(f"  ● {name}\n", style="bold #9ece6a")
                    if server["tools"]:
                        for tool in server["tools"]:
                            text.append(f"    - {tool}\n", style="#a9b1d6")
                    else:
                        text.append("    (无工具)\n", style="dim")
                elif state == "error":
                    text.append(f"  ✗ {name}\n", style="bold #f7768e")
                    if server["error"]:
                        text.append(
                            f"    {server['error'][:160]}\n", style="#f7768e"
                        )
                elif state == "disabled":
                    text.append(f"  ○ {name} · 已禁用\n", style="dim")
                else:
                    text.append(f"  ○ {name} · 等待加载\n", style="#e0af68")

        text.append("\n工具\n", style="bold #7aa2f7")
        text.append(
            f"  可用工具 {len(self.agent.get_tools())} 个\n", style="#a9b1d6"
        )
        self.query_one("#sidebar-content", Static).update(text)

    def _write_mcp_errors(self) -> None:
        for server, message in self.agent.get_mcp_errors().items():
            key = (server, message)
            if key in self._mcp_errors_seen:
                continue
            self._mcp_errors_seen.add(key)
            body = Text()
            body.append(f"{server}\n", style="bold #f7768e")
            body.append(message, style="#a9b1d6")
            self._write_block(
                Panel(
                    body,
                    title=" MCP 连接失败 ",
                    title_align="left",
                    border_style="#f7768e",
                    padding=(0, 1),
                )
            )

    def _write_user_message(self, text: str) -> None:
        body = Text(text, style="#c0caf5")
        self._write_block(
            Panel(
                body,
                title=f" 你 · {datetime.now():%H:%M} ",
                title_align="right",
                border_style="#7aa2f7",
                padding=(0, 1),
            )
        )

    def _write_agent_message(self, reply: str) -> None:
        self._write_block(
            Panel(
                Markdown(reply),
                title=f" {self.config.get_ui_title()} · {datetime.now():%H:%M} ",
                title_align="left",
                border_style="#9ece6a",
                padding=(0, 1),
            )
        )

    def _begin_reply(self) -> None:
        box = self.query_one("#stream-box", VerticalScroll)
        box.border_title = " 生成中 "
        box.add_class("visible")
        self.query_one("#stream-text", Static).update("")
        box.scroll_end(animate=False)
        self._set_status("● 思考中...", "italic #e0af68")

    def _update_preview(self, reply: str) -> None:
        self.query_one("#stream-text", Static).update(reply)
        self.query_one("#stream-box", VerticalScroll).scroll_end(animate=False)

    def _hide_stream(self) -> None:
        self.query_one("#stream-box", VerticalScroll).remove_class("visible")

    def _finish_reply(self, reply: str) -> None:
        self._busy = False
        self._hide_stream()
        if reply.strip():
            self._write_agent_message(reply)
        else:
            self._write_block(Text("  (空回复)", style="dim"))
        self._set_status("● 就绪", "italic #9ece6a")
        self._update_context_bar()
        self._refresh_sidebar()
        self._focus_input()

    def _finish_error(self, exc: Exception) -> None:
        self._busy = False
        self._hide_stream()
        self._write_block(
            Panel(
                Text(str(exc), style="#f7768e"),
                title=" 出错了 ",
                title_align="left",
                border_style="#f7768e",
                padding=(0, 1),
            )
        )
        self._set_status("● 出错", "italic #f7768e")
        self._update_context_bar()
        self._focus_input()

    def _finish_compaction(self, result: dict) -> None:
        self._compacting = False
        self._context_warned = False
        self.query_one("#input", CommandInput).disabled = False
        self._write_block(
            Panel(
                Text(
                    (
                        f" 上下文压缩完成，归档编号：{result['archive_id']}\n"
                        f" 归档文件：{result['archive_path']}"
                    ),
                    style="#9ece6a",
                ),
                title=" 压缩完成 ",
                title_align="left",
                border_style="#9ece6a",
                padding=(0, 1),
            )
        )
        self._set_status("● 就绪", "italic #9ece6a")
        self._update_context_bar()
        self.push_screen(
            CompactionModal(
                result["original"], result["summary"], result["archive_id"]
            ),
            lambda _result: self._focus_input(),
        )

    def _finish_compaction_error(self, exc: Exception) -> None:
        self._compacting = False
        self.query_one("#input", CommandInput).disabled = False
        self._write_block(
            Panel(
                Text(
                    (
                        f" 上下文压缩失败：{exc}\n"
                        " 原有上下文已保留，可以重新执行 /compact。"
                    ),
                    style="#f7768e",
                ),
                title=" 压缩失败 ",
                title_align="left",
                border_style="#f7768e",
                padding=(0, 1),
            )
        )
        self._set_status("● 压缩失败", "italic #f7768e")
        self._update_context_bar()
        self._focus_input()

    @work(thread=True)
    def load_mcp(self) -> None:
        try:
            self.agent.start_mcp()
        finally:
            try:
                self.call_from_thread(self._finish_mcp_load)
            except Exception:
                pass

    def _finish_mcp_load(self) -> None:
        self._refresh_sidebar()
        self._write_mcp_errors()
        if not self._busy and not self._compacting:
            self._set_status("● 就绪", "italic #9ece6a")

    @work(thread=True)
    def stream_reply(self, user_text: str) -> None:
        reply = ""
        last_update = 0.0
        try:
            for chunk in self.agent.run_turn(user_text):
                reply += chunk
                now = time.monotonic()
                if now - last_update >= 0.05:
                    last_update = now
                    self.call_from_thread(self._update_preview, reply)
            self.call_from_thread(self._finish_reply, reply)
        except Exception as exc:
            self.call_from_thread(self._finish_error, exc)

    @work(thread=True)
    def compact_context(self) -> None:
        try:
            result = self.agent.compact()
        except Exception as exc:
            self.call_from_thread(self._finish_compaction_error, exc)
        else:
            self.call_from_thread(self._finish_compaction, result)
