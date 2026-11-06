"""Recovery integrations for harnesses whose Harbor wrapper starts fresh per run.

Only native, structured state is restored. No conversation summaries or pickles.
"""
from __future__ import annotations
import asyncio,copy,importlib,json,os,re,shlex,time,urllib.request
from importlib.metadata import version
from pathlib import Path

try:
    from .support import atomic_json,known_secrets
except ImportError:
    from support import atomic_json,known_secrets

HOST_SERIALIZED={'terminus-2','computer-1'}
EXTRA_NATIVE={}
EXTERNAL={}
for _module in ('cli_extra','sdk_extra','provider_extra','sdk_native','deerflow_native','sdk_more','computer_native','eve_native','fabric_native'):
    _name=(__package__+'.' if __package__ else '')+_module
    try:_loaded=importlib.import_module(_name)
    except ModuleNotFoundError as exc:
        if exc.name!=_name:raise
        continue
    for _agent in _loaded.NAMES:EXTERNAL[_agent]=_loaded
ADVANCED=HOST_SERIALIZED | set(EXTRA_NATIVE) | set(EXTERNAL)


def advanced_session(trial,agent):
    if agent in EXTERNAL:return EXTERNAL[agent].latest(trial,agent)
    root=trial/'agent'
    files=list(root.glob('wetlab-native.json')) if agent in HOST_SERIALIZED else list(root.glob(EXTRA_NATIVE[agent]))
    return max(files,key=lambda p:p.stat().st_mtime) if files else None


def advanced_history(path,agent):
    if agent in EXTERNAL:return EXTERNAL[agent].history(path,agent)
    data=json.loads(path.read_text())
    if data.get('format')!='wetlab-native-state-v1' or data.get('harness')!=agent or not data.get('session_id'):
        raise ValueError('invalid native state identity')
    messages=data['chat']['_messages']
    if not isinstance(messages,list) or not all(isinstance(m,dict) and m.get('role') in ('user','assistant','system','tool') for m in messages):
        raise ValueError('invalid native messages')
    return data['session_id'],{str(i):m for i,m in enumerate(messages)}


def validate_advanced(path,agent):
    if agent in EXTERNAL:return EXTERNAL[agent].validate(path,agent)
    advanced_history(path,agent)
    data=json.loads(path.read_text());messages=data['chat']['_messages']
    if not data.get('completed') or not messages or messages[-1].get('role')!='assistant':
        raise ValueError('native harness has not completed its turn')
    if not data.get('shell_file'):raise ValueError('native terminal shell state missing')
    shell=path.parent/data['shell_file']
    if shell.name!='terminal-shell.sh' or not shell.is_file():raise ValueError('native shell companion is missing')


def _shell_script(raw,secrets):
    cwd,rest=raw.split('\n__WETLAB_VARS__\n',1)
    variables,rest=rest.split('\n__WETLAB_FUNCTIONS__\n',1)
    functions,rest=rest.split('\n__WETLAB_ALIASES__\n',1)
    aliases,options=rest.split('\n__WETLAB_OPTIONS__\n',1)
    kept=[]
    transient={'TMUX','TMUX_PANE','PPID','UID','EUID','SHLVL','BASHPID','SHELLOPTS','BASHOPTS','RANDOM','SRANDOM','SECONDS','LINENO','PIPESTATUS','_'}
    for line in variables.splitlines():
        match=re.match(r'^declare -([a-zA-Z-]+) ([A-Za-z_][A-Za-z0-9_]*)=',line)
        if not match:continue
        flags,name=match.groups()
        if 'r' in flags or name in transient or name.startswith('BASH_') or any(x in name.upper() for x in ('TOKEN','PASSWORD','SECRET','API_KEY')):continue
        if any(s in line for s in secrets):continue
        kept.append(line)
    extras=functions+'\n'+aliases+'\n'+options
    if any(s in extras for s in secrets):raise ValueError('credential embedded in native shell function/alias')
    if not cwd.strip().startswith('/'):raise ValueError('native shell cwd is not absolute')
    return 'cd -- '+shlex.quote(cwd.strip())+'\n'+'\n'.join(kept)+'\n'+extras+'\n'


async def _capture_shell(agent,environment,secrets):
    # Asciinema owns the outer tmux PTY while an interactive child bash owns
    # the real shell. Inspect foreground process groups instead of mistaking
    # the recorder's process name for an in-flight scientific command.
    check='''import pathlib,sys
seen=set();queue=[int(sys.argv[1])];idle=False
while queue:
 p=queue.pop()
 if p in seen:continue
 seen.add(p);root=pathlib.Path('/proc')/str(p)
 try:
  children=[int(x) for x in (root/'task'/str(p)/'children').read_text().split()];queue.extend(children)
  args=(root/'cmdline').read_bytes().split(b'\\0');name=pathlib.PurePosixPath(args[0].decode()).name
  fields=(root/'stat').read_text().rsplit(')',1)[1].split()
  if name in ('bash','zsh','sh','dash') and not children and fields[4]!='0' and fields[2]==fields[5]:idle=True
 except (OSError,ValueError,IndexError):pass
print('IDLE' if idle else 'BUSY')'''
    for _ in range(100):
        pane=await environment.exec('tmux display-message -t '+shlex.quote(agent._session._session_name)+" -p '#{pane_pid}'")
        pid=pane.stdout.strip().splitlines()[-1] if pane.stdout.strip() else ''
        idle=await environment.exec('python -c '+shlex.quote(check)+' '+pid) if pid.isdigit() else None
        if idle and idle.stdout.strip()=='IDLE':break
        await asyncio.sleep(.1)
    else:raise ValueError('native terminal command is still running')
    raw='/logs/agent/wetlab-shell.raw'
    command="{ pwd -P; printf '\\n__WETLAB_VARS__\\n'; declare -p; printf '\\n__WETLAB_FUNCTIONS__\\n'; declare -f; printf '\\n__WETLAB_ALIASES__\\n'; alias -p; printf '\\n__WETLAB_OPTIONS__\\n'; set +o; } > "+raw
    await agent._session.send_keys(command+'\n',block=True,max_timeout_sec=20)
    result=await environment.exec('cat '+raw)
    await environment.exec('rm -f '+raw)
    if result.return_code:raise ValueError('cannot capture native terminal state')
    script=_shell_script(result.stdout,secrets)
    local=agent.logs_dir/'terminal-shell.sh';local.write_text(script)
    await environment.upload_file(local,'/logs/agent/terminal-shell.sh')
    return local.name


def advanced_bundle(path,agent):
    return EXTERNAL[agent].bundle(path,agent) if agent in EXTERNAL else path.parent


async def prepare_integrations(agent,environment,state,saved=None):
    if state['agent'] in EXTERNAL:
        await EXTERNAL[state['agent']].prepare(agent,environment,state,saved)


def install_integrations(state,manifest=None,saved=None):
    if state.get('setup_timeout_sec') is not None:
        timeout=float(state['setup_timeout_sec'])
        if timeout<=0:raise ValueError('setup timeout must be positive')
        from harbor.trial.trial import Trial
        Trial._compute_agent_setup_timeout_sec=lambda self:timeout
    if state['agent'] in EXTERNAL:
        return EXTERNAL[state['agent']].install(state,saved)
    if state['agent']!='terminus-2':return
    from harbor.agents.terminus_2.terminus_2 import Terminus2
    original_run=Terminus2.run
    original_loop=Terminus2._run_agent_loop
    original_dump=Terminus2._dump_trajectory
    restored=json.loads(Path(saved['session_path']).read_text()) if saved else None
    Terminus2.version=lambda self:'harbor-'+version('harbor')
    class NativeBoundaryReached(Exception):pass

    def dump(self):
        original_dump(self)
        if getattr(self,'_wetlab_suspended',False) or not state.get('gateway_url'):return
        request=urllib.request.Request(state['gateway_url']+'/admin/runs/'+state['run_id'],
            headers={'Authorization':'Bearer '+os.environ['WETLAB_ADMIN_TOKEN']})
        with urllib.request.urlopen(request,timeout=10) as response:run=json.load(response)
        if run.get('finished') or any(not t.get('delivered_at') and t.get('status')!='cancelled' for t in run.get('tickets',[])):
            self._wetlab_suspended=True
            raise NativeBoundaryReached()

    async def loop(self,**kwargs):
        if restored:
            # Restore the actual Chat object before its first model request.
            current_model=self._chat._model
            self._chat.__dict__.update(copy.deepcopy(restored['chat']))
            self._chat._model=current_model
            if self._chat.messages!=restored['chat']['_messages']:
                raise ValueError('native Chat rehydration failed')
            if restored.get('pending_observation'):
                kwargs['initial_prompt']=json.dumps(restored['pending_observation'])+'\n'+kwargs['initial_prompt']
        return await original_loop(self,**kwargs)

    async def run(self,instruction,environment,context):
        self._wetlab_suspended=False
        if restored:
            self.options.session_id=restored['session_id']
            await self._session.send_keys('source /logs/agent/terminal-shell.sh\n',block=True,max_timeout_sec=20)
        try:await original_run(self,instruction,environment,context)
        except NativeBoundaryReached:pass
        shell=await _capture_shell(self,environment,known_secrets(state))
        native={k:copy.deepcopy(v) for k,v in self._chat.__dict__.items() if k!='_model'}
        atomic_json(self.logs_dir/'wetlab-native.json',{'format':'wetlab-native-state-v1','harness':'terminus-2','session_id':self._session_id,
            'chat':native,'completed':bool(self._pending_completion or self._wetlab_suspended),'shell_file':shell,
            'pending_observation':self._trajectory_steps[-1].observation.model_dump(mode='json') if self._trajectory_steps and self._trajectory_steps[-1].observation else None})
        # Harbor's final log download must not overwrite this fresh host-side
        # state with the previous round's restored container-side copy.
        await environment.upload_file(self.logs_dir/'wetlab-native.json','/logs/agent/wetlab-native.json')
    Terminus2._run_agent_loop=loop
    Terminus2.run=run
    Terminus2._dump_trajectory=dump
