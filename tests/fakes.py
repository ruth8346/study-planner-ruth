"""Fake clients for offline tests: no API key, no network, no Claude Code process."""
from __future__ import annotations

import copy
import itertools

from anthropic.types import Message
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

_ids = itertools.count(1)


def usage(inp=100, out=20, read=0, write=0) -> dict:
    return {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def tool_use(name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": args}


def message(content: list[dict], stop_reason: str, u: dict | None = None) -> Message:
    return Message.model_validate({
        "id": f"msg_{next(_ids)}", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}] + content,
        "stop_reason": stop_reason, "stop_sequence": None, "usage": u or usage(),
    })


class FakeMessages:
    def __init__(self, responder):
        self.responder = responder
        self.requests: list[dict] = []

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        return self.responder(request)


class FakeAnthropic:
    """`responder(request) -> Message` decides each reply; or pass a list to replay in order."""

    def __init__(self, responder):
        if isinstance(responder, list):
            queue = list(responder)
            responder = lambda request: queue.pop(0)  # noqa: E731
        self.messages = FakeMessages(responder)


def last_user_text(request: dict) -> str:
    """The user's own text in the newest user turn (skips tool_result turns)."""
    for m in reversed(request["messages"]):
        if m["role"] == "user" and any(b["type"] == "text" for b in m["content"]):
            return m["content"][-1]["text"]
    return ""


def tool_round_done(request: dict) -> bool:
    last = request["messages"][-1]
    return any(b.get("type") == "tool_result" for b in last["content"])


class FakeSDKClient:
    """Stands in for ClaudeSDKClient: runs the agent's real MCP tool handlers from a script."""

    def __init__(self, options, handlers: dict, script):
        self.options = options
        self.handlers = handlers
        self.script = script  # prompt -> (list of (tool, args), answer)
        self.prompt = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, prompt: str):
        self.prompt = prompt

    async def receive_response(self):
        calls, answer = self.script(self.prompt)
        blocks = [ToolUseBlock(id=f"toolu_{next(_ids)}", name=f"mcp__study__{n}", input=a) for n, a in calls]
        yield AssistantMessage(content=blocks, model="claude-opus-5-5", message_id="m1")
        for name, args in calls:
            await self.handlers[name](args)
        yield AssistantMessage(content=[TextBlock(text=answer)], model="claude-opus-5-5", message_id="m2")
        yield ResultMessage(subtype="success", duration_ms=10, duration_api_ms=8, is_error=False, num_turns=2,
                            session_id="sess-1", total_cost_usd=0.01, result=answer, usage=usage(50, 10, 400, 30))
