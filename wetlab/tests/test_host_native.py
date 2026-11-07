"""Recovery must reject altered canonical context or missing durable state."""
import json,sqlite3
import pytest
from wetlab import advanced as A,sdk_native as S,deerflow_native as D
from wetlab.sessions import assert_continuation


def test_terminal_raw_context_cannot_be_summarized_on_resume(tmp_path):
    old=tmp_path/'before.json';new=tmp_path/'after.json'
    data={'format':'wetlab-native-state-v1','harness':'terminus-2','session_id':'original-id',
          'completed':True,'shell_file':'terminal-shell.sh','chat':{'_messages':[
             {'role':'user','content':'initial nonce and real instructions'},
             {'role':'assistant','content':'raw command reply'}]}}
    old.write_text(json.dumps(data));(tmp_path/'terminal-shell.sh').write_text('cd /app\n')
    A.validate_advanced(old,'terminus-2')
    data['chat']['_messages'][0]['content']='summary of previous research'
    data['chat']['_messages'].append({'role':'assistant','content':'next step'})
    new.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='previous context changed'):assert_continuation(old,new,'terminus-2')


def test_shell_snapshot_preserves_scientific_variables_but_rebinds_auth():
    raw='/research\n__WETLAB_VARS__\ndeclare -- samples="12"\ndeclare -a observations=([0]="2" [1]="4")\ndeclare -- OPENAI_API_KEY="private-test-key"\ndeclare -r UID="0"\n__WETLAB_FUNCTIONS__\nfit () { echo 3; }\n__WETLAB_ALIASES__\nalias ll="ls -l"\n__WETLAB_OPTIONS__\nset +o noclobber\n'
    result=A._shell_script(raw,['private-test-key'])
    assert 'samples="12"' in result and 'observations=' in result and 'fit ()' in result and 'alias ll' in result
    assert 'API_KEY' not in result and 'UID=' not in result and result.startswith('cd -- /research')


def test_strands_incomplete_native_tool_result_is_rejected(tmp_path):
    path=tmp_path/'session.json';path.write_text(json.dumps({'session_id':'native-strands'}))
    folder=tmp_path/'agents/a/messages';folder.mkdir(parents=True)
    (folder/'message_0.json').write_text(json.dumps({'message':{'role':'assistant','content':[{'toolUse':{'toolUseId':'call-1','name':'shell','input':{'command':'train'}}}]}}))
    (folder/'message_1.json').write_text(json.dumps({'message':{'role':'assistant','content':[{'text':'Done'}]}}))
    with pytest.raises(ValueError,match='incomplete'):S.validate(path,'strands')


@pytest.mark.parametrize('module,agent,fmt',[(D,'deerflow','wetlab-deerflow-native-v1'),(S,'langgraph','wetlab-langgraph-native-v1')])
def test_graph_native_export_does_not_replace_actual_durable_database(tmp_path,module,agent,fmt):
    path=tmp_path/'session.json';data={'format':fmt,'session_id':'thread-1','messages':[{'type':'ai','content':'real reply'}],
       'completed':True,'system_prompt':'original system prompt'};path.write_text(json.dumps(data))
    db=tmp_path/'checkpoints.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE checkpoints (thread_id TEXT)');c.execute('INSERT INTO checkpoints VALUES (?)',('other-thread',))
    with pytest.raises(ValueError,match='missing or corrupt'):module.validate(path,agent)



def test_explicit_setup_deadline_is_applied_to_harbor_runtime_without_cli_flag(monkeypatch):
    from harbor.trial.trial import Trial
    original=Trial._compute_agent_setup_timeout_sec
    try:
        A.install_integrations({'agent':'not-a-running-agent','setup_timeout_sec':900})
        assert Trial._compute_agent_setup_timeout_sec(object())==900
    finally:Trial._compute_agent_setup_timeout_sec=original
