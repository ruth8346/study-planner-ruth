"""End-to-end offline run of scenario.json through both mains, with scripted fake models.

The fake "model" only decides which tools to call; everything else (history, memory,
context, tools, state files, checks, results json) is the real code.
"""
import asyncio
import json
from pathlib import Path

from fakes import FakeAnthropic, FakeSDKClient, last_user_text, message, text, tool_round_done, tool_use

import API.main as api_main
import SDK.main as sdk_main
from SDK.agent import StudyAgentSDK
from shared import domain
from shared.scenario import ROOT, load_scenario

SCENARIO = load_scenario(ROOT / "scenario.json")


def script(prompt: str, memory_text: str):
    """(tool calls, answer) a reasonable model would produce for each scenario prompt."""
    p = prompt.lower()
    if "remember how i like" in p:
        return [("remember", {"key": "study_time", "value": "mornings", "category": "preference"}),
                ("remember", {"key": "max_hours_per_day", "value": "3", "category": "preference"}),
                ("remember", {"key": "session_length", "value": "25-minute pomodoros", "category": "preference"})], "Saved."
    if "add my deadlines" in p:
        return [("add_task", {"course": "Algorithms", "title": "Final exam", "kind": "exam", "due_date": "2026-11-10", "est_hours": 12}),
                ("add_task", {"course": "Databases", "title": "Assignment 3", "kind": "assignment", "due_date": "2026-11-03", "est_hours": 5}),
                ("add_task", {"course": "Operating Systems", "title": "Lab report", "kind": "lab", "due_date": "2026-11-06", "est_hours": 3})], "Added 3."
    if "wikipedia" in p:
        return [("wiki_summary", {"topic": "Dynamic programming"})], "DP overview."
    if "decision" in p:
        return [("remember", {"key": "priority_decision", "value": "Databases assignment first; skip optional OS reading", "category": "decision"})], "Noted."
    if "what do you remember" in p:
        return [], "From memory: " + memory_text  # the fake can only answer from what the harness gave it
    if "change of plans" in p:
        return [("remember", {"key": "study_time", "value": "evenings", "category": "preference"}),
                ("remember", {"key": "max_hours_per_day", "value": "4", "category": "preference"})], "Updated."
    if "mark it done" in p:
        return [("complete_task", {"task_id": "T2"}),
                ("plan_week", {"start_date": "2026-11-02", "hours_per_day": 4, "time_of_day": "evening"})], "Plan ready."
    raise AssertionError(prompt)


def fake_wiki(topic):
    return "Dynamic programming: a method for solving problems by breaking them into overlapping subproblems."


def api_responder(request):
    msgs = request["messages"]
    user_turn = next(m for m in reversed(msgs) if m["role"] == "user" and m["content"][0]["type"] == "text")
    calls, answer = script(last_user_text(request), user_turn["content"][0]["text"])
    if tool_round_done(request) or not calls:
        return message([text(answer)], "end_turn")
    return message([tool_use(n, a) for n, a in calls], "tool_use")


def test_api_scenario_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(domain, "wiki_summary", fake_wiki)
    out = tmp_path / "api.json"
    result = api_main.run_scenario(SCENARIO, out, FakeAnthropic(api_responder), state_dir=tmp_path / "state")
    assert result["checks_passed"] == f"{len(SCENARIO['checks'])}/{len(SCENARIO['checks'])}", result["checks"]
    saved = json.loads(out.read_text())
    turn = saved["turns"][0]
    assert set(turn["tokens"]) == {"input", "cache_read", "cache_write", "output"}
    assert {"model_calls", "tools", "cost_usd", "seconds"} <= set(turn)
    assert saved["loc"]["loop"] > 0
    assert len(saved["turns"]) == 7 and saved["turns"][4]["session"] == 2


def test_sdk_scenario_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(domain, "wiki_summary", fake_wiki)

    class Agent(StudyAgentSDK):
        async def __aenter__(self):
            md = Path(self.options.cwd) / "CLAUDE.md"  # what Claude Code would load at session start
            loaded = md.read_text()
            self.client = FakeSDKClient(self.options, self.tool_handlers, lambda p: script(p, loaded))
            return self

    out = tmp_path / "sdk.json"
    result = asyncio.run(sdk_main.run_scenario(SCENARIO, out, state_dir=tmp_path / "state", agent_cls=Agent))
    assert result["checks_passed"] == f"{len(SCENARIO['checks'])}/{len(SCENARIO['checks'])}", result["checks"]
    assert result["loc"]["tools"] > 0
