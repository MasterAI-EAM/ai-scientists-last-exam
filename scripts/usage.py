"""Summarize recorded harness usage without exporting prompts or credentials."""

from __future__ import annotations

import json
from pathlib import Path


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _sum_counts(values):
    values = list(values)
    return sum(values) if all(value is not None for value in values) else None


def _group(events: list[dict]) -> dict:
    inputs = [_count(event.get("input_token_count")) for event in events]
    outputs = [_count(event.get("output_token_count")) for event in events]
    input_tokens, output_tokens = _sum_counts(inputs), _sum_counts(outputs)
    return {
        "model_requests": len(events),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
        "cache_tokens": _sum_counts(
            _count(event.get("cached_content_token_count")) for event in events
        ),
        "responses_with_token_counts": sum(
            first is not None and second is not None for first, second in zip(inputs, outputs)
        ),
        "cost_usd": None,
    }


def summarize_usage(job: Path | None, trial: dict, trajectory: dict, relay: dict) -> dict:
    """Keep ATIF main-agent usage separate from all native API-response telemetry."""
    agent_result = trial.get("agent_result") or {}
    final = trajectory.get("final_metrics") or {}
    main_input = _count(agent_result.get("n_input_tokens", final.get("total_prompt_tokens")))
    main_output = _count(agent_result.get("n_output_tokens", final.get("total_completion_tokens")))
    main = {
        "model_requests": sum(
            step.get("source") == "agent" and bool(step.get("metrics"))
            for step in trajectory.get("steps", [])
        ),
        "input_tokens": main_input,
        "output_tokens": main_output,
        "total_tokens": (
            main_input + main_output if main_input is not None and main_output is not None else None
        ),
        "cache_tokens": _count(agent_result.get("n_cache_tokens")),
        "cost_usd": agent_result.get("cost_usd"),
    }
    files = sorted(job.glob("*/agent/qwen-sessions/**/chats/*.jsonl")) if job else []
    events, seen = [], set()
    malformed_lines = 0
    for path in files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                event = record.get("systemPayload", {}).get("uiEvent", {})
            except (ValueError, AttributeError):
                malformed_lines += 1
                continue
            if not isinstance(event, dict) or event.get("event.name") != "qwen-code.api_response":
                continue
            key = event.get("response_id") or event.get("execution_id")
            key = ("response", key) if key else (str(path), line_number)
            if key in seen:
                continue
            seen.add(key)
            events.append(event)
    groups = {"main_agent": [], "managed_auto_memory": [], "other_auxiliary": []}
    for event in events:
        subtype = event.get("subagent_type") or event.get("subagent_name")
        category = (
            "managed_auto_memory"
            if subtype == "managed-auto-memory-extractor"
            else "other_auxiliary"
            if subtype
            else "main_agent"
        )
        groups[category].append(event)
    total = _group(events) if events else None
    relay_count = _count(relay.get("model_requests"))
    return {
        "main_trajectory": main,
        "native_api_responses": total,
        "native_categories": {key: _group(value) for key, value in groups.items()}
        if events
        else {},
        "native_jsonl_files": len(files),
        "malformed_jsonl_lines": malformed_lines,
        "relay_model_requests": relay_count,
        "native_request_count_matches_relay": len(events) == relay_count if events else None,
        "accounting": (
            "Native API responses include harness auxiliary calls. Input tokens are cumulative "
            "across requests; cached tokens and thoughts must not be added again to total tokens. "
            "Recorded usage is not a provider billing statement; unknown cost remains null."
        ),
    }
