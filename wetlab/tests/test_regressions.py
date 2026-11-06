from __future__ import annotations
import copy
import gzip
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from wetlab import checkpoint as C
from wetlab import gateway as G
from wetlab import wetlab_run as W
from wetlab.sessions import require_supported, validate_session
from wetlab.sessions import version_output
from wetlab.support import atomic_json, tree_checksum, stream_contains


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'DB', tmp_path / 'gateway.db', raising=False)
    monkeypatch.setattr(G, 'SIGNING_KEY', b'test-signing-key')
    monkeypatch.setattr(G, 'LAB_DELAY', (100, 100))
    G.init_db()
    with G.connect() as c:
        _, run = G.create_run(c, {'run_id': 'regression-run', 'budget': 3, 'task': 'wetlab-add'})
        yield c, run


def submit(c, run, key='test-key-0001'):
    code, result = G.submit(c, run['run_id'], {'idempotency_key': key, 'expr': '1+1'})
    assert code == 200
    return result['ticket']['seq']


def test_idempotent_creation_and_submission(db):
    c, run = db
    code, again = G.create_run(c, {'run_id': run['run_id'], 'budget': 3, 'task': 'wetlab-add'})
    assert code == 200 and again['token'] == run['token']
    seq = submit(c, run)
    assert submit(c, run) == seq
    assert G.run_view(c, run['run_id'], False)['used'] == 1


def test_delivery_replay_does_not_reopen_pending_batch(db):
    c, r = db; seq = submit(c, r)
    G.complete(c, seq, {'result': '2'})
    G.deliver(c, r['run_id'], {'seqs': [seq]})
    submit(c, r, 'test-key-0002')
    G.deliver(c, r['run_id'], {'seqs': [seq]})
    assert G.submit(c, r['run_id'], {'idempotency_key': 'test-key-0003', 'expr': '3+3'})[0] == 409


def test_finish_requires_delivery(db):
    c, r = db; seq = submit(c, r)
    G.complete(c, seq, {'result': '2'})
    assert G.finish(c, r['run_id'], {'answer': '2'})[0] == 409


def test_sealed_ledger_is_immutable(db):
    c, r = db; submit(c, r)
    assert G.seal(c, r['run_id'], {'pending_policy': 'cancel'})[0] == 200
    before = G.ledger(c, r['run_id'])
    assert G.finish(c, r['run_id'], {'answer': '2'})[0] == 409
    assert G.deliver(c, r['run_id'], {'seqs': [1]})[0] == 409
    assert G.rotate_token(c, r['run_id'])[0] == 409
    assert G.ledger(c, r['run_id']) == before


def test_attempt_fencing_revokes_old_token(db):
    c, r = db
    _, fresh = G.rotate_token(c, r['run_id'])
    assert fresh['token'] != r['token']
    assert c.execute('SELECT 1 FROM runs WHERE token=?', (r['token'],)).fetchone() is None


def test_recovery_event_requires_matching_checkpoint(db):
    c, r = db; seq = submit(c, r)
    G.complete(c, seq, {'result': '2'}); G.deliver(c, r['run_id'], {'seqs': [seq]})
    body = {'seqs': [seq], 'checkpoint': 'a' * 64, 'round': 1}
    assert G.record_recovery(c, r['run_id'], 'resume', body)[0] == 409
    assert G.record_recovery(c, r['run_id'], 'checkpoint', body)[0] == 200
    assert G.record_recovery(c, r['run_id'], 'resume', body)[0] == 200


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    monkeypatch.setenv('WETLAB_SIGNING_KEY', 'test-signing-key')
    root = tmp_path / 'checkpoint'; root.mkdir()
    (root / 'native.jsonl').write_text('original context')
    m = {'format': 'wetlab-checkpoint-v2', 'run_id': 'run', 'task_checksum': 'task', 'round': 1,
         'created_at': 'now', 'trial': '/tmp/trial', 'harness': 'claude-code', 'harness_version': '1',
         'model': 'model', 'services': {'main': {'image_id': 'sha256:' + '1' * 64}},
         'session_file': 'native.jsonl', 'session_sha256': C.sha256_file(root / 'native.jsonl'),
         'awaiting_tickets': [1], 'files': {'native.jsonl': C.sha256_file(root / 'native.jsonl')}}
    m['signature'] = C.signature(m); atomic_json(root / 'manifest.json', m)
    with patch.object(C, 'image_id', side_effect=lambda x: x): yield root, m


def test_tampered_checkpoint_refused(manifest):
    root, m = manifest
    assert C.validate(root, run_id='run', task_checksum='task') == m
    (root / 'native.jsonl').write_text('changed')
    with pytest.raises(ValueError): C.validate(root)


def test_unsigned_extra_session_refused(manifest):
    root, _ = manifest
    (root / 'injected.jsonl').write_text('new context')
    with pytest.raises(ValueError): C.validate(root)


def test_unsigned_nested_manifest_is_not_ignored(manifest):
    root,_=manifest
    (root/'nested').mkdir();(root/'nested/manifest.json').write_text('{}')
    with pytest.raises(ValueError):C.validate(root)


def test_manifest_identity_refused(manifest):
    root, _ = manifest
    with pytest.raises(ValueError): C.validate(root, run_id='other')
    with pytest.raises(ValueError): C.validate(root, task_checksum='other')


def test_rehydrate_after_atomic_rename(manifest, tmp_path):
    root, m = manifest
    run = W.Run(tmp_path / 'run'); run.lock()
    st = {'run_id': 'run', 'round': 1, 'phase': 'SUSPENDING', 'checkpoints': []}
    with patch.object(W, 'gw', return_value=(200, {})), patch.object(W, 'remove_project'):
        W.register_checkpoint(st, run, root, m)
        W.register_checkpoint(st, run, root, m)
    assert len(st['checkpoints']) == 1 and st['phase'] == 'SUSPENDED'
    assert Path(st['checkpoints'][0]['session_path']).is_file()


@pytest.mark.parametrize('agent', ['claude-code', 'pi', 'qwen-coder', 'opencode'])
def test_prebuilt_toml_and_compose_preserved(tmp_path, manifest, agent):
    import tomllib
    root, m = manifest
    src = tmp_path / 'task'; (src / 'environment').mkdir(parents=True)
    (src / 'task.toml').write_text('[environment]\ndocker_image="base:old"\n')
    (src / 'instruction.md').write_text('original')
    (src / 'environment/docker-compose.yaml').write_text('services:\n  main: {}\n  lab:\n    image: busybox\n')
    run = W.Run(tmp_path / 'run'); run.lock()
    st = {'task_dir': str(src), 'task_checksum': tree_checksum(src), 'run_id': 'run', 'model': 'model',
          'agent': agent, 'checkpoints': [{'dir': str(root)}], 'resume_prompt': 'result'}
    m['task_checksum'] = st['task_checksum']; m['harness'] = agent; m['services']['main']['mounts'] = []
    m['services']['lab'] = {'image_id': 'sha256:'+'2'*64, 'mounts': []}
    m['signature'] = C.signature(m); atomic_json(root / 'manifest.json', m)
    task = W.round_task(st, 2, run)
    assert tomllib.loads((task/'task.toml').read_text())['environment']['docker_image'] == m['services']['main']['image_id']
    assert 'lab:' in (task/'environment/docker-compose.yaml').read_text()


def test_native_session_validators(tmp_path):
    p = tmp_path/'claude.jsonl'
    p.write_text(json.dumps({'sessionId': 'session', 'message': {'role': 'assistant', 'content': [], 'stop_reason': 'end_turn'}})+'\n')
    assert validate_session(p)[0]
    p.write_text(json.dumps({'sessionId': 'session', 'message': {'role': 'assistant', 'content': []}})+'\n')
    assert not validate_session(p)[0]
    p.write_text('\n'.join(map(json.dumps,[{'type':'session_meta','payload':{'id':'session'}},
        {'type':'event_msg','payload':{'type':'task_complete'}}])))
    assert validate_session(p,'codex')[0]


def test_unsupported_harness_rejected_before_experiment():
    for name in ['nop']:
        with pytest.raises(ValueError, match='No experiment'): require_supported(name)


def test_every_unimplemented_registry_entry_fails_before_gateway(tmp_path, monkeypatch):
    from harbor.agents.factory import AgentFactory
    from wetlab.sessions import SUPPORTED
    for name in set(AgentFactory.registered_names()) - SUPPORTED:
        dest=tmp_path/name
        monkeypatch.setattr(sys,'argv',['wetlab-run','start','/not-a-task','--run-dir',str(dest),'--agent',name])
        with patch.object(W,'gw') as gateway:
            with pytest.raises(ValueError,match='No experiment'): W.main()
            gateway.assert_not_called()
        assert not dest.exists()


def test_stream_scan_crosses_chunk_boundaries():
    secret = 'test-secret-cross-boundary'
    assert stream_contains(io.BytesIO(b'x'*(1024*1024-4)+secret.encode()), [secret])


def test_compressed_layer_scan(tmp_path):
    p=tmp_path/'images.tar'; data=gzip.compress(b'prefix test-secret-value suffix')
    with tarfile.open(p,'w') as tf:
        info=tarfile.TarInfo('blobs/sha256/layer'); info.size=len(data);tf.addfile(info,io.BytesIO(data))
    with pytest.raises(ValueError, match='compressed'): C.scan_image_archive(p,['test-secret-value'])


def test_last_experiment_is_delivered_before_sealing(tmp_path):
    run=W.Run(tmp_path/'run');run.lock()
    st={'round':3,'max_rounds':3,'attempt':1,'phase':'ROUND_DONE','agent':'claude-code'}
    with patch.object(W,'gw_run',return_value={'finished':False,'tickets':[{'seq':3,'delivered_at':None,'status':'accepted'}]}):
        W.phase_round_done(st,run)
    assert st['phase']=='SUSPENDING'


def test_submit_monitor_ends_noncooperative_worker_and_redacts(tmp_path, monkeypatch):
    src=tmp_path/'task';(src/'environment').mkdir(parents=True)
    (src/'task.toml').write_text('[agent]\ntimeout_sec=100\n[environment]\n')
    (src/'instruction.md').write_text('test')
    fake=tmp_path/'slow.py';fake.write_text('import os,time\nprint(os.environ["OPENAI_API_KEY"],flush=True)\ntime.sleep(60)\n')
    monkeypatch.setenv('OPENAI_API_KEY','FAKE-KEY-FOR-REDACTION-TEST')
    run=W.Run(tmp_path/'run');run.lock()
    st={'round':1,'attempt':0,'phase':'READY_ROUND','task_dir':str(src),'task_checksum':tree_checksum(src),
        'agent':'claude-code','model':'test','token':'fake-run-token','gateway_url_container':'http://unused',
        'active_budget_sec':100,'round_timeout_sec':10,'suspend_grace_sec':0.5}
    original=subprocess.Popen
    with patch.object(W,'preflight'),patch.object(W,'rotate_token'),patch.object(W,'gw_run',return_value={'finished':False,'tickets':[{'seq':1,'status':'accepted','delivered_at':None}]}), \
         patch.object(W.subprocess,'Popen',side_effect=lambda cmd,**kw: original([sys.executable,str(fake)],**kw)):
        before=time.monotonic();W.phase_ready_round(st,run)
    assert time.monotonic()-before < 6
    assert st['termination_reason']=='submit/finish grace period reached'
    assert 'FAKE-KEY-FOR-REDACTION-TEST' not in (Path(st['current_job'])/'harbor_stdout.log').read_text()


def test_demo_verifier_requires_actual_resume(db, tmp_path, monkeypatch):
    c,r=db;seq=submit(c,r);G.complete(c,seq,{'result':'2'})
    G.deliver(c,r['run_id'],{'seqs':[seq]});G.finish(c,r['run_id'],{'answer':'2'});G.seal(c,r['run_id'],{'pending_policy':'cancel'})
    file=tmp_path/'ledger.json';file.write_text(json.dumps(G.ledger(c,r['run_id'])))
    path=Path(__file__).parents[1]/'tasks/wetlab-add/tests/verify.py'
    spec=importlib.util.spec_from_file_location('demo_verify',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'LEDGER',file);monkeypatch.setenv('WETLAB_SIGNING_KEY',G.SIGNING_KEY.decode())
    assert not module.check()['passed']


def test_quota_error_is_recoverable_not_a_task_reward(tmp_path):
    trial=tmp_path/'trial';trial.mkdir()
    (trial/'result.json').write_text(json.dumps({'agent_execution':{'started_at':'now'},
        'exception_info':{'exception_type':'UnknownApiError','exception_message':'API Error: 402 free trial quota for the service has been exhausted'}}))
    run=W.Run(tmp_path/'run');run.lock()
    st={'phase':'ROUND_DONE','round':1,'attempt':1,'current_trial':str(trial),'agent':'claude-code'}
    with patch.object(W,'gw_run',return_value={'finished':False,'tickets':[]}):W.phase_round_done(st,run)
    assert st['phase']=='FAILED_RECOVERABLE' and st['failure_kind']=='provider_quota'
    assert 'reward' not in st and not (run.dir/'final/ledger.json').exists()


def test_scientific_sample_id_is_not_an_http_status(tmp_path):
    trial=tmp_path/'trial';trial.mkdir()
    (trial/'result.json').write_text(json.dumps({'agent_execution':{},'exception_info':{
        'exception_type':'ValueError','exception_message':'sample 402 failed to parse'}}))
    assert 'quota' not in W.round_infra_failure({'current_trial':str(trial)})


def test_attested_resume_is_accepted_by_offline_verifier(db,tmp_path,monkeypatch):
    c,r=db;seq=submit(c,r)
    body={'seqs':[seq],'checkpoint':'a'*64,'round':1}
    assert G.record_recovery(c,r['run_id'],'checkpoint',body)[0]==200
    G.complete(c,seq,{'result':'2'});G.deliver(c,r['run_id'],{'seqs':[seq]})
    assert G.finish(c,r['run_id'],{'answer':'2'})[0]==409
    assert G.record_recovery(c,r['run_id'],'resume',{**body,'round':2})[0]==200
    assert G.finish(c,r['run_id'],{'answer':'2'})[0]==200
    G.seal(c,r['run_id'],{'pending_policy':'cancel'})
    file=tmp_path/'ledger.json';file.write_text(json.dumps(G.ledger(c,r['run_id'])))
    path=Path(__file__).parents[1]/'tasks/wetlab-add/tests/verify.py'
    spec=importlib.util.spec_from_file_location('positive_verifier',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'LEDGER',file);monkeypatch.setenv('WETLAB_SIGNING_KEY',G.SIGNING_KEY.decode())
    assert module.check()['passed']


def test_codex_version_diagnostics_do_not_change_identity():
    from harbor.agents.installed.codex import Codex
    text='WARNING: failed to clean up stale arg0 temp dirs: Cross-device link (os error 18)\ncodex-cli 0.167.0\n'
    assert Codex.parse_version(None,version_output(text))=='0.167.0'


def test_retry_reexecutes_failed_round_instead_of_regrading_error(tmp_path,monkeypatch):
    run=tmp_path/'run';atomic_json(run/'state.json',{'phase':'FAILED_RECOVERABLE','failed_phase':'ROUND_DONE',
        'failure':'old error','task_checksum':'task','attempt':3})
    monkeypatch.setattr(sys,'argv',['wetlab-run','retry',str(run)])
    with patch.object(W,'drive',side_effect=lambda r:r.load()): W.main()
    state=json.loads((run/'state.json').read_text())
    assert state['phase']=='READY_ROUND' and state['attempt']==3


def test_pi_and_qwen_native_continuation_guards(tmp_path):
    from wetlab.sessions import assert_continuation
    fixtures = {
        'pi': [
            {'type': 'session', 'id': 'native-id', 'cwd': '/app'},
            {'type': 'message', 'id': 'a', 'parentId': None, 'message': {'role': 'assistant', 'content': [{'type': 'toolCall', 'id': 'call'}], 'stopReason': 'toolUse'}},
            {'type': 'message', 'id': 'b', 'parentId': 'a', 'message': {'role': 'toolResult', 'toolCallId': 'call', 'content': []}},
            {'type': 'message', 'id': 'c', 'parentId': 'b', 'message': {'role': 'assistant', 'content': [], 'stopReason': 'stop'}},
        ],
        'qwen-coder': [
            {'sessionId': 'native-id', 'type': 'assistant', 'message': {'parts': [{'functionCall': {'id': 'call'}}]}},
            {'sessionId': 'native-id', 'type': 'tool_result', 'message': {'parts': [{'functionResponse': {'id': 'call'}}]}},
            {'sessionId': 'native-id', 'type': 'assistant', 'message': {'parts': [{'text': 'waiting'}]}},
        ],
    }
    for agent, rows in fixtures.items():
        old, new = tmp_path/(agent+'-old.jsonl'), tmp_path/(agent+'-new.jsonl')
        old.write_text('\n'.join(map(json.dumps, rows)))
        assert validate_session(old, agent) == (True, 'ok')
        new.write_text(old.read_text()+'\n'+json.dumps(rows[-1]))
        assert_continuation(old, new, agent)
        new.write_text(old.read_text())
        with pytest.raises(ValueError, match='no new'): assert_continuation(old, new, agent)
        changed = [dict(r) for r in rows]; changed[0] = {**changed[0], 'id': 'different', 'sessionId': 'different'}
        new.write_text('\n'.join(map(json.dumps, changed+[rows[-1]])))
        with pytest.raises(ValueError, match='identit'): assert_continuation(old, new, agent)
        # A final assistant message must not hide an unfinished earlier tool call.
        old.write_text('\n'.join(map(json.dumps, [rows[0], rows[-1]] if agent == 'qwen-coder' else [rows[0], rows[1], {**rows[-1], 'parentId': 'a'}])))
        assert not validate_session(old, agent)[0]


def test_opencode_native_database_continuation(tmp_path):
    import shutil
    import sqlite3
    from wetlab.sessions import assert_continuation
    old, new = tmp_path/'old.db', tmp_path/'new.db'
    with sqlite3.connect(old) as db:
        db.executescript('CREATE TABLE session(id,parent_id,time_updated); CREATE TABLE message(id,session_id,time_created,data); CREATE TABLE part(id,session_id,data);')
        db.execute('INSERT INTO session VALUES(?,?,?)', ('sid', None, 1))
        db.execute('INSERT INTO message VALUES(?,?,?,?)', ('m1','sid',1,json.dumps({'role':'assistant','finish':'stop','time':{'completed':1}})))
        db.execute('INSERT INTO part VALUES(?,?,?)',('p1','sid',json.dumps({'type':'tool','state':{'status':'completed','output':'result'}})))
    assert validate_session(old,'opencode') == (True,'ok')
    shutil.copyfile(old,new)
    with sqlite3.connect(new) as db:
        db.execute('INSERT INTO part VALUES(?,?,?)',('p2','sid',json.dumps({'type':'text','text':'new turn'})))
    assert_continuation(old,new,'opencode')
    with sqlite3.connect(new) as db:
        db.execute('UPDATE part SET data=? WHERE id=?',(json.dumps({'type':'tool','state':{'status':'running'}}),'p1'))
    assert not validate_session(new,'opencode')[0]
    with pytest.raises(ValueError,match='context changed'): assert_continuation(old,new,'opencode')


def test_stream_redaction_preserves_context_across_boundaries():
    from wetlab.support import redact_stream
    for size in (1, 3, 8, 32):
        source=io.BytesIO(b'context secret-abc more secret-abc end')
        target=io.BytesIO()
        assert redact_stream(source,target,['secret-abc'],chunk_size=size)
        assert target.getvalue()==b'context <redacted> more <redacted> end'
    target=io.BytesIO()
    assert not redact_stream(io.BytesIO(b'unchanged context'),target,['absent'],chunk_size=2)
    assert target.getvalue()==b'unchanged context'


@pytest.mark.parametrize('agent', ['copilot-cli','kimi-code','hermes','goose'])
def test_new_native_adapters_reject_partial_turns_and_wrong_context(tmp_path, agent):
    import sqlite3
    from wetlab.sessions import assert_continuation
    if agent == 'goose':
        p=tmp_path/'goose.db'
        with sqlite3.connect(p) as db:
            db.executescript('CREATE TABLE sessions(id,parent_session_id,updated_at); CREATE TABLE messages(id,session_id,role,content_json);')
            db.execute('INSERT INTO sessions VALUES(?,?,?)',('sid',None,1))
            db.execute('INSERT INTO messages VALUES(?,?,?,?)',(1,'sid','assistant',json.dumps([{'type':'toolRequest','id':'call'}])))
        assert not validate_session(p,agent)[0]
        with sqlite3.connect(p) as db:
            db.execute('INSERT INTO messages VALUES(?,?,?,?)',(2,'sid','user',json.dumps([{'type':'toolResponse','id':'call'}])))
        assert validate_session(p,agent)==(True,'ok')
        with sqlite3.connect(p) as db:
            db.execute('INSERT INTO messages VALUES(?,?,?,?)',(3,'sid','assistant',json.dumps([{'type':'text','text':'waiting'}])))
        assert validate_session(p,agent)==(True,'ok')
        return
    if agent=='kimi-code':
        p=tmp_path/'session_sid/agents/main/wire.jsonl';p.parent.mkdir(parents=True)
        (p.parents[2]/'state.json').write_text(json.dumps({'id':'session_sid','cwd':'/app'}))
        rows=[{'type':'metadata'}, {'type':'agent.turn.started'}, {'type':'prompt.completed','reason':'completed'}]
        unfinished={'type':'turn.prompt'}
    elif agent=='copilot-cli':
        p=tmp_path/'events.jsonl'
        rows=[{'type':'session.start','data':{'sessionId':'sid'}}, {'type':'assistant.turn_start'}, {'type':'assistant.turn_end'}]
        unfinished={'type':'user.message'}
    else:
        p=tmp_path/'hermes-session.jsonl'
        rows=[{'id':'sid','messages':[{'role':'assistant','content':'waiting'}]}]
        unfinished={'role':'assistant','tool_calls':[{'id':'unfinished-call'}]}
    p.write_text('\n'.join(map(json.dumps,rows)))
    assert validate_session(p,agent)==(True,'ok')
    if agent=='hermes':rows[0]['messages'].append(unfinished)
    else:rows.append(unfinished)
    p.write_text('\n'.join(map(json.dumps,rows)))
    assert not validate_session(p,agent)[0]


def test_qwen_export_discovers_current_nested_history(tmp_path):
    from wetlab.sessions import latest_session
    root=tmp_path/'agent/qwen-sessions'
    old=root/'-app/chats/native.jsonl';old.parent.mkdir(parents=True);old.write_text('old')
    new=root/'projects/-app/chats/native.jsonl';new.parent.mkdir(parents=True);new.write_text('new continuation')
    os.utime(old,(1,1));os.utime(new,(2,2))
    assert latest_session(tmp_path,'qwen-coder')==new


def test_concurrent_runs_cannot_capture_each_others_images(tmp_path, monkeypatch):
    import concurrent.futures,threading
    tags={};barrier=threading.Barrier(2);lock=threading.Lock()
    monkeypatch.setattr(C,'freeze_containers',lambda containers,names:containers)
    monkeypatch.setattr(C,'sanitize_agent_logs',lambda *args:None)
    monkeypatch.setattr(C,'inspect_container',lambda cid:{'Config':{'Env':[],'Cmd':['sleep','infinity'],'User':'','WorkingDir':'/app'},'HostConfig':{},'Mounts':[]})
    monkeypatch.setattr(C,'scan_image_archive',lambda *args:None)
    def docker(*args):
        if args[0]=='commit':
            with lock:tags[args[2]]='sha256:'+args[1]*64
            barrier.wait(timeout=10)
            return ''
        if args[:2]==('image','inspect'):
            with lock:return tags[args[-1]]
        raise AssertionError(args)
    monkeypatch.setattr(C,'docker',docker)
    def save(args,path):
        assert args[0]=='save'
        path.write_bytes(b'isolated test archive')
    monkeypatch.setattr(C,'write_docker_archive',save)
    def capture(cid):
        root=tmp_path/cid/'run/checkpoints/.r1.tmp';root.mkdir(parents=True)
        return C.capture_services.__wrapped__([(cid,'main')],root,{'main'},[])['main']['image_id']
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        images=list(pool.map(capture,['a','b']))
    assert images==['sha256:'+'a'*64,'sha256:'+'b'*64]


def test_setup_failure_exhausting_budget_stays_recoverable(tmp_path):
    run=W.Run(tmp_path/'run');run.lock()
    st={'phase':'READY_ROUND','round':1,'active_seconds':601,'active_budget_sec':600,
        'last_round_infra_failure':'agent/harness error (AgentSetupTimeoutError)'}
    W.phase_ready_round(st,run)
    assert st['phase']=='FAILED_RECOVERABLE'
    assert st['failure_kind']=='infrastructure'
    assert 'reward' not in st



def test_archive_stream_stops_before_consuming_host_disk_reserve(tmp_path,monkeypatch):
    from types import SimpleNamespace
    free=iter([4*1024**3,4*1024**3,2*1024**3])
    monkeypatch.setattr(C.shutil,'disk_usage',lambda path:SimpleNamespace(free=next(free)))
    class Process:
        def __init__(self,*args,**kwargs):
            self.stdout=io.BytesIO(b'x'*(3*1024*1024));self.terminated=False
        def poll(self):return 0 if self.terminated else None
        def terminate(self):self.terminated=True
        def wait(self,**kwargs):return 0
    process=Process();monkeypatch.setattr(C.subprocess,'Popen',lambda *args,**kwargs:process)
    target=tmp_path/'images.tar'
    with pytest.raises(OSError,match='3 GiB reserve'):C.write_docker_archive(['save','own-image'],target)
    assert process.terminated
    assert target.stat().st_size==1024*1024


def test_archive_directory_keeps_run_ledger_and_task_locations_separate(tmp_path):
    run=W.Run(tmp_path/'run')
    assert W.archive_root({},run)==run.dir
    external=tmp_path/'external'/'unique-run'
    assert W.archive_root({'archive_root':str(external)},run)==external
    assert run.dir/'final/ledger.json'!=external/'final/ledger.json'
