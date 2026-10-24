"""Context-window management: past a token threshold, summarize the whole
conversation into one message and restart the context from it.

Runs only at the start of a turn (never in the middle of a tool round). The
summary call reuses the normal request (same system + tools), so it reads the
existing prompt cache instead of paying for the history again.
"""
from __future__ import annotations

from API.harness import logger
from API.harness.history import History
from API.harness.tokens import TokenTracker

log = logger("compaction.py")

SUMMARY_INSTRUCTION = (
    "Summarize our conversation so far so you can continue it without the transcript. Keep: every task you "
    "added or changed (with ids and dates), every preference or decision Ruth stated (latest value only), "
    "open questions, and what you were about to do next. Plain bullet points, no more than 250 words."
)


class Compactor:
    def __init__(self, client, build_request, tokens: TokenTracker, threshold_tokens: int):
        self.client = client
        self.build_request = build_request
        self.tokens = tokens
        self.threshold = threshold_tokens

    def maybe_compact(self, history: History) -> bool:
        size = self.tokens.last_context_tokens
        if size < self.threshold or not history.messages:
            log(f"context {size} tokens < threshold {self.threshold}: no compaction")
            return False
        log(f"context {size} tokens >= threshold {self.threshold}: summarizing {len(history.messages)} messages")
        messages = history.messages + [{"role": "user", "content": [{"type": "text", "text": SUMMARY_INSTRUCTION}]}]
        request = self.build_request(messages)
        request["tool_choice"] = {"type": "none"}
        resp = self.client.messages.create(**request)
        self.tokens.record(resp.usage, label="compaction")
        summary = "\n".join(b.text for b in resp.content if b.type == "text").strip()
        history.compact(summary)
        self.tokens.last_context_tokens = 0
        return True
