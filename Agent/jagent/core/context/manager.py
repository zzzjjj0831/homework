import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_MAX_RESULTS = 8
DEFAULT_MAX_CHARS = 6000
SNIPPET_RADIUS = 180


def estimate_text_tokens(text: str) -> int:
    """Rough token estimate: CJK characters count as one token, others ~4 chars/token."""
    if not text:
        return 0
    cjk = 0
    for char in text:
        codepoint = ord(char)
        if (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
        ):
            cjk += 1
    other = len(text) - cjk
    return cjk + math.ceil(other / 4)


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(by_alias=True, exclude_none=True)
        except TypeError:
            return value.model_dump()
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def estimate_messages_tokens(messages: List[Any]) -> int:
    total = 0
    for message in messages:
        serialized = json.dumps(to_jsonable(message), ensure_ascii=False, default=str)
        total += estimate_text_tokens(serialized) + 4
    return total


class ContextManager:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        archive_dir: Optional[Path] = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        max_chars: int = DEFAULT_MAX_CHARS,
        snippet_radius: int = SNIPPET_RADIUS,
    ):
        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else Path.cwd().resolve()
        )
        self.archive_dir = (
            Path(archive_dir).expanduser().resolve()
            if archive_dir is not None
            else self.project_root / ".agents" / "context"
        )
        self.max_results = max_results
        self.max_chars = max_chars
        self.snippet_radius = max(20, int(snippet_radius))

    def archive(self, history: List[Any]) -> Dict[str, Any]:
        now = datetime.now()
        archive_id = self._new_archive_id(now)
        path = self.archive_dir / f"{archive_id}.jsonl"

        lines = [
            json.dumps(to_jsonable(message), ensure_ascii=False, default=str)
            for message in history
        ]
        content = "\n".join(lines) + "\n"
        self._atomic_write(path, content)

        return {
            "id": archive_id,
            "path": path,
            "created_at": now,
            "transcript": self.render_transcript(history),
        }

    def _new_archive_id(self, now: datetime) -> str:
        base = now.strftime("%Y%m%d-%H%M%S")
        candidate = base
        index = 1
        while (self.archive_dir / f"{candidate}.jsonl").exists():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        if not path.is_file() or path.stat().st_size == 0:
            raise OSError(f"failed to save context archive: {path}")

    @staticmethod
    def render_transcript(history: List[Any]) -> str:
        parts: List[str] = []
        for index, message in enumerate(history, start=1):
            data = to_jsonable(message)
            if not isinstance(data, dict):
                data = {"content": data}
            role = data.get("role", "unknown")
            parts.append(f"### 消息 {index} · {role}")

            content = data.get("content")
            if isinstance(content, str):
                if content:
                    parts.append(content)
            elif content is not None:
                parts.append(json.dumps(content, ensure_ascii=False, default=str))

            if data.get("name"):
                parts.append(f"name: {data['name']}")
            if data.get("tool_call_id"):
                parts.append(f"tool_call_id: {data['tool_call_id']}")
            if data.get("tool_calls"):
                parts.append(
                    "tool_calls:\n"
                    + json.dumps(
                        data["tool_calls"], ensure_ascii=False, indent=2, default=str
                    )
                )
            parts.append("")
        return "\n".join(parts).strip()

    def list_archives(self) -> List[str]:
        if not self.archive_dir.is_dir():
            return []
        return sorted(path.stem for path in self.archive_dir.glob("*.jsonl"))

    def search(
        self,
        text: str,
        archive_id: Optional[str] = None,
        max_results: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> str:
        query = (text or "").strip()
        if not query:
            return json.dumps({"error": "text 不能为空"}, ensure_ascii=False)

        archives = self._resolve_archives(archive_id)
        if not archives:
            payload: Dict[str, Any] = {
                "error": f"未找到上下文归档: {archive_id}",
                "query": query,
                "available": self.list_archives()[:20],
            }
            return json.dumps(payload, ensure_ascii=False)

        terms = self._query_terms(query)
        results: List[Dict[str, Any]] = []
        for path in archives:
            try:
                lines = path.read_text(encoding="utf-8-sig").splitlines()
            except (OSError, UnicodeError) as exc:
                results.append(
                    {
                        "archive_id": path.stem,
                        "error": f"failed to read archive: {type(exc).__name__}: {exc}",
                    }
                )
                continue

            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                display = self._message_text(message)
                lowered = display.lower()
                score = sum(lowered.count(term.lower()) for term in terms)
                if score <= 0:
                    continue
                snippet = self._make_snippet(display, query, terms)
                results.append(
                    {
                        "archive_id": path.stem,
                        "location": f"{path.stem}:{line_number}",
                        "line": line_number,
                        "role": message.get("role", "unknown")
                        if isinstance(message, dict)
                        else "unknown",
                        "score": score,
                        "snippet": snippet,
                    }
                )

        results.sort(
            key=lambda item: (
                -int(item.get("score", 0)),
                str(item.get("archive_id", "")),
                int(item.get("line", 0)),
            )
        )
        selected, truncated = self._limit_results(
            results,
            max_results if max_results is not None else self.max_results,
            max_chars if max_chars is not None else self.max_chars,
        )

        if not selected:
            return json.dumps(
                {
                    "query": query,
                    "archives_searched": [path.stem for path in archives],
                    "matches": [],
                    "message": "未找到匹配内容",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "query": query,
                "archives_searched": [path.stem for path in archives],
                "matches": selected,
                "total_matches": len(results),
                "truncated": truncated,
            },
            ensure_ascii=False,
        )

    def _resolve_archives(self, archive_id: Optional[str]) -> List[Path]:
        if archive_id is not None and str(archive_id).strip():
            identifier = Path(str(archive_id).strip()).name
            if identifier.endswith(".jsonl"):
                identifier = identifier[:-6]
            path = self.archive_dir / f"{identifier}.jsonl"
            return [path] if path.is_file() else []
        if not self.archive_dir.is_dir():
            return []
        return sorted(self.archive_dir.glob("*.jsonl"))

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        terms = {query}
        for part in re.split(r"\s+", query):
            if part:
                terms.add(part)
        return [term for term in terms if term]

    @staticmethod
    def _message_text(message: Any) -> str:
        if not isinstance(message, dict):
            return json.dumps(message, ensure_ascii=False, default=str)
        parts = [f"role: {message.get('role', 'unknown')}"]
        content = message.get("content")
        if isinstance(content, str):
            if content:
                parts.append(content)
        elif content is not None:
            parts.append(json.dumps(content, ensure_ascii=False, default=str))
        if message.get("name"):
            parts.append(f"name: {message['name']}")
        if message.get("tool_call_id"):
            parts.append(f"tool_call_id: {message['tool_call_id']}")
        if message.get("tool_calls"):
            parts.append(
                "tool_calls: "
                + json.dumps(message["tool_calls"], ensure_ascii=False, default=str)
            )
        return "\n".join(parts)

    def _make_snippet(self, text: str, query: str, terms: List[str]) -> str:
        lowered = text.lower()
        positions = [lowered.find(query.lower())]
        positions.extend(lowered.find(term.lower()) for term in terms)
        valid = [position for position in positions if position >= 0]
        if not valid:
            return text[: self.snippet_radius * 2]
        index = min(valid)
        start = max(0, index - self.snippet_radius)
        end = min(len(text), index + self.snippet_radius * 2)
        prefix = "... " if start > 0 else ""
        suffix = " ..." if end < len(text) else ""
        return f"{prefix}{text[start:end]}{suffix}"

    @staticmethod
    def _limit_results(
        results: List[Dict[str, Any]], max_results: int, max_chars: int
    ):
        selected: List[Dict[str, Any]] = []
        used_chars = 0
        for item in results:
            if "error" in item:
                selected.append(item)
                continue
            if len(selected) >= max_results or used_chars >= max_chars:
                break
            snippet = str(item.get("snippet", ""))
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            if len(snippet) > remaining:
                snippet = snippet[:remaining] + " ..."
            limited = dict(item)
            limited["snippet"] = snippet
            selected.append(limited)
            used_chars += len(snippet) + len(str(item.get("location", ""))) + 20
        return selected, len(selected) < len(results)
