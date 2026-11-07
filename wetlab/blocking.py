"""Host-side policy for an uninterrupted Harbor execution and external waits."""
from __future__ import annotations
import asyncio
import json
import math
import subprocess
import time
import urllib.request
from pathlib import Path

# Other adapters remain available in suspend mode. Do not silently promise that
# native tools with an early/background return can wait synchronously for a day.
SUPPORTED = {'openclaw', 'terminus-2'}


def settings(config, agent, mode=None):
    mode = mode or config.get('execution_mode', 'suspend')
    if mode not in ('suspend', 'blocking'):
        raise ValueError('execution_mode must be suspend or blocking')
    if mode == 'suspend':return {'execution_mode': mode}
    if agent not in SUPPORTED:
        raise ValueError(f'blocking policy is not validated for {agent}; use suspend mode. See TIMEOUTS.md')
    wait = float(config.get('wait_timeout_sec', 90000))
    active = float(config.get('active_budget_sec', 28800))
    budget = min(int(config.get('budget', 3)), int(config.get('max_rounds', 3)))
    minimum = active + budget * wait + 60
    total = float(config.get('blocking_agent_timeout_sec', minimum))
    if any(not math.isfinite(x) or x <= 0 for x in (wait, active, total)) or budget <= 0 or total < minimum:
        raise ValueError('blocking_agent_timeout_sec must cover active_budget_sec + budget * wait_timeout_sec + 60')
    return {'execution_mode': mode, 'wait_timeout_sec': wait, 'blocking_agent_timeout_sec': total}


def configure_worker(state):
    """Applied only in the worker process; never changes installed Harbor files."""
    if state.get('execution_mode') != 'blocking':return
    if state['agent'] not in SUPPORTED:raise ValueError('unsupported blocking harness')
    if state['agent'] == 'terminus-2':
        from harbor.agents.terminus_2.terminus_2 import Terminus2
        original = Terminus2._execute_commands
        async def execute(self, commands, session):
            result = await original(self, commands, session)
            # Terminus normally samples terminal output after at most 60s. Hold
            # its HOST loop here so it cannot ask the model to poll the terminal.
            if not any('wait_for_result' in command.keystrokes for command in commands):return result
            deadline = time.monotonic() + state['wait_timeout_sec'] + 30
            while time.monotonic() < deadline:
                def inspect():
                    req = urllib.request.Request(state['gateway_url'] + f"/admin/runs/{state['run_id']}",
                        headers={'Authorization': 'Bearer ' + __import__('os').environ['WETLAB_ADMIN_TOKEN']})
                    with urllib.request.urlopen(req, timeout=30) as response:return json.load(response)
                try:run = await asyncio.to_thread(inspect)
                except (OSError, ValueError):
                    await asyncio.sleep(.5);continue
                if not any(not t['delivered_at'] and t['status'] != 'cancelled' for t in run['tickets']):
                    await asyncio.sleep(.2)
                    return result[0], result[1] + '\n' + await session.get_incremental_output()
                await asyncio.sleep(.5)
            raise TimeoutError('external experiment wait exceeded its configured deadline')
        Terminus2._execute_commands = execute


def process_identity(pid):
    p = subprocess.run(['ps', '-p', str(pid), '-o', 'stat=', '-o', 'lstart='], capture_output=True, text=True)
    fields = p.stdout.strip().split(maxsplit=1)
    return fields[1] if p.returncode == 0 and len(fields) == 2 and 'Z' not in fields[0] else None


def reconcile_running(st, run):
    """Reattach the supervisor; never rotate tokens, freeze or recreate a live run."""
    try:from . import wetlab_run as W
    except ImportError:import wetlab_run as W
    pid = st.get('worker_pid')
    if not pid or not st.get('worker_identity'):
        raise ValueError('blocking worker identity unavailable; keep container and reconcile manually')
    done = Path(st['current_job']) / 'worker_done.json'
    while process_identity(pid) == st['worker_identity']:
        if done.exists() and json.loads(done.read_text()).get('pid') == pid:break
        # The original worker still enforces Harbor's full wall-clock timeout.
        # An adopted supervisor must not restart the harness or consume budget.
        time.sleep(.5)
    trial = W.find_trial_dir(Path(st['current_job']))
    st['current_trial'] = str(trial) if trial else None
    st['phase'] = 'ROUND_DONE'
    run.save(st)
