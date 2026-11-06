"""Real HTTP/CLI retries and durable execution admission, without model requests."""
import concurrent.futures
import asyncio
from types import SimpleNamespace
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from wetlab import gateway as G

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def lab(tmp_path,monkeypatch):
    monkeypatch.setattr(G,'DB',tmp_path/'gateway.db',raising=False)
    monkeypatch.setattr(G,'ADMIN_TOKEN','private-test-admin')
    monkeypatch.setattr(G,'SIGNING_KEY',b'private-test-signing')
    monkeypatch.setattr(G,'LAB_DELAY',(0,0))
    monkeypatch.setattr(G,'FAULT_DROP_SUBMIT',0)
    G.init_db()
    with G.connect() as c:
        _,run=G.create_run(c,{'run_id':'notification-regression','budget':3,'task':'test'})
    server=G.ThreadingHTTPServer(('0.0.0.0',0),G.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    tool=tmp_path/'wait_for_result';shutil.copyfile(ROOT/'wetlab_cli.py',tool);tool.chmod(0o700)
    env={'WETLAB_URL':f'http://127.0.0.1:{server.server_port}',
         'WETLAB_TOKEN':run['token'],'WETLAB_STATE_DIR':str(tmp_path/'client-state')}
    try:yield {'run':run,'env':env,'tool':tool,'tmp':tmp_path}
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def cli(lab,*args,command='standalone',state=None):
    program=[sys.executable,str(lab['tool'])] if command=='standalone' else [sys.executable,str(ROOT/'wetlab_cli.py'),command]
    env={**os.environ,**lab['env']}
    if state is not None:env['WETLAB_STATE_DIR']=str(state)
    p=subprocess.run([*program,*args],env=env,capture_output=True,text=True,timeout=30)
    assert p.stdout,p.stderr
    return p.returncode,json.loads(p.stdout)


def http(lab,path,body,admin=True):
    req=urllib.request.Request(lab['env']['WETLAB_URL']+path,data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+(G.ADMIN_TOKEN if admin else lab['run']['token'])})
    try:
        with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:
        raw=e.read()
        try:return e.code,json.loads(raw)
        except ValueError:return e.code,{'error':'non-JSON transport response'}


def account(lab):
    with G.connect() as c:return G.run_view(c,lab['run']['run_id'],False)


def event_count(lab,kind):
    with G.connect() as c:return c.execute('SELECT COUNT(*) FROM events WHERE run_id=? AND type=?',
        (lab['run']['run_id'],kind)).fetchone()[0]


def test_standalone_tool_aliases_and_concurrent_retries_share_one_experiment(lab):
    args=['--expr','1+1','--reasoning','measure']
    # Distinct processes and client directories still derive the same round identity.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses=list(pool.map(lambda n:cli(lab,*args,state=lab['tmp']/f'client-{n%2}'),range(16)))
    assert all(code==0 for code,_ in responses)
    seqs={r['ticket']['seq'] for _,r in responses};assert len(seqs)==1
    for alias in ('wait_for_result','submit'):
        code,r=cli(lab,*args,command=alias)
        assert code==0 and r['replayed'] and r['ticket']['seq'] in seqs
    assert account(lab)['used']==1 and event_count(lab,'ticket_accepted')==1


def test_committed_submit_response_loss_does_not_charge_or_execute_twice(lab,monkeypatch):
    monkeypatch.setattr(G,'FAULT_DROP_SUBMIT',1)
    code,r=cli(lab,'--expr','1+1','--request-id','original-notification')
    assert code==0 and r['replayed']
    assert account(lab)['used']==1
    assert event_count(lab,'ticket_accepted')==1
    count=[];monkeypatch.setattr(G,'arith',lambda expr:count.append(expr) or 2)
    G.lab_tick();G.lab_tick()
    assert count==['1+1']


def test_notification_identity_survives_delivery_and_new_round(lab):
    args=['--expr','1+1','--request-id','first-notification']
    _,first=cli(lab,*args);seq=first['ticket']['seq']
    assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})[0]==200
    assert http(lab,f"/admin/runs/{lab['run']['run_id']}/deliver",{'seqs':[seq]})[0]==200
    # Even after the gate opens for a new round, repeating the original operation
    # remains a replay. A genuinely new round may intentionally repeat the science.
    code,replay=cli(lab,*args)
    assert code==0 and replay['replayed'] and replay['ticket']['seq']==seq
    _,second=cli(lab,'--expr','1+1')
    assert second['ticket']['seq']!=seq and account(lab)['used']==2
    for _ in range(10):
        assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})[1]['replayed']
        assert http(lab,f"/admin/runs/{lab['run']['run_id']}/deliver",{'seqs':[seq]})[0]==200
        assert cli(lab,*args)[1]['ticket']['seq']==seq
    assert account(lab)['used']==2 and not account(lab)['submission_open']
    assert event_count(lab,'ticket_completed')==1
    assert event_count(lab,'ticket_delivered')==1


def test_reused_identity_cannot_change_experiment(lab):
    assert cli(lab,'--expr','1+1','--request-id','same-event')[0]==0
    code,r=cli(lab,'--expr','2+2','--request-id','same-event')
    assert code==1 and 'different experiment' in r['error']
    with G.connect() as c:
        key=c.execute('SELECT idem_key FROM tickets').fetchone()[0]
        assert G.submit(c,lab['run']['run_id'],{'idempotency_key':key,'expr':'2+2'})[0]==409
    assert account(lab)['used']==1


def test_stale_round_cannot_create_new_ticket_with_a_different_key(lab):
    _,r=cli(lab,'--expr','1+1');seq=r['ticket']['seq']
    http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})
    http(lab,f"/admin/runs/{lab['run']['run_id']}/deliver",{'seqs':[seq]})
    code,_=http(lab,'/v1/tickets',{'expr':'1+1','round':1,'idempotency_key':'different-notification'},admin=False)
    assert code==409 and account(lab)['used']==1


def test_many_workers_and_duplicate_notifications_execute_only_once(lab,monkeypatch):
    _,r=cli(lab,'--expr','1+1');seq=r['ticket']['seq'];calls=[]
    def execute(expr):calls.append(expr);time.sleep(.05);return 2
    monkeypatch.setattr(G,'arith',execute)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(lambda _:G.lab_tick(),range(24)))
    for _ in range(20):
        assert http(lab,f'/admin/tickets/{seq}/claim',{'claim_id':'duplicate-worker'})[1]['execute'] is False
        assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})[1]['replayed']
        G.lab_tick()
    assert calls==['1+1']
    assert event_count(lab,'ticket_claimed')==event_count(lab,'ticket_completed')==1
    assert account(lab)['used']==1


def test_crash_after_execution_permit_does_not_redispatch(lab,monkeypatch):
    _,r=cli(lab,'--expr','1+1');seq=r['ticket']['seq'];calls=[]
    class WorkerCrash(BaseException):pass
    def execute(expr):calls.append(expr);raise WorkerCrash()
    monkeypatch.setattr(G,'arith',execute)
    with pytest.raises(WorkerCrash):G.lab_tick()
    for _ in range(10):G.lab_tick()
    assert calls==['1+1'] and account(lab)['tickets'][0]['status']=='running'
    # Covers a lost claim response too: replaying either the original or another
    # notification never grants a second execution permit. Operator review is needed.
    assert http(lab,f'/admin/tickets/{seq}/claim',{'claim_id':'restart-worker'})[1]['execute'] is False
    assert event_count(lab,'ticket_claimed')==1


def test_duplicate_result_cannot_overwrite_or_change_sealed_ledger(lab):
    _,r=cli(lab,'--expr','1+1');seq=r['ticket']['seq']
    assert http(lab,f'/admin/tickets/{seq}/complete',{'result':2})[0]==200
    assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})[1]['replayed']
    assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'3'})[0]==409
    with G.connect() as c:
        G.seal(c,lab['run']['run_id'],{'pending_policy':'cancel'});before=G.ledger(c,lab['run']['run_id'])
    assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})[1]['replayed']
    assert http(lab,f'/admin/tickets/{seq}/claim',{'claim_id':'late-notification'})[1]['execute'] is False
    with G.connect() as c:assert G.ledger(c,lab['run']['run_id'])==before


def test_unacknowledged_cli_request_replays_after_early_delivery(lab,monkeypatch):
    spec=importlib.util.spec_from_file_location('cli_under_test',ROOT/'wetlab_cli.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'STATE',lab['tmp']/'ambiguous-client')
    for key,value in lab['env'].items():monkeypatch.setenv(key,value)
    original=module.call
    def lost(method,path,body=None,**kwargs):
        code,data=original(method,path,body,**kwargs)
        if method=='POST':return 0,{'error':'response lost after commit'}
        return code,data
    monkeypatch.setattr(module,'call',lost)
    args=type('Args',(),{'expr':'1+1','reasoning':'','request_id':None})()
    assert module.wait_for_result(args)[0]==0
    seq=account(lab)['tickets'][0]['seq']
    http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})
    http(lab,f"/admin/runs/{lab['run']['run_id']}/deliver",{'seqs':[seq]})
    monkeypatch.setattr(module,'call',original)
    code,replay=module.wait_for_result(args)
    assert code==200 and replay['replayed'] and replay['ticket']['seq']==seq
    # Resolving the ambiguous old operation must not poison the next-round journal.
    code,new=module.wait_for_result(args)
    assert code==200 and new['ticket']['seq']!=seq and account(lab)['used']==2


@pytest.mark.skipif(os.environ.get('WETLAB_DOCKER_TEST')!='1',reason='explicit Docker integration opt-in')
def test_installed_container_tool_and_duplicate_notifications(lab,monkeypatch):
    image=f'wetlab-wait-tool-test:{os.getpid()}'
    volume=f'wetlab-wait-tool-state-{os.getpid()}'
    build=subprocess.run(['docker','build','-q','-t',image,str(ROOT/'tasks/wetlab-add/environment')],capture_output=True,text=True,timeout=300)
    assert build.returncode==0,build.stderr[-2000:]
    subprocess.run(['docker','volume','create',volume],capture_output=True,check=True)
    # The test gateway serves only synthetic data and test credentials.
    server_port=lab['env']['WETLAB_URL'].rsplit(':',1)[1]
    env={**os.environ,**lab['env'],'WETLAB_URL':'http://host.docker.internal:'+server_port}
    calls=[];monkeypatch.setattr(G,'arith',lambda expr:calls.append(expr) or (2 if expr=='1+1' else 4))
    def invoke(expr,request_id):
        p=subprocess.run(['docker','run','--rm','--env','WETLAB_URL','--env','WETLAB_TOKEN',
             '--mount',f'type=volume,source={volume},target=/app/.wetlab','--entrypoint','wait_for_result',
             image,'--expr',expr,'--request-id',request_id],env=env,capture_output=True,text=True,timeout=40)
        assert p.returncode==0,p.stderr[-1000:]+p.stdout[-1000:]
        return json.loads(p.stdout)
    try:
        first=invoke('1+1','first-docker-event');seq=first['ticket']['seq']
        assert invoke('1+1','first-docker-event')['ticket']['seq']==seq
        G.lab_tick()
        assert http(lab,f"/admin/runs/{lab['run']['run_id']}/deliver",{'seqs':[seq]})[0]==200
        assert invoke('1+1','first-docker-event')['replayed']
        second=invoke('2+2','second-docker-event');seq2=second['ticket']['seq'];G.lab_tick()
        for _ in range(10):
            assert http(lab,f'/admin/tickets/{seq}/complete',{'result':'2'})[1]['replayed']
            assert http(lab,f'/admin/tickets/{seq2}/claim',{'claim_id':'duplicate-device-event'})[1]['execute'] is False
            assert http(lab,f'/admin/tickets/{seq2}/complete',{'result':'4'})[1]['replayed']
            G.lab_tick()
        assert calls==['1+1','2+2']
        assert account(lab)['used']==2 and event_count(lab,'ticket_accepted')==2
        assert event_count(lab,'ticket_claimed')==event_count(lab,'ticket_completed')==2
        # Older signed images only have `wetlab`. The framework adds the new
        # entry point while retaining the original executable byte-for-byte.
        from wetlab.support import ensure_wait_tool
        old_container='wetlab-old-tool-test-'+str(os.getpid())
        subprocess.run(['docker','run','-d','--name',old_container,'--entrypoint','sh',image,
            '-c','rm /usr/local/bin/wait_for_result; exec sleep 300'],capture_output=True,check=True)
        class Environment:
            async def exec(self,command,user=None):
                prefix=['docker','exec']+(['--user',user] if user else [])
                p=subprocess.run([*prefix,old_container,'sh','-c',command],capture_output=True,text=True)
                return SimpleNamespace(return_code=p.returncode,stdout=p.stdout,stderr=p.stderr)
            async def upload_file(self,source,destination):
                subprocess.run(['docker','cp',str(source),old_container+':'+destination],capture_output=True,check=True)
        environment=Environment()
        try:
            before=asyncio.run(environment.exec('sha256sum /usr/local/bin/wetlab')).stdout
            asyncio.run(ensure_wait_tool(environment))
            after=asyncio.run(environment.exec('sha256sum /usr/local/bin/wetlab')).stdout
            assert before==after
            help_result=asyncio.run(environment.exec('wait_for_result --help'))
            assert help_result.return_code==0 and 'usage: wait_for_result' in help_result.stdout
            # The installed tool can replay an already completed experiment.
            p=subprocess.run(['docker','exec','--env','WETLAB_URL','--env','WETLAB_TOKEN',old_container,
                'wait_for_result','--expr','1+1','--request-id','first-docker-event'],env=env,capture_output=True,text=True,timeout=40)
            assert p.returncode==0 and json.loads(p.stdout)['replayed']
            assert account(lab)['used']==2
        finally:subprocess.run(['docker','rm','-f',old_container],capture_output=True)
    finally:
        subprocess.run(['docker','volume','rm',volume],capture_output=True)
        subprocess.run(['docker','image','rm',image],capture_output=True)


def test_lost_claim_response_never_reissues_execution_permission(lab,monkeypatch):
    _,r=cli(lab,'--expr','1+1');seq=r['ticket']['seq'];path=f'/admin/tickets/{seq}/claim'
    original=G.Handler._send
    def drop(self,code,body):
        if self.path==path and body.get('execute') is True:
            self.close_connection=True;self.connection.shutdown(2);return
        return original(self,code,body)
    monkeypatch.setattr(G.Handler,'_send',drop)
    try:
        code,receipt=http(lab,path,{'claim_id':'lost-response-worker'})
        assert code>=400 and not receipt.get('execute')
    except (ConnectionError,urllib.error.URLError):pass
    code,replay=http(lab,path,{'claim_id':'lost-response-worker'})
    assert code==200 and replay['execute'] is False
    calls=[];monkeypatch.setattr(G,'arith',lambda expr:calls.append(expr) or 2)
    G.lab_tick()
    assert calls==[] and account(lab)['tickets'][0]['status']=='running'
    assert event_count(lab,'ticket_claimed')==1
