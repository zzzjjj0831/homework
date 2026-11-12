"""本地文件/目录操作工具。

设计要点：
- 每次调用都真实产生文件系统副作用（无占位实现）
- 所有路径先过 PathPolicy，默认限制在工作区内
- 失败统一返回 {ok: false, error: {code, message}}，不裸抛异常
- 破坏性操作（删除/重命名）默认要求 confirm=True，避免模型"顺手删库"
- 读文件支持 offset/limit 分段，避免一次性把大文件塞进上下文
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .envelope import ToolError, ok
from .paths import PathPolicy

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
DEFAULT_READ_LIMIT = 20000
MAX_READ_LIMIT = 200000


def _policy(policy: PathPolicy | None) -> PathPolicy:
    return policy if policy is not None else PathPolicy()


def _fail(exc: Exception) -> str:
    if isinstance(exc, ToolError):
        return exc.to_json()
    return json.dumps(
        {"ok": False, "error": {"code": "TOOL_FAILED", "message": f"{type(exc).__name__}: {exc}"}},
        ensure_ascii=False,
    )


def get_date() -> str:
    """返回当前日期与时间（本地时区），不依赖 shell 的 date 命令。"""
    try:
        now = datetime.now().astimezone()
        return ok(
            iso=now.isoformat(timespec="seconds"),
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            weekday=WEEKDAYS[now.weekday()],
            timezone=now.strftime("%Z") or now.strftime("%z"),
            utc_offset=now.strftime("%z"),
            timestamp=int(now.timestamp()),
        )
    except Exception as exc:  # pragma: no cover - 系统时钟异常才会走到
        return _fail(exc)


def is_leap_year(year: int) -> str:
    """闰年判定：能被 4 整除，但整百年必须被 400 整除。"""
    try:
        if isinstance(year, bool) or year is None:
            raise ToolError("INVALID_ARGUMENT", "year 必须是整数", year=year)
        if isinstance(year, str) and year.strip().lstrip("+-").isdigit():
            year = int(year.strip())
        if not isinstance(year, int):
            raise ToolError("INVALID_ARGUMENT", "year 必须是整数", year=year)
        if year < -4712 or year > 9999:
            raise ToolError("INVALID_ARGUMENT", "year 超出可判定范围（-4712 ~ 9999）", year=year)
        is_leap = year % 400 == 0 if year % 100 == 0 else year % 4 == 0
        return ok(year=year, isLeapYear=is_leap, rule="4 年一闰，百年不闰，400 年再闰")
    except Exception as exc:
        return _fail(exc)


def get_current_working_directory() -> str:
    try:
        cwd = Path.cwd()
        return ok(cwd=str(cwd), drive=cwd.drive or None)
    except Exception as exc:
        return _fail(exc)


def list_directory(path: str = ".", policy: PathPolicy | None = None) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path, default=".")
        if not target.exists():
            raise ToolError("NOT_FOUND", f"路径不存在：{path}", path=str(target))
        if not target.is_dir():
            raise ToolError("NOT_A_DIRECTORY", f"不是目录：{path}", path=str(target))
        entries = []
        for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            entry_info = {
                "name": entry.name,
                "type": "dir" if entry.is_dir() else ("link" if entry.is_symlink() else "file"),
                "size": entry.stat().st_size if entry.is_file() else None,
            }
            entries.append(entry_info)
        return ok(
            path=str(target),
            relative_path=guard.relative(target),
            count=len(entries),
            entries=entries,
        )
    except Exception as exc:
        return _fail(exc)


def get_file_type(path: str, policy: PathPolicy | None = None) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path)
        if not target.exists():
            raise ToolError("NOT_FOUND", f"路径不存在：{path}", path=str(target))
        if target.is_dir():
            kind = "directory"
        elif target.is_symlink():
            kind = "link"
        elif target.is_file():
            kind = "file"
        else:
            kind = "other"
        suffix = target.suffix
        return ok(
            path=str(target),
            type=kind,
            extension=suffix or None,
            readable=target.is_file() or target.is_dir(),
        )
    except Exception as exc:
        return _fail(exc)


def get_file_content(
    path: str,
    offset: int = 0,
    max_chars: int = DEFAULT_READ_LIMIT,
    policy: PathPolicy | None = None,
) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path)
        if not target.exists():
            raise ToolError("NOT_FOUND", f"文件不存在：{path}", path=str(target))
        if not target.is_file():
            raise ToolError("NOT_A_FILE", f"不是文件：{path}", path=str(target))
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise ToolError(
                "NOT_TEXT", "不是可解码的 UTF-8 文本文件", path=str(target)
            ) from exc

        total = len(content)
        if offset < 0:
            raise ToolError("INVALID_ARGUMENT", "offset 不能为负", offset=offset)
        limit = max(200, min(int(max_chars), MAX_READ_LIMIT))
        window = content[offset : offset + limit]
        truncated = offset + len(window) < total
        return ok(
            path=str(target),
            range=[offset, offset + len(window)],
            total_chars=total,
            truncated=truncated,
            next_offset=offset + len(window) if truncated else None,
            content=window,
        )
    except Exception as exc:
        return _fail(exc)


def create_file(
    dir_path: str,
    file_name: str,
    content: str = "",
    overwrite: bool = False,
    policy: PathPolicy | None = None,
) -> str:
    try:
        guard = _policy(policy)
        directory = guard.resolve(dir_path, default=".")
        clean_name = (file_name or "").strip()
        if not clean_name or Path(clean_name).name != clean_name:
            raise ToolError(
                "INVALID_ARGUMENT",
                "file_name 必须是纯文件名，不能带路径分隔符",
                file_name=file_name,
            )
        target = guard.resolve(str(directory / clean_name))
        if target.exists() and target.is_dir():
            raise ToolError("IS_DIRECTORY", f"同名目录已存在：{target}", path=str(target))
        if target.exists() and not overwrite:
            raise ToolError(
                "FILE_EXISTS",
                "目标文件已存在，默认不覆盖；如确认覆盖请带 overwrite=true",
                path=str(target),
            )
        directory.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ok(
            path=str(target),
            relative_path=guard.relative(target),
            bytes_written=len(content.encode("utf-8")),
            created=True,
            overwritten=bool(overwrite),
        )
    except Exception as exc:
        return _fail(exc)


def edit_file(
    path: str,
    content: str,
    mode: str = "replace",
    policy: PathPolicy | None = None,
) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path)
        if not target.exists():
            raise ToolError("NOT_FOUND", f"文件不存在：{path}", path=str(target))
        if not target.is_file():
            raise ToolError("NOT_A_FILE", f"不是文件：{path}", path=str(target))
        if mode not in ("replace", "append"):
            raise ToolError("INVALID_ARGUMENT", "mode 只支持 replace 或 append", mode=mode)
        if mode == "append":
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            target.write_text(content, encoding="utf-8")
        return ok(
            path=str(target),
            relative_path=guard.relative(target),
            mode=mode,
            bytes_written=len(content.encode("utf-8")),
            size=target.stat().st_size,
        )
    except Exception as exc:
        return _fail(exc)


def create_directory(path: str, policy: PathPolicy | None = None) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path)
        if target.exists():
            if target.is_dir():
                raise ToolError("DIR_EXISTS", f"目录已存在：{path}", path=str(target))
            raise ToolError("FILE_EXISTS", f"同名文件已存在：{path}", path=str(target))
        target.mkdir(parents=True, exist_ok=True)
        return ok(path=str(target), relative_path=guard.relative(target), created=True)
    except Exception as exc:
        return _fail(exc)


def remove_directory(
    path: str,
    recursive: bool = False,
    confirm: bool = False,
    policy: PathPolicy | None = None,
) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path)
        if not target.exists():
            raise ToolError("NOT_FOUND", f"路径不存在：{path}", path=str(target))
        if not target.is_dir():
            raise ToolError("NOT_A_DIRECTORY", f"不是目录：{path}", path=str(target))
        guard.check_destructive(target)
        if not confirm:
            raise ToolError(
                "CONFIRM_REQUIRED",
                "删除目录属于破坏性操作：确认后请用 confirm=true 重新调用",
                path=str(target),
                recursive=bool(recursive),
            )
        if recursive:
            shutil.rmtree(target)
            return ok(path=str(target), removed=True, recursive=True)
        try:
            target.rmdir()
        except OSError as exc:
            raise ToolError(
                "DIRECTORY_NOT_EMPTY",
                "目录非空；如需连同子项删除请使用 recursive=true",
                path=str(target),
            ) from exc
        return ok(path=str(target), removed=True, recursive=False)
    except Exception as exc:
        return _fail(exc)


def remove_file(
    path: str, confirm: bool = False, policy: PathPolicy | None = None
) -> str:
    try:
        guard = _policy(policy)
        target = guard.resolve(path)
        if not target.exists():
            raise ToolError("NOT_FOUND", f"文件不存在：{path}", path=str(target))
        if not target.is_file():
            raise ToolError("NOT_A_FILE", f"不是文件：{path}", path=str(target))
        guard.check_destructive(target)
        if not confirm:
            raise ToolError(
                "CONFIRM_REQUIRED",
                "删除文件属于破坏性操作：确认后请用 confirm=true 重新调用",
                path=str(target),
            )
        target.unlink()
        return ok(path=str(target), removed=True)
    except Exception as exc:
        return _fail(exc)


def rename_path(
    old_path: str,
    new_path: str,
    confirm: bool = False,
    policy: PathPolicy | None = None,
) -> str:
    try:
        guard = _policy(policy)
        source = guard.resolve(old_path)
        target = guard.resolve(new_path)
        if not source.exists():
            raise ToolError("NOT_FOUND", f"源路径不存在：{old_path}", path=str(source))
        guard.check_destructive(source)
        if target.exists():
            raise ToolError("DEST_EXISTS", f"目标已存在：{new_path}", path=str(target))
        if not confirm:
            raise ToolError(
                "CONFIRM_REQUIRED",
                "重命名/移动属于破坏性操作：确认后请用 confirm=true 重新调用",
                source=str(source),
                target=str(target),
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return ok(
            source=str(source),
            target=str(target),
            relative_target=guard.relative(target),
            renamed=True,
        )
    except Exception as exc:
        return _fail(exc)
