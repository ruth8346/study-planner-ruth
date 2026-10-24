"""Long-term memory: state/memory.json, a key -> {value, category, updated} map.

Writes are upserts by key, so a contradicting request replaces the old value
instead of piling up next to it. Retrieval is keyword overlap, and preferences
are always considered relevant (there are few of them and they shape every plan).
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from API.harness import logger

log = logger("memory.py")

_WORD = re.compile(r"[a-z0-9֐-׿]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "my", "i", "me", "is", "it",
         "do", "you", "what", "how", "with", "that", "this", "be", "about", "please", "can"}


def _words(text: str) -> set[str]:
    words = set()
    for w in _WORD.findall(text.lower().replace("_", " ")):
        if w in _STOP:
            continue
        words.add(w[:5])  # crude stemming: prioritize / priority -> "prior"
    return words


class MemoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        log(f"loaded {len(self.data)} memories from {self.path.name}")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def remember(self, key: str, value: str, category: str) -> str:
        key = re.sub(r"[^a-z0-9_]+", "_", key.strip().lower()).strip("_")
        if not key:
            raise ValueError("key must contain letters or digits")
        old = self.data.get(key)
        self.data[key] = {"value": value.strip(), "category": category, "updated": date.today().isoformat()}
        self._save()
        if old and old["value"] != value.strip():
            log(f"overwrote '{key}': '{old['value']}' -> '{value.strip()}'")
            return f"updated {key} (was: {old['value']})"
        log(f"saved '{key}' = '{value.strip()}'")
        return f"saved {key}"

    def forget(self, key: str) -> str:
        if self.data.pop(key, None) is None:
            raise KeyError(f"no memory with key '{key}'")
        self._save()
        log(f"deleted '{key}'")
        return f"forgot {key}"

    def search(self, query: str, k: int = 5) -> list[tuple[str, dict]]:
        q = _words(query)
        scored = []
        for key, entry in self.data.items():
            score = len(q & _words(f"{key} {entry['value']}"))
            if score:
                scored.append((score, key, entry))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [(key, entry) for _, key, entry in scored[:k]]

    def relevant(self, prompt: str, k: int = 6) -> list[tuple[str, dict]]:
        """Preferences + the best keyword matches, at most k entries, in a stable order."""
        picked = {key: e for key, e in self.data.items() if e["category"] == "preference"}
        for key, e in self.search(prompt, k):
            picked.setdefault(key, e)
        items = sorted(picked.items())[:k]
        log(f"selected {len(items)} of {len(self.data)} memories for this turn: {[k for k, _ in items]}")
        return items

    def as_dict(self) -> dict[str, str]:
        return {k: e["value"] for k, e in sorted(self.data.items())}
