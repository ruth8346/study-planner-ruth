"""Domain tools of the study planner: JSON schemas + implementations, shared by API/ and SDK/.

Token optimization: every tool returns a short plain-text answer (one line per
item, no pretty JSON, no echo of the input). Errors raise ToolError and each
harness reports them back to the model as an is_error tool result.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from shared.planner import build_plan, render_plan
from shared.store import PlanStore, TaskStore
from shared.wiki import WikiError, wiki_summary


class ToolError(Exception):
    """A problem the model can fix (bad date, unknown task id, ...)."""


DOMAIN_TOOL_SPECS: list[dict] = [
    {
        "name": "add_task",
        "description": "Add (or update, if course+title exists) an exam, assignment, lab or reading with its due date and estimated study hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course": {"type": "string", "description": "Course name, e.g. 'Algorithms'"},
                "title": {"type": "string", "description": "Short task title, e.g. 'Final exam'"},
                "kind": {"type": "string", "enum": ["exam", "assignment", "lab", "reading", "other"]},
                "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                "est_hours": {"type": "number", "description": "Estimated hours of work"},
            },
            "required": ["course", "title", "kind", "due_date", "est_hours"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks, one compact line each. Filter by status and/or course.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "done", "all"], "description": "Default: open"},
                "course": {"type": "string", "description": "Optional course name filter"},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as done by its id (e.g. 'T2'). Use list_tasks first if you do not know the id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "plan_week",
        "description": "Build and save a study plan over the open tasks (earliest deadline first). Pass the user's current preferences for hours per day and time of day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "hours_per_day": {"type": "number"},
                "time_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
                "days": {"type": "integer", "description": "Default 7"},
            },
            "required": ["start_date", "hours_per_day", "time_of_day"],
        },
    },
    {
        "name": "wiki_summary",
        "description": "External: fetch a short Wikipedia summary of a study topic (internet).",
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    },
]

# Memory tools have the same schema in both versions; only where they store differs
# (API/harness/memory.py -> memory.json, SDK/tools.py -> CLAUDE.md).
MEMORY_TOOL_SPECS: list[dict] = [
    {
        "name": "remember",
        "description": "Save a lasting preference, decision or fact about the user. Reuse the same key to replace an old value (e.g. when the user changes their mind).",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Stable snake_case key, e.g. 'study_time', 'max_hours_per_day', 'priority_decision'"},
                "value": {"type": "string"},
                "category": {"type": "string", "enum": ["preference", "decision", "fact"]},
            },
            "required": ["key", "value", "category"],
        },
    },
    {
        "name": "forget",
        "description": "Delete a saved memory by key.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
]


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolError(f"bad date '{value}', expected YYYY-MM-DD")


def _task_line(t: dict) -> str:
    return f"{t['id']}|{t['course']}|{t['kind']}:{t['title']}|due {t['due_date']}|{t['est_hours']:g}h|{t['status']}"


def add_task(state_dir: Path, course: str, title: str, kind: str, due_date: str, est_hours: float) -> str:
    _parse_date(due_date)
    if float(est_hours) <= 0:
        raise ToolError("est_hours must be > 0")
    task, created = TaskStore(state_dir).upsert(course.strip(), title.strip(), kind, due_date, float(est_hours))
    return ("added " if created else "updated ") + _task_line(task)


def list_tasks(state_dir: Path, status: str = "open", course: str | None = None) -> str:
    tasks = TaskStore(state_dir).all()
    if status != "all":
        tasks = [t for t in tasks if t["status"] == status]
    if course:
        tasks = [t for t in tasks if course.lower() in t["course"].lower()]
    return "\n".join(_task_line(t) for t in tasks) or "no tasks"


def complete_task(state_dir: Path, task_id: str) -> str:
    task = TaskStore(state_dir).set_status(task_id, "done")
    if task is None:
        raise ToolError(f"unknown task id '{task_id}'")
    return "done " + _task_line(task)


def plan_week(state_dir: Path, start_date: str, hours_per_day: float, time_of_day: str, days: int = 7) -> str:
    start = _parse_date(start_date)
    if not 0 < float(hours_per_day) <= 16:
        raise ToolError("hours_per_day must be between 0 and 16")
    if not 1 <= int(days) <= 31:
        raise ToolError("days must be between 1 and 31")
    plan = build_plan(TaskStore(state_dir).all(), start, int(days), float(hours_per_day), time_of_day)
    PlanStore(state_dir).save(plan)
    return render_plan(plan)


def wiki(state_dir: Path, topic: str) -> str:
    try:
        return wiki_summary(topic)
    except WikiError as e:
        raise ToolError(str(e))


DOMAIN_FUNCS = {
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "plan_week": plan_week,
    "wiki_summary": wiki,
}


def run_domain_tool(state_dir: Path, name: str, args: dict) -> str:
    """Run one domain tool. Raises ToolError for anything the model should see as an error."""
    if name not in DOMAIN_FUNCS:
        raise ToolError(f"unknown tool '{name}'")
    spec = next(s for s in DOMAIN_TOOL_SPECS if s["name"] == name)
    missing = [k for k in spec["input_schema"].get("required", []) if k not in args]
    if missing:
        raise ToolError(f"missing required field(s): {', '.join(missing)}")
    allowed = spec["input_schema"]["properties"]
    unknown = [k for k in args if k not in allowed]
    if unknown:
        raise ToolError(f"unknown field(s): {', '.join(unknown)}")
    for k, v in args.items():
        enum = allowed[k].get("enum")
        if enum and v not in enum:
            raise ToolError(f"{k} must be one of {enum}")
    try:
        return DOMAIN_FUNCS[name](Path(state_dir), **args)
    except (TypeError, ValueError) as e:
        raise ToolError(f"bad arguments: {e}")
