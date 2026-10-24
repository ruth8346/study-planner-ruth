"""Offline tests for the SDK version: configuration, CLAUDE.md memory, MCP tool handlers."""
import asyncio

from fakes import FakeSDKClient

from SDK.agent import StudyAgentSDK
from SDK.tools import build_server, read_memory, remember


def test_options_are_restricted(tmp_path):
    agent = StudyAgentSDK(tmp_path, "claude-opus-5-5", "medium")
    o = agent.options
    assert o.strict_mcp_config is True
    assert o.tools == []
    assert o.setting_sources == ["project"]
    assert o.model == "claude-opus-5-5" and o.effort == "medium"
    assert o.system_prompt.startswith("You are Ruth's personal study planner")
    assert sorted(o.allowed_tools) == sorted(f"mcp__study__{n}" for n in
                                             ["add_task", "list_tasks", "complete_task", "plan_week",
                                              "wiki_summary", "remember", "forget"])
    assert (tmp_path / "workspace" / "CLAUDE.md").exists()
    assert o.resume is None


def test_claude_md_memory_upsert(tmp_path):
    md = tmp_path / "CLAUDE.md"
    remember(md, "study_time", "mornings", "preference")
    assert "was: mornings" in remember(md, "study_time", "evenings", "preference")
    assert read_memory(md) == {"study_time": ("preference", "evenings")}
    assert md.read_text().count("study_time") == 1


def test_tool_handler_errors_are_is_error(tmp_path):
    calls = []
    _, _, tools = build_server(tmp_path, tmp_path / "CLAUDE.md", calls)
    handlers = {t.name: t.handler for t in tools}
    ok = asyncio.run(handlers["add_task"]({"course": "OS", "title": "Lab", "kind": "lab",
                                           "due_date": "2026-11-06", "est_hours": 3}))
    bad = asyncio.run(handlers["complete_task"]({"task_id": "T9"}))
    assert ok["is_error"] is False and ok["content"][0]["text"].startswith("added T1")
    assert bad["is_error"] is True
    assert [c["is_error"] for c in calls] == [False, True]


def test_resume_uses_saved_session_id(tmp_path):
    (tmp_path / "sdk_session.json").write_text('{"session_id": "abc"}')
    assert StudyAgentSDK(tmp_path, "claude-opus-5-5", "medium", resume=True).options.resume == "abc"
    assert StudyAgentSDK(tmp_path, "claude-opus-5-5", "medium", resume=False).options.resume is None


def test_ask_collects_usage_and_tools(tmp_path):
    def script(prompt):
        return [("remember", {"key": "study_time", "value": "mornings", "category": "preference"})], "Saved."

    class Agent(StudyAgentSDK):
        async def __aenter__(self):
            self.client = FakeSDKClient(self.options, self.tool_handlers, script)
            return self

    async def go():
        async with Agent(tmp_path, "claude-opus-5-5", "medium") as agent:
            return await agent.ask("remember mornings")

    r = asyncio.run(go())
    assert r["answer"] == "Saved."
    assert r["model_calls"] == 2
    assert r["tokens"] == {"input": 50, "cache_read": 400, "cache_write": 30, "output": 10}
    assert [c["name"] for c in r["tool_calls"]] == ["remember"]
    assert read_memory(tmp_path / "workspace" / "CLAUDE.md")["study_time"][1] == "mornings"
    assert (tmp_path / "sdk_session.json").exists()


def test_cumulative_session_usage_becomes_per_turn_delta(tmp_path):
    """Claude Code reports model_usage / total_cost_usd per session; results must be per turn."""
    from claude_agent_sdk import ResultMessage

    def mu(inp, out, read, write):
        return {"inputTokens": inp, "outputTokens": out, "cacheReadInputTokens": read, "cacheCreationInputTokens": write}

    snapshots = [
        (0.03, {"claude-opus-5-5": mu(4, 300, 2000, 3000), "claude-haiku-5-5": mu(1200, 17, 0, 0)}),
        (0.05, {"claude-opus-5-5": mu(8, 500, 6000, 3500), "claude-haiku-5-5": mu(1200, 17, 0, 0)}),
    ]

    class Client:
        def __init__(self, options):
            pass

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def query(self, prompt):
            pass

        async def receive_response(self):
            cost, usage_ = snapshots.pop(0)
            yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                                session_id="s", total_cost_usd=cost, result="ok", model_usage=usage_)

    async def go():
        async with StudyAgentSDK(tmp_path, "claude-opus-5-5", "medium", client_cls=Client) as agent:
            return await agent.ask("a"), await agent.ask("b")

    first, second = asyncio.run(go())
    assert first["tokens"] == {"input": 1204, "cache_read": 2000, "cache_write": 3000, "output": 317}
    assert list(first["background_calls"]) == ["claude-haiku-5-5"] and first["model_calls"] == 1
    assert second["tokens"] == {"input": 4, "cache_read": 4000, "cache_write": 500, "output": 200}
    assert second["background_calls"] == {} and abs(second["cost_usd"] - 0.02) < 1e-9
