"""Wires the harness pieces into one agent. One instance = one session."""
from __future__ import annotations

from pathlib import Path

from API.harness import caching, compaction, context, loop, logger
from API.harness.history import History
from API.harness.memory import MemoryStore
from API.harness.tokens import TokenTracker
from API.harness.tools import ToolRegistry

log = logger("agent.py")


class StudyAgent:
    def __init__(self, client, state_dir: Path, model: str, effort: str, max_tokens: int = 16000,
                 session_id: str | None = None, compact_at_tokens: int = 40_000):
        self.client = client
        self.state_dir = Path(state_dir)
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self.memory = MemoryStore(self.state_dir / "memory.json")
        self.history = History(self.state_dir / "sessions", session_id)
        self.tools = ToolRegistry(self.state_dir, self.memory)
        self.tokens = TokenTracker(model)
        self.system = context.system_prompt()  # frozen for the session
        self.compactor = compaction.Compactor(client, self.build_request, self.tokens, compact_at_tokens)
        log(f"agent ready: model={model} effort={effort} session={self.history.session_id}")

    def build_request(self, messages: list[dict]) -> dict:
        return caching.apply({
            "model": self.model,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "system": self.system,
            "tools": self.tools.schemas(),
            "messages": messages,
        })

    def ask(self, prompt: str) -> dict:
        self.tokens.start_turn()
        self.tools.calls = []
        self.compactor.maybe_compact(self.history)
        self.history.append(context.build_user_message(prompt, self.memory, self.state_dir))
        answer = loop.run(self.client, self.build_request, self.history, self.tools, self.tokens)
        return {"answer": answer, "tool_calls": self.tools.calls, **self.tokens.end_turn()}
