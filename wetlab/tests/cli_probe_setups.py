"""Parallel install/CLI probes. No experiments or model generations are submitted."""
import argparse,concurrent.futures,json,os,secrets,shutil,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT.parent))
from wetlab.support import atomic_json,scrub_logs,redact
from wetlab import wetlab_run as W

p=argparse.ArgumentParser();p.add_argument('--env-file',required=True);p.add_argument('--out',required=True);p.add_argument('--agents',nargs='+',required=True);p.add_argument('--workers',type=int,default=6);p.add_argument('--harbor',required=True);a=p.parse_args()
out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
values={}
for line in Path(a.env_file).read_text().splitlines():
 line=line.strip().removeprefix('export ')
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);values[k.strip()]=v.strip().strip('\"\'')
key=values['OPENAI_API_KEY'];base=values['OPENAI_API_BASE']
env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['API_KEY','TOKEN','PASSWORD','SIGNING_KEY'])};env.update(OPENAI_API_KEY=key,OPENAI_BASE_URL=base,OPENAI_API_BASE=base,HARBOR=a.harbor)

def execute(name):
 d=out/name;d.mkdir();task=d/'task';shutil.copytree(ROOT/'tasks/wetlab-add',task)
 state={'agent':name,'round':1,'checkpoints':[],'task_dir':str(task),'current_job':str(d/'jobs/probe'),'run_id':secrets.token_hex(8)}
 atomic_json(d/'state.json',state)
 cmd=[sys.executable,str(ROOT/'tests/cli_probe_worker.py'),'run','-p',str(task),'-a',name,'-m','openai/deepseek/deepseek-flash','--base-url',base,'--api-key-name','OPENAI_API_KEY','-o',str(d/'jobs'),'--job-name','probe','--no-delete','--ek','keep_containers=true','--disable-verification']
 started=time.monotonic();proc=subprocess.Popen(cmd,env={**env,'WETLAB_RUN_STATE':str(d/'state.json')},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
 try:log,_=proc.communicate(timeout=950)
 except subprocess.TimeoutExpired:
  os.killpg(proc.pid,signal.SIGTERM)
  try:log,_=proc.communicate(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);log,_=proc.communicate()
 (d/'console.log').write_text(log.replace(key,'<redacted>'));scrub_logs(d,[key])
 probes=list(d.glob('jobs/**/agent/probe.json'));errors=[]
 for f in d.glob('jobs/**/exception.txt'):errors.append(f.read_text()[-2000:].replace(key,'<redacted>'))
 result={'agent':name,'installed':bool(probes),'seconds':round(time.monotonic()-started,2),'errors':errors}
 if probes:result['probe']=json.loads(probes[0].read_text())
 for trial in d.glob('jobs/probe/*'):
  if not trial.is_dir() or not (trial/'trial.log').exists():continue
  project=W.project_of(trial)
  W.remove_project(project)
 atomic_json(d/'summary.json',result);print(json.dumps({'agent':name,'installed':result['installed'],'seconds':result['seconds'],'errors':[e[-120:] for e in errors]}),flush=True)
 return result
with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:results=list(pool.map(execute,a.agents))
atomic_json(out/'results.json',{'results':results,'model_calls':0,'experiment_submissions':0})
