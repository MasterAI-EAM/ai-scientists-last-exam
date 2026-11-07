"""Process-local native CLI resume adapters; no transcript reconstruction."""
from __future__ import annotations
import ctypes,ctypes.util,hashlib,json,re,shlex,shutil,sqlite3
from contextlib import closing
from urllib.parse import quote
from pathlib import Path

NAMES={'grok-build','code-puppy','openclaw','mcode','fx','fx-dev','vibe'}

def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def latest(trial:Path,agent):
    root=trial/'agent'
    patterns={'grok-build':'sessions/**/chat_history.jsonl','code-puppy':'code-puppy-home/autosaves/*.json',
      'openclaw':'openclaw-home/agents/*/sessions/*.jsonl','mcode':'mcode-home/v2/sessions/**/messages.jsonl',
      'fx':'fx-home/sessions/v2/*/log.jsonl','fx-dev':'fx-home/sessions/v2/*/log.jsonl','vibe':'vibe-export-*/session/CURRENT'}
    files=[p for p in root.glob(patterns[agent]) if not p.name.endswith('_meta.json')]
    if agent=='openclaw':
        databases=list(root.glob('openclaw-home/agents/*/agent/openclaw-agent.sqlite'))
        if databases:files=databases
    if agent=='code-puppy':
        files=[p for p in files if json.loads(p.read_text()).get('format')==2]
    return max(files,key=lambda p:p.stat().st_mtime) if files else None

def _zstd_payload(blob,expected):
    if not isinstance(blob,bytes) or not 1<=len(blob)<=4194304 or not isinstance(expected,int) or not 1<=expected<=4194304:
        raise ValueError('invalid native compressed transcript bounds')
    library=ctypes.util.find_library('zstd')
    if not library:
        executable=shutil.which('zstd')
        candidate=Path(executable).resolve().parent.parent/'lib'/'libzstd.dylib' if executable else None
        if candidate and candidate.is_file():library=str(candidate)
    if not library:raise ValueError('native zstd transcript codec is unavailable')
    codec=ctypes.CDLL(library)
    codec.ZSTD_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
    codec.ZSTD_decompress.restype=ctypes.c_size_t
    codec.ZSTD_isError.argtypes=[ctypes.c_size_t];codec.ZSTD_isError.restype=ctypes.c_uint
    target=ctypes.create_string_buffer(expected)
    result=codec.ZSTD_decompress(target,expected,blob,len(blob))
    if codec.ZSTD_isError(result) or result!=expected:raise ValueError('invalid native compressed transcript payload length')
    return target.raw.decode('utf-8')


def _openclaw_database(path):
    with closing(sqlite3.connect('file:'+quote(str(path.resolve()))+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'session_windows','transcript_events'}<=tables:raise ValueError('unsupported OpenClaw native database schema')
        cols={r[1] for r in db.execute('PRAGMA table_info(transcript_events)')}
        if not {'session_id','seq','event_json','event_zstd','event_utf8_bytes'}<=cols:raise ValueError('unsupported OpenClaw native event payload schema')
        selector=path.parent/'wetlab-session-id.json'
        if selector.is_file():
            sid=json.loads(selector.read_text()).get('session_id')
            if not isinstance(sid,str) or not sid:raise ValueError('invalid OpenClaw native CLI session selector')
            session=db.execute('SELECT session_id FROM session_windows WHERE session_id=?',(sid,)).fetchone()
        else:session=db.execute('SELECT session_id FROM session_windows ORDER BY updated_at DESC LIMIT 1').fetchone()
        if not session:raise ValueError('empty OpenClaw native session database')
        sid=session[0];records=[]
        for seq,plain,compressed,length in db.execute('SELECT seq,event_json,event_zstd,event_utf8_bytes FROM transcript_events WHERE session_id=? ORDER BY seq',(sid,)):
            event=json.loads(plain if plain is not None else _zstd_payload(compressed,length))
            records.append((seq,event))
        if not records or records[0][1].get('type')!='session' or records[0][1].get('id')!=sid:raise ValueError('OpenClaw database transcript identity mismatch')
        messages={str(seq):event for seq,event in records if event.get('type')=='message'}
        if not messages:raise ValueError('empty OpenClaw native message history')
        return sid,messages


def history(path,agent):
    if agent=='code-puppy':
        data=json.loads(path.read_text())
        if data.get('format')!=2 or data.get('encoding')!='pydantic-ai-messages':raise ValueError('unsupported Code Puppy native format')
        rows=data['messages'];sid=path.stem
    elif agent in ('fx','fx-dev'):
        rows=_rows(path)
        if rows[0].get('kind')!='session_created' or rows[0].get('v')!=1:raise ValueError('unsupported FX native session schema')
        sid=rows[0]['id']
        if sid!=path.parent.name:raise ValueError('FX native session identity mismatch')
        return sid,{str(r['seq']):r for r in rows}
    elif agent=='vibe':
        current=json.loads(path.read_text())
        if current.get('store_format')!='mistral.vibe.unified-session-store/v1':raise ValueError('unsupported Vibe native store')
        sid=current['session_id']
        if not re.fullmatch(r'[0-9]{16}',current['generation']):raise ValueError('invalid Vibe native generation path')
        generation=path.parent/'generations'/current['generation']
        manifest=json.loads((generation/'manifest.json').read_text())
        checkpoint=json.loads((generation/'checkpoint.json').read_text())
        rows=list(checkpoint.get('context',{}).get('messages',[]))
        for digest in manifest['checkpoint'].get('chunks',[]):
            if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('invalid Vibe native chunk path')
            chunk=json.loads((path.parent/'chunks'/(digest+'.json')).read_text())
            if not isinstance(chunk,list):raise ValueError('invalid Vibe native model context chunk')
            rows.extend(chunk)
        if not rows:raise ValueError('empty Vibe native model context')
        return sid,{str(i):r for i,r in enumerate(rows)}
    elif agent=='mcode':
        meta=json.loads((path.parent/'manifest.json').read_text())
        if meta.get('schemaVersion')!=1:raise ValueError('unsupported MCode native session schema')
        sid=meta['sessionId'];rows=_rows(path)
        return sid,{r['message_id']:r for r in rows}
    elif agent=='grok-build':rows=_rows(path);sid=path.parent.name
    elif agent=='openclaw':
        if path.suffix=='.sqlite':return _openclaw_database(path)
        raw=_rows(path);header=raw[0]
        if header.get('type')!='session' or not header.get('id'):raise ValueError('OpenClaw native session header missing')
        sid=header['id'];rows=[r for r in raw if r.get('type')=='message']
    else:raise ValueError('unsupported native CLI harness')
    if not rows:raise ValueError('empty native conversation')
    return sid,{str(i):row for i,row in enumerate(rows)}

def validate(path,agent):
    sid,entries=history(path,agent);rows=list(entries.values())
    if not sid:raise ValueError('native session identity missing')
    pending=set()
    if agent=='grok-build':
        for r in rows:
            if r.get('type')=='assistant':
                for t in r.get('tool_calls') or []:
                    if t['id'] in pending:raise ValueError('duplicate native tool call')
                    pending.add(t['id'])
            elif r.get('type')=='tool_result':
                if r['tool_call_id'] not in pending:raise ValueError('orphan native tool result')
                pending.remove(r['tool_call_id'])
        if pending or rows[-1].get('type')!='assistant' or rows[-1].get('tool_calls'):raise ValueError('Grok turn is incomplete')
    elif agent=='code-puppy':
        for row in rows:
            if row.get('kind') not in ('request','response'):raise ValueError('invalid PydanticAI message')
            for p in row.get('parts',[]):
                if p.get('part_kind')=='tool-call':pending.add(p['tool_call_id'])
                elif p.get('part_kind') in ('tool-return','retry-prompt') and p.get('tool_call_id'):
                    if p['tool_call_id'] not in pending:raise ValueError('orphan native tool result')
                    pending.remove(p['tool_call_id'])
        if pending or rows[-1].get('kind')!='response' or rows[-1].get('finish_reason')!='stop' or rows[-1].get('state')!='complete':raise ValueError('Code Puppy turn is incomplete')
    elif agent=='openclaw':
        for row in rows:
            m=row.get('message',{})
            for p in m.get('content',[]) if isinstance(m.get('content'),list) else []:
                if p.get('type')=='toolCall':pending.add(p['id'])
            if m.get('role')=='toolResult':
                if m.get('toolCallId') not in pending:raise ValueError('orphan native tool result')
                pending.remove(m['toolCallId'])
        if pending or rows[-1].get('message',{}).get('role')!='assistant':raise ValueError('OpenClaw turn is incomplete')
    elif agent in ('fx','fx-dev'):
        sequences=[r['seq'] for r in rows]
        if sequences!=list(range(1,len(rows)+1)):raise ValueError('FX native event sequence broken')
        for r in rows:
            for digest in r.get('blobs',[]):
                if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('invalid FX native blob path')
                if hashlib.sha256((path.parent/'blobs'/digest).read_bytes()).hexdigest()!=digest:raise ValueError('FX native blob integrity failure')
            if r.get('kind')=='item' and r.get('type')=='tool_call':pending.add(r['data']['call_id'])
            elif r.get('kind')=='item' and r.get('type')=='tool_result':
                if r['data']['call_id'] not in pending:raise ValueError('orphan FX native tool result')
                pending.remove(r['data']['call_id'])
        if pending or rows[-1]['kind']!='closed' or not any(r['kind']=='turn_committed' for r in rows):raise ValueError('FX native turn is incomplete')
    elif agent=='vibe':
        current=json.loads(path.read_text())
        if not re.fullmatch(r'[0-9]{16}',current['generation']):raise ValueError('invalid Vibe native generation path')
        generation=path.parent/'generations'/current['generation']
        raw=(generation/'manifest.json').read_bytes()
        if hashlib.sha256(raw.rstrip(b'\n')).hexdigest()!=current['manifest_sha256']:raise ValueError('Vibe native manifest hash mismatch')
        manifest=json.loads(raw)
        if manifest.get('execution_state')!='quiescent' or manifest['session_id']!=sid:raise ValueError('Vibe native state is not quiescent')
        for kind in ('checkpoint','projection_state','runtime_state'):
            entry=manifest[kind]
            if entry['path']!=kind.replace('_','-')+'.json':raise ValueError('invalid Vibe native state path')
            part=generation/entry['path']
            if hashlib.sha256(part.read_bytes().rstrip(b'\n')).hexdigest()!=entry['sha256']:raise ValueError('Vibe native state hash mismatch')
            for digest in entry.get('chunks',[]):
                if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('invalid Vibe native chunk path')
                if hashlib.sha256((path.parent/'chunks'/(digest+'.json')).read_bytes().rstrip(b'\n')).hexdigest()!=digest:raise ValueError('Vibe native chunk hash mismatch')
        journal=[]
        for segment in sorted((path.parent/'journal').glob('*.jsonl')):journal.extend(_rows(segment))
        journal.sort(key=lambda r:r['sequence'])
        if not journal:raise ValueError('empty Vibe native journal')
        if [r['sequence'] for r in journal]!=list(range(journal[0]['sequence'],journal[-1]['sequence']+1)):raise ValueError('Vibe native journal sequence broken')
        previous=None
        for row in journal:
            payload={k:v for k,v in row.items() if k!='record_sha256'}
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            if digest!=row['record_sha256'] or (previous and row['previous_record_sha256']!=previous):raise ValueError('Vibe native journal integrity failure')
            previous=digest
        if journal[-1]['type']!='receipt_succeeded' or journal[-1]['sequence']!=manifest['snapshot_sequence']:raise ValueError('Vibe native turn is incomplete')
        for row in rows:
            message=row['message']
            if message.get('role') not in ('user','assistant','tool','system'):raise ValueError('invalid Vibe native model message')
            for part in message.get('content',[]):
                if part.get('type')=='tool_call':pending.add(part['id'])
            if message.get('role')=='tool':
                if message['tool_call_id'] not in pending:raise ValueError('orphan Vibe native tool result')
                pending.remove(message['tool_call_id'])
        if pending or rows[-1]['message'].get('role')!='assistant':raise ValueError('Vibe model turn is incomplete')
    elif agent=='mcode':
        for row in rows:
            m=row['message']
            if m.get('role') not in ('user','assistant','toolResult'):raise ValueError('invalid MCode native message')
            for part in m.get('content',[]):
                if part.get('type')=='toolCall':pending.add(part['id'])
            if m.get('role')=='toolResult':
                if m.get('toolCallId') not in pending:raise ValueError('orphan MCode native tool result')
                pending.remove(m['toolCallId'])
        if pending or rows[-1]['message'].get('role')!='assistant' or rows[-1]['message'].get('stopReason')!='stop':raise ValueError('MCode turn is incomplete')
    else:raise ValueError(agent+' native format needs verified schema')

def bundle(path,agent):
    return path.parent

async def _export(environment,source,target):
    # Docker Desktop copies container logs only after Trial._run_agent_phase.
    # Publish the actual native files before the worker's continuation guard.
    import shutil,tempfile
    with tempfile.TemporaryDirectory(prefix='wetlab-native-export-') as folder:
        staged=Path(folder)/'native'
        await environment.download_dir(source,staged)
        if any(p.is_symlink() for p in staged.rglob('*')):raise ValueError('native export contains a symlink')
        if target.is_symlink() or (target.exists() and any(p.is_symlink() for p in target.rglob('*'))):raise ValueError('native export destination contains a symlink')
        shutil.copytree(staged,target,dirs_exist_ok=True)


def install(state,saved=None):
    name=state['agent']
    restored=history(Path(saved['session_path']),name)[0] if saved else None
    if name=='grok-build':
        from harbor.agents.installed.grok_build import GrokBuild
        original=GrokBuild.exec_as_agent
        async def execute(self,environment,command,*args,**kwargs):
            if restored:command=command.replace('--session-id '+self._session_id,'--resume '+shlex.quote(restored),1)
            return await original(self,environment,command,*args,**kwargs)
        GrokBuild.exec_as_agent=execute
        original_run=GrokBuild.run
        async def run(self,instruction,environment,context):
            result=await original_run(self,instruction,environment,context)
            await _export(environment,'/logs/agent/sessions',self.logs_dir/'sessions')
            return result
        GrokBuild.run=run
    elif name=='code-puppy':
        from harbor.agents.installed.code_puppy import CodePuppy
        original_cfg=CodePuppy._render_puppy_cfg;original_cmd=CodePuppy._build_run_command
        CodePuppy._render_puppy_cfg=lambda self,alias:original_cfg(self,alias).replace('auto_save_session = false','auto_save_session = true')
        def command(self,instruction):
            cmd=original_cmd(self,instruction)
            if restored:cmd=cmd.replace('code-puppy --yolo','code-puppy --resume '+shlex.quote('/logs/agent/code-puppy-home/autosaves/'+restored+'.json')+' --yolo',1)
            return cmd
        CodePuppy._build_run_command=command
        original_run=CodePuppy.run
        async def run(self,instruction,environment,context):
            result=await original_run(self,instruction,environment,context)
            await _export(environment,'/logs/agent/code-puppy-home/autosaves',self.logs_dir/'code-puppy-home'/'autosaves')
            return result
        CodePuppy.run=run
    elif name=='openclaw':
        from harbor.agents.installed.openclaw import OpenClaw
        # Native npm + Node installation is separate from the model turn budget.
        OpenClaw.DEFAULT_SETUP_TIMEOUT_SEC=900
        original_version_command=OpenClaw.get_version_command
        OpenClaw.get_version_command=lambda self:'export OPENCLAW_STATE_DIR=/logs/agent/openclaw-home OPENCLAW_CONFIG_PATH=/logs/agent/openclaw-home/openclaw.json; '+original_version_command(self)
        def parse_version(self,stdout):
            for line in stdout.splitlines():
                if re.fullmatch(r'OpenClaw [0-9][A-Za-z0-9.+-]* \([a-f0-9]{7,40}\)',line.strip()):return line.strip()
            raise ValueError('OpenClaw native version/build identity is missing')
        OpenClaw.parse_version=parse_version
        original_install=OpenClaw.install
        async def install_native(self,environment):
            requested=self._version
            if requested in (None,'2026.11.1'):
                probe=await environment.exec(self.get_version_command(),timeout_sec=30)
                if probe.return_code==0:
                    try:actual=self.parse_version(probe.stdout)
                    except ValueError:actual=None
                    if actual=='OpenClaw 2026.11.1 (4ffdd20)':return
            try:
                # Keep the first installation and any retry on the exact
                # validated native release; Base.setup records its full build.
                self._version=requested or '2026.11.1'
                return await original_install(self,environment)
            finally:self._version=requested
        OpenClaw.install=install_native
        original_config=OpenClaw._build_full_openclaw_config
        def config(self):
            value=original_config(self)
            value.setdefault('agents',{}).setdefault('defaults',{})['skipBootstrap']=True
            return value
        OpenClaw._build_full_openclaw_config=config
        original_exec=OpenClaw.exec_as_agent
        async def execute(self,environment,command,*args,**kwargs):
            kwargs['env']={**(kwargs.get('env') or {}),'OPENCLAW_STATE_DIR':'/logs/agent/openclaw-home','OPENCLAW_CONFIG_PATH':'/logs/agent/openclaw-home/openclaw.json'}
            if 'npm install -g ' in command and 'openclaw' in command:
                # Normal npm cache preference still fetches missing packages and
                # runs the original installer/integrity/version checks.
                kwargs['env']['npm_config_prefer_offline']='true'
            if 'cp /logs/agent/openclaw.upload.json ' in command:
                await environment.upload_file(self.logs_dir/'openclaw.upload.json','/logs/agent/openclaw.upload.json')
                command=command.replace('~/.openclaw','/logs/agent/openclaw-home')
            return await original_exec(self,environment,command,*args,**kwargs)
        OpenClaw.exec_as_agent=execute
        original_run=OpenClaw.run
        async def run(self,instruction,environment,context):
            result=await original_run(self,instruction,environment,context)
            await _export(environment,'/logs/agent/openclaw-home/agents',self.logs_dir/'openclaw-home'/'agents')
            output=await environment.exec('cat /logs/agent/openclaw.txt')
            envelope=self._load_json_object(output.stdout) or {}
            session_id=(envelope.get('meta') or {}).get('agentMeta',{}).get('sessionId')
            if not isinstance(session_id,str) or not session_id:raise ValueError('OpenClaw native CLI did not attest its session ID')
            agent_id=self.options.openclaw_agent_id
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',agent_id):raise ValueError('invalid OpenClaw native agent profile')
            target=self.logs_dir/'openclaw-home'/'agents'/agent_id/'agent'/'wetlab-session-id.json'
            try:from .support import atomic_json
            except ImportError:from support import atomic_json
            atomic_json(target,{'session_id':session_id,'source':'native CLI meta.agentMeta.sessionId'})
            return result
        OpenClaw.run=run
        original=OpenClaw.build_cli_flags
        OpenClaw.build_cli_flags=lambda self:original(self)+' --session-id '+shlex.quote(restored or state['run_id'])
    elif name=='mcode':
        from harbor.agents.installed.mcode import MCode
        if 'tokenhub.tencentmaas.com' in state.get('base_url',''):
            MCode._native_api_format=staticmethod(lambda fmt:'anthropic-messages')
        MCode._DATA_DIR='/logs/agent/mcode-home';MCode._SKILLS_DIR=MCode._DATA_DIR+'/skills'
        original_flags=MCode.build_cli_flags
        MCode.build_cli_flags=lambda self:original_flags(self)+((' --session '+shlex.quote(restored)) if restored else '')
        original=MCode.run
        async def run(self,*args,**kwargs):
            self._resume=False
            result=await original(self,*args,**kwargs)
            environment=kwargs.get('environment') or args[1]
            await _export(environment,'/logs/agent/mcode-home/v2/sessions',self.logs_dir/'mcode-home'/'v2'/'sessions')
            return result
        MCode.run=run
    elif name in ('fx','fx-dev'):
        from harbor.agents.installed.fx import Fx
        original=Fx.exec_as_agent
        async def execute(self,environment,command,*args,**kwargs):
            if restored and 'fx ask ' in command:command=command.replace('fx ask ','fx ask --resume '+shlex.quote(restored)+' ',1)
            return await original(self,environment,command,*args,**kwargs)
        Fx.exec_as_agent=execute
        original_run=Fx.run
        async def run(self,instruction,environment,context):
            result=await original_run(self,instruction,environment,context)
            await environment.exec('mkdir -p /logs/agent/fx-home; if [ -d "$HOME/.fx" ]; then cp -a "$HOME/.fx/." /logs/agent/fx-home/; fi')
            await _export(environment,'/logs/agent/fx-home/sessions',self.logs_dir/'fx-home'/'sessions')
            return result
        Fx.run=run
    elif name=='vibe':
        from harbor.agents.installed.vibe import Vibe
        Vibe._REMOTE_VIBE_HOME=Path('/opt/wetlab-vibe')
        original_run=Vibe.run
        async def run(self,instruction,environment,context):
            result=await original_run(self,instruction,environment,context)
            export='vibe-export-'+str(state['round'])
            await _export(environment,'/logs/agent/'+export+'/session',self.logs_dir/export/'session')
            return result
        Vibe.run=run
        original=Vibe.build_cli_flags
        Vibe.build_cli_flags=lambda self:original(self)+' --output-dir /logs/agent/vibe-export-'+str(state['round'])+((' --resume '+shlex.quote(restored)) if restored else '')
        original_cfg=Vibe._build_config_toml
        def config(self):
            import toml
            data=toml.loads(original_cfg(self))
            if isinstance(data.get('models'),list):data['models']={m['alias']:m for m in data['models']}
            return toml.dumps(data)
        Vibe._build_config_toml=config

async def prepare(agent,environment,state,saved=None):
    if state['agent']=='openclaw':
        result=await environment.exec('mkdir -p /logs/agent/openclaw-home/workspace; cd /logs/agent/openclaw-home/workspace; pwd -P')
        cwd=result.stdout.strip()
        if result.return_code or not cwd.startswith('/'):raise ValueError('OpenClaw workspace is not canonical')
        agent._SETUP_CLI='openclaw setup --baseline --skip-bootstrap --workspace '+shlex.quote(cwd)
        agent._SETUP_BASELINE={'agents':{'defaults':{'workspace':cwd,'skipBootstrap':True}},'gateway':{'mode':'local'}}
    if saved and state['agent']=='grok-build':agent._session_id=history(Path(saved['session_path']),'grok-build')[0]
    profile={'code-puppy':('.code_puppy','code-puppy-home')}.get(state['agent'])
    if not profile:return
    home,target=profile;dest='/logs/agent/'+target
    command=f'mkdir -p {shlex.quote(dest)}; if [ ! -L "$HOME/{home}" ]; then if [ -d "$HOME/{home}" ]; then cp -a "$HOME/{home}/." {shlex.quote(dest)}/; rm -rf "$HOME/{home}"; fi; ln -s {shlex.quote(dest)} "$HOME/{home}"; fi'
    result=await environment.exec(command)
    if result.return_code:raise ValueError('cannot expose native CLI profile in checkpoint log mount')
