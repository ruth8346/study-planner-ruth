"""Run the scenario on the hand-written Messages API harness.

    python API/main.py --scenario scenario.json --out results/api.json

Needs ANTHROPIC_API_KEY in the environment (set it in the terminal only, never in code or git).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from API.agent import StudyAgent  # noqa: E402
from API.harness.history import History  # noqa: E402
from shared.scenario import api_loc, load_scenario, reset_state, snapshot, write_results  # noqa: E402

STATE_DIR = ROOT / "API" / "state"


def run_scenario(scenario: dict, out: Path, client, state_dir: Path = STATE_DIR, compact_at: int = 40_000) -> dict:
    reset_state(state_dir)
    turns, states, n = [], {}, 0
    for s_idx, session in enumerate(scenario["sessions"], start=1):
        print(f"\n===== session {s_idx}: new agent instance, state loaded from {state_dir} =====", flush=True)
        session_id = History.latest_session_id(state_dir / "sessions") if session.get("resume") else None
        agent = StudyAgent(client, state_dir, scenario["model"], scenario["effort"],
                           session_id=session_id, compact_at_tokens=compact_at)
        for prompt in session["turns"]:
            n += 1
            print(f"\n--- turn {n} (session {s_idx}) ---\nUSER: {prompt}", flush=True)
            result = agent.ask(prompt)
            print(f"AGENT: {result['answer']}", flush=True)
            turns.append({"turn": n, "session": s_idx, "prompt": prompt, **result,
                          "tools": [c["name"] for c in result["tool_calls"]]})
        states[f"session_{s_idx}"] = snapshot(state_dir, agent.memory.as_dict())
    states["final"] = states[f"session_{len(scenario['sessions'])}"]
    return write_results(out, scenario, "API", turns, states, api_loc())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="scenario.json")
    parser.add_argument("--out", default="results/api.json")
    parser.add_argument("--compact-at", type=int, default=40_000, help="compaction threshold in context tokens")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Set it in this terminal only, e.g. PowerShell: "
                 "$env:ANTHROPIC_API_KEY = '...'")
    import anthropic

    try:
        result = run_scenario(load_scenario(args.scenario), Path(args.out), anthropic.Anthropic(), compact_at=args.compact_at)
    except anthropic.AuthenticationError:
        sys.exit("The API rejected ANTHROPIC_API_KEY (401). Paste the real key from console.anthropic.com "
                 "into the environment variable, not a placeholder.")
    print(f"\nchecks passed: {result['checks_passed']}  totals: {result['totals']}")
    print(f"results written to {args.out}")


if __name__ == "__main__":
    main()
