#!/usr/bin/env python3
"""Explicit paid model probe: uninterrupted agent, Docker identity and signed verifier.

--wait-seconds 86410 performs a real >=24h wait; do not infer that result from
short probes. All evidence stays in --out; credentials remain outside reports.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from wetlab.support import atomic_json, known_secrets, redact


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--env-file',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--harbor',required=True);ap.add_argument('--archive-dir',required=True)
    ap.add_argument('--agents',nargs='+',choices=['openclaw','terminus-2'],default=['openclaw'])
    ap.add_argument('--wait-seconds',type=float,default=20)
    ap.add_argument('--install-cache-image')
    ap.add_argument('--timeout',type=float,default=1800,help='Extra allowance beyond the real lab wait')
    args=ap.parse_args()
    if args.wait_seconds<=0:raise ValueError('wait seconds must be positive')
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False,mode=0o700)
    values={}
    for line in Path(args.env_file).read_text().splitlines():
        line=line.strip().removeprefix('export ')
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1);values[k.strip()]=v.strip().strip('\"\'')
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['API_KEY','TOKEN','PASSWORD','SIGNING_KEY'])}
    env.update(OPENAI_API_KEY=values['OPENAI_API_KEY'],OPENAI_API_BASE=values['OPENAI_API_BASE'],
        HARBOR=args.harbor,HARBOR_PYTHON=sys.executable,
        WETLAB_ADMIN_TOKEN=secrets.token_hex(32),WETLAB_SIGNING_KEY=secrets.token_hex(32),PYTHONUNBUFFERED='1')
    private=Path('/tmp')/('wetlab-blocking-private-'+secrets.token_hex(8)+'.json')
    atomic_json(private,{k:env[k] for k in ['WETLAB_ADMIN_TOKEN','WETLAB_SIGNING_KEY']})
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    endpoint=f'http://127.0.0.1:{port}'
    def request(path,body=None):
        req=urllib.request.Request(endpoint+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+env['WETLAB_ADMIN_TOKEN'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
    def inspect(cid):
        return json.loads(subprocess.run(['docker','inspect',cid],check=True,capture_output=True,text=True).stdout)[0]
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')}
    atomic_json(out/'source_hashes.json',source_hashes)
    with (out/'gateway.log').open('w') as glog:
        gateway=subprocess.Popen([sys.executable,str(ROOT/'gateway.py'),'--port',str(port),'--db',str(out/'gateway.db'),'--manual-lab'],env=env,stdout=glog,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:request('/health');break
                except OSError:time.sleep(.1)
            def probe(agent):
                import toml
                d=out/agent;d.mkdir();task=d/'task';shutil.copytree(ROOT/'tasks/wetlab-add',task)
                cfg=toml.loads((task/'task.toml').read_text());cfg['wetlab'].update(execution_mode='blocking',budget=1,max_rounds=1,active_budget_sec=600,wait_timeout_sec=max(90000,args.wait_seconds+120))
                (task/'task.toml').write_text(toml.dumps(cfg))
                (task/'instruction.md').write_text('''Measure 1+1 through the wetlab. This task uses BLOCKING mode.
First write /app/before.txt containing KEEP. A trusted test observer will maintain an independent heartbeat in this container.
Call wait_for_result --expr "1+1" --request-id blocking-science exactly once, synchronously, with a timeout of at least 90000 seconds. Do not background this tool, do not end your turn while it is waiting, and do not poll with extra model calls. It returns the lab result in this same turn. After receiving result 2, verify /app/before.txt still contains KEEP and call wetlab finish --answer 2. Do not submit another experiment.\n''')
                if agent=='openclaw' and args.install_cache_image:
                    import re
                    if not re.fullmatch(r'wetlab-openclaw-install-cache:[A-Za-z0-9_.-]+',args.install_cache_image):raise ValueError('invalid install cache tag')
                    p=task/'environment/Dockerfile';s=p.read_text();p.write_text('FROM '+args.install_cache_image+' AS cache\n'+s+'\nCOPY --from=cache /root/.nvm /root/.nvm\nCOPY --from=cache /root/.npm /root/.npm\n')
                cmd=[sys.executable,str(ROOT/'wetlab_run.py'),'start',str(task),'--run-dir',str(d/'run'),'--agent',agent,'--model','openai/deepseek/deepseek-flash','--base-url',values['OPENAI_API_BASE'],'--api-key-name','OPENAI_API_KEY','--allow-agent-host','tokenhub.tencentmaas.com','--gateway-url',endpoint,'--gateway-url-container',f'http://host.docker.internal:{port}','--setup-timeout','900','--archive-dir',args.archive_dir]
                samples=[];claimed=None;started=None;last=None;actual_wait=None;st={};heartbeat=False;deadline=time.monotonic()+args.timeout+args.wait_seconds
                with (d/'controller.log').open('w') as log:
                    controller=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        while controller.poll() is None and time.monotonic()<deadline:
                            state_path=d/'run/state.json'
                            if state_path.exists():
                                st=json.loads(state_path.read_text())
                                try:run=request('/admin/runs/'+st['run_id'])
                                except urllib.error.HTTPError as exc:
                                    if st['phase']=='INIT' and exc.code in (404,500):time.sleep(.2);continue
                                    raise
                                if run['container_id']:
                                    try:info=inspect(run['container_id'])
                                    except subprocess.CalledProcessError:info=None
                                    if info and not run['finished']:
                                        if not heartbeat:
                                            subprocess.run(['docker','exec','-d',info['Id'],'python','-c',"import pathlib,time; p=pathlib.Path('/app/heartbeat'); exec('while True:\n p.write_text(str(time.time()))\n time.sleep(1)')"],check=True,capture_output=True)
                                            heartbeat=True
                                        current={'at':time.time(),'container_id':info['Id'],'started_at':info['State']['StartedAt'],'running':info['State']['Running'],'paused':info['State']['Paused']}
                                        if samples:assert current['container_id']==samples[0]['container_id'] and current['started_at']==samples[0]['started_at']
                                        assert current['running'] and not current['paused'];samples.append(current)
                                pending=[t for t in run['tickets'] if t['status']=='accepted']
                                if pending and claimed is None:
                                    ticket=pending[0];claimed=request(f"/admin/tickets/{ticket['seq']}/claim",{'claim_id':'blocking-test-lab-worker'})
                                    assert claimed['execute'];started=time.monotonic()
                                if claimed and last is None and time.monotonic()-started>=args.wait_seconds:
                                    actual_wait=time.monotonic()-started
                                    seq=claimed['ticket']['seq'];last=request(f'/admin/tickets/{seq}/complete',{'result':'2'})
                                    assert not request(f'/admin/tickets/{seq}/claim',{'claim_id':'duplicate-notification'})['execute']
                                    assert request(f'/admin/tickets/{seq}/complete',{'result':'2'})['replayed']
                            time.sleep(.5)
                        if controller.poll() is None:raise TimeoutError('live probe deadline exceeded; container is retained')
                        st=json.loads((d/'run/state.json').read_text())
                        ledger=json.loads((d/'run/final/ledger.json').read_text())['ledger'] if (d/'run/final/ledger.json').exists() else None
                        trial_result=json.loads((Path(st['current_trial'])/'result.json').read_text()) if st.get('current_trial') and (Path(st['current_trial'])/'result.json').exists() else {}
                        result={'no_harness_exception': bool(trial_result) and not trial_result.get('exception_info'), 'agent':agent,'controller_exit':controller.returncode,'phase':st['phase'],'reward':st.get('reward'),
                            'configured_wait_sec':cfg['wetlab']['wait_timeout_sec'],'actual_wait_sec':actual_wait,
                            'wait_completed':last is not None,'one_container_throughout':bool(samples) and len({x['container_id'] for x in samples})==1,
                            'unpaused_samples':len(samples),'no_checkpoints':not st['checkpoints'],
                            'one_experiment':bool(ledger and ledger['run']['used']==1 and len(ledger['run']['tickets'])==1),
                            'no_checkpoint_events':bool(ledger and not any(x['type']=='checkpoint_committed' for x in ledger['events']))}
                        result['passed']=st['phase']=='COMPLETED' and st.get('reward')=='1' and all(result[k] for k in ['no_harness_exception','wait_completed','one_container_throughout','no_checkpoints','one_experiment','no_checkpoint_events'])
                        atomic_json(d/'verification.json',result);atomic_json(d/'container-samples.json',samples)
                        print(json.dumps(result),flush=True);return result
                    finally:
                        if controller.poll() is None:controller.terminate();controller.wait(timeout=15)
                        # Raw diagnostics stay private; redact known credentials before reuse.
                        path=d/'controller.log';path.write_text(redact(path.read_text(),known_secrets({'token':st.get('token','')})+[v for k,v in env.items() if any(x in k for x in ['TOKEN','KEY'])]))
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.agents)) as pool:results=list(pool.map(probe,args.agents))
            atomic_json(out/'summary.json',{'results':results,'private_metadata':str(private),'source_hashes':source_hashes,'implementation_unchanged':source_hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')}})
            if not all(x['passed'] for x in results):raise SystemExit(1)
        finally:gateway.terminate();gateway.wait(timeout=10)

if __name__=='__main__':main()
