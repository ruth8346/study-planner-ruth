"""JSON file storage for the study planner's domain data (tasks and the last plan).

Both harnesses point this at their own state directory, so API/ and SDK/ never
share data, but they read and write it with exactly the same code.
"""
from __future__ import annotations

import json
from pathlib import Path


def _read(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class TaskStore:
    """tasks.json: a list of {id, course, title, kind, due_date, est_hours, status}."""

    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / "tasks.json"

    def all(self) -> list[dict]:
        return _read(self.path, [])

    def save_all(self, tasks: list[dict]) -> None:
        _write(self.path, tasks)

    def upsert(self, course: str, title: str, kind: str, due_date: str, est_hours: float) -> tuple[dict, bool]:
        """Add a task, or update it if the same course+title already exists. Returns (task, created)."""
        tasks = self.all()
        for t in tasks:
            if t["course"].lower() == course.lower() and t["title"].lower() == title.lower():
                t.update(kind=kind, due_date=due_date, est_hours=est_hours)
                self.save_all(tasks)
                return t, False
        next_id = 1 + max((int(t["id"][1:]) for t in tasks), default=0)
        task = {"id": f"T{next_id}", "course": course, "title": title, "kind": kind,
                "due_date": due_date, "est_hours": est_hours, "status": "open"}
        tasks.append(task)
        self.save_all(tasks)
        return task, True

    def set_status(self, task_id: str, status: str) -> dict | None:
        tasks = self.all()
        for t in tasks:
            if t["id"].lower() == task_id.lower():
                t["status"] = status
                self.save_all(tasks)
                return t
        return None


class PlanStore:
    """plan.json: the most recent study plan the agent produced."""

    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / "plan.json"

    def load(self) -> dict | None:
        return _read(self.path, None)

    def save(self, plan: dict) -> None:
        _write(self.path, plan)
