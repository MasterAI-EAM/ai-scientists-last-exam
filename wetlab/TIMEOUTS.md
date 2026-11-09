# Blocking mode: harness timeout validation

Environment: Harbor 0.25.0. Recorded on 2026-11-07. Harbor registers 46 agents, or 44 model harnesses after excluding oracle/nop. Native recovery and synchronous tool waiting require separate validation.

## Three timeout layers

1. Gateway/transport: each gateway long poll lasts at most 20 seconds and can reconnect using the original experiment ID. The default tool wait is 90000 seconds. Disconnecting does not submit or execute an experiment.
2. Harness tool/turn: native CLIs may impose separate tool timeouts or automatically return in the background. Extending only the Harbor timeout does not guarantee continued agent waiting.
3. Harbor/controller: `blocking_agent_timeout_sec >= active_budget_sec + budget * wait_timeout_sec + 60`. Waiting counts toward the total deadline; suspend-mode active-budget cutoffs and submission grace periods no longer apply.

Harbor 0.25.0 uses `asyncio.wait_for(..., timeout=timeout_sec)` in `_run_agent_phase` in `harbor/trial/trial.py`, so experiment waiting explicitly consumes the total agent time budget. The framework generates extended task configuration for blocking mode and retains containers after timeout for inspection.

## Current policies and evidence

- OpenClaw: the tested version is pinned to `2026.11.1 (4ffdd20)`. Set `agents.defaults.timeoutSeconds`, `tools.exec.timeoutSeconds` and CLI `timeout`, and add `process` to `tools.deny` to make exec wait synchronously. In this package, `lazy-exec-tool-*.mjs` controls background execution based on availability of `process`; `bash-tools-*.mjs` caps foreground sampling at 120000 ms by default, so increasing yield alone is insufficient.
- Terminus-2: Harbor caps native terminal command duration at 60 seconds (`harbor/agents/terminus_2/terminus_2.py`). The local in-process adapter waits for external experiment delivery after `_execute_commands`, then samples the result and resumes reasoning. It does not require repeated empty commands from the model.
- Other 42 harnesses: this version has no blocking-wait policy and rejects blocking-mode launches. See [VALIDATION.md](VALIDATION.md) for their suspend-mode status. The table below does not treat a total-timeout option as proof that an individual tool supports 24-hour waits.

OpenClaw documentation states that disabling `process` makes exec synchronous and distinguishes exec lifetime from yield time: [Exec tool](https://docs.openclaw.ai/tools/exec), [Background exec](https://docs.openclaw.ai/background-process). Online documentation may change; the installed version and actual tests remain authoritative.

| Harness | Blocking-wait policy | >=24h configuration capability | >=24h actual continuous wait |
| --- | --- | --- | --- |
| acp | Not adapted; rejected before submission | Unconfirmed | Not run |
| terminus-2 | Implemented; short live-model test below | Native sampling capped at 60s; host loop extends the wait | Not run |
| claude-code | Not adapted; rejected before submission | Unconfirmed | Not run |
| copilot-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| code-puppy | Not adapted; rejected before submission | Unconfirmed | Not run |
| aider | Not adapted; rejected before submission | Unconfirmed | Not run |
| cline-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| codex | Not adapted; rejected before submission | Unconfirmed | Not run |
| cortex-code | Not adapted; rejected before submission | Unconfirmed | Not run |
| cursor-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| gemini-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| antigravity-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| antigravity-sdk | Not adapted; rejected before submission | Unconfirmed | Not run |
| rovodev-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| goose | Not adapted; rejected before submission | Unconfirmed | Not run |
| grok-build | Not adapted; rejected before submission | Unconfirmed | Not run |
| hermes | Not adapted; rejected before submission | Unconfirmed | Not run |
| junie | Not adapted; rejected before submission | Unconfirmed | Not run |
| kimi-code | Not adapted; rejected before submission | Unconfirmed | Not run |
| kimi-cli | Not adapted; rejected before submission | Unconfirmed | Not run |
| langgraph | Not adapted; rejected before submission | Unconfirmed | Not run |
| deerflow | Not adapted; rejected before submission | Unconfirmed | Not run |
| mini-swe-agent | Not adapted; rejected before submission | Unconfirmed | Not run |
| nemo-agent | Not adapted; rejected before submission | Unconfirmed | Not run |
| swe-agent | Not adapted; rejected before submission | Unconfirmed | Not run |
| opencode | Not adapted; rejected before submission | Unconfirmed | Not run |
| mimo | Not adapted; rejected before submission | Unconfirmed | Not run |
| mcode | Not adapted; rejected before submission | Unconfirmed | Not run |
| openclaw | Implemented; short live-model test below | Native tool/turn settings configurable; foreground policy integrated | Not run |
| openhands | Not adapted; rejected before submission | Unconfirmed | Not run |
| openhands-sdk | Not adapted; rejected before submission | Unconfirmed | Not run |
| pi | Not adapted; rejected before submission | Unconfirmed | Not run |
| qwen-coder | Not adapted; rejected before submission | Unconfirmed | Not run |
| devin | Not adapted; rejected before submission | Unconfirmed | Not run |
| trae-agent | Not adapted; rejected before submission | Unconfirmed | Not run |
| computer-1 | Not adapted; rejected before submission | Unconfirmed | Not run |
| eve | Not adapted; rejected before submission | Unconfirmed | Not run |
| fx | Not adapted; rejected before submission | Unconfirmed | Not run |
| fx-dev | Not adapted; rejected before submission | Unconfirmed | Not run |
| dspy-rlm | Not adapted; rejected before submission | Unconfirmed | Not run |
| vibe | Not adapted; rejected before submission | Unconfirmed | Not run |
| muse-code | Not adapted; rejected before submission | Unconfirmed | Not run |
| strands | Not adapted; rejected before submission | Unconfirmed | Not run |
| fabric | Not adapted; rejected before submission | Unconfirmed | Not run |

## Reproducible validation

- HTTP/CLI regression: actual gateway restart, termination of the waiting process, lost result responses, repeated waits, unauthorized ticket IDs and wait deadlines. Experiment counts must remain unchanged and delivery must occur only once.
- Docker regression: container ID/StartedAt stay unchanged while waiting, Running=true and Paused=false, and an independent heartbeat continues writing.
- Live-model entry point `tests/run_blocking_live.py`: OpenClaw and Terminus-2 can run together. The test uses the designated DeepSeek model, simulates manual result submission, records container samples, and scores the signed experiment ledger with an independent offline verifier. Raw records stay local; do not commit credentials or trajectories.
- Only `--wait-seconds 86410` tests an actual >=24h wait. Short probes do not validate host sleep, day-long connectivity or provider session lifetimes; these remain unverified.

## Results of the short live-model retest

Full regression: `113 passed in 71.45s`, including seven actual Docker integration checks. The final live-model retest used the same implementation version: OpenClaw waited 70.103 seconds and Terminus-2 70.221 seconds. Both had no Harbor harness exception, unchanged container identities and start times, no suspension/intermediate checkpoint, and independent verifier reward=1. The actual Harbor total timeout was 90660 seconds with no smaller agent override/max. See [VALIDATION.md](VALIDATION.md).

Acceptance checks must inspect model-harness exception records; `wetlab finish` and reward alone do not establish full framework success. An actual >=24h test has not been run.
