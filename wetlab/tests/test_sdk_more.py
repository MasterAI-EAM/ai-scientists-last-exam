"""NAT keeps native channel records and requires its actual durable graph."""
import json,sqlite3
import pytest
from wetlab import sdk_more as S


def make_snapshot(directory,**updates):
    directory.mkdir()
    data={'format':'wetlab-nat-native-v1','harness':'nemo-agent','session_id':'native-thread',
          'completed':True,'checkpoint_id':'native-checkpoint',
          'native_state':{'messages':[{'type':'human','content':'research task'}],
             'agent_scratchpad':[{'tool':'shell','tool_input':'pwd','log':'raw model reasoning'}],
             'tool_responses':[{'content':'/app','tool_call_id':'native-call'}]}}
    data.update(updates);path=directory/S.FILE;path.write_text(json.dumps(data))
    return path


def test_nat_requires_matching_actual_sqlite_checkpoint(tmp_path):
    path=make_snapshot(tmp_path/'session')
    with pytest.raises(ValueError,match='SQLite checkpoint missing'):S.validate(path,'nemo-agent')
    with sqlite3.connect(path.parent/'nat-checkpoints.sqlite') as conn:
        conn.execute('CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT)')
        conn.execute('INSERT INTO checkpoints VALUES (?,?)',('native-thread','native-checkpoint'))
    S.validate(path,'nemo-agent')
    data=json.loads(path.read_text());data['checkpoint_id']='other';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='identity missing'):S.validate(path,'nemo-agent')


def test_nat_separate_native_channels_keep_raw_old_records(tmp_path):
    old=make_snapshot(tmp_path/'old');data=json.loads(old.read_text())
    data['native_state']['messages'].append({'type':'human','content':'lab result 2'})
    data['native_state']['agent_scratchpad'].append({'tool':'shell','tool_input':'train.py','log':'new model reasoning'})
    new=tmp_path/'continued.json';new.write_text(json.dumps(data))
    old_id,previous=S.history(old,'nemo-agent');new_id,current=S.history(new,'nemo-agent')
    assert old_id==new_id and len(current)>len(previous)
    assert all(current[k]==v for k,v in previous.items())
    compile(S.NAT_RUNTIME.replace('__SESSION_ID__',repr('native-thread')),'native-NAT','exec')
