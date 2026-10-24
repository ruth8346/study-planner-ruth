"""The agent loop: call the model, run the tools it asked for, repeat while stop_reason == "tool_use"."""
from __future__ import annotations

from API.harness import logger
from API.harness.history import History
from API.harness.tokens import TokenTracker
from API.harness.tools import ToolRegistry

log = logger("loop.py")

MAX_ITERATIONS = 10  # safety net against a model that never stops calling tools


def _to_dict(block) -> dict:
    """Store blocks exactly as received (thinking blocks keep their signature)."""
    return block.model_dump(mode="json", exclude_none=True) if hasattr(block, "model_dump") else dict(block)


def run(client, build_request, history: History, tools: ToolRegistry, tokens: TokenTracker) -> str:
    stop_reason = None
    content: list[dict] = []
    for i in range(1, MAX_ITERATIONS + 1):
        resp = client.messages.create(**build_request(history.messages))
        tokens.record(resp.usage)
        content = [_to_dict(b) for b in resp.content]
        stop_reason = resp.stop_reason
        history.append({"role": "assistant", "content": content})
        tool_uses = [b for b in content if b["type"] == "tool_use"]
        log(f"iteration {i}: stop_reason={stop_reason}, {len(tool_uses)} tool_use block(s)")
        if stop_reason != "tool_use":
            break
        history.append(tools.dispatch(tool_uses))
    else:
        log(f"stopped after {MAX_ITERATIONS} iterations")

    if stop_reason == "refusal":
        log("model refused this request")
        return "[refused]"
    if stop_reason == "max_tokens":
        log("hit max_tokens: answer may be cut off")
    return "\n".join(b["text"] for b in content if b["type"] == "text").strip()
