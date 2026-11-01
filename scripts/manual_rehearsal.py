"""Persistent manual-lab protocol rehearsal; all measurements are SIMULATED.

Invoke start, return, resume, return, report in separate controller processes.
This checks software hand-off/recovery without performing a wet experiment.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

import yaml

from aisle.contracts import AgentSpec, canonical
from aisle.engine import Engine
from aisle.execution import run_agent_loop
from aisle.store import Store
from aisle.tasks.simulator import LightGBMSimulator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["start", "return", "resume", "report"])
    parser.add_argument("--state", default=".aisle/manual-rehearsal")
    parser.add_argument("--provider", choices=["tencent", "local"], default="tencent")
    args = parser.parse_args()
    folder = Path(args.state)
    engine = Engine(Store(folder))
    registration = folder / "rehearsal.json"
    if args.phase == "start":
        if registration.exists():
            raise ValueError("rehearsal already exists; resume the recorded run")
        task_dir = folder / "task"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "examples/tasks/color_matching", task_dir
        )
        manifest = yaml.safe_load((task_dir / "task.yaml").read_text())
        manifest["budget"] = {"max_rounds": 2, "max_samples": 2}
        (task_dir / "task.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
        agent = AgentSpec(
            agent_id="qwen3.6-plus-tools-rehearsal",
            model="qwen3.6-plus",
            harness="tools",
            base_url_env="DASHSCOPE_API_BASE",
            api_key_env="DASHSCOPE_API_KEY",
            temperature=1,
            max_tokens=4096,
            max_turns=6,
            extra_body={"enable_thinking": False},
        )
        run, _ = engine.create_run(task_dir / "task.yaml", agent, mode="rehearsal")
        registration.write_text(
            canonical(
                {
                    "run_id": run["id"],
                    "provider": args.provider,
                    "purpose": "engineering only; simulated measurements; no physical experiment",
                }
            )
        )
    config = json.loads(registration.read_text())
    run_id = config["run_id"]
    if args.phase in {"start", "resume"}:
        state = run_agent_loop(engine, run_id, provider=config["provider"])
        if state["pending_order"]:
            order = engine.store.read("orders", state["pending_order"])
            (folder / (order["id"] + "-work-order.json")).write_text(canonical(order))
    elif args.phase == "return":
        state = engine.state(run_id)
        if not state["pending_order"]:
            raise ValueError("no pending experiment; do not fabricate a new order")
        order_id = state["pending_order"]
        order = engine.store.read("orders", order_id)
        engine.transition(order_id, "executing", "engineering-fixture")
        simulator = LightGBMSimulator(os.environ["AISLE_SIM_MODEL"])
        raw = simulator.execute(order["action"], state["task"]["target"])
        raw["rehearsal_notice"] = "SIMULATED measurement, not a physical experiment"
        engine.complete(order_id, raw, "engineering-fixture", [canonical(raw).encode()])
        before = engine.store.read("runs", run_id)
        engine.complete(order_id, raw, "engineering-fixture", [canonical(raw).encode()])
        after = engine.store.read("runs", run_id)
        assert before == after, "redelivery changed state or consumed another sample"
    state = engine.state(run_id)
    summary = {
        **config,
        "status": state["status"],
        "pending_order": state["pending_order"],
        "observations": len(state["history"]),
        "cost": state["cost"],
        "summary": state["summary"],
    }
    if args.phase == "report":
        with engine.store.connect() as db:
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT kind,payload FROM events WHERE run_id=? ORDER BY seq", (run_id,)
                )
            ]
        metadata = [json.loads(e["payload"]) for e in events if e["kind"] == "executor_started"]
        summary["execution_sessions"] = metadata
        summary["fresh_sandboxes"] = len({m.get("sandbox_id") for m in metadata})
        summary["orders"] = len([o for o in engine.store.list("orders") if o["run_id"] == run_id])
        assert (
            state["status"] == "completed"
            and summary["observations"] == 2
            and summary["orders"] == 2
        )
        assert state["cost"]["physical_samples"] == 0
        report = Path("docs/validation/manual-rehearsal.json")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
