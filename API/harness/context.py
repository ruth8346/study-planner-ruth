"""What goes into each turn.

- system prompt: frozen for the whole session (cache-friendly).
- tools: the full fixed list (see tools.py).
- the new user message: a small <context> block (today's date, only the memories
  relevant to this prompt, one summary line about tasks) + the user's text.

The full task list and the rest of memory are NOT sent; the model pulls them with
list_tasks / recall_memory when it needs them. The context block is stored in
history as part of that turn and never edited later.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from API.harness import logger
from API.harness.memory import MemoryStore
from shared.prompts import API_SYSTEM_PROMPT
from shared.store import TaskStore

log = logger("context.py")


def system_prompt() -> str:
    return API_SYSTEM_PROMPT


def task_summary(state_dir: Path) -> str:
    open_tasks = sorted((t for t in TaskStore(state_dir).all() if t["status"] == "open"), key=lambda t: t["due_date"])
    if not open_tasks:
        return "open tasks: 0"
    nxt = open_tasks[0]
    return f"open tasks: {len(open_tasks)} (next due: {nxt['course']} {nxt['title']} {nxt['due_date']}; use list_tasks for details)"


def build_user_message(prompt: str, memory: MemoryStore, state_dir: Path, today: date | None = None) -> dict:
    today = today or date.today()
    mems = memory.relevant(prompt)
    lines = [f"<context date=\"{today.isoformat()}\">"]
    if mems:
        lines.append(f"memories ({len(mems)} of {len(memory.data)}):")
        lines += [f"- {k}: {e['value']}" for k, e in mems]
    else:
        lines.append(f"memories: none relevant ({len(memory.data)} saved)")
    lines.append(task_summary(state_dir))
    lines.append("</context>")
    block = "\n".join(lines)
    log(f"context block: {len(block)} chars, {len(mems)} memories, task summary line")
    return {"role": "user", "content": [{"type": "text", "text": block}, {"type": "text", "text": prompt}]}
