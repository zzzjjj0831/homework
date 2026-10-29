from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, Input, RichLog

from core.agent.agent_core import AgentCore


class JagAgentApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #log {
        height: 1fr;
        border: tall $accent;
    }
    #input {
        dock: bottom;
    }
    """

    def __init__(self):
        super().__init__()
        self.agent = AgentCore()

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="log", markup=True, auto_scroll=True)
        yield Input(placeholder="请输入问题，按回车发送...", id="input")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[bold green]jagent TUI 已启动，按 Ctrl+C 或 Ctrl+Q 退出[/bold green]")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value
        if not user_text:
            return
        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        log = self.query_one("#log", RichLog)
        log.write(f"[bold cyan]你:[/bold cyan] {user_text}")
        log.write("[bold yellow]Agent:[/bold yellow] ", end="")
        for chunk in self.agent.run_turn(user_text):
            log.write(chunk, end="")
        log.write("")
