"""Run the scenario on the Claude Agent SDK version.

    python SDK/main.py --scenario scenario.json --out results/sdk.json

Runs on your Claude Code login. ANTHROPIC_API_KEY must NOT be set, or billing moves to that key.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from SDK.agent import StudyAgentSDK  # noqa: E402
from SDK.tools import read_memory  # noqa: E402
from shared.scenario import load_scenario, reset_state, sdk_loc, snapshot, write_results  # noqa: E402

STATE_DIR = ROOT / "SDK" / "state"


async def run_scenario(scenario: dict, out: Path, state_dir: Path = STATE_DIR, agent_cls=StudyAgentSDK) -> dict:
    reset_state(state_dir)
    turns, states, n = [], {}, 0
    for s_idx, session in enumerate(scenario["sessions"], start=1):
        print(f"\n===== session {s_idx}: new agent instance, state loaded from {state_dir} =====", flush=True)
        agent = agent_cls(state_dir, scenario["model"], scenario["effort"], resume=session.get("resume", False))
        async with agent:
            for prompt in session["turns"]:
                n += 1
                print(f"\n--- turn {n} (session {s_idx}) ---\nUSER: {prompt}", flush=True)
                result = await agent.ask(prompt)
                print(f"AGENT: {result['answer']}", flush=True)
                turns.append({"turn": n, "session": s_idx, "prompt": prompt, **result,
                              "tools": [c["name"] for c in result["tool_calls"]]})
        memory = {k: v for k, (_, v) in read_memory(agent.md_path).items()}
        states[f"session_{s_idx}"] = snapshot(state_dir, memory)
    states["final"] = states[f"session_{len(scenario['sessions'])}"]
    return write_results(out, scenario, "SDK", turns, states, sdk_loc())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="scenario.json")
    parser.add_argument("--out", default="results/sdk.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is set: the SDK would bill that key instead of your Claude Code login. "
                 "Unset it in this terminal first (PowerShell: Remove-Item Env:ANTHROPIC_API_KEY).")
    result = asyncio.run(run_scenario(load_scenario(args.scenario), Path(args.out)))
    print(f"\nchecks passed: {result['checks_passed']}  totals: {result['totals']}")
    print(f"results written to {args.out}")


if __name__ == "__main__":
    main()
