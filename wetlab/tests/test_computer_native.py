import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from harbor.agents.computer_1.computer_1 import Computer1Chat
from harbor.models.trajectories import Step,Observation,ObservationResult
from wetlab import computer_native as C


def native_agent():
    chat=Computer1Chat(object());chat._messages=[{'role':'user','content':'original nonce'}, {'role':'assistant','content':'{"action":{"type":"bash","command":"wetlab submit"}}'}]
    chat._cumulative_input_tokens=100;chat._cumulative_output_tokens=20;chat._cumulative_cache_tokens=50;chat._cumulative_cost=.01
    step=Step(step_id=1,source='agent',message='native bash action',observation=Observation(results=[ObservationResult(content='native stdout: experiment #1 pending')]))
    return SimpleNamespace(_chat=chat,_session_id='native-original',_recorder=SimpleNamespace(steps=[step]),_compactor=SimpleNamespace(compaction_count=2),_pending_completion=False,_wait_streak_count=0,_n_episodes=1,_api_request_times=[23.0],_wetlab_pending_prompt=[{'role':'user','content':[{'type':'text','text':'native stdout: experiment #1 pending'}]}],_wetlab_suspended=True,_early_termination_reason='wetlab_checkpoint')


def test_computer_native_round_trip_preserves_chat_counters_and_pending_observation(tmp_path):
    agent=native_agent();state=C._snapshot(agent);path=tmp_path/'computer-native.json';path.write_text(json.dumps(state))
    C.validate(path,'computer-1');sid,history=C.history(path,'computer-1')
    assert sid=='native-original' and history['0']['content']=='original nonce'
    restored=SimpleNamespace(_chat=Computer1Chat(object()));model=restored._chat._model
    C._restore_chat(restored,state)
    assert restored._chat.__dict__=={**agent._chat.__dict__,'_model':model}
    assert C._observation_text(agent._recorder.steps[-1])=='native stdout: experiment #1 pending'
    assert state['pending_prompt']==agent._wetlab_pending_prompt
    assert state['compaction_count']==2 and state['agent_flags']['_api_request_times']==[23.0]


def test_computer_native_copy_is_independent_of_running_chat():
    agent=native_agent();state=C._snapshot(agent);agent._chat._messages[0]['content']='changed'
    assert state['chat']['_messages'][0]['content']=='original nonce'


@pytest.mark.parametrize('change,match',[
    ({'mode':{'provider':'openai','enable_images':True,'extra_tools':['bash']}},'text'),
    ({'pending_prompt':[]},'observation'),
    ({'completed_action':False},'completed'),
    ({'recorder_steps':[]},'receipt'),
])
def test_computer_native_rejects_unproven_boundary_or_flavor(tmp_path,change,match):
    state=C._snapshot(native_agent());state.update(change);p=tmp_path/'computer-native.json';p.write_text(json.dumps(state))
    with pytest.raises(ValueError,match=match):C.validate(p,'computer-1')


def test_computer_fixture_adds_real_runtime_dependencies(tmp_path):
    from wetlab.tests.computer_fixture import configure
    folder=tmp_path/'environment';folder.mkdir();(folder/'Dockerfile').write_text('FROM python:3.12-slim-bookworm\n')
    configure(tmp_path);text=(folder/'Dockerfile').read_text()
    for package in ('xvfb','xfce4-session','chromium','xdotool','imagemagick','wmctrl'):assert package in text
    assert 'DEBIAN_FRONTEND=noninteractive' in text

def test_native_action_environment_forwards_only_configured_env_without_mutation():
    import asyncio
    calls=[]
    class Environment:
        default_user='agent'
        async def exec(self,*args,**kwargs):calls.append((args,kwargs));return 'native result'
    env=Environment();extra={'WETLAB_URL':'http://test','WETLAB_TOKEN':'round-token'}
    proxy=C._ActionEnvironment(env,extra)
    supplied={'EXPERIMENT_SEED':'42'}
    assert asyncio.run(proxy.exec(command='wetlab status',env=supplied,cwd='/app'))=='native result'
    assert calls[0][1]['env']=={**extra,'EXPERIMENT_SEED':'42'}
    assert extra=={'WETLAB_URL':'http://test','WETLAB_TOKEN':'round-token'} and supplied=={'EXPERIMENT_SEED':'42'}
    assert proxy.default_user=='agent'
