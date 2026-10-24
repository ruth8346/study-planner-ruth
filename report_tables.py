"""Regenerate the measured tables in REPORT.md from results/api.json and results/sdk.json.

    python report_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

from shared.scenario import api_loc, sdk_loc

ROOT = Path(__file__).resolve().parent
START, END = "<!-- TABLES:START -->", "<!-- TABLES:END -->"


def load(name: str) -> dict | None:
    path = ROOT / "results" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def cell(run: dict | None, fn) -> str:
    return fn(run) if run else "לא הורץ"


def tables(api: dict | None, sdk: dict | None) -> str:
    rows = [
        ("טוקנים: input", lambda r: f"{r['totals']['tokens']['input']:,}"),
        ("טוקנים: cache read", lambda r: f"{r['totals']['tokens']['cache_read']:,}"),
        ("טוקנים: cache write", lambda r: f"{r['totals']['tokens']['cache_write']:,}"),
        ("טוקנים: output", lambda r: f"{r['totals']['tokens']['output']:,}"),
        ("אחוז cache", lambda r: f"{r['totals']['cache_hit_pct']}%"),
        ("קריאות למודל", lambda r: str(r["totals"]["model_calls"])),
        ("עלות", lambda r: f"${r['totals']['cost_usd']:.3f}"),
        ("בדיקות שעברו", lambda r: r["checks_passed"]),
    ]
    out = ["## 1. API מול SDK", "", "| מדד | API | SDK |", "|---|---|---|"]
    out += [f"| {name} | {cell(api, fn)} | {cell(sdk, fn)} |" for name, fn in rows]

    parts = ["loop", "tools", "history", "memory", "context", "compaction", "caching", "tokens"]
    out += ["", "## 2. שורות קוד לכל חלק", "",
            "ב-API ספרתי את שורות הקוד בכל קובץ של ה-harness, וב-SDK את השורות שמסומנות בהערה replaces.", "",
            "| חלק | API | SDK |", "|---|---|---|"]
    a, b = api_loc(), sdk_loc()  # line counts come from the code itself, not from a run
    for p in parts:
        out.append(f"| {p} | {a.get(p, 0)} | {b.get(p, 0)} |")
    out.append(f"| **סה\"כ** | **{sum(a.get(p, 0) for p in parts)}** | **{sum(b.get(p, 0) for p in parts)}** |")
    return "\n".join(out)


def main() -> None:
    report = ROOT / "REPORT.md"
    text = report.read_text(encoding="utf-8")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    report.write_text(before + START + "\n" + tables(load("api"), load("sdk")) + "\n" + END + after, encoding="utf-8")
    print("REPORT.md tables updated")


if __name__ == "__main__":
    main()
