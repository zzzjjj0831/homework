from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    aliases: Tuple[str, ...] = ()

    @property
    def all_names(self) -> Tuple[str, ...]:
        return (self.name, *self.aliases)


COMMANDS: Tuple[SlashCommand, ...] = (
    SlashCommand("/help", "显示所有斜杠命令和快捷键"),
    SlashCommand("/new", "新建会话，并自动保存当前会话历史"),
    SlashCommand("/resume", "打开历史会话列表并恢复选中的会话"),
    SlashCommand("/save", "保存当前会话到事件日志"),
    SlashCommand("/compact", "压缩当前上下文并生成工作摘要"),
    SlashCommand("/context", "查看上下文占用和会话状态"),
    SlashCommand("/clear", "清空对话显示区域"),
    SlashCommand("/tools", "查看当前可用的全部工具"),
    SlashCommand("/mcp", "查看已连接 MCP 服务器和可用 tools"),
    SlashCommand("/agents", "查看 AGENTS.md 注入状态"),
    SlashCommand("/model", "查看当前模型和关键配置"),
    SlashCommand("/quit", "保存当前会话并退出程序", aliases=("/exit",)),
)


def resolve_command(value: str) -> Optional[SlashCommand]:
    token = (value or "").strip().split(maxsplit=1)[0].lower()
    if not token:
        return None
    for command in COMMANDS:
        if token == command.name or token in command.aliases:
            return command
    return None


def suggest_commands(prefix: str) -> List[SlashCommand]:
    prefix = (prefix or "").strip().lower()
    if not prefix.startswith("/") or " " in prefix or "\t" in prefix:
        return []
    matches = [
        command
        for command in COMMANDS
        if any(name.startswith(prefix) for name in command.all_names)
    ]
    matches.sort(
        key=lambda command: 0
        if command.name == prefix or prefix in command.aliases
        else 1
    )
    return matches


def alias_text(command: SlashCommand) -> str:
    if not command.aliases:
        return ""
    return f"  (别名: {', '.join(command.aliases)})"
