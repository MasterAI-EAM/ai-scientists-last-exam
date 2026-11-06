import http.client,json,urllib.error
from pathlib import Path
import pytest
from wetlab.model_bridge import GoogleChatBridge,UnsupportedRequest,to_chat,to_google


def test_native_reasoning_tools_roundtrip():
    native={'systemInstruction':{'parts':[{'text':'scientific task'}]},'contents':[
        {'role':'user','parts':[{'text':'calculate'}]},
        {'role':'model','parts':[{'text':'reasoning','thought':True},{'functionCall':{'id':'stable-id','name':'shell','args':{'cmd':'pwd'}}}]},
        {'role':'user','parts':[{'functionResponse':{'id':'stable-id','name':'shell','response':{'output':'/workspace'}}}]}],
        'tools':[{'functionDeclarations':[{'name':'shell','parameters':{'type':'OBJECT','properties':{'cmd':{'type':'STRING'}}}}]}]}
    result=to_chat(native,'deepseek/deepseek-flash')
    assert result['model']=='deepseek/deepseek-flash'
    assert result['messages'][0]=={'role':'system','content':'scientific task'}
    assert result['messages'][2]['reasoning_content']=='reasoning'
    assert result['messages'][3]['tool_call_id']=='stable-id'
    assert result['tools'][0]['function']['parameters']['type']=='object'
    response=to_google({'id':'response1','choices':[{'message':{'reasoning_content':'thinking','content':'answer','tool_calls':[{'id':'next','function':{'name':'shell','arguments':'{"cmd":"ls"}'}}]},'finish_reason':'tool_calls'}],
        'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,'completion_tokens_details':{'reasoning_tokens':2}}},'deepseek/deepseek-flash')
    assert response['candidates'][0]['content']['parts']==[{'text':'thinking','thought':True},{'text':'answer'},{'functionCall':{'id':'next','name':'shell','args':{'cmd':'ls'}}}]
    assert response['usageMetadata']['thoughtsTokenCount']==2


def test_invented_tools_unpaired_results_and_opaque_signatures_fail():
    for request in [
        {'tools':[{'googleSearch':{}}]},
        {'contents':[{'parts':[{'functionResponse':{'name':'shell','response':{}}}]}]},
        {'contents':[{'role':'model','parts':[{'text':'thought','thoughtSignature':'opaque'}]}]},
    ]:
        with pytest.raises(UnsupportedRequest):to_chat(request,'deepseek/deepseek-flash')
    with pytest.raises(ValueError):to_google({'error':{'message':'failed'}},'deepseek/deepseek-flash')
    for sentinel in ('skip_thought_signature_validator','c2tpcF90aG91Z2h0X3NpZ25hdHVyZV92YWxpZGF0b3I='):
        translated=to_chat({'contents':[{'role':'model','parts':[{'text':'plain DeepSeek history','thoughtSignature':sentinel}]}]},'deepseek/deepseek-flash')
        assert translated['messages']==[{'role':'assistant','content':'plain DeepSeek history'}]


def test_bridge_auth_wrong_model_and_quota_status(monkeypatch):
    bridge=GoogleChatBridge(upstream='https://provider.example/v1',key='private-test-key',bind='127.0.0.1')
    def send(path,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',bridge.server.server_port,timeout=5)
        c.request('POST',path,json.dumps({'contents':[{'role':'user','parts':[{'text':'hello'}]}]}),headers=headers or {})
        r=c.getresponse();data=r.read();c.close();return r.status,json.loads(data)
    try:
        assert send('/v1beta/models/deepseek/deepseek-flash:generateContent')[0]==401
        assert send('/v1beta/models/different:generateContent',{'x-goog-api-key':'private-test-key'})[0]==400
        def quota(*args,**kwargs):raise urllib.error.HTTPError('https://provider.example',402,'quota',{},None)
        monkeypatch.setattr('wetlab.model_bridge.urllib.request.urlopen',quota)
        status,result=send('/v1beta/models/deepseek/deepseek-flash:generateContent',{'x-goog-api-key':'private-test-key'})
        assert status==402 and result['error']['code']==402
        assert 'private-test-key' not in json.dumps(result)
        assert bridge.evidence()['provider_requests']==1
    finally:bridge.close()


def test_gemini_native_jsonl_preserves_update_and_tool_state(tmp_path):
    from wetlab.provider_extra import history,validate
    path=tmp_path/'gemini-cli.trajectory.jsonl'
    records=[{'sessionId':'session-id'},{'type':'user','id':'u','content':'original task'},
        {'type':'gemini','id':'a','content':'answer','thoughts':[{'subject':'analysis','description':'reason'}]},
        {'type':'message_update','id':'a','toolCalls':[{'id':'t','status':'success','result':'done'}]}]
    path.write_text('\n'.join(json.dumps(r) for r in records))
    sid,messages=history(path,'gemini-cli');validate(path,'gemini-cli')
    assert sid=='session-id' and messages['a']['thoughts'][0]['description']=='reason'
    assert messages['a']['toolCalls'][0]['result']=='done'
    records[-1]['toolCalls'][0]['status']='executing'
    path.write_text('\n'.join(json.dumps(r) for r in records))
    with pytest.raises(ValueError):validate(path,'gemini-cli')


def test_antigravity_native_database_error_and_unfinished_boundary(tmp_path):
    import sqlite3
    from wetlab.provider_extra import history,validate
    path=tmp_path/'antigravity-conversation.db'
    with sqlite3.connect(path) as c:
        c.execute('create table trajectory_meta(trajectory_id text,cascade_id text)')
        c.execute('insert into trajectory_meta values (?,?)',('trajectory','cascade'))
        c.execute('create table steps(idx integer primary key,step_type integer,status integer,metadata blob,error_details blob,step_payload blob)')
        c.execute('insert into steps values (0,14,3,?,NULL,?)',(b'metadata',b'complete original user context'))
        c.execute('insert into steps values (1,15,3,?,NULL,?)',(b'model reasoning',b'complete original model response'))
    (tmp_path/'antigravity-stream.jsonl').write_text(json.dumps({'event':'result','result':{'conversation_id':'cascade','status':'SUCCESS'}})+'\n')
    sid,records=history(path,'antigravity-cli');validate(path,'antigravity-cli')
    assert sid=='cascade' and records['0'][-1]==b'complete original user context'.hex()
    with sqlite3.connect(path) as c:c.execute('update steps set status=2 where idx=1')
    with pytest.raises(ValueError,match='unfinished'):validate(path,'antigravity-cli')
    with sqlite3.connect(path) as c:c.execute('update steps set status=3,step_type=17 where idx=1')
    with pytest.raises(ValueError,match='failed step'):validate(path,'antigravity-cli')


def test_junie_native_auth_cache_is_removed_without_losing_context(tmp_path):
    import os,subprocess,sys
    from wetlab.provider_extra import _JUNIE_SANITIZE
    root=tmp_path/'.junie/sessions/native-id';root.mkdir(parents=True)
    blob={'env':{'WETLAB_TOKEN':'old-runtime-token','WETLAB_MODEL_API_KEY':'provider-secret','LANG':'C.UTF-8','MAX_TOKENS':'8192','EXPERIMENT_TOKEN':'scientific-nonce'},
          'lastAgentState':{'isFinished':True,'observations':[{'content':'original task and tool result'}]},
          'lastSessionHistorySnapshot':{'env':{'WETLAB_TOKEN':'old-runtime-token','PWD':'/app'}}}
    path=root/'state.json';path.write_text(json.dumps({'event':{'agentEvent':{'blob':json.dumps(blob)}}}))
    env={**os.environ,'HOME':str(tmp_path),'WETLAB_SANITIZE_VALUES':json.dumps(['provider-secret','old-runtime-token'])}
    subprocess.run([sys.executable,'-c',_JUNIE_SANITIZE],env=env,check=True)
    cleaned=json.loads(json.loads(path.read_text())['event']['agentEvent']['blob'])
    assert cleaned['env']=={'LANG':'C.UTF-8','MAX_TOKENS':'8192','EXPERIMENT_TOKEN':'scientific-nonce'}
    assert cleaned['lastSessionHistorySnapshot']['env']=={'PWD':'/app'}
    assert cleaned['lastAgentState']==blob['lastAgentState']
    original=path.read_bytes()
    subprocess.run([sys.executable,'-c',_JUNIE_SANITIZE],env=env,check=True)
    assert path.read_bytes()==original


@pytest.mark.parametrize('agent',['acp','cline-cli','junie'])
def test_provider_adapters_never_substitute_the_requested_model(agent):
    from wetlab.provider_extra import install
    with pytest.raises(ValueError,match='authorized DeepSeek'):
        install({'agent':agent,'model':'openai/different-model'})
