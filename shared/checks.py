"""Pass/fail checks declared in scenario.json, evaluated the same way for both versions.

A run looks like:
  {"turns": [{"turn": 1, "session": 1, "answer": "...", "tool_calls": [{"name", "input", "is_error"}]}],
   "states": {"session_1": state, "final": state}}
where state = {"tasks": [...], "plan": {...} | None, "memory": {key: value}}.
Most check types look at the saved state, not at the answer text.
"""
from __future__ import annotations


def _memory_text(memory: dict) -> list[str]:
    return [f"{k}: {v}".lower() for k, v in memory.items()]


def _find_task(tasks: list[dict], course_contains: str) -> list[dict]:
    return [t for t in tasks if course_contains.lower() in t["course"].lower()]


def check_task_exists(run: dict, c: dict) -> tuple[bool, str]:
    tasks = _find_task(run["states"][c.get("at", "final")]["tasks"], c["course_contains"])
    ok = [t for t in tasks if t["due_date"] == c["due_date"] and (not c.get("kind") or t["kind"] == c["kind"])]
    return bool(ok), f"matching tasks: {[t['id'] + ' ' + t['due_date'] for t in tasks] or 'none'}"


def check_task_status(run: dict, c: dict) -> tuple[bool, str]:
    tasks = _find_task(run["states"][c.get("at", "final")]["tasks"], c["course_contains"])
    ok = bool(tasks) and all(t["status"] == c["status"] for t in tasks)
    return ok, f"statuses: {[t['status'] for t in tasks] or 'no task'}"


def check_memory_contains(run: dict, c: dict) -> tuple[bool, str]:
    """Every group in `all_of` must be satisfied by some memory entry containing any of its words."""
    entries = _memory_text(run["states"][c["at"]]["memory"])
    missing = [group for group in c["all_of"] if not any(any(w in e for w in group) for e in entries)]
    return not missing, f"missing {missing}" if missing else f"{len(entries)} entries ok"


def check_memory_excludes(run: dict, c: dict) -> tuple[bool, str]:
    """No memory entry may mention `term` unless it also mentions `unless` (e.g. 'changed from morning to evening')."""
    entries = _memory_text(run["states"][c["at"]]["memory"])
    bad = [e for e in entries if c["term"] in e and not (c.get("unless") and c["unless"] in e)]
    return not bad, f"stale: {bad}" if bad else "no stale entry"


def check_tool_called(run: dict, c: dict) -> tuple[bool, str]:
    turns = [t for t in run["turns"] if "turn" not in c or t["turn"] == c["turn"]]
    calls = [tc for t in turns for tc in t["tool_calls"] if tc["name"] == c["name"]]
    good = [tc for tc in calls if not tc["is_error"]
            and all(w.lower() in str(tc["input"]).lower() for w in c.get("input_contains", []))]
    return bool(good), f"{len(calls)} call(s), {len(good)} matching"


def check_answer_contains(run: dict, c: dict) -> tuple[bool, str]:
    answer = next(t["answer"] for t in run["turns"] if t["turn"] == c["turn"]).lower()
    missing = [group for group in c["all_of"] if not any(w in answer for w in group)]
    return not missing, f"missing {missing}" if missing else "all terms present"


def check_plan_matches(run: dict, c: dict) -> tuple[bool, str]:
    plan = run["states"][c.get("at", "final")]["plan"]
    if not plan:
        return False, "no plan saved"
    problems = []
    if plan["hours_per_day"] > c["max_hours_per_day"]:
        problems.append(f"hours_per_day {plan['hours_per_day']}")
    if c.get("min_hours_per_day") and plan["hours_per_day"] < c["min_hours_per_day"]:
        problems.append(f"hours_per_day {plan['hours_per_day']} below preference")
    if plan["time_of_day"] != c["time_of_day"]:
        problems.append(f"time_of_day {plan['time_of_day']}")
    courses = {b["course"].lower() for d in plan["schedule"] for b in d["blocks"]}
    for want in c.get("includes", []):
        if not any(want in course for course in courses):
            problems.append(f"missing {want}")
    for unwanted in c.get("excludes", []):
        if any(unwanted in course for course in courses):
            problems.append(f"contains {unwanted}")
    return not problems, "; ".join(problems) or f"courses {sorted(courses)}"


CHECKS = {
    "task_exists": check_task_exists,
    "task_status": check_task_status,
    "memory_contains": check_memory_contains,
    "memory_excludes": check_memory_excludes,
    "tool_called": check_tool_called,
    "answer_contains": check_answer_contains,
    "plan_matches": check_plan_matches,
}


def run_checks(run: dict, checks: list[dict]) -> list[dict]:
    results = []
    for c in checks:
        try:
            passed, detail = CHECKS[c["type"]](run, c)
        except Exception as e:  # a missing turn or state counts as a failure, not a crash
            passed, detail = False, f"check error: {e!r}"
        results.append({"id": c["id"], "type": c["type"], "on": c.get("on", "state"),
                        "description": c["description"], "passed": passed, "detail": detail})
    return results
