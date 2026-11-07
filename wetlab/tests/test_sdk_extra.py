"""Native SDK boundaries must reject truncated sessions and rewritten history."""
import json
from pathlib import Path
import pytest
from wetlab import sdk_extra as S
from wetlab.sessions import assert_continuation


def snapshot(tmp_path,name,messages,**fields):
    path=tmp_path/name;path.mkdir()
    target=path/S.FILE
    target.write_text(json.dumps({'format':'wetlab-sdk-native-v1','harness':'mini-swe-agent',
        'session_id':'same-native-id','messages':messages,'completed':True,**fields}))
    return target


def test_native_prefix_is_preserved_and_new_feedback_is_required(tmp_path):
    initial=[{'role':'system','content':'native system'}, {'role':'assistant','tool_calls':[{'id':'a','function':{'name':'bash','arguments':'pwd'}}]}, {'role':'tool','tool_call_id':'a','content':'/app'}]
    old=snapshot(tmp_path,'old',initial)
    new=snapshot(tmp_path,'new',initial+[{'role':'user','content':'lab result: 2'}])
    S.validate(old,'mini-swe-agent')
    assert_continuation(old,new,'mini-swe-agent')
    mutated=json.loads(new.read_text());mutated['messages'][1]['tool_calls'][0]['function']['arguments']='changed'
    new.write_text(json.dumps(mutated))
    with pytest.raises(ValueError,match='previous context changed'):assert_continuation(old,new,'mini-swe-agent')


def test_partial_or_missing_native_state_fails_closed(tmp_path):
    path=snapshot(tmp_path,'partial',[{'role':'user','content':'task'}],completed=False)
    with pytest.raises(ValueError,match='complete turn boundary'):S.validate(path,'mini-swe-agent')
    data=json.loads(path.read_text());data.update(harness='openhands-sdk',completed=True)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='base state missing'):S.validate(path,'openhands-sdk')


def test_injected_sources_compile_without_importing_native_packages():
    for name in ('MINI_HOOK','AIDER_HOOK','SWE_HOOK','TRAE_HOOK','OPENHANDS_HOOK'):
        compile(getattr(S,name).replace('__SESSION_ID__',repr('native-id')),name,'exec')


def test_exhausted_experiment_budget_keeps_final_reasoning_turn_open(monkeypatch):
    """A closed submission slot is not a pending experiment after final feedback."""
    import ast,io,os,urllib.request
    import types
    state={'finished':False,'submission_open':False,'budget':2,'used':2,
        'tickets':[{'seq':1,'status':'done','delivered_at':'earlier'},
                   {'seq':2,'status':'done','delivered_at':'now'}]}
    monkeypatch.setenv('WETLAB_URL','http://not-used.invalid')
    monkeypatch.setenv('WETLAB_TOKEN','test-token')
    monkeypatch.setattr(urllib.request,'urlopen',lambda *args,**kwargs:io.StringIO(json.dumps(state)))
    for source in (S.MINI_HOOK,S.SWE_HOOK,S.OPENHANDS_HOOK):
        tree=ast.parse(source.replace('__SESSION_ID__',repr('test-id')))
        fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_boundary')
        namespace={'os':os,'json':json,'urllib':urllib}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'native-boundary','exec'),namespace)
        assert not namespace['_boundary']()
        state['tickets'][1]['delivered_at']=None
        assert namespace['_boundary']()
        state['tickets'][1]['delivered_at']='now'
        state['finished']=True
        assert namespace['_boundary']()
        state['finished']=False


def test_native_nested_history_uses_identical_secret_placeholder(monkeypatch):
    import os
    secret='native-provider-key-for-unit-test'
    token='native-run-token-for-unit-test'
    monkeypatch.setenv('PRIVATE_API_KEY',secret)
    monkeypatch.setenv('WETLAB_TOKEN',token)
    ns={'json':json,'os':os}
    exec(S.JSON_HELPER,ns)
    message={'role':'tool','content':'WETLAB_TOKEN='+token}
    data={'messages':[message],'native_client_history':[message],
          'replay_config':json.dumps({'api_key':secret})}
    serialized=ns['_wetlab_json'](data)
    assert secret not in serialized and token not in serialized
    restored=json.loads(serialized)
    assert restored['messages']==restored['native_client_history']
    assert restored['messages'][0]['content']=='WETLAB_TOKEN=<redacted>'
    assert json.loads(restored['replay_config'])['api_key']=='<redacted>'


def test_missing_native_version_fails_before_model_or_hook_upload():
    import asyncio,types
    uploads=[]
    class Environment:
        async def exec(self,command):return types.SimpleNamespace(return_code=0,stdout='unknown')
        async def upload_file(self,*args):uploads.append(args)
    agent=types.SimpleNamespace(get_version_command=lambda:'native --version',parse_version=lambda value:value)
    with pytest.raises(ValueError,match='version cannot be verified before model execution'):
        asyncio.run(S.prepare(agent,Environment(),{'agent':'swe-agent','run_id':'test'},None))
    assert uploads==[]


def test_research_cache_key_is_not_mistaken_for_model_auth(monkeypatch):
    import os
    monkeypatch.setenv('TIKTOKEN_CACHE_DIR','/app/tokenizer-cache')
    monkeypatch.setenv('TRAINED_MODEL_KEY','scientific-model-id-1234')
    ns={'json':json,'os':os}
    exec(S.JSON_HELPER,ns)
    data={'content':'/app/tokenizer-cache scientific-model-id-1234'}
    assert json.loads(ns['_wetlab_json'](data))==data
