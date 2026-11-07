"""Strands FileSessionManager and pinned original Kimi CLI native persistence."""
from __future__ import annotations
import json,re,shlex
from pathlib import Path
NAMES={'strands','kimi-cli','langgraph'}
ROOT=Path(__file__).resolve().parent


def latest(trial,agent):
    root=Path(trial)/'agent'
    pattern={'strands':'native/strands/session_*/session.json','kimi-cli':'kimi/share/sessions/*/*/context.jsonl','langgraph':'langgraph-native/session.json'}[agent]
    files=list(root.glob(pattern))
    return max(files,key=lambda p:p.stat().st_mtime) if files else None


def history(path,agent):
    path=Path(path)
    if agent=='langgraph':
        data=json.loads(path.read_text())
        if data.get('format')!='wetlab-langgraph-native-v1' or not data.get('session_id') or not data.get('messages'):
            raise ValueError('LangGraph native context is missing')
        return data['session_id'],{str(i):m for i,m in enumerate(data['messages'])}
    if agent=='strands':
        meta=json.loads(path.read_text());sid=meta.get('session_id')
        messages={}
        for f in path.parent.glob('agents/*/messages/message_*.json'):
            data=json.loads(f.read_text())
            messages[str(f.relative_to(path.parent))]=data.get('message',data)
        if not sid or not messages:raise ValueError('Strands native session identity/messages missing')
        return sid,messages
    rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    messages=[r for r in rows if r.get('role') in ('user','assistant','tool','system')]
    if not messages:raise ValueError('Kimi native context has no model messages')
    return path.parent.name,{str(i):r for i,r in enumerate(messages)}


def validate(path,agent):
    sid,records=history(path,agent)
    if agent=='langgraph':
        import sqlite3
        data=json.loads(Path(path).read_text());db=Path(path).parent/'checkpoints.sqlite'
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as c:
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or not c.execute('SELECT 1 FROM checkpoints WHERE thread_id=? LIMIT 1',(sid,)).fetchone():
                raise ValueError('LangGraph native SQLite checkpoint is missing or corrupt')
        if not data['completed'] or data['messages'][-1].get('type')!='ai' or data['messages'][-1].get('tool_calls'):
            raise ValueError('LangGraph native turn is incomplete')
        return
    if agent=='strands':
        files=sorted(Path(path).parent.glob('agents/*/messages/message_*.json'),key=lambda p:int(p.stem.rsplit('_',1)[-1]))
        rows=[json.loads(p.read_text())['message'] for p in files];calls=set();results=set()
        for row in rows:
            for part in row.get('content',[]):
                if 'toolUse' in part:calls.add(part['toolUse']['toolUseId'])
                if 'toolResult' in part:results.add(part['toolResult']['toolUseId'])
        if calls-results or rows[-1].get('role')!='assistant' or any('toolUse' in p for p in rows[-1].get('content',[])):
            raise ValueError('Strands native turn is incomplete')
    else:
        rows=list(records.values());calls=set();results=set()
        for row in rows:
            calls.update(c['id'] for c in row.get('tool_calls') or [])
            if row.get('role')=='tool':results.add(row['tool_call_id'])
        if calls-results or rows[-1].get('role')!='assistant' or rows[-1].get('tool_calls'):
            raise ValueError('Kimi native turn is incomplete')


def bundle(path,agent):return Path(path).parent


def install(state,saved=None):
    if state['agent']=='langgraph':
        from harbor.agents.installed.langgraph import LangGraph
        original=LangGraph.__init__
        def initialize(self,*args,**kwargs):
            if not kwargs.get('project_path'):kwargs['project_path']=str(ROOT/'factories/langgraph-default')
            configurable=dict(kwargs.get('configurable') or {});configurable.setdefault('thread_id',state['run_id']);kwargs['configurable']=configurable
            original(self,*args,**kwargs)
        LangGraph.__init__=initialize
    elif state['agent']=='strands':
        from harbor.agents.installed.strands import Strands
        original=Strands.__init__
        def initialize(self,*args,**kwargs):
            if not kwargs.get('factory_path'):kwargs['factory_path']=str(ROOT/'factories/strands-default')
            original(self,*args,**kwargs)
        Strands.__init__=initialize
    elif state['agent']=='kimi-cli':
        from harbor.agents.installed.kimi_cli import KimiCli
        original=KimiCli.__init__;run=KimiCli.run
        def initialize(self,*args,**kwargs):
            if not kwargs.get('version'):kwargs['version']='1.51.0'
            original(self,*args,**kwargs)
        async def invoke(self,instruction,environment,context):
            self._resume=bool(saved)
            try:return await run(self,instruction,environment,context)
            finally:await environment.exec('rm -f /tmp/kimi-config.json')
        KimiCli.__init__=initialize;KimiCli.run=invoke
        KimiCli.get_version_command=lambda self:'export PATH="$HOME/.local/bin:$PATH"; kimi --version'
        KimiCli.parse_version=lambda self,text:(re.search(r'\b\d+\.\d+\.\d+\b',text).group(0) if re.search(r'\b\d+\.\d+\.\d+\b',text) else text.strip())


async def prepare(agent,environment,state,saved=None):
    if state['agent']=='langgraph':
        local=agent.logs_dir/'wetlab-graph-connection.json'
        local.write_text(json.dumps({'model':state['model'].partition('/')[2], 'base_url':state['base_url'], 'api_key_name':state.get('api_key_name') or 'OPENAI_API_KEY'}))
        await environment.exec('mkdir -p /logs/agent/langgraph-native')
        await environment.upload_file(local,'/logs/agent/langgraph-native/connection.json')
        return
    if state['agent']!='strands':return
    from harbor.agents.installed import strands
    source=Path(strands.__file__).with_name('strands_runner.py').read_text()
    needle='        return self.agent'
    if source.count(needle)!=1:raise ValueError('Strands native runner contract changed')
    sid=state['run_id']
    replacement=f'''        from strands.session.file_session_manager import FileSessionManager
        if self.agent._session_manager is not None:
            raise ValueError('wetlab Strands requires task-local FileSessionManager; configure a factory without an external session manager')
        manager=FileSessionManager(session_id={sid!r},storage_dir='/logs/agent/native/strands')
        self.agent._session_manager=manager
        self.agent._session_id=manager.session_id
        manager.initialize(self.agent)
        self.agent.hooks.add_hook(manager)
        return self.agent'''
    source=source.replace(needle,replacement)
    local=agent.logs_dir/'wetlab-strands-runner.py';local.write_text(source)
    await environment.upload_file(local,str(agent._RUNNER_PATH))
