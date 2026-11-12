"""结构化日志初始化。

写文件（默认 .agents/logs/jagent.log，按大小轮转）+ 控制台只输出 WARNING 以上，
避免 TUI 画面被日志打断；行格式为 key=value，便于 grep 与后续统计。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s level=%(levelname)s logger=%(name)s %(message)s"
_CONFIGURED = False


def setup_logging(log_path: Path | str, level: str = "INFO") -> Path | None:
    """初始化根日志。返回实际写入的日志文件路径（初始化失败时返回 None）。"""
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED:
        return None
    _CONFIGURED = True

    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT)

    stream = logging.StreamHandler(stream=sys.stderr)
    stream.setFormatter(formatter)
    stream.setLevel(logging.WARNING)
    root.addHandler(stream)

    try:
        path = Path(log_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG)
        root.addHandler(handler)
        return path
    except OSError:
        # 日志目录不可写不应阻断主流程
        root.warning("log file unavailable, fallback to stderr only")
        return None
