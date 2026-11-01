"""Opt-in live model × harness × task engineering check; never a scientific ranking.

Usage: uv run --env-file /path/to/credentials.env python scripts/live_smoke.py
The progress file makes resuming interrupted work explicit; no blind reruns.
"""

import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

from aisle.contracts import AgentSpec
from aisle.engine import Engine
from aisle.execution import run_agent_loop
from aisle.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["local", "tencent"], default="tencent")
    parser.add_argument("--state", default=".aisle/live-smoke")
    parser.add_argument("--report", default="docs/validation/live-smoke.json")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--jobs", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state_dir = Path(args.state)
    state_dir.mkdir(parents=True, exist_ok=True)
    progress_path = state_dir / "progress.json"
    engine = Engine(Store(state_dir))
    if progress_path.exists():
        progress = json.loads(progress_path.read_text())
        if progress["provider"] != args.provider or progress["rounds"] != args.rounds:
            raise ValueError("resume with the original provider and rounds")
    else:
        agents = []
        for model, env, parameter in [
            ("qwen3.6-plus", "DASHSCOPE", "max_tokens"),
            ("gpt-5.4", "OPENAI", "max_completion_tokens"),
        ]:
            for harness in ["json", "tools"]:
                agents.append(
                    AgentSpec(
                        agent_id=model + "-" + harness,
                        model=model,
                        harness=harness,
                        temperature=1,
                        max_tokens=4096,
                        max_turns=8,
                        token_parameter=parameter,
                        base_url_env=env + "_API_BASE",
                        api_key_env=env + "_API_KEY",
                        extra_body={"enable_thinking": False} if env == "DASHSCOPE" else {},
                    )
                )
        progress = {
            "provider": args.provider,
            "rounds": args.rounds,
            "runs": [],
            "purpose": "engineering smoke; not scientific acceptance or leaderboard",
        }
        for task_id in ["color_matching", "color_matching_safety"]:
            task_dir = state_dir / "task-packages" / task_id
            shutil.copytree(root / "examples/tasks" / task_id, task_dir)
            task_path = task_dir / "task.yaml"
            task = yaml.safe_load(task_path.read_text())
            task["budget"] = {"max_rounds": args.rounds, "max_samples": args.rounds}
            task_path.write_text(yaml.safe_dump(task, sort_keys=False))
            campaign = engine.create_campaign(task_path, agents, k=2, engineering_only=True)
            for agent in agents:
                run, _ = engine.create_run(task_path, agent, campaign_id=campaign["id"])
                progress["runs"].append(
                    {"run_id": run["id"], "task_id": task_id, "agent_id": agent.agent_id}
                )
        progress_path.write_text(json.dumps(progress, indent=2))
    report = {**progress, "checked_at": datetime.now(timezone.utc).isoformat(), "results": []}

    def check(item):
        run = engine.store.read("runs", item["run_id"])
        print(json.dumps({**item, "starting_status": run["status"]}), flush=True)
        try:
            result = run_agent_loop(engine, run["id"], provider=args.provider)
            saved = engine.store.read("runs", run["id"])
            with engine.store.connect() as db:
                events = [
                    json.loads(r["payload"])
                    for r in db.execute(
                        "SELECT payload FROM events WHERE run_id=? AND kind='model_response'",
                        (run["id"],),
                    )
                ]
            row = {
                **item,
                "status": result["status"],
                "rounds": len(result["history"]),
                "cost": result["cost"],
                "summary": result["summary"],
                "feedback_used": bool(result["checkpoint"].get("seen_orders")),
                "task_revision": saved["task_revision"],
                "code_revision": saved["code_revision"],
                "agent_revision": saved["agent_revision"],
                "response_models": sorted(
                    {e["response_model"] for e in events if e.get("response_model")}
                ),
                "termination": result["checkpoint"].get("pending_finish", "task_or_budget_stop"),
            }
        except Exception as exc:  # noqa: BLE001 - record each independent live check and continue.
            row = {
                **item,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:160],
            }
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(check, item) for item in progress["runs"]]
        for future in as_completed(futures):
            report["results"].append(future.result())
            output = Path(args.report)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            )
    # Choosing to finish after seeing feedback is a valid Agent decision. Check
    # actual feedback consumption, rather than force a desired number of actions.
    if any(r["status"] != "completed" or not r.get("feedback_used") for r in report["results"]):
        raise SystemExit(
            "Some live checks lack a completed feedback-conditioned decision; inspect saved state."
        )


if __name__ == "__main__":
    main()
