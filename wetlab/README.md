# Wetlab: suspend and resume laboratory experiments

`wetlab` adds a local Docker controller around Harbor 0.25.0. After an agent submits an experiment, the framework saves container files, mounted data and the native session, removes the task containers, and waits outside the containers. Once results arrive, it rebuilds the environment and continues the next round in the original session.

Recovery covers persistent files and native context. Running processes, GPU memory, training state not written to disk, and network connections are outside the snapshot scope; background training must first save a restartable checkpoint. The current execution backend is local Docker.

## 0. Choose an execution mode

The same `wait_for_result` tool switches modes through the task's `[wetlab].execution_mode` or the `--execution-mode` launch option. The CLI option takes precedence. The default is `suspend`, preserving behavior for old runs.

| Mode | Tool returns | While waiting | Continuation |
| --- | --- | --- | --- |
| `suspend` | Acceptance receipt | Sign archives and remove containers | Rebuild containers, restore the native session and inject a result message |
| `blocking` | Experiment result | Containers and harness sessions keep running; the gateway waits outside them | The same tool call returns the result and the agent continues in the same session |

Blocking-mode configuration example (currently supported for **OpenClaw and Terminus-2**):

```toml
[wetlab]
execution_mode = "blocking"
budget = 3
max_rounds = 3
active_budget_sec = 28800
wait_timeout_sec = 90000  # Maximum external wait per experiment: 25 hours
blocking_agent_timeout_sec = 298860  # Active budget + 3 * wait limit + 60 seconds
```

Alternatively, append `--execution-mode blocking` to the launch command below to use the default 25-hour wait limit. `blocking_agent_timeout_sec` must be at least the value calculated above and is calculated automatically when omitted. It sets both the Harbor agent timeout and the controller monitoring deadline. Blocking-mode deadlines include waiting; `round_timeout_sec` and the post-submission suspension grace period do not terminate waits early.

A trusted worker binds the gateway to the full Docker container ID. Accepted experiments record the ticket ID, container identity and budget. Inside the container, submit and wait in one call:

```bash
wait_for_result --expr "1+1" --request-id measurement-001
# Wait for the external gateway result; continue analysis only after return.
wetlab finish --answer 2
```

Alternatively, use two explicit steps: confirm acceptance, then wait using the receipt's `seq`:

```bash
wetlab submit --expr "1+1" --request-id measurement-001
wait_for_result --ticket-id 1
```

`wetlab submit` returns only a receipt in either mode; `wetlab wait_for_result` is equivalent to the standalone command. In blocking mode, do not end the turn after submission, run the tool in the background or poll through model calls. The framework appends mode-specific instructions.

The gateway uses reconnectable HTTP long polling with short intervals. Each connection waits at most 20 seconds; gateway threads sleep until result notifications arrive, and the client retries transport only. There is no model polling or single 24-hour TCP connection. After gateway restart, network loss or termination of the waiting process, wait again with the same `--ticket-id`; no new ticket is created and no additional budget is charged. `--wait-timeout` ends only the current client wait, not the experiment. Duplicate results and waits produce only one delivery record.

OpenClaw extends native session and exec timeouts and disables the `process` tool to force synchronous exec returns. Terminus-2 blocks the host-side terminal sampling loop beyond its native 60-second sampling window. Other harnesses reject blocking mode before experiment submission; their existing `suspend` adapters remain available. **A configuration of ≥24h is not evidence of a completed ≥24h test.** See [TIMEOUTS.md](TIMEOUTS.md) for all 44 harnesses.

After controller interruption, `continue` can take over the same running worker without rotating tokens, pausing or rebuilding containers. If the harness has exited, the framework retains containers and tickets and marks an auditable failure; it does not automatically restart the harness. Waiting again by experiment ID restores only tool waiting, not an exited model process. Final archiving, ledger sealing and independent offline scoring occur after task completion.

## 1. Installation and credentials

Run from the repository root. Requires Python 3.12, running Docker and model-provider credentials:

```bash
# Reuse an existing .venv if available.
uv venv --python 3.12
uv pip install --python .venv/bin/python -r wetlab/requirements-dev.txt
cp wetlab/.env.example wetlab/.env
chmod 600 wetlab/.env
```

Edit `wetlab/.env` locally:

- `WETLAB_ADMIN_TOKEN`: experiment gateway administrator credential.
- `WETLAB_SIGNING_KEY`: checkpoint and ledger signing key.
- `OPENAI_API_KEY`, `OPENAI_API_BASE`: model credential and OpenAI-compatible endpoint used by the example.
- `WETLAB_ARCHIVE_DIR`: optional directory on a high-capacity disk.

Use independent random values for the administrator credential and signing key, for example from `secrets.token_hex(32)`. The gateway and controller must load the same configuration, and the signing key must remain unchanged throughout a run. Do not commit `.env`, `.wetlab.env` or `state/` to Git.

Load the configuration in both terminals below:

```bash
set -a
. wetlab/.env
set +a
export HARBOR="$PWD/.venv/bin/harbor"
export HARBOR_PYTHON="$PWD/.venv/bin/python"
```

Configure other providers using `--model`, `--base-url`, `--api-key-name` and harness options. Providers must support the protocol used by the harness. See `wetlab_run.py start --help` for CLI options.

## 2. Run the simulated example first

In terminal A, start the persistent gateway:

```bash
.venv/bin/python wetlab/gateway.py \
  --port 18765 --db wetlab/state/gateway.db --lab-delay 10 15
```

The default laboratory backend is an arithmetic simulator that returns results after 10–15 seconds. This example validates suspend/resume behavior; it is not a physical wet-lab experiment.

In terminal B, start the agent (this makes real model-provider requests):

```bash
.venv/bin/python wetlab/wetlab_run.py start wetlab/tasks/wetlab-add \
  --run-dir wetlab/state/example-001 \
  --agent openclaw --model openai/deepseek/deepseek-flash \
  --base-url "$OPENAI_API_BASE" --api-key-name OPENAI_API_KEY \
  --allow-agent-host tokenhub.tencentmaas.com \
  --gateway-url http://127.0.0.1:18765 \
  --gateway-url-container http://host.docker.internal:18765 \
  --setup-timeout 900 \
  --archive-dir "${WETLAB_ARCHIVE_DIR:-$PWD/wetlab/state/archives}"
```

This example uses Tencent TokenHub. `openai/` is Harbor's protocol prefix; the actual model ID is `deepseek/deepseek-flash`. Update `--allow-agent-host` when changing the endpoint. The container must reach `--gateway-url-container`: Docker Desktop supports `host.docker.internal`; other Docker installations require a reachable host address or host-gateway mapping.

`example-001` is a unique directory for one run. Use a new directory for a new experiment and `continue` or `retry` to resume an existing run. For large checkpoints, point `WETLAB_ARCHIVE_DIR` to a disk with sufficient capacity.

## 3. How agents submit experiments and read results

The canonical tools inside the container are:

```bash
wait_for_result --expr "1+1" --reasoning "measurement" --request-id experiment-001
wetlab status
wetlab history
wetlab finish --answer 2
```

In default `suspend` mode, `wait_for_result` immediately returns a ticket receipt and asks the agent to end the current round. It does not block or poll inside the container. The framework then:

1. Verifies that the native session has reached a resumable boundary, freezes all task services, and saves and signs filesystems, mounted data and sessions.
2. Removes task containers and waits at the external gateway for the batch of tickets. Early results are buffered until the checkpoint is committed.
3. Validates the checkpoint, delivers results, rebuilds containers and native sessions, and appends experiment results as the next user message.
4. Checks the session ID, all prior messages and new events to confirm continuation of the original task.

Result messages include the ticket ID, original expression, completion status, result, error if any, and remaining budget. Resumed agents can query delivered results through `wetlab history`; undelivered results remain hidden.

`wetlab wait_for_result` is equivalent. `wetlab submit` returns only an acceptance receipt, retaining compatibility with the original suspension behavior. Example images install both command entry points; the framework also installs `wait_for_result` when it is missing in older images, preserving the original `wetlab` file.

### Connect your own task to the controller

Copy `wetlab/tasks/wetlab-add` to a new task directory, retain Harbor's `instruction.md`, `task.toml` and `environment/`, and adapt instructions, dependencies and the verifier. The example Dockerfile installs `wetlab` and `wait_for_result`; custom images should install both entry points and provide Python 3.

Configure `task.toml`:

```toml
[wetlab]
max_rounds = 3
budget = 3
round_timeout_sec = 900
active_budget_sec = 28800
suspend_grace_sec = 25
pending_policy_on_seal = "cancel"
```

`budget` limits experiment submissions and cannot exceed `max_rounds`; the agent still receives a completion round after the last result. `active_budget_sec` limits accumulated active execution time, excluding experiment waiting. Instructions should require saving files before calling `wait_for_result` and ending the round, then completing the task with `wetlab finish`. Do not modify a task directory after launch; the controller checks its checksum.

The current ticket format uses a demonstration `expr` string and `reasoning`, not a general experiment-plan schema. A trusted laboratory backend can interpret an agreed text format for real workflows. Structured plans or attachments require coordinated client and gateway extensions while preserving idempotent identities.

Final scoring builds a separate verifier image from the task's `tests/Dockerfile` and runs `/tests/test.sh` without network access. The signed ledger is mounted read-only at `/ledger/ledger.json`, and output goes to `/logs/verifier/reward.txt`. The example verifier checks the experiment ledger. Scoring agent files or models requires additional read-only artifact inputs; ordinary Harbor verifier file-access assumptions cannot simply be reused.

## 4. Connect a human or external laboratory

Before starting a new real-experiment workflow, disable the arithmetic simulator with `--manual-lab`:

```bash
.venv/bin/python wetlab/gateway.py \
  --port 18765 --db wetlab/state/manual-gateway.db --manual-lab
```

The laboratory backend uses administrator credentials to query and claim tickets. This example assumes ticket 1:

```bash
curl --fail-with-body -sS \
  -H "Authorization: Bearer $WETLAB_ADMIN_TOKEN" \
  http://127.0.0.1:18765/admin/pending

curl --fail-with-body -sS \
  -H "Authorization: Bearer $WETLAB_ADMIN_TOKEN" \
  --json '{"claim_id":"lab-worker-attempt-001"}' \
  http://127.0.0.1:18765/admin/tickets/1/claim
```

**Execute only when `execute` is `true` in the claim response.** Use the returned `execution_id` as the idempotency key in external instruments or a LIMS. Submit the result after completion:

```bash
curl --fail-with-body -sS \
  -H "Authorization: Bearer $WETLAB_ADMIN_TOKEN" \
  --json '{"result":"2"}' \
  http://127.0.0.1:18765/admin/tickets/1/complete
```

For failures, use `{"failed":true,"result":null,"error":"failure description"}`. Results are currently text payloads; automatic upload, download or mounting of raw experimental files is not implemented. LIMS/UI integration must be implemented separately. Gateway administration interfaces are intended for local or trusted networks; the deployment layer must enforce network access controls.

## 5. Duplicate notifications and execution state

- Reuse `--request-id` and the original parameters when retrying the same operation across rounds. If omitted, the client uses one default identity per run/round. Use a new ID for an intentional repeat experiment in a later round.
- The client serializes concurrent calls with a file lock and persists and fsyncs the request record before POST. Lost responses reuse the original key.
- The gateway accepts the request, charges the experiment budget and closes submissions in one transaction. Reusing a key returns the original ticket; the same key with different content returns 409.
- Claiming first persists `accepted -> running`, issuing at most one execution permit per ticket. Duplicate notifications and competing workers receive `execute: false`.
- Repeated identical result submissions return the original result; conflicting results are rejected. Duplicate deliveries do not reopen a round that already has a pending experiment.
- A lost claim response or crashed execution process may leave a ticket in `running`. Query `/admin/running` and reconcile manually; do not rerun automatically.

This protocol provides at most one execution permit. Physical devices and human operators must respect claim results and ticket identities. The framework cannot deduplicate physical work performed outside the protocol. Legacy laboratory systems can still submit results directly, but execution integrations should use the claim protocol above.

## 6. Interruption, recovery and archives

```bash
.venv/bin/python wetlab/wetlab_run.py status wetlab/state/example-001
.venv/bin/python wetlab/wetlab_run.py continue wetlab/state/example-001
.venv/bin/python wetlab/wetlab_run.py retry wetlab/state/example-001
.venv/bin/python wetlab/wetlab_run.py abort wetlab/state/example-001
```

`continue` resumes an interrupted controller; `retry` retries a `FAILED_RECOVERABLE` stage; `abort` seals the ledger and handles pending tickets according to configuration. `status` can be used alongside a running controller. Only one controller may write to a run directory.

Signed checkpoints include immutable images for every task service, bind/volume/tmpfs archives, native sessions and companion files, exact harness versions and SHA-256 checksums. Mount restoration verifies contents, permissions, ownership and links, and restores shared-volume relationships. A read-only helper joins only the target PID namespace to collect tmpfs data.

`--archive-dir` stores large archives under a separate run-ID directory at the chosen location; state, logs and the ledger remain under `--run-dir`. Preserve both locations and the signing key. Images can be reloaded from `images.tar` after deleting the local image cache. Final-round files and trained models remain in the final environment archive.

Snapshot writes are serialized across processes and stop when either the archive disk or local run disk has less than 3 GiB of reserved free space. Free space before using `retry`. The framework refuses to commit snapshots when known credentials appear in configuration, sessions, mounts or compressed image layers. Unsigned legacy v1 checkpoints are not automatically upgraded.

Device/socket mounts, scaled Compose services and non-Docker backends are not approximately restored. `/wetlab-restore` and `/run/wetlab-internal` are framework-reserved paths.

## 7. Harnesses and validation scope

Native import, native filesystem restoration and protocol bridging are handled by `sessions.py`, `advanced.py` and adapter modules. Harness versions installed inside containers must match those before recovery. Workers integrate in-process only and do not modify installed Harbor source files.

The historical validation below applies to suspend mode. See [VALIDATION.md](VALIDATION.md) for the 29 harnesses tested with real models, mode limitations and incomplete adapters. Registration of an adapter does not establish live validation. The tested OpenClaw version is `2026.11.1 (4ffdd20)`. Gemini/Antigravity protocol bridges still call the designated DeepSeek model; ACP selects the OpenCode ACP backend; project-based frameworks such as Strands and LangGraph include example factories.

## 8. Tests

```bash
# No model requests; checks requiring Docker are skipped by default.
.venv/bin/python -m pytest wetlab/tests -q

# Includes real Docker, mount restoration, crash recovery, CLI/HTTP concurrency and duplicate notifications.
WETLAB_DOCKER_TEST=1 .venv/bin/python -m pytest wetlab/tests -q
```

Docker tests build their own base image from the example environment, without depending on machine-specific test tags. Building requires access to dependency sources; `WETLAB_TEST_IMAGE` can explicitly select an already prepared compatible base image.

Three-round tests with real models must be explicitly invoked and make provider requests; experiment feedback remains simulated:

```bash
.venv/bin/python wetlab/tests/run_live.py --env-file wetlab/.env \
  --harbor "$PWD/.venv/bin/harbor" --out wetlab/state/live-test-001 \
  --archive-dir "${WETLAB_ARCHIVE_DIR:-$PWD/wetlab/state/archives}" \
  --agents openclaw --workers 1 --setup-timeout 900 --active-budget 1800 --timeout 2400

.venv/bin/python wetlab/tests/verify_live.py \
  wetlab/state/live-test-001/openclaw/run --out wetlab/state/openclaw-verification.json
```

Private signing metadata for tests is saved locally in `/tmp` files with mode 0600; retain it for independent verification. Fault injection is for tests only: `WETLAB_CRASH_AT=after_checkpoint_rename`, `before_deliver`, `after_deliver`, and gateway `--fault-drop-submit-response N`.

Blocking-mode live-model validation entry point (provider credentials required; the test program simulates feedback):

```bash
.venv/bin/python wetlab/tests/run_blocking_live.py \
  --env-file wetlab/.env --out wetlab/state/blocking-live-001 \
  --harbor "$PWD/.venv/bin/harbor" --archive-dir "$WETLAB_ARCHIVE_DIR" \
  --agents openclaw terminus-2 --wait-seconds 70
```

Only `--wait-seconds 86410` tests an actual wait exceeding 24 hours. Keep the host, Docker, gateway and power supply stable; do not describe short passing tests as day-long validation. The run directory includes repeated container-state samples and `verification.json`. Provider credentials are not written to records; private signing metadata is stored separately in local `/tmp`.
