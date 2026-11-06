"""NeMo Agent Toolkit native ReAct workflow, tool, and SQLite graph recovery.

This uses NAT's registered react_agent and its ReActGraphState unchanged. Only a
research shell function and native LangGraph persistence/interrupts are added.
"""
from __future__ import annotations
import json,sqlite3,uuid,shlex
from pathlib import Path
try:from .sdk_extra import JSON_HELPER
except ImportError:from sdk_extra import JSON_HELPER

NAMES={'nemo-agent'}
FILE='wetlab-nat-session.json'


def latest(trial,agent):
    path=trial/'agent'/FILE
    return path if path.is_file() else None


def history(path,agent):
    data=json.loads(path.read_text())
    if data.get('format')!='wetlab-nat-native-v1' or data.get('harness')!=agent or not data.get('session_id'):
        raise ValueError('invalid NAT native identity')
    state=data.get('native_state',{})
    records={}
    for field in ('messages','agent_scratchpad','tool_responses'):
        if not isinstance(state.get(field),list):raise ValueError('missing NAT native state channel: '+field)
        for i,record in enumerate(state[field]):
            if not isinstance(record,dict):raise ValueError('invalid NAT native state record')
            records[field+':'+str(i)]=record
    if not records:raise ValueError('empty NAT native history')
    return data['session_id'],records


def validate(path,agent):
    sid,_=history(path,agent);data=json.loads(path.read_text())
    if not data.get('completed'):raise ValueError('NAT workflow has no safe native boundary')
    db=path.parent/'nat-checkpoints.sqlite'
    if not db.is_file():raise ValueError('NAT native SQLite checkpoint missing')
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('invalid NAT checkpoint database')
        if not conn.execute('SELECT 1 FROM checkpoints WHERE thread_id=? AND checkpoint_id=?',(sid,data.get('checkpoint_id'))).fetchone():
            raise ValueError('NAT checkpoint identity missing from native database')


def bundle(path,agent):return path.parent


def install(state,saved=None):
    if state['agent']!='nemo-agent':return
    from harbor.agents.installed.nemo_agent import NemoAgent
    import yaml
    NemoAgent._CONTAINER_CONFIG_PATH='/installed-agent/nemo-agent-config.yml'
    def command(self,instruction):
        return '/opt/nvidia-nat-venv/bin/python '+shlex.quote(self._CONTAINER_WRAPPER_PATH)+' '+shlex.quote(self._CONTAINER_CONFIG_PATH)+' '+shlex.quote(instruction)+' --trajectory-output /logs/agent/trajectory.json 2>&1 | tee /logs/agent/nemo-agent-output.txt'
    NemoAgent._build_run_command=command
    generate=NemoAgent._generate_config_yaml
    def configuration(self,model_name,api_key):
        config=yaml.safe_load(generate(self,model_name,api_key))
        # NAT's OpenAI plugin reads OPENAI_API_KEY directly at runtime.
        for value in config['llms'].values():value.pop('api_key',None)
        llm_name=next(iter(config['llms']))
        config['functions']={'wetlab_shell':{'_type':'wetlab_research_shell'}}
        config['workflow']={'_type':'react_agent','llm_name':llm_name,'tool_names':['wetlab_shell'],
            'use_native_tool_calling':True,'max_tool_calls':100,'max_history':100000,
            'additional_instructions':'Use the provided shell tool for real task execution. Persist research artifacts in files. After a successful wait_for_result or finish, stop immediately. Never poll waiting for experiments.'}
        return yaml.safe_dump(config,sort_keys=False)
    NemoAgent._generate_config_yaml=configuration
    original=NemoAgent.exec_as_agent
    async def execute(self,environment,command,**kwargs):
        if 'uv pip install --python /opt/nvidia-nat-venv/bin/python' in command:
            for old in ("'nvidia-nat[eval,langchain]>=1.5'","'nvidia-nat[eval,langchain]==1.9.0'"):
                command=command.replace(old,"'nvidia-nat==1.9.0' 'nvidia-nat-langchain[openai]==1.9.0' 'nvidia-nat-eval==1.9.0'")
            command+=' langgraph-checkpoint-sqlite'
        return await original(self,environment,command=command,**kwargs)
    NemoAgent.exec_as_agent=execute


async def prepare(agent,environment,state,saved=None):
    if state['agent']!='nemo-agent':return
    result=await environment.exec(agent.get_version_command())
    actual=agent.parse_version(result.stdout).strip() if result.return_code==0 and result.stdout else None
    if actual!='1.9.0':raise ValueError('NAT native recovery requires verified installed version 1.9.0 before model execution')
    agent._version=actual
    if agent.options.config_file:
        raise ValueError('NAT native recovery currently requires the registered react_agent default workflow')
    from harbor.agents.installed import nemo_agent
    sid=history(Path(saved['session_path']),'nemo-agent')[0] if saved else str(uuid.uuid5(uuid.NAMESPACE_URL,'wetlab:'+state['run_id']))
    runtime=JSON_HELPER+NAT_RUNTIME.replace('__SESSION_ID__',repr(sid))
    local=agent.logs_dir/'wetlab_nat_runtime.py';local.write_text(runtime)
    await environment.upload_file(local,'/installed-agent/wetlab_nat_runtime.py')
    wrapper=(Path(nemo_agent.__file__).parent/'nemo_agent_run_wrapper.py').read_text()
    needle='import traceback\n'
    if wrapper.count(needle)!=1:raise ValueError('NAT Harbor wrapper changed')
    wrapper=wrapper.replace(needle,needle+'import wetlab_nat_runtime\n')
    wrapper=wrapper.replace('        await session_manager.shutdown()', '        await session_manager.shutdown()\n        await wetlab_nat_runtime.close()')
    local=agent.logs_dir/'wetlab_nat_runner.py';local.write_text(wrapper)
    await environment.upload_file(local,'/installed-agent/nemo_agent_run_wrapper.py')


NAT_RUNTIME=r'''import asyncio,copy,json,os,urllib.request
from pathlib import Path
import aiosqlite
from langchain_core.load import dumpd
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.types import Command,interrupt
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from nat.plugins.langchain.agent.base import AgentDecision
from nat.plugins.langchain.agent.dual_node import DualNodeAgent
from nat.plugins.langchain.agent.react_agent.agent import ReActAgentGraph

_SID=__SESSION_ID__
_PATH=Path('/logs/agent/wetlab-nat-session.json')
_DB='/logs/agent/nat-checkpoints.sqlite'
_connections=[]

def _boundary():
    request=urllib.request.Request(os.environ['WETLAB_URL'].rstrip('/')+'/v1/run',headers={'Authorization':'Bearer '+os.environ['WETLAB_TOKEN']})
    with urllib.request.urlopen(request,timeout=10) as response:data=json.load(response)
    return bool(data.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in data.get('tickets',[])))

def _redact_text(text):
    for key,value in os.environ.items():
        if len(value)>=8 and (key.endswith('_API_KEY') or key in ('WETLAB_TOKEN','ANTHROPIC_AUTH_TOKEN','HF_TOKEN',os.environ.get('WETLAB_MODEL_KEY_ENV',''))):text=text.replace(value,'<redacted>')
    return text

class ShellConfig(FunctionBaseConfig,name='wetlab_research_shell'):
    pass

@register_function(config_type=ShellConfig)
async def shell_function(config,builder):
    async def shell(command:str)->str:
        """Execute a bash command in the task container. Files persist; each call starts a fresh shell."""
        proc=await asyncio.create_subprocess_exec('bash','-lc',command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        try:output,_=await asyncio.wait_for(proc.communicate(),timeout=120)
        except asyncio.TimeoutError:
            proc.kill();output,_=await proc.communicate()
            return _redact_text('Command timed out.\n'+output.decode(errors='replace'))
        return _redact_text('exit_code='+str(proc.returncode)+'\n'+output.decode(errors='replace'))
    yield FunctionInfo.create(single_fn=shell,description='Execute shell commands and scripts inside the research task container.')

_native_agent=ReActAgentGraph.agent_node
async def agent_node(self,state,config=None):
    # Interrupt exactly after the preceding tool result is already durable.
    # On continuation, consume the native interrupt's resume value once.
    if getattr(self,'_wetlab_resuming',False) or _boundary():
        feedback=interrupt({'reason':'wetlab_native_turn_boundary'})
        self._wetlab_resuming=False
        state.messages.append(HumanMessage(content=str(feedback)))
    return await _native_agent(self,state,config)
ReActAgentGraph.agent_node=agent_node

class NativeGraph:
    def __init__(self,graph,owner):self.graph=graph;self.owner=owner
    def __getattr__(self,name):return getattr(self.graph,name)
    async def ainvoke(self,initial,config=None,**kwargs):
        config=copy.deepcopy(config or {})
        config.setdefault('configurable',{})['thread_id']=_SID
        previous=await self.graph.aget_state(config)
        if previous.next:
            self.owner._wetlab_resuming=True
            initial=Command(resume=str(initial.messages[-1].content))
        elif previous.values:
            raise ValueError('NAT graph already ended; cannot replace a completed conversation with a fresh one')
        result=await self.graph.ainvoke(initial,config=config,**kwargs)
        snapshot=await self.graph.aget_state(config)
        data={'format':'wetlab-nat-native-v1','harness':'nemo-agent','session_id':_SID,
              'checkpoint_id':snapshot.config['configurable']['checkpoint_id'],
              'native_state':dumpd(snapshot.values),'next':list(snapshot.next),'completed':_boundary()}
        temp=_PATH.with_suffix('.tmp');temp.write_text(_wetlab_json(data));temp.replace(_PATH)
        return result

_native_build=DualNodeAgent._build_graph
async def build(self,state_schema):
    if not isinstance(self,ReActAgentGraph):return await _native_build(self,state_schema)
    connection=await aiosqlite.connect(_DB);_connections.append(connection)
    saver=AsyncSqliteSaver(connection)
    # NAT's own dual-node graph, with a native durable checkpointer attached.
    graph=StateGraph(state_schema)
    graph.add_node('agent',self.agent_node)
    graph.add_node('tool',self.tool_node)
    graph.add_edge('tool','agent')
    graph.add_conditional_edges('agent',self.conditional_edge,{AgentDecision.TOOL:'tool',AgentDecision.END:'__end__'})
    graph.set_entry_point('agent')
    self.graph=NativeGraph(graph.compile(checkpointer=saver),self)
    return self.graph
DualNodeAgent._build_graph=build

async def close():
    for connection in _connections:
        await connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        await connection.close()
    _connections.clear()
'''
