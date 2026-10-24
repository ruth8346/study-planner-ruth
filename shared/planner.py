"""Deterministic weekly study scheduler: earliest deadline first, capped hours per day."""
from __future__ import annotations

from datetime import date, timedelta


def build_plan(tasks: list[dict], start: date, days: int, hours_per_day: float, time_of_day: str) -> dict:
    """Spread the open tasks' estimated hours over `days` days starting at `start`.

    A task is only studied on days strictly before its due date. Hours are
    allocated in half-hour steps. Whatever does not fit is listed as unscheduled.
    """
    open_tasks = sorted((t for t in tasks if t["status"] == "open"), key=lambda t: (t["due_date"], t["id"]))
    remaining = {t["id"]: float(t["est_hours"]) for t in open_tasks}
    schedule = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        capacity = float(hours_per_day)
        blocks = []
        for t in open_tasks:
            if capacity <= 0:
                break
            if remaining[t["id"]] <= 0 or day >= date.fromisoformat(t["due_date"]):
                continue
            hours = min(capacity, remaining[t["id"]])
            hours = int(hours * 2) / 2  # half-hour steps
            if hours <= 0:
                continue
            blocks.append({"task_id": t["id"], "course": t["course"], "title": t["title"], "hours": hours})
            remaining[t["id"]] -= hours
            capacity -= hours
        schedule.append({"date": day.isoformat(), "blocks": blocks})
    unscheduled = [{"task_id": t["id"], "course": t["course"], "hours": remaining[t["id"]], "due_date": t["due_date"]}
                   for t in open_tasks if remaining[t["id"]] > 0]
    return {"start_date": start.isoformat(), "days": days, "hours_per_day": hours_per_day,
            "time_of_day": time_of_day, "schedule": schedule, "unscheduled": unscheduled}


def render_plan(plan: dict) -> str:
    """One short line per day: compact on purpose, this text goes back to the model."""
    lines = [f"plan {plan['start_date']} +{plan['days']}d, {plan['time_of_day']}, max {plan['hours_per_day']}h/day"]
    for day in plan["schedule"]:
        d = date.fromisoformat(day["date"])
        body = ", ".join(f"{b['course']} {b['hours']:g}h" for b in day["blocks"]) or "free"
        lines.append(f"{d:%a %m-%d}: {body}")
    if plan["unscheduled"]:
        lines.append("unscheduled: " + ", ".join(f"{u['course']} {u['hours']:g}h (due {u['due_date']})"
                                                for u in plan["unscheduled"]))
    return "\n".join(lines)
