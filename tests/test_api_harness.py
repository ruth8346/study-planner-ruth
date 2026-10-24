"""Offline tests for each API/harness file, with a fake Anthropic client."""
import json
from datetime import date

from fakes import FakeAnthropic, message, text, tool_use, usage

from API.agent import StudyAgent
from API.harness import caching, context, loop
from API.harness.history import History
from API.harness.memory import MemoryStore
from API.harness.tokens import TokenTracker
from API.harness.tools import ToolRegistry


def make_agent(tmp_path, replies, **kw):
    client = FakeAnthropic(replies)
    return StudyAgent(client, tmp_path, "claude-opus-5-5", "medium", **kw), client


# ---------- loop.py ----------

def test_loop_runs_while_tool_use_and_returns_all_results_in_one_message(tmp_path):
    agent, client = make_agent(tmp_path, [
        message([tool_use("add_task", {"course": "Algorithms", "title": "Final", "kind": "exam",
                                       "due_date": "2026-11-10", "est_hours": 12}),
                 tool_use("add_task", {"course": "Databases", "title": "HW3", "kind": "assignment",
                                       "due_date": "2026-11-03", "est_hours": 5})], "tool_use"),
        message([text("Added both.")], "end_turn"),
    ])
    result = agent.ask("add two tasks")
    assert result["answer"] == "Added both."
    assert result["model_calls"] == 2
    second = client.messages.requests[1]["messages"]
    tool_msg = second[-1]
    assert tool_msg["role"] == "user"
    assert [b["type"] for b in tool_msg["content"]] == ["tool_result", "tool_result"]
    assert len(json.loads((tmp_path / "tasks.json").read_text())) == 2


def test_loop_stops_on_end_turn_without_tools(tmp_path):
    agent, client = make_agent(tmp_path, [message([text("hi")], "end_turn")])
    assert agent.ask("hello")["answer"] == "hi"
    assert len(client.messages.requests) == 1


def test_loop_has_iteration_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "MAX_ITERATIONS", 3)
    agent, client = make_agent(tmp_path, lambda req: message([tool_use("list_tasks", {})], "tool_use"))
    agent.ask("loop forever")
    assert len(client.messages.requests) == 3


def test_thinking_blocks_are_sent_back_unchanged(tmp_path):
    agent, client = make_agent(tmp_path, [
        message([tool_use("list_tasks", {})], "tool_use"),
        message([text("none")], "end_turn"),
    ])
    agent.ask("list")
    assistant = client.messages.requests[1]["messages"][1]
    assert assistant["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}


# ---------- tools.py ----------

def test_tool_errors_go_back_as_is_error(tmp_path):
    reg = ToolRegistry(tmp_path, MemoryStore(tmp_path / "memory.json"))
    bad_date = reg.run_one(tool_use("add_task", {"course": "A", "title": "x", "kind": "exam",
                                                  "due_date": "next week", "est_hours": 2}))
    unknown = reg.run_one(tool_use("launch_rocket", {}))
    missing = reg.run_one(tool_use("complete_task", {}))
    no_task = reg.run_one(tool_use("complete_task", {"task_id": "T99"}))
    for r in (bad_date, unknown, missing, no_task):
        assert r["is_error"] is True and r["content"].startswith("Error:")
    assert [c["is_error"] for c in reg.calls] == [True] * 4


def test_tool_schemas_are_stable(tmp_path):
    reg = ToolRegistry(tmp_path, MemoryStore(tmp_path / "memory.json"))
    names = [s["name"] for s in reg.schemas()]
    assert names == [s["name"] for s in reg.schemas()]
    assert {"add_task", "list_tasks", "complete_task", "plan_week", "wiki_summary",
            "remember", "forget", "recall_memory"} == set(names)


# ---------- history.py ----------

def test_history_is_append_only_and_resumable(tmp_path):
    h = History(tmp_path / "sessions")
    h.append({"role": "user", "content": [text("a")]})
    h.append({"role": "assistant", "content": [text("b")]})
    before = (h.path).read_text()
    h.append({"role": "user", "content": [text("c")]})
    assert h.path.read_text().startswith(before)  # nothing rewritten
    again = History(tmp_path / "sessions", h.session_id)
    assert again.messages == h.messages
    assert History.latest_session_id(tmp_path / "sessions") == h.session_id


def test_history_reload_after_compaction(tmp_path):
    h = History(tmp_path / "sessions")
    for i in range(4):
        h.append({"role": "user" if i % 2 == 0 else "assistant", "content": [text(str(i))]})
    h.compact("summary here")
    h.append({"role": "user", "content": [text("new")]})
    lines = h.path.read_text().splitlines()
    assert len(lines) == 6  # 4 messages + compaction + 1, old lines still on disk
    again = History(tmp_path / "sessions", h.session_id)
    assert len(again.messages) == 3
    assert "summary here" in again.messages[0]["content"][0]["text"]


# ---------- memory.py ----------

def test_memory_overwrites_contradiction(tmp_path):
    m = MemoryStore(tmp_path / "memory.json")
    m.remember("study_time", "mornings", "preference")
    out = m.remember("Study Time", "evenings", "preference")
    assert "was: mornings" in out
    assert MemoryStore(tmp_path / "memory.json").as_dict() == {"study_time": "evenings"}


def test_memory_relevance(tmp_path):
    m = MemoryStore(tmp_path / "memory.json")
    m.remember("study_time", "mornings", "preference")
    m.remember("priority_decision", "Databases assignment first", "decision")
    m.remember("favorite_cafe", "the library cafe", "fact")
    keys = [k for k, _ in m.relevant("what did I decide to prioritize?")]
    assert "priority_decision" in keys and "study_time" in keys and "favorite_cafe" not in keys


# ---------- context.py ----------

def test_context_sends_only_relevant_memory_and_task_summary(tmp_path):
    m = MemoryStore(tmp_path / "memory.json")
    m.remember("study_time", "mornings", "preference")
    m.remember("favorite_cafe", "the library cafe", "fact")
    reg = ToolRegistry(tmp_path, m)
    reg.run_one(tool_use("add_task", {"course": "OS", "title": "Lab", "kind": "lab",
                                      "due_date": "2026-11-06", "est_hours": 3}))
    msg = context.build_user_message("plan my week", m, tmp_path, today=date(2026, 10, 23))
    block = msg["content"][0]["text"]
    assert "study_time: mornings" in block and "favorite_cafe" not in block
    assert "open tasks: 1" in block and "2026-10-23" in block
    assert msg["content"][1]["text"] == "plan my week"


# ---------- caching.py ----------

def test_caching_marks_three_breakpoints_on_a_copy():
    request = {"tools": [{"name": "a"}, {"name": "b"}], "system": "sys",
               "messages": [{"role": "user", "content": [text("x"), text("y")]}]}
    out = caching.apply(request)
    assert out["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert out["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert out["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in request["tools"][-1]  # history/tools untouched
    assert "cache_control" not in request["messages"][-1]["content"][-1]
    assert json.dumps(out).count("cache_control") <= 4


# ---------- compaction.py ----------

def test_compaction_over_threshold(tmp_path):
    replies = [
        message([text("one")], "end_turn", usage(inp=900)),
        message([text("- Ruth likes mornings")], "end_turn"),  # the summary call
        message([text("two")], "end_turn"),
    ]
    agent, client = make_agent(tmp_path, replies, compact_at_tokens=500)
    agent.ask("first")
    result = agent.ask("second")
    summary_req = client.messages.requests[1]
    assert summary_req["tool_choice"] == {"type": "none"}
    assert "Summarize our conversation" in summary_req["messages"][-1]["content"][0]["text"]
    after = client.messages.requests[2]["messages"]
    assert "Ruth likes mornings" in after[0]["content"][0]["text"]
    assert len(after) == 3  # summary, ack, new user turn
    assert result["model_calls"] == 2  # summary call is counted in the turn


def test_no_compaction_under_threshold(tmp_path):
    agent, client = make_agent(tmp_path, [message([text("a")], "end_turn"), message([text("b")], "end_turn")])
    agent.ask("1")
    agent.ask("2")
    assert len(client.messages.requests) == 2
    assert len(client.messages.requests[1]["messages"]) == 3  # full history kept


# ---------- tokens.py ----------

def test_token_costs():
    t = TokenTracker("claude-opus-5-5")
    t.start_turn()
    t.record(message([], "end_turn", usage(inp=1000, out=500, read=10000, write=2000)).usage)
    r = t.end_turn()
    # 1000*4 + 500*20 + 10000*0.2 + 2000*5 = 26000 per million
    assert abs(r["cost_usd"] - 0.026) < 1e-9
    assert r["tokens"] == {"input": 1000, "cache_read": 10000, "cache_write": 2000, "output": 500}
    assert t.last_context_tokens == 13000


def test_request_shape(tmp_path):
    agent, client = make_agent(tmp_path, [message([text("ok")], "end_turn")])
    agent.ask("hi")
    req = client.messages.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"] == {"effort": "medium"}
    assert req["thinking"] == {"type": "adaptive"}
    assert "temperature" not in req


# ---------- the real anthropic client, with a mock HTTP transport (no key, no network) ----------

def test_requests_serialize_through_real_sdk(tmp_path):
    import anthropic
    import httpx2

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            content = [{"type": "thinking", "thinking": "", "signature": "s"},
                       {"type": "tool_use", "id": "toolu_1", "name": "list_tasks", "input": {}}]
            stop = "tool_use"
        else:
            content, stop = [{"type": "text", "text": "done"}], "end_turn"
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})

    client = anthropic.Anthropic(api_key="offline-test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert StudyAgent(client, tmp_path, "claude-opus-5-5", "medium").ask("hi")["answer"] == "done"
    body = sent[1]
    assert body["messages"][1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "s"}
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
