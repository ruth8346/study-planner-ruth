"""Scenario plumbing shared by API/main.py and SDK/main.py: loading, clean state,
state snapshots, totals, line counts and writing results/*.json."""
from __future__ import annotations

import json
import re
import shutil
from importlib import metadata
from pathlib import Path

from shared.checks import run_checks
from shared.store import PlanStore, TaskStore

ROOT = Path(__file__).resolve().parent.parent


def load_scenario(path: str | Path) -> dict:
    scenario = json.loads(Path(path).read_text(encoding="utf-8"))
    n = sum(len(s["turns"]) for s in scenario["sessions"])
    assert len(scenario["sessions"]) == 2 and 6 <= n <= 8, "scenario must have 2 sessions and 6-8 turns"
    return scenario


def reset_state(state_dir: Path) -> None:
    """Every run starts from a clean state."""
    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True)


def snapshot(state_dir: Path, memory: dict) -> dict:
    return {"tasks": TaskStore(state_dir).all(), "plan": PlanStore(state_dir).load(), "memory": dict(memory)}


def totals(turns: list[dict]) -> dict:
    keys = ("input", "cache_read", "cache_write", "output")
    tok = {k: sum(t["tokens"][k] for t in turns) for k in keys}
    all_input = tok["input"] + tok["cache_read"] + tok["cache_write"]
    return {
        "tokens": tok,
        "cache_hit_pct": round(100 * tok["cache_read"] / all_input, 1) if all_input else 0.0,
        "model_calls": sum(t["model_calls"] for t in turns),
        "tool_calls": sum(len(t["tool_calls"]) for t in turns),
        "cost_usd": round(sum(t["cost_usd"] for t in turns), 4),
        "seconds": round(sum(t["seconds"] for t in turns), 1),
    }


def _code_lines(path: Path) -> list[str]:
    """Non-blank lines that are not pure comments."""
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]


def api_loc() -> dict:
    harness = ROOT / "API" / "harness"
    parts = {p.stem: len(_code_lines(p)) for p in sorted(harness.glob("*.py")) if p.stem != "__init__"}
    parts["agent.py + main.py (wiring)"] = len(_code_lines(ROOT / "API" / "agent.py")) + len(_code_lines(ROOT / "API" / "main.py"))
    return parts


def sdk_loc() -> dict:
    """Count the SDK lines tagged `# replaces: <part>` per harness part."""
    parts = {name: 0 for name in ("loop", "tools", "history", "memory", "context", "compaction", "caching", "tokens")}
    total = 0
    for p in sorted((ROOT / "SDK").glob("*.py")):
        lines = _code_lines(p)
        total += len(lines)
        for line in lines:
            m = re.search(r"#\s*replaces:\s*([a-z_]+)", line)
            if m:
                parts[m.group(1)] = parts.get(m.group(1), 0) + 1
    parts["all SDK/*.py lines"] = total
    return parts


def versions() -> dict:
    out = {}
    for pkg in ("anthropic", "claude-agent-sdk"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def write_results(out: str | Path, scenario: dict, version: str, turns: list[dict], states: dict,
                  loc: dict, extra: dict | None = None) -> dict:
    checks = run_checks({"turns": turns, "states": states}, scenario["checks"])
    result = {
        "version": version,
        "model": scenario["model"],
        "effort": scenario["effort"],
        "libraries": versions(),
        "turns": turns,
        "totals": totals(turns),
        "checks": checks,
        "checks_passed": f"{sum(c['passed'] for c in checks)}/{len(checks)}",
        "states": states,
        "loc": loc,
        **(extra or {}),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
