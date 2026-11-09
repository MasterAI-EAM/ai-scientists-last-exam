"""Export the full model outputs of each agent run.

For every case in build.CASES (plus the single-colour run) this writes:
  transcripts/<name>.md         readable turn-by-turn transcript: the model's reasoning
                                (when the provider returned it), its analysis/plan message,
                                every keystroke batch it sent, and the terminal output it got
                                back, with per-turn token usage
  raw/<name>/trajectory.json    terminus-2 ATIF trajectory, unmodified
  raw/<name>/terminus_2.pane    final tmux pane scrollback, unmodified
  raw/<name>/result.json, verifier/{reward,diagnostics}.json

Run: python3 report/tools/export_transcripts.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import CASES, JOBS, OUT, SINGLE  # noqa: E402

FENCE = "````"  # observations contain ``` occasionally


def block(text: str, lang: str = "") -> str:
    return f"{FENCE}{lang}\n{text.rstrip()}\n{FENCE}\n"


def transcript(name: str, trial: Path) -> str:
    traj = json.loads((trial / "agent" / "trajectory.json").read_text())
    result = json.loads((trial / "result.json").read_text())
    reward = json.loads((trial / "verifier" / "reward.json").read_text())
    steps = traj["steps"]
    fm = traj.get("final_metrics", {})
    out = [
        f"# {name} — Full model output\n",
        f"- trial: `{trial.parent.name}/{trial.name}`",
        f"- reward: **{reward.get('reward')}**",
        f"- Start / end: {result.get('started_at')} → {result.get('finished_at')}",
        f"- Steps: {len(steps)} (agent turns {sum(s.get('source') == 'agent' for s in steps)})",
        f"- token: prompt {fm.get('total_prompt_tokens')}, completion {fm.get('total_completion_tokens')}, "
        f"cached {fm.get('total_cached_tokens')}",
        "",
        "Each turn contains model reasoning (when returned by the provider), model response (analysis / plan), "
        "terminal keystrokes and the terminal output observed on the next turn. Raw data: "
        f"`raw/{name}/trajectory.json`.\n",
    ]
    turn = 0
    for s in steps:
        src = s.get("source")
        ts = s.get("timestamp", "")
        if src != "agent":
            title = "System prompt + task instructions (first message to the model)" if s.get("step_id") == 1 else f"{src} message"
            out.append(f"\n## step {s.get('step_id')} · {title}\n")
            out.append(f"<details><summary>Expand</summary>\n\n{block(s.get('message') or '')}\n</details>\n")
            continue
        turn += 1
        m = s.get("metrics") or {}
        usage = ", ".join(f"{k} {v}" for k, v in m.items() if isinstance(v, (int, float)))
        out.append(f"\n## Turn {turn} · step {s.get('step_id')} · {ts}\n")
        if usage:
            out.append(f"_{usage}_\n")
        if s.get("reasoning_content"):
            out.append(f"<details><summary>Reasoning (reasoning_content)</summary>\n\n"
                       f"{block(s['reasoning_content'])}\n</details>\n")
        out.append("**Model response**\n")
        out.append(block(s.get("message") or ""))
        calls = s.get("tool_calls") or []
        if calls:
            out.append("**Commands sent**\n")
            for c in calls:
                args = c.get("arguments") or {}
                if c.get("function_name") == "bash_command":
                    out.append(f"`{c.get('tool_call_id')}` · Wait {args.get('duration')} s\n")
                    out.append(block(args.get("keystrokes", ""), "bash"))
                else:
                    out.append(f"`{c.get('function_name')}`\n")
                    out.append(block(json.dumps(args, ensure_ascii=False, indent=2), "json"))
        results = (s.get("observation") or {}).get("results") or []
        if results:
            text = "\n".join(r.get("content", "") for r in results)
            out.append("**Terminal output**\n")
            out.append(block(text))
    return "\n".join(out) + "\n"


def main():
    runs = {k: v[0] for k, v in CASES.items()}
    runs["single_color_001_kimi-k3"] = SINGLE
    tdir, rdir = OUT / "transcripts", OUT / "raw"
    tdir.mkdir(exist_ok=True)
    for name, rel in runs.items():
        trial = JOBS / rel
        (tdir / f"{name}.md").write_text(transcript(name, trial))
        dst = rdir / name
        (dst / "verifier").mkdir(parents=True, exist_ok=True)
        for f in ["agent/trajectory.json", "agent/terminus_2.pane", "result.json",
                  "verifier/reward.json", "verifier/diagnostics.json"]:
            if (trial / f).exists():
                shutil.copy2(trial / f, dst / Path(f).name if f.startswith("agent/") else dst / f)
        print(f"{name}: transcripts/{name}.md, raw/{name}/")


if __name__ == "__main__":
    main()
