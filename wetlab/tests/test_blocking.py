"""Real HTTP and CLI interruption/replay tests for external result waiting."""
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from wetlab import gateway as G
from wetlab import blocking as B
from wetlab.tests.test_wait_for_result import lab, cli, http, account, event_count


def activate(lab):
    with G.connect() as c:
        c.execute("UPDATE runs SET execution_mode='blocking' WHERE run_id=?", (lab['run']['run_id'],))
        assert G.bind_container(c, lab['run']['run_id'], {'container_id': 'a'*64})[0] == 200


def test_receipt_then_external_wait_and_replay(lab):
    activate(lab)
    code, receipt = cli(lab, '--expr', '1+1', '--request-id', 'measurement-1', command='submit')
    seq = receipt['ticket']['seq']
    assert code == 0 and receipt['execution_mode'] == 'blocking'
    assert account(lab)['container_id'] == 'a'*64
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(cli, lab, '--ticket-id', str(seq))
        time.sleep(.2);assert not future.done()
        # Long polling must not monopolize the global mutation lock.
        assert http(lab, f'/admin/tickets/{seq}/claim', {'claim_id':'lab-worker-one'})[1]['execute']
        assert http(lab, f'/admin/tickets/{seq}/complete', {'result':'2'})[0] == 200
        code, result = future.result(timeout=5)
    assert code == 0 and result['ticket']['result'] == '2'
    assert cli(lab, '--ticket-id', str(seq))[1]['replayed']
    _, next_receipt = cli(lab, '--expr', '2+2', command='submit')
    assert cli(lab, '--ticket-id', str(seq))[0] == 0
    assert not account(lab)['submission_open'] and account(lab)['used'] == 2
    assert event_count(lab, 'blocking_result_returned') == 1
    assert next_receipt['ticket']['seq'] != seq


def test_combined_wait_returns_result_without_next_turn(lab):
    activate(lab)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(cli, lab, '--expr', '1+1')
        deadline = time.monotonic()+5
        while not account(lab)['tickets'] and time.monotonic()<deadline:time.sleep(.02)
        ticket = account(lab)['tickets'][0]
        assert not future.done()
        http(lab, f"/admin/tickets/{ticket['seq']}/complete", {'result':'2'})
        assert future.result(timeout=5)[1]['ticket']['result'] == '2'
    assert cli(lab, '--answer', '2', command='finish')[0] == 0
    assert account(lab)['used'] == 1


def test_killed_waiter_and_server_restart_reattach_same_experiment(lab):
    activate(lab)
    _, receipt = cli(lab, '--expr', '1+1', command='submit');seq=receipt['ticket']['seq']
    env={**os.environ,**lab['env']}
    p=subprocess.Popen([sys.executable,str(lab['tool']),'--ticket-id',str(seq)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    time.sleep(.2);assert p.poll() is None
    p.kill();p.communicate(timeout=3)
    # Reopening the durable DB performs the same initialization as a new gateway.
    G.init_db()
    assert http(lab, f'/admin/tickets/{seq}/complete', {'result':'2'})[0] == 200
    code,result=cli(lab,'--ticket-id',str(seq))
    assert code==0 and result['ticket']['result']=='2'
    assert account(lab)['used']==1 and event_count(lab,'ticket_accepted')==1


def test_local_deadline_preserves_experiment_and_authorization(lab):
    activate(lab)
    _,r=cli(lab,'--expr','1+1',command='submit');seq=r['ticket']['seq']
    code,res=cli(lab,'--ticket-id',str(seq),'--wait-timeout','.1')
    assert code==1 and res['ticket_id']==seq and account(lab)['used']==1
    with G.connect() as c:
        assert G.wait_result(c,lab['run']['run_id'],seq+100)[0]==404
        assert G.bind_container(c,lab['run']['run_id'],{'container_id':'b'*64})[0]==409
        _,other=G.create_run(c,{'run_id':'other','budget':1,'execution_mode':'blocking'})
        G.bind_container(c,'other',{'container_id':'c'*64})
        assert G.wait_result(c,'other',seq)[0]==404
    assert account(lab)['tickets'][0]['delivered_at'] is None


def test_lost_result_response_replays_without_second_delivery(lab,monkeypatch):
    activate(lab)
    _,r=cli(lab,'--expr','1+1',command='submit');seq=r['ticket']['seq']
    http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})
    original=G.Handler._send;dropped=[]
    def send(self,code,body):
        if self.path.endswith('/wait') and code==200 and not dropped:
            dropped.append(True);self.close_connection=True;self.connection.shutdown(2);return
        return original(self,code,body)
    monkeypatch.setattr(G.Handler,'_send',send)
    code,result=cli(lab,'--ticket-id',str(seq))
    assert code==0 and result['replayed'] and account(lab)['used']==1
    assert event_count(lab,'ticket_delivered')==1


def test_wait_not_available_in_suspend_mode_or_before_container_binding(lab):
    with G.connect() as c:
        assert G.wait_result(c,lab['run']['run_id'],1)[0]==409
        c.execute("UPDATE runs SET execution_mode='blocking'")
        assert G.submit(c,lab['run']['run_id'],{'expr':'1+1','idempotency_key':'unbound-experiment'})[0]==409


def test_wall_clock_budget_covers_all_waits_and_rejects_unsupported_harness():
    cfg=B.settings({'budget':2,'wait_timeout_sec':86400,'active_budget_sec':600},'openclaw','blocking')
    assert cfg['blocking_agent_timeout_sec']==173460
    with pytest.raises(ValueError,match='must cover'):
        B.settings({'blocking_agent_timeout_sec':86400},'openclaw','blocking')
    with pytest.raises(ValueError,match='not validated'):
        B.settings({},'codex','blocking')
    assert B.settings({},'codex')=={'execution_mode':'suspend'}


def test_actual_gateway_process_restart_during_wait(lab):
    import socket
    import urllib.request
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    endpoint=f'http://127.0.0.1:{port}'
    env={**os.environ,'WETLAB_ADMIN_TOKEN':'restart-test-admin','WETLAB_SIGNING_KEY':'restart-test-signing'}
    command=[sys.executable,str(Path(G.__file__)),'--port',str(port),'--db',str(lab['tmp']/'restart.db'),'--manual-lab']
    def launch():
        p=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            try:
                urllib.request.urlopen(endpoint+'/health',timeout=.2).close();return p
            except OSError:time.sleep(.05)
        p.kill();p.wait();raise AssertionError('gateway did not start')
    def post(path,body,token='restart-test-admin'):
        req=urllib.request.Request(endpoint+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
    gateway=launch();waiter=None
    try:
        run=post('/admin/runs',{'run_id':'restart','budget':1,'execution_mode':'blocking'})
        post('/admin/runs/restart/bind-container',{'container_id':'d'*64})
        ticket=post('/v1/tickets',{'expr':'1+1','idempotency_key':'same-experiment-after-restart'},run['token'])['ticket']
        client_env={**os.environ,'WETLAB_URL':endpoint,'WETLAB_TOKEN':run['token'],'WETLAB_STATE_DIR':str(lab['tmp']/'restart-client')}
        waiter=subprocess.Popen([sys.executable,str(lab['tool']),'--ticket-id',str(ticket['seq'])],env=client_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        time.sleep(.2);assert waiter.poll() is None
        gateway.kill();gateway.wait(timeout=3)
        time.sleep(.2);assert waiter.poll() is None
        gateway=launch()
        post(f"/admin/tickets/{ticket['seq']}/complete",{'result':'2'})
        stdout,stderr=waiter.communicate(timeout=10)
        assert waiter.returncode==0,stderr
        assert json.loads(stdout)['ticket']['result']=='2'
        with __import__('sqlite3').connect(lab['tmp']/'restart.db') as c:
            assert c.execute('SELECT used FROM runs').fetchone()[0]==1
            assert c.execute('SELECT count(*) FROM tickets').fetchone()[0]==1
    finally:
        if waiter and waiter.poll() is None:waiter.kill();waiter.wait()
        gateway.kill();gateway.wait(timeout=3)


def test_supervisor_reattaches_without_fencing_running_container(tmp_path,monkeypatch):
    from wetlab import wetlab_run as W
    from wetlab.support import atomic_json
    job=tmp_path/'job';trial=job/'task__fixture';trial.mkdir(parents=True)
    (trial/'config.json').write_text('{}')
    worker=subprocess.Popen([sys.executable,'-c','import time; time.sleep(.7)'])
    def forbidden(*args,**kwargs):raise AssertionError('live blocking run must not be fenced or restarted')
    monkeypatch.setattr(W,'rotate_token',forbidden)
    monkeypatch.setattr(W.checkpoint,'freeze_containers',forbidden)
    monkeypatch.setattr(W,'remove_project',forbidden)
    run=W.Run(tmp_path/'run')
    st={'execution_mode':'blocking','phase':'READY_ROUND','attempt':1,'current_job':str(job),'worker_pid':worker.pid,'worker_identity':B.process_identity(worker.pid)}
    try:
        W.reconcile(st,run)
        assert st['phase']=='ROUND_DONE' and st['current_trial']==str(trial)
    finally:worker.wait(timeout=3)


def test_terminus_wait_preserves_first_terminal_output(lab,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from harbor.agents.terminus_2.terminus_2 import Terminus2
    activate(lab)
    with monkeypatch.context() as m:
        async def original(self,commands,session):return False,'ORIGINAL-TOOL-OUTPUT'
        m.setattr(Terminus2,'_execute_commands',original)
        m.setenv('WETLAB_ADMIN_TOKEN',G.ADMIN_TOKEN)
        B.configure_worker({'execution_mode':'blocking','agent':'terminus-2','wait_timeout_sec':90000,'run_id':lab['run']['run_id'],'gateway_url':lab['env']['WETLAB_URL']})
        class Terminal:
            async def get_incremental_output(self):return 'NEW-TOOL-OUTPUT'
        result=asyncio.run(Terminus2._execute_commands(object(),[SimpleNamespace(keystrokes='wait_for_result --help')],Terminal()))
        assert 'ORIGINAL-TOOL-OUTPUT' in result[1] and 'NEW-TOOL-OUTPUT' in result[1]


def test_finish_receipt_does_not_hide_harness_failure(lab,tmp_path,monkeypatch):
    from wetlab import wetlab_run as W
    activate(lab)
    assert cli(lab,'--answer','2',command='finish')[0]==0
    trial=tmp_path/'trial';trial.mkdir()
    (trial/'result.json').write_text(json.dumps({'exception_info':{'exception_type':'ValueError','exception_message':'native identity missing'},'agent_execution':{}}))
    monkeypatch.setenv('WETLAB_ADMIN_TOKEN',G.ADMIN_TOKEN)
    st={'execution_mode':'blocking','phase':'ROUND_DONE','current_trial':str(trial),'gateway_url':lab['env']['WETLAB_URL'],'run_id':lab['run']['run_id']}
    W.phase_round_done(st,W.Run(tmp_path/'run'))
    assert st['phase']=='FAILED_RECOVERABLE' and 'cleanly' in st['failure']
