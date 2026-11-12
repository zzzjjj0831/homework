"""文件/目录工具的路径边界策略。

所有读写操作先过 PathPolicy：
- 相对路径一律相对"工作区根目录"解析，不随进程 cwd 漂移
- 解析后必须落在工作区内，否则返回 OUTSIDE_WORKSPACE（不做静默放行）
- 破坏性操作（删除/重命名）禁止作用于工作区根目录本身
- 需要访问外部目录时必须显式配置 tools.allow_outside_workspace = true

这是"路径白名单"的实现，默认拒绝而不是默认允许。
"""

from __future__ import annotations

import os
from pathlib import Path

from .envelope import ToolError


def _same_or_child(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return os.path.normcase(str(target)).startswith(
            os.path.normcase(str(root)) + os.sep
        )


class PathPolicy:
    def __init__(self, root: Path | str | None = None, allow_outside: bool = False):
        self.root = (
            Path(root).expanduser().resolve() if root is not None else Path.cwd().resolve()
        )
        self.allow_outside = bool(allow_outside)

    def resolve(self, raw: str | None, default: str | None = None) -> Path:
        text = (raw or "").strip()
        if not text:
            if default is None:
                raise ToolError("INVALID_PATH", "路径不能为空")
            text = default
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise ToolError("INVALID_PATH", f"无法解析路径：{exc}", path=text) from exc
        if not self.allow_outside and not _same_or_child(resolved, self.root):
            raise ToolError(
                "OUTSIDE_WORKSPACE",
                "路径超出工作区范围，已拒绝访问",
                path=str(resolved),
                workspace=str(self.root),
                hint="把目标移入工作区，或在 config.ini 里显式设置 tools.allow_outside_workspace = true",
            )
        return resolved

    def check_destructive(self, target: Path) -> None:
        if target == self.root:
            raise ToolError(
                "FORBIDDEN_TARGET",
                "拒绝对工作区根目录本身执行删除/重命名",
                path=str(target),
            )

    def relative(self, target: Path) -> str:
        try:
            return target.relative_to(self.root).as_posix()
        except ValueError:
            return str(target)
