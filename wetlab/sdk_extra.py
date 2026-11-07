"""Native persistence adapters for Python SDK and CLI research harnesses.

The small hooks run inside the task container. Serialized model messages/events are
never approximated with prose, and no untrusted pickle is loaded on the host.
"""
from __future__ import annotations
import json,shlex,uuid,textwrap,re
from pathlib import Path

NAMES={'openhands-sdk','mini-swe-agent','aider','swe-agent','trae-agent','openhands'}
FILE='wetlab-sdk-session.json'

JSON_HELPER=r'''def _wetlab_json(data,**options):
    raw=json.dumps(data,**options)
    for key,value in os.environ.items():
        if len(value)>=8 and (key.endswith('_API_KEY') or key in ('WETLAB_TOKEN','ANTHROPIC_AUTH_TOKEN','HF_TOKEN',os.environ.get('WETLAB_MODEL_KEY_ENV',''))):
            raw=raw.replace(json.dumps(value)[1:-1],'<redacted>').replace(value,'<redacted>')
    return raw
'''



def latest(trial:Path,agent:str):
    path=trial/'agent'/FILE
    return path if path.is_file() else None


def history(path,agent):
    data=json.loads(path.read_text())
    if data.get('format')!='wetlab-sdk-native-v1' or data.get('harness')!=agent or not data.get('session_id'):
        raise ValueError('invalid SDK native session identity')
    messages=data.get('messages')
    if not isinstance(messages,list) or not messages or not all(isinstance(m,dict) for m in messages):
        raise ValueError('native SDK history is empty or malformed')
    return data['session_id'],{str(i):m for i,m in enumerate(messages)}


def validate(path,agent):
    history(path,agent)
    data=json.loads(path.read_text())
    if not data.get('completed'):raise ValueError('native SDK has no complete turn boundary')
    if agent=='openhands-sdk':
        native=path.parent/'sdk-native'/data['session_id'].replace('-','')/'base_state.json'
        if not native.is_file():raise ValueError('OpenHands persisted native base state missing')
        if json.loads(native.read_text()).get('id')!=data['session_id']:raise ValueError('OpenHands conversation identity mismatch')


def bundle(path,agent):return path.parent


def install(state,saved=None):
    """Keep Harbor's actual harness and inject only its native restore hooks."""
    if state['agent'] not in NAMES:return
    if state['agent']=='mini-swe-agent':
        from harbor.agents.installed.mini_swe_agent import MiniSweAgent
        cls=MiniSweAgent
    elif state['agent']=='aider':
        from harbor.agents.installed.aider import Aider
        cls=Aider
    elif state['agent']=='swe-agent':
        from harbor.agents.installed.swe_agent import SweAgent
        cls=SweAgent
        def trajectory_file(self):
            files=list((self.logs_dir/'swe-agent-output').glob('**/*.traj'))
            return max(files,key=lambda p:p.stat().st_mtime) if files else None
        cls._find_trajectory_file=trajectory_file
        cls.get_version_command=lambda self: '/opt/sweagent-venv/bin/python -c '+shlex.quote('import sweagent; print(sweagent.__version__)')
        def parse_native_version(self,stdout):
            lines=[line.strip() for line in stdout.splitlines() if re.fullmatch(r'[0-9]+(?:\.[0-9]+)+(?:[a-zA-Z0-9.+-]*)?',line.strip())]
            return lines[-1] if lines else ''
        cls.parse_version=parse_native_version
    elif state['agent']=='trae-agent':
        from harbor.agents.installed.trae_agent import TraeAgent
        cls=TraeAgent
    elif state['agent']=='openhands':
        from harbor.agents.installed.openhands import OpenHands
        cls=OpenHands
    else:
        from harbor.agents.installed.openhands_sdk import OpenHandsSDK
        cls=OpenHandsSDK
    if state['agent'] in ('mini-swe-agent','swe-agent','openhands'):
        dependencies=cls.ensure_system_dependencies
        async def ensure(self,environment,required,**kwargs):
            return await dependencies(self,environment,tuple(x for x in required if x!='build_tools'),**kwargs)
        cls.ensure_system_dependencies=ensure
    original=cls.exec_as_agent
    async def execute(self,environment,command,**kwargs):
        if state['agent']=='mini-swe-agent' and 'uv tool install --python' in command:
            command=command.replace('--with fastapi','--with fastapi --with mcp')
        if state['agent']=='swe-agent' and 'cp /opt/sweagent-repo/config/default_backticks.yaml' in command:
            command=command.replace('cp /opt/sweagent-repo/config/default_backticks.yaml /opt/sweagent-configs/default_backticks.yaml 2>/dev/null || true && ', '(cp /opt/sweagent-repo/config/default_backticks.yaml /opt/sweagent-configs/default_backticks.yaml 2>/dev/null || true) && ')
        if state['agent']=='swe-agent' and 'sweagent run' in command:
            command=command.replace('sweagent run ','sweagent run --agent.model.per_instance_cost_limit=0 --agent.model.total_cost_limit=0 ')
        if state['agent']=='aider' and 'aider --yes' in command:
            command=command.replace('aider --yes ','aider --yes --edit-format diff --max-chat-history-tokens 1000000 ')
        if state['agent']=='openhands' and 'uv pip install openhands-ai &&' in command:
            command=command.replace('uv pip install openhands-ai &&','uv pip install openhands-ai==0.62.0 &&').replace('uv python install 3.13','uv python install 3.12').replace('--python 3.13','--python 3.12')
        if state['agent']=='trae-agent' and 'uv tool install --python' in command:
            command=command.replace('uv tool install --python 3.12','uv tool install --python 3.12 --with pydantic==2.11.10')
        # The entry-point process imports sitecustomize before its native CLI.
        if (state['agent']=='mini-swe-agent' and 'mini-swe-agent --yolo' in command) or (state['agent']=='aider' and 'aider --yes' in command) or (state['agent']=='swe-agent' and 'sweagent run' in command) or (state['agent']=='trae-agent' and 'trae-cli run' in command) or (state['agent']=='openhands' and 'python -m openhands.core.main' in command and '--task=' in command):
            env=dict(kwargs.pop('env',{}) or {});env['WETLAB_MODEL_KEY_ENV']=state.get('api_key_name') or 'OPENAI_API_KEY';env['PYTHONPATH']='/installed-agent/wetlab-hooks'+(':'+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
            kwargs['env']=env
        return await original(self,environment,command=command,**kwargs)
    cls.exec_as_agent=execute
    if state['agent']=='swe-agent':
        root_execute=cls.exec_as_root
        async def execute_root(self,environment,command,**kwargs):
            command=command.replace('cp /opt/sweagent-repo/config/default_backticks.yaml /opt/sweagent-configs/default_backticks.yaml 2>/dev/null || true && ', '(cp /opt/sweagent-repo/config/default_backticks.yaml /opt/sweagent-configs/default_backticks.yaml 2>/dev/null || true) && ').replace('uv pip install /opt/sweagent-repo &&','uv pip install /opt/sweagent-repo mcp &&')
            return await root_execute(self,environment,command=command,**kwargs)
        cls.exec_as_root=execute_root


async def prepare(agent,environment,state,saved=None):
    name=state['agent']
    if name not in NAMES:return
    # Harbor's setup records versions best-effort. A durable research session
    # requires an actual native version before the first model request.
    version_command=agent.get_version_command()
    result=await environment.exec(version_command) if version_command else None
    actual=agent.parse_version(result.stdout).strip() if result is not None and result.return_code==0 and result.stdout else None
    if not actual or actual.lower() in ('unknown','unavailable','none'):
        raise ValueError('native '+name+' version cannot be verified before model execution')
    agent._version=actual
    sid=history(Path(saved['session_path']),name)[0] if saved else str(uuid.uuid5(uuid.NAMESPACE_URL,'wetlab:'+state['run_id']))
    if name=='openhands-sdk':
        from harbor.agents.installed import openhands_sdk
        source=(Path(openhands_sdk.__file__).parent/'openhands_sdk_runner.py').read_text()
        needle='    conversation = Conversation(**conv_kwargs)'
        if source.count(needle)!=1:raise ValueError('OpenHands SDK runner changed')
        injected='''    import uuid
    _wetlab_path = Path('/logs/agent/wetlab-sdk-session.json')
    _wetlab_previous = json.loads(_wetlab_path.read_text()) if _wetlab_path.exists() else {}
    _wetlab_events = list(_wetlab_previous.get('messages', []))
    def _wetlab_record(event=None, completed=False):
        if event is not None:
            item=event.model_dump(mode='json', exclude_none=True)
            if not any(old.get('id') == item.get('id') for old in _wetlab_events):
                _wetlab_events.append(item)
            # An observation is durable before this callback. A submitted wetlab
            # command has returned, so no tool is still executing at this boundary.
            if 'END YOUR TURN NOW' in json.dumps(item):
                completed=True
        data={'format':'wetlab-sdk-native-v1','harness':'openhands-sdk',
              'session_id':%r,'messages':_wetlab_events,'completed':completed}
        tmp=_wetlab_path.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(_wetlab_path)
    conv_kwargs.update(persistence_dir='/logs/agent/sdk-native', conversation_id=uuid.UUID(%r),
                       delete_on_close=False, callbacks=[_wetlab_record])
    conversation = Conversation(**conv_kwargs)'''%(sid,sid)
        injected=injected.replace('    import uuid\n','    import uuid\n'+textwrap.indent(JSON_HELPER,'    ')).replace('tmp.write_text(json.dumps(data))','tmp.write_text(_wetlab_json(data))')
        source=source.replace(needle,injected).replace('    conversation.run()','    conversation.run()\n    _wetlab_record(completed=True)')
        local=agent.logs_dir/'wetlab_openhands_runner.py';local.write_text(source)
        await environment.upload_file(local,'/installed-agent/run_agent.py')
    elif name in ('mini-swe-agent','aider','swe-agent','trae-agent','openhands'):
        if name=='swe-agent':
            await agent.exec_as_agent(environment,command='if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git init -q && git add -A && git -c user.name=Benchmark -c user.email=benchmark@localhost commit -q --allow-empty -m \"Task state before native SWE Agent\"; fi')
        source={'mini-swe-agent':MINI_HOOK,'aider':AIDER_HOOK,'swe-agent':SWE_HOOK,'trae-agent':TRAE_HOOK,'openhands':OPENHANDS_HOOK}[name].replace('__SESSION_ID__',repr(sid))
        source=JSON_HELPER+source.replace('write_text(json.dumps(','write_text(_wetlab_json(')
        triggers={'mini-swe-agent':'mini-swe-agent','aider':'aider','swe-agent':'sweagent.run.run','trae-agent':'trae-cli','openhands':'openhands.core.main'}
        trigger=triggers[name]
        source='import sys,os\nif os.path.basename(sys.argv[0])=='+repr(trigger)+' or '+repr(trigger)+' in getattr(sys,\"orig_argv\",[])[1:3]:\n    exec('+repr(source)+')\n'
        local=agent.logs_dir/('wetlab-'+name+'-sitecustomize.py');local.write_text(source)
        await environment.exec('mkdir -p /installed-agent/wetlab-hooks')
        await environment.upload_file(local,'/installed-agent/wetlab-hooks/sitecustomize.py')


MINI_HOOK=r'''# Imported by Python before mini-swe-agent's unmodified native CLI.
import copy,json,os,time,urllib.request
from pathlib import Path
from minisweagent.agents.default import DefaultAgent
_PATH=Path('/logs/agent/wetlab-sdk-session.json')
_SID=__SESSION_ID__
_previous=json.loads(_PATH.read_text()) if _PATH.exists() else None
class WetlabBoundary(BaseException):pass
_run=DefaultAgent.run
_add=DefaultAgent.add_messages
_execute=DefaultAgent.execute_actions
_save=DefaultAgent.save

def _boundary():
    req=urllib.request.Request(os.environ['WETLAB_URL'].rstrip('/')+'/v1/run',headers={'Authorization':'Bearer '+os.environ['WETLAB_TOKEN']})
    with urllib.request.urlopen(req,timeout=10) as response:data=json.load(response)
    return data.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in data.get('tickets',[]))

def _dump(self,completed=False):
    data={'format':'wetlab-sdk-native-v1','harness':'mini-swe-agent','session_id':_SID,
          'messages':copy.deepcopy(self.messages),'completed':completed,
          'native_agent':{'cost':self.cost,'n_calls':self.n_calls,'n_consecutive_format_errors':self.n_consecutive_format_errors,
                          'extra_template_vars':self.extra_template_vars}}
    tmp=_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(_PATH)

def add(self,*messages):
    if getattr(self,'_wetlab_restoring',False):
        self._wetlab_restoring=False
        self.messages=copy.deepcopy(_previous['messages'])
        old=_previous['native_agent']
        self.cost=old['cost'];self.n_calls=old['n_calls'];self.n_consecutive_format_errors=old['n_consecutive_format_errors']
        return _add(self,messages[-1])
    return _add(self,*messages)

def execute(self,message):
    value=_execute(self,message)
    if _boundary():
        _dump(self,True)
        raise WetlabBoundary()
    return value

def save(self,path,*extras):
    data=_save(self,path,*extras)
    # Native configuration serializes the live API key. Persist only its env
    # reference: the next native process receives credentials independently.
    if path and isinstance(data,dict):
        model=data.get('info',{}).get('config',{}).get('model',{})
        kw=model.get('model_kwargs',{})
        if 'api_key' in kw:kw['api_key']='<runtime-environment>'
        path.write_text(json.dumps(data,indent=2))
    if not getattr(self,'_wetlab_boundary',False):_dump(self,False)
    return data

def run(self,task='',**kwargs):
    self._wetlab_restoring=bool(_previous)
    self._wetlab_boundary=False
    if _previous:self.extra_template_vars=copy.deepcopy(_previous['native_agent']['extra_template_vars'])
    try:
        value=_run(self,task,**kwargs)
        _dump(self,True)
        return value
    except WetlabBoundary:
        _dump(self,True)
        return {'exit_status':'WetlabSuspended','submission':''}
DefaultAgent.add_messages=add
DefaultAgent.execute_actions=execute
# InteractiveAgent overrides execute_actions, so wrap its actual native method.
from minisweagent.agents.interactive import InteractiveAgent
_i_execute=InteractiveAgent.execute_actions

def interactive_execute(self,message):
    value=_i_execute(self,message)
    if _boundary():
        self._wetlab_boundary=True
        _dump(self,True)
        raise WetlabBoundary()
    return value
InteractiveAgent.execute_actions=interactive_execute
DefaultAgent.save=save
DefaultAgent.run=run
'''


AIDER_HOOK=r'''# Native Aider Coder buffers, not its lossy Markdown chat importer.
import base64,copy,json,shlex
from pathlib import Path
from aider.coders.base_coder import Coder
_PATH=Path('/logs/agent/wetlab-sdk-session.json')
_SID=__SESSION_ID__
_previous=json.loads(_PATH.read_text()) if _PATH.exists() else None
_run=Coder.run
_handle=Coder.handle_shell_commands
def shell(self,commands_str,group):
    # Aider's native --yes deliberately declines explicit shell confirmations.
    # This benchmark has already authorized sandbox execution. Feed the whole
    # shell block to its native runner as one command (preserves heredocs).
    ask=self.io.confirm_ask
    def confirm(question,*args,**kwargs):
        if question in ('Run shell command?','Run shell commands?') and self.io.yes is True:return True
        return ask(question,*args,**kwargs)
    self.io.confirm_ask=confirm
    encoded=base64.b64encode(commands_str.encode()).decode()
    command='bash -lc \"$(printf %s '+shlex.quote(encoded)+' | base64 -d)\"'
    try:return _handle(self,command,group)
    finally:self.io.confirm_ask=ask
Coder.handle_shell_commands=shell
def run(self,with_message=None,preproc=True):
    if _previous and not getattr(self,'_wetlab_loaded',False):
        self._wetlab_loaded=True
        native=_previous['native_coder']
        self.done_messages=copy.deepcopy(native['done_messages'])
        self.cur_messages=copy.deepcopy(native['cur_messages'])
        self.abs_fnames=set(native['abs_fnames'])
        self.abs_read_only_fnames=set(native['abs_read_only_fnames'])
    if with_message:
        with_message+='\nHarness execution format: put terminal commands in fenced bash blocks so Aider executes them. Execute requested commands; do not merely describe them. Do not include a wait_for_result in the same bash block as a later command.'
    try:return _run(self,with_message=with_message,preproc=preproc)
    finally:
        native={'done_messages':self.done_messages,'cur_messages':self.cur_messages,
                'abs_fnames':sorted(self.abs_fnames),'abs_read_only_fnames':sorted(self.abs_read_only_fnames)}
        data={'format':'wetlab-sdk-native-v1','harness':'aider','session_id':_SID,
              'messages':self.done_messages+self.cur_messages,'native_coder':native,'completed':True}
        tmp=_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(_PATH)
Coder.run=run
'''


SWE_HOOK=r'''import copy,json,os,urllib.request
from pathlib import Path
from sweagent.agent.agents import DefaultAgent
from sweagent.environment.swe_env import SWEEnv
import shlex
# Preserve native cwd/ROOT setup while keeping every restored research file.
def keep_repository(self):
    if self.repo is not None:self.communicate(input='cd '+shlex.quote('/'+self.repo.repo_name.lstrip('/'))+' && export ROOT=$(pwd -P)',check='raise')
SWEEnv._reset_repository=keep_repository
_PATH=Path('/logs/agent/wetlab-sdk-session.json')
_SID=__SESSION_ID__
_previous=json.loads(_PATH.read_text()) if _PATH.exists() else None
_setup=DefaultAgent.setup
_step=DefaultAgent.step
_save=DefaultAgent.save_trajectory
_get=DefaultAgent.get_trajectory_data
def trajectory(self):return json.loads(_wetlab_json(_get(self)))
DefaultAgent.get_trajectory_data=trajectory
def _boundary():
    req=urllib.request.Request(os.environ['WETLAB_URL'].rstrip('/')+'/v1/run',headers={'Authorization':'Bearer '+os.environ['WETLAB_TOKEN']})
    with urllib.request.urlopen(req,timeout=10) as response:data=json.load(response)
    return data.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in data.get('tickets',[]))
def setup(self,env,problem_statement,output_dir=Path('.')):
    value=_setup(self,env,problem_statement,output_dir)
    if _previous:
        native=_previous['native_agent']
        self.history=copy.deepcopy(_previous['messages'])
        self._trajectory=copy.deepcopy(native['trajectory'])
        self.info.update(copy.deepcopy(native['info']))
        self.model.stats=type(self.model.stats).model_validate(native['model_stats'])
        self._append_history({'role':'user','content':problem_statement.get_problem_statement(),'agent':self.name,'message_type':'wetlab_feedback'})
    return value
def step(self):
    value=_step(self)
    completed=_boundary()
    data={'format':'wetlab-sdk-native-v1','harness':'swe-agent','session_id':_SID,
          'messages':self.history,'completed':completed,
          'native_agent':{'trajectory':self.trajectory,'info':dict(self.info),'model_stats':self.model.stats.model_dump()}}
    tmp=_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(_PATH)
    if completed:
        value.done=True
        _save(self)
    return value
DefaultAgent.setup=setup
DefaultAgent.step=step
'''

TRAE_HOOK=r'''import copy,json,os,urllib.request
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from trae_agent.agent.base_agent import BaseAgent
from trae_agent.agent.agent_basics import AgentState
from trae_agent.utils.llm_clients import openai_client as _openai_module
from trae_agent.utils.llm_clients.openai_compatible_base import OpenAICompatibleClient,ProviderConfig
import openai
class NativeEndpoint(ProviderConfig):
    def create_client(self,api_key,base_url,api_version):return openai.OpenAI(api_key=api_key,base_url=base_url)
    def get_service_name(self):return 'Configured OpenAI-compatible endpoint'
    def get_provider_name(self):return 'openai'
    def get_extra_headers(self):return {}
    def supports_tool_calling(self,model_name):return True
class OpenAIClient(OpenAICompatibleClient):
    # Use Trae's existing native Chat Completions engine. Tencent accepts its
    # full tool history; the Responses FC history was rejected with HTTP 400.
    def __init__(self,model_config):
        model_config.parallel_tool_calls=False
        super().__init__(model_config,NativeEndpoint())
_openai_module.OpenAIClient=OpenAIClient
from trae_agent.utils.llm_clients.llm_basics import LLMMessage
from trae_agent.tools.base import ToolCall,ToolResult
_PATH=Path('/logs/agent/wetlab-sdk-session.json')
_SID=__SESSION_ID__
_previous=json.loads(_PATH.read_text()) if _PATH.exists() else None
_init=OpenAIClient.__init__
_execute=BaseAgent.execute_task
_finalize=BaseAgent._finalize_step
def init(self,config):
    _init(self,config)
    if _previous:self.message_history=copy.deepcopy(_previous['native_client_history'])
async def execute(self):
    if _previous:
        pending=[]
        for raw in _previous['pending_messages']:
            raw=copy.deepcopy(raw)
            if raw.get('tool_call'):raw['tool_call']=ToolCall(**raw['tool_call'])
            if raw.get('tool_result'):raw['tool_result']=ToolResult(**raw['tool_result'])
            pending.append(LLMMessage(**raw))
        fresh=[m for m in self._initial_messages if m.role!='system']
        self._initial_messages=pending+fresh
    return await _execute(self)
async def finalize(self,step,messages,execution):
    value=await _finalize(self,step,messages,execution)
    req=urllib.request.Request(os.environ['WETLAB_URL'].rstrip('/')+'/v1/run',headers={'Authorization':'Bearer '+os.environ['WETLAB_TOKEN']})
    with urllib.request.urlopen(req,timeout=10) as response:data=json.load(response)
    completed=bool(data.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in data.get('tickets',[])))
    native=self._llm_client.client.message_history
    pending=[asdict(m) for m in messages]
    all_messages=native+self._llm_client.client.parse_messages(messages)
    snapshot={'format':'wetlab-sdk-native-v1','harness':'trae-agent','session_id':_SID,
              'messages':all_messages,'completed':completed,'native_client_history':native,
              'pending_messages':pending,'execution':asdict(execution)}
    tmp=_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(snapshot,default=lambda x:x.value if isinstance(x,Enum) else str(x)));tmp.replace(_PATH)
    if completed:execution.agent_state=AgentState.COMPLETED
    return value
OpenAIClient.__init__=init
BaseAgent.execute_task=execute
BaseAgent._finalize_step=finalize
'''


OPENHANDS_HOOK=r'''# Legacy OpenHands 0.62 native event stream and State restore.
import json,os,urllib.request
from pathlib import Path
from openhands.core import setup
from openhands.controller.agent_controller import AgentController
from openhands.core.schema.agent import AgentState
from openhands.events.serialization.event import event_to_dict
_SID=__SESSION_ID__.replace('-','')
_PATH=Path('/logs/agent/wetlab-sdk-session.json')
setup.generate_sid=lambda *args,**kwargs:_SID
_step=AgentController._step

def _boundary():
    req=urllib.request.Request(os.environ['WETLAB_URL'].rstrip('/')+'/v1/run',headers={'Authorization':'Bearer '+os.environ['WETLAB_TOKEN']})
    with urllib.request.urlopen(req,timeout=10) as response:data=json.load(response)
    return data.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in data.get('tickets',[]))

def _save(self,completed):
    events=[event_to_dict(e) for e in self.event_stream.search_events()]
    data={'format':'wetlab-sdk-native-v1','harness':'openhands','session_id':_SID,'messages':events,'completed':completed}
    tmp=_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(_PATH)

async def step(self):
    if _boundary() and not self._pending_action:
        await self.set_agent_state_to(AgentState.PAUSED)
        self.state.save_to_session(self.event_stream.sid,self.event_stream.file_store,self.event_stream.user_id)
        _save(self,True)
        return
    return await _step(self)
AgentController._step=step
'''
