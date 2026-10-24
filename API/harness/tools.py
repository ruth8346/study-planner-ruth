"""Tool schemas sent to the model, dispatch of tool_use blocks, and errors as is_error results."""
from __future__ import annotations

import json
from pathlib import Path

from API.harness import logger
from API.harness.memory import MemoryStore
from shared.domain import DOMAIN_TOOL_SPECS, MEMORY_TOOL_SPECS, ToolError, run_domain_tool

log = logger("tools.py")

RECALL_SPEC = {
    "name": "recall_memory",
    "description": "Search saved memories by keywords, for memories not already shown in the <context> block.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}

MAX_RESULT_CHARS = 1500  # hard cap on what a single tool result may add to the context


class ToolRegistry:
    def __init__(self, state_dir: Path, memory: MemoryStore):
        self.state_dir = Path(state_dir)
        self.memory = memory
        self.calls: list[dict] = []  # every call this turn: {name, input, is_error}

    def schemas(self) -> list[dict]:
        """Same list, same order, every request: a changing tool list would break the prompt cache."""
        return [dict(s) for s in DOMAIN_TOOL_SPECS + MEMORY_TOOL_SPECS + [RECALL_SPEC]]

    def _run(self, name: str, args: dict) -> str:
        if name == "remember":
            return self.memory.remember(args["key"], args["value"], args.get("category", "fact"))
        if name == "forget":
            return self.memory.forget(args["key"])
        if name == "recall_memory":
            hits = self.memory.search(args["query"], k=5)
            return "\n".join(f"{k}: {e['value']}" for k, e in hits) or "no matching memory"
        return run_domain_tool(self.state_dir, name, args)

    def run_one(self, block: dict) -> dict:
        name, args = block["name"], block.get("input") or {}
        try:
            output, is_error = self._run(name, args), False
        except (ToolError, KeyError, ValueError) as e:
            output, is_error = f"Error: {e}", True
        except Exception as e:  # a bug in a tool must not kill the loop; the model sees it and can adapt
            output, is_error = f"Error: unexpected {type(e).__name__}: {e}", True
        if len(output) > MAX_RESULT_CHARS:
            output = output[:MAX_RESULT_CHARS] + " ...[truncated]"
        self.calls.append({"name": name, "input": args, "is_error": is_error})
        log(f"{name}({json.dumps(args, ensure_ascii=False)}) -> {'ERROR ' if is_error else ''}"
            f"{len(output)} chars: {output.splitlines()[0][:90] if output else ''}")
        result = {"type": "tool_result", "tool_use_id": block["id"], "content": output}
        if is_error:
            result["is_error"] = True
        return result

    def dispatch(self, tool_uses: list[dict]) -> dict:
        """Run every tool_use of one assistant message; all results go back in ONE user message."""
        results = [self.run_one(b) for b in tool_uses]
        log(f"returning {len(results)} tool_result block(s) in a single user message")
        return {"role": "user", "content": results}
