import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.context.manager import to_jsonable

AGENTS_MD_MARKER = "<!-- AGENTS.md -->"


def is_agents_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith(AGENTS_MD_MARKER)


def _content_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    return ""


@dataclass
class SessionInfo:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    path: Path
    preview: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "path": str(self.path),
            "preview": self.preview,
        }


class SessionManager:
    def __init__(
        self,
        project_root: Optional[Path] = None,
        sessions_dir: Optional[Path] = None,
        title_length: int = 60,
    ):
        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else Path.cwd().resolve()
        )
        self.sessions_dir = (
            Path(sessions_dir).expanduser().resolve()
            if sessions_dir is not None
            else self.project_root / ".agents" / "sessions"
        )
        self.title_length = max(10, int(title_length))

    def new_session_id(self) -> str:
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        index = 1
        while self.path_for(candidate).exists():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def path_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{self._safe_id(session_id)}.jsonl"

    def save(
        self,
        session_id: str,
        history: List[Any],
        title: str,
        model: str,
        cwd: str,
        agents_md_injected: bool,
        visible: bool,
    ) -> Dict[str, Any]:
        session_id = self._safe_id(session_id)
        path = self.path_for(session_id)
        now = datetime.now()
        created_at = self._existing_created_at(path) or now.isoformat(timespec="seconds")
        saved_at = now.isoformat(timespec="seconds")
        title = (title or self.derive_title(history)).strip() or "未命名会话"

        events: List[Dict[str, Any]] = [
            {
                "type": "session",
                "id": session_id,
                "created_at": created_at,
                "cwd": cwd,
                "model": model,
            },
            {
                "type": "meta",
                "saved_at": saved_at,
                "title": title,
                "message_count": len(history),
                "agents_md_injected": bool(agents_md_injected),
                "visible": bool(visible),
            },
        ]
        for message in history:
            source = "agents_md" if is_agents_message(message) else None
            events.append(
                {
                    "type": "message",
                    "timestamp": saved_at,
                    "source": source,
                    "message": to_jsonable(message),
                }
            )

        content = "\n".join(
            json.dumps(event, ensure_ascii=False, default=str) for event in events
        )
        self._atomic_write(path, content + "\n")
        return {
            "id": session_id,
            "path": str(path),
            "title": title,
            "created_at": created_at,
            "updated_at": saved_at,
            "message_count": len(history),
            "visible": bool(visible),
        }

    def list_sessions(self) -> List[Dict[str, Any]]:
        if not self.sessions_dir.is_dir():
            return []
        sessions: List[Dict[str, Any]] = []
        for path in self.sessions_dir.glob("*.jsonl"):
            parsed = self._parse(path)
            if parsed is None:
                continue
            meta = parsed["meta"]
            if not meta.get("visible", True):
                continue
            messages = parsed["messages"]
            title = str(meta.get("title") or "").strip() or self.derive_title(messages)
            preview = self._preview(messages)
            updated_at = str(meta.get("saved_at") or "").strip()
            if not updated_at:
                updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                    timespec="seconds"
                )
            sessions.append(
                SessionInfo(
                    id=path.stem,
                    title=title or "未命名会话",
                    created_at=str(parsed["session"].get("created_at", "")),
                    updated_at=updated_at,
                    message_count=int(
                        meta.get("message_count", len(messages)) or len(messages)
                    ),
                    path=path,
                    preview=preview,
                ).to_dict()
            )
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        return sessions

    def load(self, session_id: str) -> Dict[str, Any]:
        path = self.path_for(session_id)
        parsed = self._parse(path)
        if parsed is None:
            raise FileNotFoundError(f"会话不存在或已损坏: {session_id}")
        history = parsed["messages"]
        if not history:
            raise ValueError(f"会话没有可恢复的消息: {session_id}")
        meta = parsed["meta"]
        return {
            "id": path.stem,
            "path": str(path),
            "title": str(meta.get("title") or self.derive_title(history)),
            "created_at": str(parsed["session"].get("created_at", "")),
            "updated_at": str(meta.get("saved_at", "")),
            "message_count": len(history),
            "agents_md_injected": bool(meta.get("agents_md_injected", False)),
            "messages": history,
        }

    def derive_title(self, history: List[Any]) -> str:
        for message in history:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "user" or is_agents_message(message):
                continue
            text = " ".join(_content_text(message).split())
            if text:
                return text[: self.title_length]
        return "未命名会话"

    @staticmethod
    def has_user_messages(history: List[Any]) -> bool:
        return any(
            isinstance(message, dict)
            and message.get("role") == "user"
            and not is_agents_message(message)
            and bool(_content_text(message).strip())
            for message in history
        )

    def _parse(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.is_file():
            return None
        session: Dict[str, Any] = {}
        meta: Dict[str, Any] = {}
        messages: List[Any] = []
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            return None
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "session":
                session = event
            elif event_type == "meta":
                meta = event
            elif event_type == "message":
                message = event.get("message")
                if isinstance(message, dict):
                    messages.append(message)
            elif event_type == "replace":
                replacement = event.get("messages")
                if isinstance(replacement, list):
                    messages = [
                        message for message in replacement if isinstance(message, dict)
                    ]
        if not session and not messages:
            return None
        return {"session": session, "meta": meta, "messages": messages}

    @staticmethod
    def _preview(messages: List[Any]) -> str:
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "user" or is_agents_message(message):
                continue
            text = " ".join(_content_text(message).split())
            if text:
                return text[:120]
        return ""

    @staticmethod
    def _safe_id(session_id: str) -> str:
        identifier = Path(str(session_id).strip()).name
        if identifier.endswith(".jsonl"):
            identifier = identifier[:-6]
        if not identifier or identifier in (".", ".."):
            raise ValueError("无效的会话编号")
        return identifier

    def _existing_created_at(self, path: Path) -> str:
        if not path.is_file():
            return ""
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                first = handle.readline()
            event = json.loads(first)
            if isinstance(event, dict) and event.get("type") == "session":
                return str(event.get("created_at", ""))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ""
        return ""

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
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
            raise OSError(f"failed to save session: {path}")
