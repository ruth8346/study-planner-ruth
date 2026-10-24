"""Token usage and cost per model call and per turn."""
from __future__ import annotations

import time

from API.harness import logger
from shared.pricing import cost_usd

log = logger("tokens.py")


class TokenTracker:
    def __init__(self, model: str):
        self.model = model
        self.last_context_tokens = 0  # size of the last prompt the model saw (for compaction.py)
        self._turn: dict | None = None

    def start_turn(self) -> None:
        self._turn = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "model_calls": 0,
                      "cost_usd": 0.0, "t0": time.perf_counter()}

    def record(self, usage, label: str = "loop") -> None:
        u = {
            "input": usage.input_tokens,
            "cache_read": usage.cache_read_input_tokens or 0,
            "cache_write": usage.cache_creation_input_tokens or 0,
            "output": usage.output_tokens,
        }
        cost = cost_usd(self.model, u["input"], u["output"], u["cache_read"], u["cache_write"])
        for k, v in u.items():
            self._turn[k] += v
        self._turn["model_calls"] += 1
        self._turn["cost_usd"] += cost
        self.last_context_tokens = u["input"] + u["cache_read"] + u["cache_write"]
        log(f"call {self._turn['model_calls']} ({label}): in={u['input']} cache_read={u['cache_read']} "
            f"cache_write={u['cache_write']} out={u['output']} ${cost:.4f}")

    def end_turn(self) -> dict:
        t = self._turn
        result = {
            "tokens": {k: t[k] for k in ("input", "cache_read", "cache_write", "output")},
            "model_calls": t["model_calls"],
            "cost_usd": round(t["cost_usd"], 5),
            "seconds": round(time.perf_counter() - t["t0"], 2),
        }
        log(f"turn total: {result['tokens']} calls={result['model_calls']} ${result['cost_usd']:.4f} {result['seconds']}s")
        return result
