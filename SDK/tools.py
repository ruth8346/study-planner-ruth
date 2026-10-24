"""The same domain tools, exposed to Claude Code as an in-process MCP server.

Memory lives in CLAUDE.md inside the agent's working directory. Claude Code loads
it into context by itself at session start (setting_sources=["project"]); the
remember / forget tools only edit the file.
"""
from __future__ import annotations

import re
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from shared.domain import DOMAIN_TOOL_SPECS, MEMORY_TOOL_SPECS, ToolError, run_domain_tool

SERVER_NAME = "study"
MEMORY_HEADER = ("# Ruth's study planner memory\n\n"  # replaces: memory
                 "Saved by the `remember` tool, one line per memory: `- key (category): value`.\n\n")  # replaces: memory
_LINE = re.compile(r"^- ([a-z0-9_]+) \((\w+)\): (.*)$")  # replaces: memory


def read_memory(md_path: Path) -> dict[str, tuple[str, str]]:  # replaces: memory
    """key -> (category, value), parsed from CLAUDE.md."""
    if not md_path.exists():  # replaces: memory
        return {}  # replaces: memory
    found = (_LINE.match(line) for line in md_path.read_text(encoding="utf-8").splitlines())  # replaces: memory
    return {m.group(1): (m.group(2), m.group(3)) for m in found if m}  # replaces: memory


def write_memory(md_path: Path, memory: dict[str, tuple[str, str]]) -> None:  # replaces: memory
    lines = [f"- {k} ({cat}): {value}" for k, (cat, value) in sorted(memory.items())]  # replaces: memory
    md_path.write_text(MEMORY_HEADER + "\n".join(lines) + "\n", encoding="utf-8")  # replaces: memory


def remember(md_path: Path, key: str, value: str, category: str) -> str:  # replaces: memory
    key = re.sub(r"[^a-z0-9_]+", "_", key.strip().lower()).strip("_")  # replaces: memory
    if not key:  # replaces: memory
        raise ToolError("key must contain letters or digits")  # replaces: memory
    memory = read_memory(md_path)  # replaces: memory
    old = memory.get(key)  # replaces: memory
    memory[key] = (category, " ".join(value.split()))  # replaces: memory
    write_memory(md_path, memory)  # replaces: memory
    return f"updated {key} (was: {old[1]})" if old and old[1] != memory[key][1] else f"saved {key}"  # replaces: memory


def forget(md_path: Path, key: str) -> str:  # replaces: memory
    memory = read_memory(md_path)  # replaces: memory
    if memory.pop(key, None) is None:  # replaces: memory
        raise ToolError(f"no memory with key '{key}'")  # replaces: memory
    write_memory(md_path, memory)  # replaces: memory
    return f"forgot {key}"  # replaces: memory


def build_server(state_dir: Path, md_path: Path, call_log: list[dict]):  # replaces: tools
    """Returns (mcp server config, allowed tool names, tool objects). `call_log` collects every call for results/sdk.json."""

    def make(spec: dict):  # replaces: tools
        name = spec["name"]  # replaces: tools

        @tool(name, spec["description"], spec["input_schema"])  # replaces: tools
        async def handler(args: dict) -> dict:  # replaces: tools
            try:  # replaces: tools
                if name == "remember":  # replaces: tools
                    out = remember(md_path, args["key"], args["value"], args.get("category", "fact"))  # replaces: memory
                elif name == "forget":  # replaces: tools
                    out = forget(md_path, args["key"])  # replaces: memory
                else:  # replaces: tools
                    out = run_domain_tool(state_dir, name, args)  # replaces: tools
                is_error = False  # replaces: tools
            except (ToolError, KeyError) as e:  # replaces: tools
                out, is_error = f"Error: {e}", True  # replaces: tools
            call_log.append({"name": name, "input": args, "is_error": is_error})  # replaces: tools
            print(f"[SDK/tools.py] {name}({args}) -> {'ERROR ' if is_error else ''}{out.splitlines()[0][:90]}", flush=True)  # replaces: tools
            return {"content": [{"type": "text", "text": out}], "is_error": is_error}  # replaces: tools

        return handler  # replaces: tools

    tools = [make(spec) for spec in DOMAIN_TOOL_SPECS + MEMORY_TOOL_SPECS]  # replaces: tools
    server = create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=tools)  # replaces: tools
    allowed = [f"mcp__{SERVER_NAME}__{t.name}" for t in tools]  # replaces: tools
    return server, allowed, tools  # replaces: tools
