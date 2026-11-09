import configparser
from pathlib import Path

from openai import OpenAI

DEFAULT_VALUES = {
    "llm": {
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "your-model-name",
        "api_key": "DUMMY",
        "context_window": "auto",
        "default_context_window": "131072",
        "request_timeout": "600",
        "summary_reasoning_effort": "none",
    },
    "agent": {
        "name": "jagent",
    },
    "ui": {
        "title": "jagent",
        "sub_title": "本地大模型终端助手",
        "theme": "tokyo-night",
        "sidebar_width": "38",
        "autocomplete_enabled": "true",
        "command_panel_max_items": "12",
    },
    "context": {
        "archive_dir": ".agents/context",
        "warning_ratio": "0.6",
        "summary_target_tokens": "5000",
        "max_results": "8",
        "max_chars": "6000",
        "snippet_radius": "180",
    },
    "sessions": {
        "dir": ".agents/sessions",
        "autosave_on_quit": "true",
        "autosave_on_new": "true",
        "autosave_after_turn": "true",
        "title_length": "60",
    },
    "mcp": {
        "enabled": "true",
        "config_path": ".mcp.json",
        "connect_timeout": "30",
        "call_timeout": "60",
        "max_tool_name_length": "64",
    },
    "tools": {
        "cli_timeout": "30",
        "cli_max_timeout": "300",
        "cli_max_output_chars": "4000",
        "web_timeout": "30",
        "web_connect_timeout": "10",
        "web_max_summary_chars": "600",
        "search_api_url": "https://qianfan.baidubce.com/v2/ai_search/web_search",
        "search_top_k": "10",
        "search_timeout": "30",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    },
    "skills": {
        "dir": ".agents/skills",
        "max_name_length": "64",
        "max_description_length": "1024",
    },
    "agents": {
        "enabled": "true",
        "file": "AGENTS.md",
    },
    "search": {
        "baidu_qianfan_api_key": "",
    },
}

CONFIG_TEMPLATE = """# jagent configuration
# The values below are mock defaults. Update them before using a real model
# or online search. Restart jagent after editing this file.

[llm]
base_url = http://127.0.0.1:1234/v1
model = your-model-name
api_key = DUMMY
context_window = auto
default_context_window = 131072
request_timeout = 600
summary_reasoning_effort = none

[agent]
name = jagent

[ui]
title = jagent
sub_title = 本地大模型终端助手
theme = tokyo-night
sidebar_width = 38
autocomplete_enabled = true
command_panel_max_items = 12

[context]
archive_dir = .agents/context
warning_ratio = 0.6
summary_target_tokens = 5000
max_results = 8
max_chars = 6000
snippet_radius = 180

[sessions]
dir = .agents/sessions
autosave_on_quit = true
autosave_on_new = true
autosave_after_turn = true
title_length = 60

[mcp]
enabled = true
config_path = .mcp.json
connect_timeout = 30
call_timeout = 60
max_tool_name_length = 64

[tools]
cli_timeout = 30
cli_max_timeout = 300
cli_max_output_chars = 4000
web_timeout = 30
web_connect_timeout = 10
web_max_summary_chars = 600
search_api_url = https://qianfan.baidubce.com/v2/ai_search/web_search
search_top_k = 10
search_timeout = 30
user_agent = Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36

[skills]
dir = .agents/skills
max_name_length = 64
max_description_length = 1024

[agents]
enabled = true
file = AGENTS.md

[search]
baidu_qianfan_api_key = YOUR_SEARCH_API_KEY
"""


class Config:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = (
            Path(config_path).expanduser().resolve()
            if config_path is not None
            else (Path.cwd() / "config.ini").resolve()
        )
        self.project_root = self.config_path.parent
        self.was_created = not self.config_path.is_file()
        if self.was_created:
            self.config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")

        self.config = configparser.ConfigParser(interpolation=None)
        self.config.read(self.config_path, encoding="utf-8-sig")
        self._apply_defaults()
        self.llm = self.config["llm"]

    def _apply_defaults(self) -> None:
        for section, values in DEFAULT_VALUES.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
            for key, value in values.items():
                if not self.config.has_option(section, key):
                    self.config.set(section, key, str(value))

    def get(self, section: str, option: str, fallback: str = "") -> str:
        return self.config.get(section, option, fallback=fallback).strip()

    def get_int(self, section: str, option: str, fallback: int) -> int:
        try:
            return int(float(self.get(section, option, str(fallback))))
        except (TypeError, ValueError):
            return fallback

    def get_float(self, section: str, option: str, fallback: float) -> float:
        try:
            return float(self.get(section, option, str(fallback)))
        except (TypeError, ValueError):
            return fallback

    def get_bool(self, section: str, option: str, fallback: bool) -> bool:
        raw = self.get(section, option, "true" if fallback else "false").lower()
        return raw in ("1", "true", "yes", "on")

    def get_path(self, section: str, option: str, fallback: str) -> Path:
        raw = self.get(section, option, fallback)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def get_client(self) -> OpenAI:
        timeout = self.get_float("llm", "request_timeout", 600.0)
        return OpenAI(
            base_url=self.get("llm", "base_url"),
            api_key=self.get("llm", "api_key") or "DUMMY",
            timeout=timeout if timeout > 0 else None,
        )

    def get_model(self) -> str:
        return self.get("llm", "model", "your-model-name")

    def get_search_api_key(self) -> str:
        return self.get("search", "baidu_qianfan_api_key")

    def get_context_window(self) -> tuple[int, bool]:
        default_window = max(
            1, self.get_int("llm", "default_context_window", 128 * 1024)
        )
        raw = self.get("llm", "context_window")
        if not raw:
            return default_window, True

        value = raw.lower().replace(",", "").replace("_", "").strip()
        multiplier = 1
        if value.endswith("k"):
            multiplier = 1024
            value = value[:-1].strip()
        elif value.endswith("m"):
            multiplier = 1024 * 1024
            value = value[:-1].strip()
        try:
            number = float(value)
        except ValueError:
            return default_window, True
        if number <= 0:
            return default_window, True
        return int(number * multiplier), False

    def get_warning_ratio(self) -> float:
        ratio = self.get_float("context", "warning_ratio", 0.6)
        if ratio > 1:
            ratio = ratio / 100
        return min(max(ratio, 0.01), 0.99)

    def get_summary_target_tokens(self) -> int:
        return max(200, self.get_int("context", "summary_target_tokens", 5000))

    def get_context_max_results(self) -> int:
        return max(1, self.get_int("context", "max_results", 8))

    def get_context_max_chars(self) -> int:
        return max(200, self.get_int("context", "max_chars", 6000))

    def get_context_snippet_radius(self) -> int:
        return max(20, self.get_int("context", "snippet_radius", 180))

    def get_archive_dir(self) -> Path:
        return self.get_path("context", "archive_dir", ".agents/context")

    def get_sessions_dir(self) -> Path:
        return self.get_path("sessions", "dir", ".agents/sessions")

    def get_autosave_on_quit(self) -> bool:
        return self.get_bool("sessions", "autosave_on_quit", True)

    def get_autosave_on_new(self) -> bool:
        return self.get_bool("sessions", "autosave_on_new", True)

    def get_autosave_after_turn(self) -> bool:
        return self.get_bool("sessions", "autosave_after_turn", True)

    def get_sessions_title_length(self) -> int:
        return max(10, self.get_int("sessions", "title_length", 60))

    def get_mcp_enabled(self) -> bool:
        return self.get_bool("mcp", "enabled", True)

    def get_mcp_config_path(self) -> Path:
        return self.get_path("mcp", "config_path", ".mcp.json")

    def get_mcp_connect_timeout(self) -> float:
        return max(1.0, self.get_float("mcp", "connect_timeout", 30.0))

    def get_mcp_call_timeout(self) -> float:
        return max(1.0, self.get_float("mcp", "call_timeout", 60.0))

    def get_mcp_max_tool_name_length(self) -> int:
        return max(8, self.get_int("mcp", "max_tool_name_length", 64))

    def get_skills_dir(self) -> Path:
        return self.get_path("skills", "dir", ".agents/skills")

    def get_skills_max_name_length(self) -> int:
        return max(1, self.get_int("skills", "max_name_length", 64))

    def get_skills_max_description_length(self) -> int:
        return max(1, self.get_int("skills", "max_description_length", 1024))

    def get_agents_enabled(self) -> bool:
        return self.get_bool("agents", "enabled", True)

    def get_agents_path(self) -> Path:
        return self.get_path("agents", "file", "AGENTS.md")

    def get_cli_timeout(self) -> int:
        return max(1, self.get_int("tools", "cli_timeout", 30))

    def get_cli_max_timeout(self) -> int:
        return max(
            self.get_cli_timeout(), self.get_int("tools", "cli_max_timeout", 300)
        )

    def get_cli_max_output_chars(self) -> int:
        return max(100, self.get_int("tools", "cli_max_output_chars", 4000))

    def get_web_timeout(self) -> int:
        return max(1, self.get_int("tools", "web_timeout", 30))

    def get_web_connect_timeout(self) -> int:
        return max(1, self.get_int("tools", "web_connect_timeout", 10))

    def get_web_max_summary_chars(self) -> int:
        return max(80, self.get_int("tools", "web_max_summary_chars", 600))

    def get_search_api_url(self) -> str:
        return self.get(
            "tools",
            "search_api_url",
            "https://qianfan.baidubce.com/v2/ai_search/web_search",
        )

    def get_search_top_k(self) -> int:
        return max(1, min(self.get_int("tools", "search_top_k", 10), 20))

    def get_search_timeout(self) -> int:
        return max(1, self.get_int("tools", "search_timeout", 30))

    def get_user_agent(self) -> str:
        return self.get("tools", "user_agent", DEFAULT_VALUES["tools"]["user_agent"])

    def get_summary_reasoning_effort(self) -> str:
        return self.get("llm", "summary_reasoning_effort", "none")

    def get_agent_name(self) -> str:
        return self.get("agent", "name", "jagent")

    def get_ui_title(self) -> str:
        return self.get("ui", "title", "jagent")

    def get_ui_sub_title(self) -> str:
        return self.get("ui", "sub_title", "本地大模型终端助手")

    def get_ui_theme(self) -> str:
        return self.get("ui", "theme", "tokyo-night")

    def get_ui_sidebar_width(self) -> int:
        return max(20, min(self.get_int("ui", "sidebar_width", 38), 80))

    def get_ui_autocomplete_enabled(self) -> bool:
        return self.get_bool("ui", "autocomplete_enabled", True)

    def get_ui_command_panel_max_items(self) -> int:
        return max(1, min(self.get_int("ui", "command_panel_max_items", 12), 30))
