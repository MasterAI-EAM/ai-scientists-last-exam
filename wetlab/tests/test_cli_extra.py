import json
from pathlib import Path
import pytest
from wetlab import cli_extra as C

def dump(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
    return path

def test_grok_native_identity_and_tool_boundary(tmp_path):
    p=dump(tmp_path/'sessions'/'app'/'stable-id'/'chat_history.jsonl',[
      {'type':'user','content':'remember nonce'},
      {'type':'assistant','content':'','tool_calls':[{'id':'c','name':'shell','arguments':'{}'}]},
      {'type':'tool_result','tool_call_id':'c','content':'submitted'},
      {'type':'assistant','content':'waiting'}])
    C.validate(p,'grok-build');sid,m=C.history(p,'grok-build')
    assert sid=='stable-id' and m['0']['content']=='remember nonce'
    rows=[json.loads(x) for x in p.read_text().splitlines()]
    dump(p,rows[:-2]+rows[-1:])
    with pytest.raises(ValueError,match='incomplete'):C.validate(p,'grok-build')

def test_puppy_requires_safe_native_json_and_closed_tools(tmp_path):
    p=tmp_path/'native.json';p.write_text(json.dumps({'format':2,'encoding':'pydantic-ai-messages','messages':[
      {'kind':'request','parts':[{'part_kind':'user-prompt','content':'nonce'}]},
      {'kind':'response','parts':[{'part_kind':'tool-call','tool_call_id':'c','tool_name':'shell','args':'{}'}]},
      {'kind':'request','parts':[{'part_kind':'tool-return','tool_call_id':'c','content':'ok'}]},
      {'kind':'response','finish_reason':'stop','state':'complete','parts':[{'part_kind':'text','content':'done'}]}]}))
    C.validate(p,'code-puppy');assert C.history(p,'code-puppy')[0]=='native'
    d=json.loads(p.read_text());d['messages'][2]['parts'][0]['tool_call_id']='alien';p.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='orphan'):C.validate(p,'code-puppy')
    p.write_text('not a pickle or JSON')
    with pytest.raises(ValueError):C.validate(p,'code-puppy')

def test_openclaw_requires_native_session_header_and_tool_resolution(tmp_path):
    p=dump(tmp_path/'session.jsonl',[{'type':'session','id':'stable'},{'type':'message','message':{'role':'assistant','content':[{'type':'toolCall','id':'c'}]}},{'type':'message','message':{'role':'toolResult','toolCallId':'c','content':[]}},{'type':'message','message':{'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'done'}]}}])
    C.validate(p,'openclaw');assert C.history(p,'openclaw')[0]=='stable'
    rows=[json.loads(x) for x in p.read_text().splitlines()];dump(p,rows[:-1])
    with pytest.raises(ValueError,match='incomplete'):C.validate(p,'openclaw')

def test_vibe_verifies_native_recovery_hash_chain(tmp_path):
    import hashlib
    root=tmp_path/'native';gen=root/'generations'/'0000000000000001';gen.mkdir(parents=True)
    digest=lambda raw:hashlib.sha256(raw).hexdigest()
    def compact(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    row={'payload':{'client_command_id':'first'},'previous_record_sha256':None,'recovery_journal_record_version':1,'sequence':1,'type':'receipt_succeeded'}
    row['record_sha256']=digest(compact(row));dump(root/'journal'/'0000000000000001.jsonl',[row])
    manifest={'execution_state':'quiescent','session_id':'native-sid','snapshot_sequence':1}
    for name in ('checkpoint','runtime_state','projection_state'):
        raw=compact({'native':'preserved'});filename=name.replace('_','-')+'.json';(gen/filename).write_bytes(raw+b'\n')
        manifest[name]={'path':filename,'sha256':digest(raw),'chunks':[]}
    context=compact([{'message':{'role':'assistant','content':[{'type':'text','text':'native model response'}]},'source':'model','turn_index':1}])
    chunk=digest(context);(root/'chunks').mkdir();(root/'chunks'/(chunk+'.json')).write_bytes(context+b'\n')
    manifest['checkpoint']['chunks']=[chunk]
    raw=compact(manifest);(gen/'manifest.json').write_bytes(raw+b'\n')
    current=root/'CURRENT';current.write_text(json.dumps({'generation':gen.name,'session_id':'native-sid','manifest_sha256':digest(raw),'store_format':'mistral.vibe.unified-session-store/v1'}))
    C.validate(current,'vibe');assert C.history(current,'vibe')[0]=='native-sid'
    row['payload']['client_command_id']='tampered';dump(root/'journal'/'0000000000000001.jsonl',[row])
    with pytest.raises(ValueError,match='journal integrity'):C.validate(current,'vibe')

def test_mcode_requires_original_identity_and_completed_model_turn(tmp_path):
    p=dump(tmp_path/'messages.jsonl',[{'message_id':'original','turn_id':'turn','message':{'role':'user','content':[]}},{'message_id':'reply','turn_id':'turn','message':{'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'done'}]}}])
    (tmp_path/'manifest.json').write_text(json.dumps({'schemaVersion':1,'sessionId':'mvs-original'}))
    C.validate(p,'mcode');assert C.history(p,'mcode')[0]=='mvs-original';assert 'original' in C.history(p,'mcode')[1]
    dump(p,[{'message_id':'bad','message':{'role':'toolResult','toolCallId':'unknown','content':[]}}])
    with pytest.raises(ValueError,match='orphan'):C.validate(p,'mcode')

def test_fx_uses_native_log_identity_and_content_addressed_blobs(tmp_path):
    import hashlib
    p=tmp_path/'native-id'/'log.jsonl';blob=b'full original model/tool output';digest=hashlib.sha256(blob).hexdigest()
    rows=[{'v':1,'seq':1,'kind':'session_created','id':'native-id'},
      {'v':1,'seq':2,'kind':'item','type':'tool_call','data':{'call_id':'c'},'blobs':[digest]},
      {'v':1,'seq':3,'kind':'item','type':'tool_result','data':{'call_id':'c'}},
      {'v':1,'seq':4,'kind':'turn_committed'}, {'v':1,'seq':5,'kind':'closed'}]
    dump(p,rows);(p.parent/'blobs').mkdir();(p.parent/'blobs'/digest).write_bytes(blob)
    C.validate(p,'fx');C.validate(p,'fx-dev');assert C.history(p,'fx')[0]=='native-id'
    (p.parent/'blobs'/digest).write_bytes(b'edited')
    with pytest.raises(ValueError,match='blob integrity'):C.validate(p,'fx')

def test_native_export_is_safe_when_host_target_is_the_mounted_source(tmp_path):
    import asyncio,shutil
    target=tmp_path/'shared-native';target.mkdir();(target/'context.json').write_text('{"original":true}')
    class Environment:
        async def download_dir(self,source,destination):
            assert (target/'context.json').is_file()
            shutil.copytree(target,destination)
    asyncio.run(C._export(Environment(),'/logs/agent/native',target))
    assert json.loads((target/'context.json').read_text())=={'original':True}

def test_vibe_reads_full_native_model_context_after_journal_rotation(tmp_path):
    import hashlib
    root=tmp_path/'session';gen=root/'generations'/'0000000000000041';gen.mkdir(parents=True);(root/'chunks').mkdir()
    context=[{'message':{'role':'user','content':[{'type':'text','text':'original nonce'}]},'source':'user','turn_index':0},
      {'message':{'role':'assistant','content':[{'type':'text','text':'original reply'}]},'source':'model','turn_index':1}]
    raw=json.dumps(context).encode();digest=hashlib.sha256(raw).hexdigest();(root/'chunks'/(digest+'.json')).write_bytes(raw)
    (gen/'checkpoint.json').write_text(json.dumps({'context':{'messages':[]}}));(gen/'manifest.json').write_text(json.dumps({'checkpoint':{'chunks':[digest]}}))
    current=root/'CURRENT';current.write_text(json.dumps({'store_format':'mistral.vibe.unified-session-store/v1','session_id':'same-native-id','generation':gen.name}))
    # Previous journal segment has been replaced by a new segment at seq 42.
    dump(root/'journal'/'0000000000000042.jsonl',[{'sequence':42,'type':'command_reserved','payload':{}}])
    sid,messages=C.history(current,'vibe')
    assert sid=='same-native-id' and list(messages.values())==context
    assert messages['0']['message']['content'][0]['text']=='original nonce'

def test_openclaw_current_native_sqlite_reads_plain_and_bounded_zstd_events(tmp_path):
    import sqlite3,subprocess,shutil
    p=tmp_path/'openclaw-agent.sqlite'
    with sqlite3.connect(p) as db:
        db.executescript('CREATE TABLE session_windows(session_id TEXT PRIMARY KEY,updated_at INTEGER); CREATE TABLE transcript_events(session_id TEXT,seq INTEGER,event_json TEXT,event_zstd BLOB,event_utf8_bytes INTEGER,PRIMARY KEY(session_id,seq));')
        db.execute('INSERT INTO session_windows VALUES(?,?)',('native-session',1))
        header={'type':'session','id':'native-session'}
        user={'type':'message','id':'user-original','message':{'role':'user','content':[{'type':'text','text':'native nonce'}]}}
        assistant={'type':'message','id':'reply-original','message':{'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'done'}]}}
        for seq,event in enumerate([header,user,assistant]):
            raw=json.dumps(event).encode()
            if seq==1 and shutil.which('zstd'):
                compressed=subprocess.run(['zstd','-q','--stdout'],input=raw,capture_output=True,check=True).stdout
                db.execute('INSERT INTO transcript_events VALUES(?,?,?,?,?)',('native-session',seq,None,compressed,len(raw)))
            else:db.execute('INSERT INTO transcript_events VALUES(?,?,?,?,?)',('native-session',seq,raw.decode(),None,None))
    C.validate(p,'openclaw');sid,m=C.history(p,'openclaw')
    assert sid=='native-session' and m['1']['id']=='user-original' and m['1']['message']['content'][0]['text']=='native nonce'
    with pytest.raises(ValueError,match='bounds'):C._zstd_payload(b'not zstd',4194305)
    with sqlite3.connect(p) as db:db.execute('UPDATE transcript_events SET event_json=? WHERE seq=0',(json.dumps({'type':'session','id':'wrong'}),))
    with pytest.raises(ValueError,match='identity mismatch'):C.validate(p,'openclaw')

def test_openclaw_database_selector_tracks_cli_root_instead_of_newer_child(tmp_path):
    import sqlite3
    p=tmp_path/'openclaw-agent.sqlite'
    with sqlite3.connect(p) as db:
        db.executescript('CREATE TABLE session_windows(session_id TEXT PRIMARY KEY,updated_at INTEGER); CREATE TABLE transcript_events(session_id TEXT,seq INTEGER,event_json TEXT,event_zstd BLOB,event_utf8_bytes INTEGER,PRIMARY KEY(session_id,seq));')
        for sid,updated in [('original-root',1),('newer-child',2)]:
            db.execute('INSERT INTO session_windows VALUES(?,?)',(sid,updated))
            for seq,event in enumerate([{'type':'session','id':sid},{'type':'message','message':{'role':'assistant','content':[{'type':'text','text':sid}]}}]):
                db.execute('INSERT INTO transcript_events VALUES(?,?,?,?,?)',(sid,seq,json.dumps(event),None,None))
    (tmp_path/'wetlab-session-id.json').write_text(json.dumps({'session_id':'original-root','source':'native CLI meta.agentMeta.sessionId'}))
    assert C.history(p,'openclaw')[0]=='original-root'
    (tmp_path/'wetlab-session-id.json').write_text(json.dumps({'session_id':'missing-root'}))
    with pytest.raises(ValueError,match='empty'):C.history(p,'openclaw')

def test_openclaw_uses_supported_headless_bootstrap_and_canonical_state_config(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from harbor.agents.installed.openclaw import OpenClaw
    tracked=('_load_json_object','install','DEFAULT_SETUP_TIMEOUT_SEC','get_version_command','parse_version','_build_full_openclaw_config','exec_as_agent','run','build_cli_flags')
    with monkeypatch.context() as m:
        for name in tracked:m.setattr(OpenClaw,name,getattr(OpenClaw,name))
        calls=[]
        async def native_exec(self,environment,command,*args,**kwargs):calls.append((command,kwargs));return SimpleNamespace(return_code=0,stdout='')
        m.setattr(OpenClaw,'exec_as_agent',native_exec);m.setenv('OPENAI_API_KEY','unit-fixture-key')
        C.install({'agent':'openclaw','run_id':'unit-native-session','round':1,'base_url':'https://example.invalid/v1'})
        agent=OpenClaw(logs_dir=tmp_path,model_name='openai/deepseek/deepseek-flash',base_url='https://example.invalid/v1',model_api_key_name='OPENAI_API_KEY')
        uploads=[]
        class Environment:
            async def exec(self,command):return SimpleNamespace(return_code=0,stdout='/logs/agent/openclaw-home/workspace\n')
            async def upload_file(self,source,destination):uploads.append((source,destination))
        env=Environment();asyncio.run(C.prepare(agent,env,{'agent':'openclaw'},None))
        cfg=agent._build_full_openclaw_config()
        assert cfg['agents']['defaults']['workspace']=='/logs/agent/openclaw-home/workspace'
        assert cfg['agents']['defaults']['skipBootstrap'] is True
        assert '--skip-bootstrap' in agent._SETUP_CLI
        assert cfg['models']['providers']['openai']['apiKey']=='${OPENAI_API_KEY}'
        assert 'unit-fixture-key' not in json.dumps(cfg)
        asyncio.run(agent.exec_as_agent(env,'mkdir -p ~/.openclaw && cp /logs/agent/openclaw.upload.json ~/.openclaw/openclaw.json',env={'TASK_SEED':'42'}))
        command,kwargs=calls[-1]
        assert '~/.openclaw' not in command and '/logs/agent/openclaw-home/openclaw.json' in command
        assert kwargs['env']=={'TASK_SEED':'42','OPENCLAW_STATE_DIR':'/logs/agent/openclaw-home','OPENCLAW_CONFIG_PATH':'/logs/agent/openclaw-home/openclaw.json'}
        assert uploads[-1][1]=='/logs/agent/openclaw.upload.json'
        assert agent.parse_version('Now using node v24.22.2\nOpenClaw 2026.11.1 (4ffdd20)\n')=='OpenClaw 2026.11.1 (4ffdd20)'
        with pytest.raises(ValueError,match='version/build'):agent.parse_version('unknown')
        assert 'OPENCLAW_STATE_DIR=/logs/agent/openclaw-home' in agent.get_version_command()
        asyncio.run(agent.exec_as_agent(env,'npm install -g openclaw@latest',env={}))
        assert calls[-1][1]['env']['npm_config_prefer_offline']=='true'
        asyncio.run(agent.exec_as_agent(env,'openclaw agent --local --json',env={}))
        assert 'npm_config_prefer_offline' not in calls[-1][1]['env']

def test_openclaw_preinstalled_probe_requires_exact_native_build_and_preserves_version_recording(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from harbor.agents.installed.openclaw import OpenClaw
    tracked=('_load_json_object','install','DEFAULT_SETUP_TIMEOUT_SEC','get_version_command','parse_version','_build_full_openclaw_config','exec_as_agent','run','build_cli_flags')
    with monkeypatch.context() as m:
        for name in tracked:m.setattr(OpenClaw,name,getattr(OpenClaw,name))
        installed=[]
        async def installer(self,environment):installed.append(self._version)
        m.setattr(OpenClaw,'install',installer)
        C.install({'agent':'openclaw','run_id':'native-run','round':1})
        agent=object.__new__(OpenClaw);agent._version=None
        class Environment:
            native='OpenClaw 2026.11.1 (4ffdd20)'
            async def exec(self,command,**kwargs):return SimpleNamespace(return_code=0,stdout=self.native)
        env=Environment();asyncio.run(agent.install(env))
        assert installed==[] and agent._version is None
        env.native='OpenClaw 2026.11.1 (deadbee)'
        asyncio.run(agent.install(env))
        assert installed==['2026.11.1'] and agent._version is None


def test_openclaw_envelope_accepts_trailing_cli_diagnostics_without_inventing_identity():
    from wetlab.cli_extra import openclaw_envelope
    native={'meta':{'agentMeta':{'sessionId':'native-session-123'}},'payloads':[{'text':'answer'}]}
    assert openclaw_envelope(json.dumps(native,indent=2)+'\n[diagnostic] cleanup complete\n')==native
    assert openclaw_envelope('invalid stdout') is None
    assert openclaw_envelope('{"meta": {"agentMeta": {}}}\n[diagnostic] done') is None
