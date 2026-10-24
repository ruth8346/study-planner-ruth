"""Conversation history: state/sessions/<session_id>.jsonl, append-only.

Each line is either a message or a compaction record. Nothing is ever rewritten:
compaction appends a record, and loading replays the file from the last
compaction record on. The in-memory `messages` list is append-only too, which
keeps the prompt-cache prefix and the thinking-block signatures valid.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from API.harness import logger

log = logger("history.py")


class History:
    def __init__(self, sessions_dir: Path, session_id: str | None = None):
        self.dir = Path(sessions_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.path = self.dir / f"{self.session_id}.jsonl"
        self.messages: list[dict] = []
        if self.path.exists():
            self._load()
        else:
            log(f"new session {self.session_id}")

    def _load(self) -> None:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            rec = json.loads(line)
            if rec["type"] == "compaction":
                self.messages = list(rec["messages"])
            else:
                self.messages.append(rec["message"])
        log(f"resumed session {self.session_id}: {len(lines)} records -> {len(self.messages)} messages in context")

    def _write(self, rec: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def append(self, message: dict) -> None:
        self.messages.append(message)
        self._write({"type": "message", "message": message})
        kinds = [b.get("type") for b in message["content"]] if isinstance(message["content"], list) else ["text"]
        log(f"appended {message['role']} message {kinds} (#{len(self.messages)})")

    def compact(self, summary: str) -> None:
        """Start the context over from a summary. The old lines stay on disk."""
        self.messages = [
            {"role": "user", "content": [{"type": "text", "text": f"<conversation_summary>\n{summary}\n</conversation_summary>"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Got it, continuing from the summary."}]},
        ]
        self._write({"type": "compaction", "messages": self.messages})
        log(f"wrote compaction record; context restarts with {len(self.messages)} messages")

    @staticmethod
    def latest_session_id(sessions_dir: Path) -> str | None:
        files = sorted(Path(sessions_dir).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        return files[-1].stem if files else None
