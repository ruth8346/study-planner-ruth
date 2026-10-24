"""Offline tests for the shared domain code (no network: the Wikipedia call is faked)."""
import io
import json
from datetime import date

import pytest

from shared import domain, wiki
from shared.checks import run_checks
from shared.domain import ToolError, run_domain_tool
from shared.planner import build_plan, render_plan
from shared.scenario import load_scenario, sdk_loc, api_loc, ROOT


def add(tmp_path, course, title, kind, due, hours):
    return run_domain_tool(tmp_path, "add_task", {"course": course, "title": title, "kind": kind,
                                                  "due_date": due, "est_hours": hours})


def test_add_task_is_idempotent(tmp_path):
    assert add(tmp_path, "Algorithms", "Final", "exam", "2026-11-10", 12).startswith("added T1")
    assert add(tmp_path, "algorithms", "final", "exam", "2026-11-11", 10).startswith("updated T1")
    assert "T1|Algorithms|exam:Final|due 2026-11-11|10h|open" == run_domain_tool(tmp_path, "list_tasks", {})


def test_domain_validation(tmp_path):
    with pytest.raises(ToolError):
        run_domain_tool(tmp_path, "add_task", {"course": "A", "title": "b", "kind": "party",
                                               "due_date": "2026-11-01", "est_hours": 1})
    with pytest.raises(ToolError):
        run_domain_tool(tmp_path, "list_tasks", {"colour": "red"})
    with pytest.raises(ToolError):
        run_domain_tool(tmp_path, "plan_week", {"start_date": "2026-11-02", "hours_per_day": 40,
                                                "time_of_day": "evening"})


def test_planner_respects_deadlines_and_capacity():
    tasks = [
        {"id": "T1", "course": "Algorithms", "title": "Final", "kind": "exam", "due_date": "2026-11-10", "est_hours": 12, "status": "open"},
        {"id": "T2", "course": "Databases", "title": "HW3", "kind": "assignment", "due_date": "2026-11-03", "est_hours": 5, "status": "done"},
        {"id": "T3", "course": "Operating Systems", "title": "Lab", "kind": "lab", "due_date": "2026-11-06", "est_hours": 3, "status": "open"},
    ]
    plan = build_plan(tasks, date(2026, 11, 2), 7, 4, "evening")
    for day in plan["schedule"]:
        assert sum(b["hours"] for b in day["blocks"]) <= 4
        for b in day["blocks"]:
            due = next(t["due_date"] for t in tasks if t["id"] == b["task_id"])
            assert day["date"] < due
    courses = {b["course"] for d in plan["schedule"] for b in d["blocks"]}
    assert courses == {"Algorithms", "Operating Systems"}
    assert plan["unscheduled"] == []
    assert render_plan(plan).splitlines()[1].startswith("Mon 11-02: Operating Systems 3h")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_wiki_summary_is_trimmed():
    pages = {
        "opensearch": ["dynamic programming", ["Dynamic programming"], [""], ["u"]],
        "summary": {"title": "Dynamic programming", "extract": "word " * 400,
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Dynamic_programming"}}},
    }

    def opener(req, timeout):
        key = "opensearch" if "opensearch" in req.full_url else "summary"
        return FakeResponse(json.dumps(pages[key]).encode())

    out = wiki.wiki_summary("dynamic programming", opener=opener)
    assert out.startswith("Dynamic programming: word")
    assert len(out) < 700 and out.endswith("wiki/Dynamic_programming")


def test_wiki_failure_becomes_tool_error(tmp_path, monkeypatch):
    def boom(topic):
        raise wiki.WikiError("Wikipedia request failed: offline")
    monkeypatch.setattr(domain, "wiki_summary", boom)
    with pytest.raises(ToolError):
        run_domain_tool(tmp_path, "wiki_summary", {"topic": "x"})


def test_checks_on_state():
    scenario = load_scenario(ROOT / "scenario.json")
    state = {"tasks": [{"id": "T1", "course": "Algorithms", "title": "Final", "kind": "exam", "due_date": "2026-11-10", "est_hours": 12, "status": "open"},
                       {"id": "T2", "course": "Databases", "title": "HW3", "kind": "assignment", "due_date": "2026-11-03", "est_hours": 5, "status": "done"}],
             "plan": {"hours_per_day": 4, "time_of_day": "evening",
                      "schedule": [{"date": "2026-11-02", "blocks": [{"course": "Algorithms", "hours": 4},
                                                                      {"course": "Operating Systems", "hours": 1}]}]},
             "memory": {"study_time": "evenings", "max_hours_per_day": "4", "priority_decision": "Databases first"}}
    s1 = dict(state, memory={"study_time": "mornings", "max_hours_per_day": "3", "priority_decision": "Databases first"})
    run = {"states": {"session_1": s1, "final": state},
           "turns": [{"turn": 3, "answer": "", "tool_calls": [{"name": "wiki_summary", "input": {"topic": "Dynamic programming"}, "is_error": False}]},
                     {"turn": 5, "answer": "You study in the mornings; Databases first.", "tool_calls": []}]}
    results = run_checks(run, scenario["checks"])
    assert all(r["passed"] for r in results), results
    stale = dict(state, memory={"study_time": "mornings", "max_hours_per_day": "4"})
    run["states"]["final"] = stale
    failed = {r["id"] for r in run_checks(run, scenario["checks"]) if not r["passed"]}
    assert {"no_stale_preference", "contradiction_overwrites"} <= failed


def test_scenario_shape_and_loc():
    scenario = load_scenario(ROOT / "scenario.json")
    assert len(scenario["checks"]) >= 5
    assert sum(c["on"] == "state" for c in scenario["checks"]) > len(scenario["checks"]) / 2
    assert set(api_loc()) >= {"loop", "tools", "history", "memory", "context", "compaction", "caching", "tokens"}
    loc = sdk_loc()
    assert loc["loop"] > 0 and loc["tools"] > 0 and loc["memory"] > 0 and loc["caching"] == 0
