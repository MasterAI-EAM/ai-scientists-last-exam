"""Native Computer1Chat recovery for Harbor's explicit text + bash flavor.

The real desktop runtime and generic JSON harness still execute. DeepSeek is
not a vision model: screenshots are not sent to the model, and browser RAM is
outside the filesystem checkpoint contract.
"""
from __future__ import annotations
import copy,json,os,urllib.request
from importlib.metadata import version
from pathlib import Path

try:
    from .support import atomic_json
except ImportError:
    from support import atomic_json

NAMES={'computer-1'}
FORMAT='wetlab-computer1-native-v1'
FLAGS=('_pending_completion','_wait_streak_count','_n_episodes','_api_request_times')


def latest(trial,agent):
    path=trial/'agent'/'computer-native.json'
    return path if path.is_file() else None


def _load(path):
    data=json.loads(path.read_text())
    if data.get('format')!=FORMAT or data.get('harness')!='computer-1' or not data.get('session_id'):
        raise ValueError('invalid Computer1 native state identity')
    if data.get('mode')!={'provider':'litellm','enable_images':False,'extra_tools':['bash']}:
        raise ValueError('Computer1 recovery requires the explicit text + bash flavor')
    messages=data.get('chat',{}).get('_messages')
    if not isinstance(messages,list) or not messages:raise ValueError('empty Computer1 native model history')
    for message in messages:
        if not isinstance(message,dict) or message.get('role') not in ('user','assistant','system','tool'):
            raise ValueError('invalid Computer1 native message')
        if isinstance(message.get('content'),list) and any(p.get('type')=='image_url' for p in message['content'] if isinstance(p,dict)):
            raise ValueError('vision state is outside this Computer1 recovery flavor')
    return data


def history(path,agent):
    data=_load(path)
    return data['session_id'],{str(i):message for i,message in enumerate(data['chat']['_messages'])}


def validate(path,agent):
    data=_load(path)
    if not data.get('completed_action') or data['chat']['_messages'][-1].get('role')!='assistant':
        raise ValueError('Computer1 native action has not completed')
    if not isinstance(data.get('recorder_steps'),list) or not data['recorder_steps']:
        raise ValueError('Computer1 native action receipt is missing')
    if data.get('suspended') and not data.get('pending_prompt'):
        raise ValueError('Computer1 completed action observation is missing')
    for key in ('_cumulative_input_tokens','_cumulative_output_tokens','_cumulative_cache_tokens','_cumulative_cost'):
        value=data['chat'].get(key)
        if not isinstance(value,(int,float)) or value<0:raise ValueError('invalid Computer1 native usage state')


def bundle(path,agent):return path.parent


def _observation_text(step):
    observation=step.observation
    if observation is None:return ''
    parts=[]
    for result in observation.results:
        content=result.content
        if isinstance(content,str):parts.append(content)
        elif isinstance(content,list):parts.extend(p.text for p in content if p.type=='text' and p.text)
    return '\n'.join(parts)


def _snapshot(agent):
    return {
        'format':FORMAT,'harness':'computer-1','session_id':agent._session_id,
        'mode':{'provider':'litellm','enable_images':False,'extra_tools':['bash']},
        'chat':{k:copy.deepcopy(v) for k,v in agent._chat.__dict__.items() if k!='_model'},
        'agent_flags':{key:copy.deepcopy(getattr(agent,key)) for key in FLAGS},
        'compaction_count':agent._compactor.compaction_count,
        'recorder_steps':[step.model_dump(mode='json') for step in agent._recorder.steps],
        'pending_prompt':copy.deepcopy(getattr(agent,'_wetlab_pending_prompt',None)),
        'suspended':bool(agent._wetlab_suspended),
        'completed_action':bool(agent._wetlab_suspended or agent._early_termination_reason=='task_complete'),
    }


def _restore_chat(agent,data):
    model=agent._chat._model
    agent._chat.__dict__.update(copy.deepcopy(data['chat']))
    agent._chat._model=model
    if agent._chat.messages!=data['chat']['_messages']:raise ValueError('Computer1 native chat restoration failed')


class _ActionEnvironment:
    """Forward the configured per-agent environment to native bash actions."""
    def __init__(self,environment,extra):self.environment=environment;self.extra=dict(extra)
    def __getattr__(self,name):return getattr(self.environment,name)
    async def exec(self,*args,**kwargs):
        kwargs['env']={**self.extra,**(kwargs.get('env') or {})}
        return await self.environment.exec(*args,**kwargs)


def install(state,saved=None):
    if state['agent']!='computer-1':return
    from harbor.agents.computer_1.computer_1 import Computer1,Computer1Recorder
    from harbor.agents.computer_1.providers.generic import GenericJsonProvider
    from harbor.agents.computer_1.runtime import Computer1Session
    from harbor.models.trajectories import Step
    restored=_load(Path(saved['session_path'])) if saved else None
    original_init=Computer1.__init__;original_run=Computer1.run;original_loop=Computer1._run_loop
    original_setup=Computer1.setup
    original_bash=Computer1Session._execute_bash
    original_publish=Computer1Recorder.publish_snapshot
    original_fallback=Computer1._maybe_write_final_answer_fallback
    original_initial=GenericJsonProvider.initial_messages
    Computer1.version=lambda self:'harbor-'+version('harbor')
    class NativeBoundaryReached(Exception):pass

    async def bash(self,action):
        # Harbor 0.25 records extra_env but its native bash dispatch omits it.
        # Scope the missing forwarding to the original native action only.
        environment=self.environment
        self.environment=_ActionEnvironment(environment,self._extra_env)
        try:return await original_bash(self,action)
        finally:self.environment=environment
    Computer1Session._execute_bash=bash

    def initialize(self,*args,**kwargs):
        kwargs.setdefault('provider','litellm');kwargs.setdefault('enable_images',False);kwargs.setdefault('extra_tools',['bash'])
        if kwargs['provider']!='litellm' or kwargs['enable_images'] is not False or kwargs['extra_tools']!=['bash']:
            raise ValueError('Computer1 recovery is currently tested only with provider=litellm, enable_images=false, extra_tools=[bash]')
        kwargs.setdefault('env_io_dir','/logs/agent/computer-1-r'+str(state.get('round',1)))
        original_init(self,*args,**kwargs)
        self._recorder._viewer_base_dirs=('/logs/agent',)
    Computer1.__init__=initialize

    async def setup(self,environment):
        if restored:
            # PID memory is deliberately not restored; clear only the native
            # desktop's stale process locks before genuine runtime startup.
            await environment.exec('if ! pgrep -x Xvfb >/dev/null; then rm -f /tmp/.X1-lock /tmp/.X11-unix/X1; fi; if ! pgrep -x chromium >/dev/null; then rm -f /tmp/computer_1_runtime/profile/SingletonLock /tmp/computer_1_runtime/profile/SingletonSocket /tmp/computer_1_runtime/profile/SingletonCookie; fi')
        return await original_setup(self,environment)
    Computer1.setup=setup

    initial_used=False
    def initial(self,instruction,screenshot_ref):
        nonlocal initial_used
        messages=original_initial(self,instruction,screenshot_ref)
        if restored and not initial_used:
            initial_used=True
            return copy.deepcopy(restored.get('pending_prompt') or [])+messages
        return messages
    GenericJsonProvider.initial_messages=initial

    def publish(self,chat,reason):
        original_publish(self,chat,reason)
        owner=getattr(self,'_wetlab_owner',None)
        if not owner or owner._wetlab_suspended or not self.steps or not self.steps[-1].tool_calls:return
        if not state.get('gateway_url'):return
        request=urllib.request.Request(state['gateway_url']+'/admin/runs/'+state['run_id'],headers={'Authorization':'Bearer '+os.environ['WETLAB_ADMIN_TOKEN']})
        with urllib.request.urlopen(request,timeout=10) as response:run=json.load(response)
        if run.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in run.get('tickets',[])):
            observation=_observation_text(self.steps[-1])
            if not observation:raise ValueError('Computer1 completed action has no native observation')
            owner._wetlab_pending_prompt=owner._provider.follow_up_messages(None,observation,'')
            owner._wetlab_suspended=True
            owner._early_termination_reason='wetlab_checkpoint'
            raise NativeBoundaryReached()
    Computer1Recorder.publish_snapshot=publish

    async def fallback(self,instruction):
        if getattr(self,'_wetlab_suspended',False):return
        return await original_fallback(self,instruction)
    Computer1._maybe_write_final_answer_fallback=fallback

    async def loop(self,*args,**kwargs):
        if restored:_restore_chat(self,restored)
        return await original_loop(self,*args,**kwargs)
    Computer1._run_loop=loop

    async def run(self,instruction,environment,context):
        self._wetlab_suspended=False;self._wetlab_pending_prompt=None
        self._recorder._wetlab_owner=self
        if restored:
            self._session_id=restored['session_id'];self._recorder._session_id=self._session_id
            self._recorder._steps=[Step.model_validate(item) for item in restored['recorder_steps']]
            for key,value in restored['agent_flags'].items():
                if key not in FLAGS:raise ValueError('unknown Computer1 native state field')
                setattr(self,key,copy.deepcopy(value))
            self._compactor.compaction_count=restored['compaction_count']
        try:await original_run(self,instruction,environment,context)
        except NativeBoundaryReached:pass
        if self._chat is None:raise ValueError('Computer1 text provider did not create native chat')
        atomic_json(self.logs_dir/'computer-native.json',_snapshot(self))
    Computer1.run=run


async def prepare(agent,environment,state,saved=None):
    # The genuine Computer1.setup owns Xvfb/XFCE/Chromium start and readiness.
    # No screenshots, desktop actions, or liveness checks are simulated here.
    return None
