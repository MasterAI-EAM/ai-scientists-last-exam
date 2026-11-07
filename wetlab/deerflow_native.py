"""Cold continuation through DeerFlowClient's native thread/checkpointer API."""
from pathlib import Path
import json,shlex,sqlite3
NAMES={'deerflow'}


def latest(trial,agent):
 p=Path(trial)/'agent/deerflow-native/session.json'
 return p if p.is_file() else None


def history(path,agent):
 d=json.loads(Path(path).read_text())
 if d.get('format')!='wetlab-deerflow-native-v1' or not d.get('session_id') or not d.get('messages') or not d.get('system_prompt'):
  raise ValueError('DeerFlow native checkpoint identity or original prompt missing')
 return d['session_id'],{str(i):m for i,m in enumerate(d['messages'])}


def validate(path,agent):
 sid,messages=history(path,agent);d=json.loads(Path(path).read_text())
 db=Path(path).parent/'checkpoints.sqlite'
 with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as c:
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or not c.execute('SELECT 1 FROM checkpoints WHERE thread_id=? LIMIT 1',(sid,)).fetchone():
   raise ValueError('DeerFlow native database missing or corrupt')
 last=list(messages.values())[-1]
 if not d.get('completed') or last.get('type')!='ai' or last.get('tool_calls'):
  raise ValueError('DeerFlow native turn is incomplete')


def bundle(path,agent):return Path(path).parent


def install(state,saved=None):
 from harbor.agents.installed.deerflow import DeerFlow
 original=DeerFlow._write_config
 async def write_config(self,environment):
  await original(self,environment)
  await prepare(self,environment,state,saved)
 DeerFlow._write_config=write_config


async def prepare(agent,environment,state,saved=None):
 if agent._runtime_context is None:await agent._resolve_runtime_context(environment)
 from harbor.agents.installed import deerflow
 source=Path(deerflow.__file__).with_name('deerflow_runner.py').read_text()
 setup='''    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3
    import deerflow.client as native_client
    native_root=Path('/logs/agent/deerflow-native')
    native_root.mkdir(parents=True,exist_ok=True)
    native_file=native_root/'session.json'
    previous=json.loads(native_file.read_text()) if native_file.exists() else None
    original_prompt=native_client.apply_prompt_template
    prompt_holder={}
    def durable_prompt(*args,**kwargs):
        text=previous['system_prompt'] if previous else original_prompt(*args,**kwargs)
        prompt_holder['text']=text
        return text
    native_client.apply_prompt_template=durable_prompt
    connection=sqlite3.connect(native_root/'checkpoints.sqlite',check_same_thread=False)
    checkpointer=SqliteSaver(connection)
'''
 marker='    client = DeerFlowClient(\n'
 if source.count(marker)!=1:raise ValueError('DeerFlow runner constructor contract changed')
 source=source.replace(marker,setup+marker+'        checkpointer=checkpointer,\n')
 marker='    message_usage: dict[str, dict[str, int]] = {}'
 setup=f'''    native_sid={state['run_id']!r}
    native_config=client._get_runnable_config(native_sid)
    client._ensure_agent(native_config)
    if previous:
        restored=client._agent.get_state(native_config)
        rows=[m.model_dump(mode='json') for m in restored.values.get('messages',[])]
        if previous['session_id']!=native_sid or rows!=previous['messages']:
            raise ValueError('DeerFlow native history was not restored')

'''
 if source.count(marker)!=1:raise ValueError('DeerFlow runner state contract changed')
 source=source.replace(marker,setup+marker)
 source=source.replace('message, recursion_limit=_int(', 'message, thread_id=native_sid, recursion_limit=_int(')
 marker='    _write_summary(status=status, usage=usage, error=error)'
 export='''    native_state=client._agent.get_state(native_config)
    native_data={'format':'wetlab-deerflow-native-v1','session_id':native_sid,
        'messages':[m.model_dump(mode='json') for m in native_state.values.get('messages',[])],
        'completed':status=='completed' and not native_state.next,
        'system_prompt':prompt_holder['text'],'checkpoint':native_state.config}
    temporary=native_file.with_suffix('.tmp')
    temporary.write_text(json.dumps(native_data));os.chmod(temporary,0o600);temporary.replace(native_file)
    connection.commit();connection.close()
'''
 if source.count(marker)!=1:raise ValueError('DeerFlow runner finalization contract changed')
 source=source.replace(marker,export+marker)
 local=agent.logs_dir/'wetlab-deerflow-runner.py';local.write_text(source)
 # Install the native persistence driver in the isolated harness environment.
 # All subsequent turns use the archived installation without network setup.
 if not saved:
  cmd=shlex.quote(agent._VENV_PYTHON)+" -c 'import langgraph.checkpoint.sqlite'"
  result=await environment.exec(cmd)
  if result.return_code:
   result=await environment.exec('export PATH="$HOME/.local/bin:$PATH"; uv pip install --python '+shlex.quote(agent._VENV_PYTHON)+' langgraph-checkpoint-sqlite==3.1.3',timeout_sec=240)
   if result.return_code:raise RuntimeError('DeerFlow native SQLite driver installation failed')
 await environment.upload_file(local,str(agent._REMOTE_RUNNER_PATH))
