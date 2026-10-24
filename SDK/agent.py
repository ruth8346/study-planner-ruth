"""The same agent on the Claude Agent SDK: Claude Code runs the harness, this file configures it.

Lines tagged `# replaces: <part>` stand in for API/harness/<part>.py.
caching.py has no counterpart line: Claude Code places cache_control by itself.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, SystemMessage

from SDK.tools import SERVER_NAME, build_server, write_memory
from shared.pricing import cost_usd
from shared.prompts import SDK_SYSTEM_PROMPT


USAGE_FIELDS = {"input": "inputTokens", "cache_read": "cacheReadInputTokens",
                "cache_write": "cacheCreationInputTokens", "output": "outputTokens"}
RESULT_USAGE_FIELDS = {"input": "input_tokens", "cache_read": "cache_read_input_tokens",
                       "cache_write": "cache_creation_input_tokens", "output": "output_tokens"}


def log(msg: str) -> None:
    print(f"[SDK/agent.py] {msg}", flush=True)


class StudyAgentSDK:
    def __init__(self, state_dir: Path, model: str, effort: str, resume: bool = False, client_cls=ClaudeSDKClient):
        self.state_dir = Path(state_dir)
        self.model = model
        self.workspace = self.state_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.md_path = self.workspace / "CLAUDE.md"
        if not self.md_path.exists():
            write_memory(self.md_path, {})  # replaces: memory
        self.session_file = self.state_dir / "sdk_session.json"
        resume_id = json.loads(self.session_file.read_text())["session_id"] if resume and self.session_file.exists() else None  # replaces: history
        self.calls: list[dict] = []
        server, allowed, sdk_tools = build_server(self.state_dir, self.md_path, self.calls)
        self.tool_handlers = {t.name: t.handler for t in sdk_tools}  # used by the offline tests
        self.options = ClaudeAgentOptions(
            model=model,
            effort=effort,
            system_prompt=SDK_SYSTEM_PROMPT,  # replaces: context
            tools=[],  # no built-in Claude Code tools: only our MCP tools
            mcp_servers={SERVER_NAME: server},  # replaces: tools
            allowed_tools=allowed,  # replaces: tools
            strict_mcp_config=True,
            permission_mode="dontAsk",
            setting_sources=["project"],  # replaces: memory
            cwd=str(self.workspace),
            resume=resume_id,  # replaces: history
            max_turns=10,  # replaces: loop
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},  # memory comes only from our CLAUDE.md
        )
        self.client_cls = client_cls
        self.prev_model_usage: dict = {}
        self.prev_reported_cost = 0.0
        log(f"options ready: model={model} effort={effort} resume={resume_id} cwd={self.workspace}")

    async def __aenter__(self):
        self.client = self.client_cls(options=self.options)
        await self.client.connect()
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()

    async def ask(self, prompt: str) -> dict:
        t0 = time.perf_counter()
        self.calls.clear()
        message_ids: set[str] = set()
        result: ResultMessage | None = None
        await self.client.query(prompt)  # replaces: loop
        async for msg in self.client.receive_response():  # replaces: loop
            if isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
                message_ids.add(msg.message_id or str(id(msg)))  # one API call can arrive as several messages
            elif isinstance(msg, SystemMessage) and msg.subtype == "compact_boundary":
                log(f"Claude Code compacted the conversation: {msg.data}")  # replaces: compaction
            elif isinstance(msg, ResultMessage):
                result = msg
        if result is None:
            raise RuntimeError("no ResultMessage received")
        self.session_file.write_text(json.dumps({"session_id": result.session_id}))  # replaces: history
        # ResultMessage.usage is per turn but covers only the main model; model_usage and
        # total_cost_usd are cumulative for the session and include Claude Code's own
        # background calls (a Haiku call per session). So take per-turn deltas of those.
        per_model = {}
        for model, mu in (result.model_usage or {}).items():  # replaces: tokens
            prev = self.prev_model_usage.get(model, {})  # replaces: tokens
            per_model[model] = {k: mu.get(src, 0) - prev.get(src, 0) for k, src in USAGE_FIELDS.items()}  # replaces: tokens
        self.prev_model_usage = result.model_usage or {}
        if not per_model:  # older CLI without model_usage: fall back to the main model's usage
            u = result.usage or {}  # replaces: tokens
            per_model[self.model] = {k: u.get(src, 0) for k, src in RESULT_USAGE_FIELDS.items()}  # replaces: tokens
        tokens = {k: sum(d[k] for d in per_model.values()) for k in USAGE_FIELDS}
        background = {m: d for m, d in per_model.items() if m != self.model and any(d.values())}
        reported = result.total_cost_usd or 0.0  # replaces: tokens
        turn_cost = reported - self.prev_reported_cost  # replaces: tokens
        self.prev_reported_cost = reported
        # Cross-check: Claude Code writes the prompt cache with the 1-hour TTL (2x input price).
        recomputed = sum(cost_usd(m, d["input"], d["output"], d["cache_read"], d["cache_write"], cache_ttl="1h")
                         for m, d in per_model.items())
        turn = {
            "answer": (result.result or "").strip(),
            "tool_calls": list(self.calls),
            "tokens": tokens,
            "model_calls": len(message_ids) + len(background),
            "background_calls": background,
            "cost_usd": round(turn_cost, 5),
            "cost_recomputed_usd": round(recomputed, 5),
            "num_turns": result.num_turns,
            "seconds": round(time.perf_counter() - t0, 2),
            "session_id": result.session_id,
        }
        log(f"turn done: {tokens} calls={turn['model_calls']} (background: {list(background)}) "
            f"${turn['cost_usd']:.4f} (recomputed ${recomputed:.4f}) {turn['seconds']}s")
        return turn
