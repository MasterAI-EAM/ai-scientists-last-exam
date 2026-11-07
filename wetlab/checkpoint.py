"""Local Docker checkpoints: immutable images, all task services and mount data.

No host-side extraction of agent-authored tar archives. Restores happen in an
isolated helper container before application services start.
"""
from __future__ import annotations
import hashlib
import fcntl
import functools
import gzip
import hmac
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

try:
    from .support import sha256_file, stream_contains, redact, redact_stream
except ImportError:
    from support import sha256_file, stream_contains, redact, redact_stream

HELPER = os.environ.get('WETLAB_ARCHIVE_IMAGE', 'busybox:latest')
READER = os.environ.get('WETLAB_READER_IMAGE', 'python:3.12-slim-bookworm')
MANAGED = {'/logs/agent', '/logs/verifier', '/logs/artifacts'}
INTERNAL = {'/wetlab-restore', '/run/wetlab-internal'}
WRAPPER = ['/bin/sh', '/wetlab-restore/restore.sh']


def docker(*args, **kwargs):
    result = subprocess.run(['docker', *map(str, args)], check=False, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(redact(f'Docker {args[0]} failed ({result.returncode}): {(result.stderr or result.stdout)[:2000]}'))
    return result.stdout


def inspect_container(cid):
    return json.loads(docker('inspect', cid))[0]


def image_id(ref):
    value = docker('image', 'inspect', '--format', '{{.Id}}', ref).strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
        raise ValueError('Docker returned an invalid image ID')
    return value


def signature(manifest):
    payload = {k: v for k, v in manifest.items() if k != 'signature'}
    return hmac.new(os.environ['WETLAB_SIGNING_KEY'].encode(),
                    json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def validate(root: Path, *, run_id=None, task_checksum=None, load_images=True):
    m = json.loads((root / 'manifest.json').read_text())
    if m.get('format') != 'wetlab-checkpoint-v2' or not hmac.compare_digest(m.get('signature', ''), signature(m)):
        raise ValueError('checkpoint manifest signature/version mismatch')
    if run_id is not None and m['run_id'] != run_id:
        raise ValueError('checkpoint belongs to another run')
    if task_checksum is not None and m['task_checksum'] != task_checksum:
        raise ValueError('task changed since checkpoint creation')
    actual_files = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p != root / 'manifest.json'}
    if actual_files != set(m['files']) or any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('checkpoint file set changed')
    for name, digest in m['files'].items():
        p = root / name
        if p.is_symlink() or root.resolve() not in p.resolve().parents or not p.is_file() or sha256_file(p) != digest:
            raise ValueError(f'checkpoint file missing or changed: {name}')
    for service in m['services'].values():
        ref = service['image_id']
        try:
            actual = image_id(ref)
        except (subprocess.CalledProcessError, RuntimeError):
            if not load_images:
                raise
            docker('load', '-i', root / 'images.tar')
            actual = image_id(ref)
        if actual != ref:
            raise ValueError('checkpoint image identity mismatch')
    if sha256_file(root / m['session_file']) != m['session_sha256']:
        raise ValueError('checkpoint native session changed')
    return m


def archive_inventory(path):
    result = {}
    with tarfile.open(path, 'r|*') as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if member.name.startswith('/') or '..' in parts:
                raise ValueError('unsafe archive member')
            name = member.name[2:].rstrip('/') if member.name.startswith('./') else '/'.join(parts[1:])
            if name in ('.', ''): name = ''
            row = {'mode': member.mode, 'uid': member.uid, 'gid': member.gid, 'type': member.type.decode('ascii')}
            if member.isfile():
                h = hashlib.sha256()
                with archive.extractfile(member) as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
                row['sha256'] = h.hexdigest()
            elif member.issym() or member.islnk():
                if member.islnk():
                    target = PurePosixPath(member.linkname)
                    if member.linkname.startswith('/') or '..' in target.parts:
                        raise ValueError('unsafe hard-link target')
                    row['link'] = member.linkname[2:] if member.linkname.startswith('./') else '/'.join(target.parts[1:])
                else:
                    row['link'] = member.linkname
            result[name] = row
    groups = {}
    for name, row in result.items():
        if row['type'] != '1': continue
        seen = {name}; target = row['link']
        while target in result and result[target]['type'] == '1':
            if target in seen: raise ValueError('cyclic hard-link archive')
            seen.add(target); target = result[target]['link']
        if target not in result or result[target]['type'] != '0':
            raise ValueError('hard-link target missing from archive')
        groups.setdefault(target, {target}).add(name)
    for target, names in groups.items():
        original = dict(result[target])
        for name in names:
            result[name] = {**original, 'hardlinks': sorted(names)}
    return result


def capture_archive(cid, destination, path, tmpfs=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if tmpfs:
        info = inspect_container(cid)
        if info['HostConfig'].get('PidMode') not in ('', 'private', None):
            raise ValueError('tmpfs reader requires a private container PID namespace')
        dest = PurePosixPath(destination)
        script = "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|');t.add(sys.argv[1],arcname=sys.argv[2],recursive=True);t.close()"
        args=['run','--rm','--network','none','--read-only','--cap-drop','ALL',
              '--cap-add','SYS_PTRACE','--security-opt','no-new-privileges','--pid',f'container:{cid}',
              READER,'python','-c',script,'/proc/1/root'+destination,dest.name]
    else:args=['cp',f'{cid}:{destination}','-']
    write_docker_archive(args,path)
    return archive_inventory(path)


def reject_secrets(path, secrets):
    with path.open('rb') as f:
        if stream_contains(f, secrets):
            raise ValueError(f'credential found in checkpoint material: {path.name}')


def scan_image_archive(path, secrets):
    reject_secrets(path, secrets)
    with tarfile.open(path) as archive:
        for member in archive:
            if not member.isfile(): continue
            with archive.extractfile(member) as f:
                magic = f.read(4)
                f.seek(0)
                if magic[:2] == b'\x1f\x8b':
                    with gzip.GzipFile(fileobj=f) as layer:
                        if stream_contains(layer, secrets): raise ValueError('credential in compressed image layer')
                elif magic == b'\x28\xb5\x2f\xfd':
                    import zstandard
                    with zstandard.ZstdDecompressor().stream_reader(f) as layer:
                        if stream_contains(layer, secrets): raise ValueError('credential in compressed image layer')


def freeze_containers(containers, names):
    """Quiesce without destroying volatile mounts, including during recovery."""
    task_containers = [(cid, svc) for cid, svc in containers if svc in names]
    if len({s for _, s in task_containers}) != len(task_containers):
        raise ValueError('replicated Compose services are not supported')
    for cid, _ in task_containers:
        data = inspect_container(cid)
        if data['HostConfig'].get('Tmpfs') and data['HostConfig'].get('PidMode') not in ('', 'private', None):
            raise ValueError('tmpfs reader requires a private container PID namespace')
        # Tmpfs cannot survive stop. Never silently capture an already-lost tmpfs.
        if data['HostConfig'].get('Tmpfs') and not data['State']['Running']:
            raise ValueError('tmpfs container was stopped before capture; keep containers running until checkpoint')
        if data['State']['Running'] and not data['State'].get('Paused'):
            docker('pause', cid)
    return task_containers


def sanitize_agent_logs(cid, secrets):
    """Redact native text logs and remove credentials from Hermes shell cache.

    Preserve non-secret context, file names, ownership, modes and timestamps.
    Ephemeral auth declarations must be inherited from the resumed CLI environment
    rather than overriding its rotated credentials with old cached values.
    """
    for root in ('/logs/agent', '/tmp/hermes/cache/scratch'):
        _sanitize_native_tree(cid, root, secrets)


def _sanitize_native_tree(cid, root, secrets):
    shell_cache = root.endswith('/scratch')
    with tempfile.TemporaryFile() as original, tempfile.TemporaryFile() as sanitized:
        copied = subprocess.run(['docker', 'cp', f'{cid}:{root}', '-'],
                                stdout=original, stderr=subprocess.PIPE)
        if copied.returncode:
            if b'Could not find' in copied.stderr or b'No such file' in copied.stderr: return
            raise ValueError('cannot inspect native state before checkpoint')
        original.seek(0)
        count = 0
        with tarfile.open(fileobj=original) as src, tarfile.open(fileobj=sanitized, mode='w') as dst:
            for member in src:
                if not member.isfile(): continue
                if shell_cache:
                    if not Path(member.name).name.startswith('hermes-snap-') or not member.name.endswith('.sh'): continue
                elif Path(member.name).suffix not in ('.json', '.jsonl', '.txt', '.log', '.yaml', '.yml', '.toml', '.cfg', '.md', '.traj'): continue
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != PurePosixPath(root).name or '..' in parts or member.name.startswith('/'):
                    raise ValueError('unsafe native state archive path')
                with tempfile.SpooledTemporaryFile(max_size=1024*1024) as clean:
                    if shell_cache:
                        if member.size > 16*1024*1024: raise ValueError('oversized native shell snapshot')
                        data = src.extractfile(member).read()
                        pattern = rb'^\s*(?:declare(?: -[a-zA-Z]+)*|export)\s+[A-Za-z_][A-Za-z0-9_]*='
                        updated = b''.join(line for line in data.splitlines(keepends=True)
                            if not (re.match(pattern, line) and any(s.encode() in line for s in secrets)))
                        if updated == data: continue
                        clean.write(updated)
                    else:
                        if not redact_stream(src.extractfile(member), clean, secrets): continue
                    member.size = clean.tell(); clean.seek(0)
                    dst.addfile(member, clean); count += 1
        if count:
            sanitized.seek(0)
            parent = PurePosixPath(root).parent
            subprocess.run(['docker', 'cp', '-a', '-', f'{cid}:{parent}/'], stdin=sanitized,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def require_storage_space(target: Path):
    # Leave room for Docker's daemon/VM and unrelated services. This is checked
    # during archive streaming too, so a large model cannot fill the host disk.
    checked=set()
    for directory in (target.parent,Path(tempfile.gettempdir())):
        device=directory.stat().st_dev
        if device in checked:continue
        checked.add(device)
        if shutil.disk_usage(directory).free < 3 * 1024**3:
            raise OSError('checkpoint or local runtime storage below 3 GiB reserve; free disk space and retry this checkpoint')


def write_docker_archive(args, path):
    require_storage_space(path)
    with tempfile.TemporaryFile() as errors, path.open('wb') as output:
        process=subprocess.Popen(['docker',*map(str,args)],stdout=subprocess.PIPE,stderr=errors)
        try:
            while chunk:=process.stdout.read(1024*1024):
                require_storage_space(path)
                output.write(chunk)
            code=process.wait()
            if code:
                errors.seek(0)
                raise RuntimeError(redact('Docker archive failed: '+errors.read(2000).decode(errors='replace')))
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            process.stdout.close()


def serialized_capture(function):
    @functools.wraps(function)
    def wrapped(containers,target,names,secrets):
        # A common lock serializes disk-heavy snapshots across independent runs.
        # Only task capture is serialized; model execution remains concurrent.
        with open(Path(tempfile.gettempdir())/'wetlab-checkpoint-storage.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            require_storage_space(target/'images.tar')
            return function(containers,target,names,secrets)
    return wrapped


@serialized_capture
def capture_services(containers, target: Path, names, secrets):
    """Freeze a consistent filesystem cut, including tmpfs, before removal."""
    services = {}
    task_containers = freeze_containers(containers, names)
    for cid, svc in task_containers:
        if svc == 'main': sanitize_agent_logs(cid, secrets)
        data = inspect_container(cid)
        for value in secrets:
            if value in json.dumps(data['Config']):
                raise ValueError(f'credential in {svc} container configuration')
        mounts = []
        raw_mounts = list(data.get('Mounts', []))
        known_dest = {x['Destination'] for x in raw_mounts}
        for dest in data['HostConfig'].get('Tmpfs', {}):
            if dest not in known_dest:
                raw_mounts.append({'Type': 'tmpfs', 'Destination': dest, 'RW': True})
        for index, mount in enumerate(raw_mounts):
            if mount['Type'] not in ('bind', 'volume', 'tmpfs'):
                raise ValueError(f'unsupported mount type: {mount["Type"]}')
            dest = mount['Destination']
            if dest in INTERNAL:
                if data['Config'].get('Entrypoint') != WRAPPER:
                    raise ValueError(f'reserved framework mount: {dest}')
                continue
            if dest in ('/', '/proc', '/sys', '/dev') or dest.endswith('docker.sock'):
                raise ValueError(f'cannot checkpoint special mount: {dest}')
            rel = f'mounts/{svc}/{index}.tar'
            inventory = capture_archive(cid, dest, target / rel, tmpfs=mount['Type'] == 'tmpfs')
            reject_secrets(target / rel, secrets)
            mounts.append({'type': mount['Type'], 'destination': dest, 'read_only': not mount.get('RW', True),
                           'source_name': mount.get('Name') or mount.get('Source'),
                           'archive': rel, 'inventory': inventory,
                           'directory': inventory.get('', {}).get('type') == '5'})
        prefix = re.sub(r'[^a-z0-9_.-]', '-', target.parent.parent.name.lower())
        # Different runs often share the basename "run". A shared tag lets a
        # concurrent commit win between commit() and inspect(), returning the
        # other run's immutable image ID. Scope it to this checkpoint location.
        prefix += '-' + hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:16]
        # Resolve the tag through inspect; CLI diagnostics must never become an image ID.
        tag = f'wetlab-ckpt/{prefix}-{svc}:{target.name.strip(".")}'
        docker('commit', cid, tag)
        ref = image_id(tag)
        health = data['Config'].get('Healthcheck') or {}
        health_config = {'test': health['Test']} if health.get('Test') else {}
        for original, name in [('Interval','interval'),('Timeout','timeout'),('StartPeriod','start_period')]:
            if health.get(original): health_config[name] = f'{health[original]}ns'
        if health.get('Retries'): health_config['retries'] = health['Retries']
        startup = {'entrypoint': data['Config'].get('Entrypoint') or [], 'command': data['Config'].get('Cmd') or [],
                   'healthcheck': health_config}
        if data['Config'].get('Entrypoint') == WRAPPER:
            startup = json.loads((data['Config'].get('Labels') or {})['wetlab.checkpoint-startup'])
        services[svc] = {'image_id': ref, 'mounts': mounts, **startup,
                         'working_dir': data['Config'].get('WorkingDir') or '/', 'user': data['Config'].get('User') or '',
                         'environment': dict(x.split('=',1) for x in data['Config'].get('Env') or [])}
    refs = [s['image_id'] for s in services.values()]
    if not refs: raise ValueError('no task containers to capture')
    write_docker_archive(['save',*refs],target/'images.tar')
    scan_image_archive(target / 'images.tar', secrets)
    return services


def _helper_mount(source, target, readonly=False, kind='bind'):
    return f'type={kind},source={source},target={target}' + (',readonly' if readonly else '')


def materialize(archive: Path, staging: Path, mount: dict):
    """Use a private bind directory; preserve file, directory, permissions and links."""
    staging.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tf:
        first = next(iter(tf)).name.rstrip('/')
    if first.startswith('/') or len(PurePosixPath(first).parts) != 1 or first in ('', '.', '..'):
        raise ValueError('unexpected mount archive root')
    docker('run', '--rm', '--network', 'none', '--mount', _helper_mount(staging, '/restore'),
           '--mount', _helper_mount(archive, '/archive.tar', True), HELPER, 'tar', '-xpf', '/archive.tar', '-C', '/restore')
    restored = staging / first
    # Re-archive and compare semantic contents rather than unstable tar byte order.
    check = staging.with_name(staging.name + '.verification.tar')
    try:
        with check.open('wb') as out:
            subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--mount', _helper_mount(staging, '/restore', True),
                            HELPER, 'tar', '-cpf', '-', '-C', '/restore', first], stdout=out, stderr=subprocess.PIPE, check=True)
        if archive_inventory(check) != mount['inventory']:
            raise ValueError('restored mount contents/metadata do not match checkpoint')
    finally:
        check.unlink(missing_ok=True)
    return restored


def materialize_volume(archive, staging, mount):
    name = 'wetlab-restore-' + hashlib.sha256(str(staging).encode()).hexdigest()[:24]
    docker('volume', 'create', '--label', 'wetlab.restore=true', name)
    meta = mount['inventory'].get('', {})
    command = 'tar -xpf /archive.tar --strip-components=1 -C /restore'
    if meta:
        command += f'; chown {meta["uid"]}:{meta["gid"]} /restore; chmod {meta["mode"]:o} /restore'
    docker('run', '--rm', '--network', 'none', '--mount', _helper_mount(name, '/restore', kind='volume'),
           '--mount', _helper_mount(archive, '/archive.tar', True), HELPER, 'sh', '-ec', command)
    staging.parent.mkdir(parents=True, exist_ok=True)
    check = staging.with_suffix('.verification.tar')
    try:
        with check.open('wb') as out:
            subprocess.run(['docker','run','--rm','--network','none','--mount',_helper_mount(name,'/restore',True,'volume'),
                            HELPER,'tar','-cpf','-','-C','/restore','.'], stdout=out, stderr=subprocess.PIPE, check=True)
        if archive_inventory(check) != mount['inventory']:
            raise ValueError('restored volume contents/metadata do not match checkpoint')
    finally:
        check.unlink(missing_ok=True)
    return name


def restore_compose(root: Path, manifest: dict, environment: Path, stage: Path):
    import yaml
    path = environment / 'docker-compose.yaml'
    compose = yaml.safe_load(path.read_text()) if path.exists() else {}
    compose = compose or {}
    services = compose.setdefault('services', {})
    shared = {}
    for svc, saved in manifest['services'].items():
        config = services.setdefault(svc, {})
        config.pop('build', None)
        config.pop('env_file', None)
        config['image'] = saved['image_id']
        # These are already-expanded runtime values. Do not let Compose expand
        # dollars a second time against the controller's current environment.
        if 'environment' in saved: config['environment'] = {k:v.replace('$','$$') for k,v in saved['environment'].items()}
        for field in ('entrypoint','command'):
            if field in saved: config[field] = [x.replace('$','$$') for x in saved[field]]
        for field in ('working_dir','user'):
            if field in saved: config[field] = saved[field].replace('$','$$')
        mounts, tmpfs = [], []
        for index, mount in enumerate(saved['mounts']):
            dest = mount['destination']
            if svc == 'main' and dest in MANAGED:
                # Harbor creates these dynamically; worker restores their new host source before start.
                continue
            if mount['type'] == 'tmpfs':
                tmpfs.append(mount)
                continue
            identity = (mount['type'], mount.get('source_name'), mount['archive'] if not mount.get('source_name') else '')
            if identity not in shared:
                restore = materialize_volume if mount['type'] == 'volume' else materialize
                shared[identity] = restore(root / mount['archive'], stage / f'{svc}-{index}', mount)
            kind = 'volume' if mount['type'] == 'volume' else 'bind'
            if kind == 'volume': compose.setdefault('volumes', {})[shared[identity]] = {'external': True}
            mounts.append({'type': kind, 'source': str(shared[identity]), 'target': dest,
                           'read_only': mount['read_only']})
        config['volumes'] = mounts
        if tmpfs:
            restore_dir = stage / f'{svc}-tmpfs'
            restore_dir.mkdir(parents=True, exist_ok=True)
            lines = ['#!/bin/sh', 'set -eu']
            for i, mount in enumerate(tmpfs):
                shutil.copy2(root / mount['archive'], restore_dir / f'{i}.tar')
                dest = shlex.quote(mount['destination'])
                lines += [f'tar -xpf /wetlab-restore/{i}.tar --strip-components=1 -C {dest}']
                meta = mount['inventory'].get('', {})
                if meta:
                    lines += [f'chown {meta["uid"]}:{meta["gid"]} {dest}', f'chmod {meta["mode"]:o} {dest}']
            lines += ['touch /run/wetlab-internal/ready', 'exec "$@"']
            (restore_dir / 'restore.sh').write_text('\n'.join(lines) + '\n')
            config['volumes'].append({'type': 'bind', 'source': str(restore_dir), 'target': '/wetlab-restore', 'read_only': True})
            config['entrypoint'] = WRAPPER
            config['command'] = [x.replace('$','$$') for x in saved['entrypoint'] + saved['command']]
            labels = config.get('labels') or {}
            if isinstance(labels, list): labels = dict(x.split('=', 1) for x in labels)
            labels['wetlab.checkpoint-startup'] = json.dumps({k:saved[k] for k in ['entrypoint','command','healthcheck']}).replace('$','$$')
            config['labels'] = labels
            raw_tmpfs = config.get('tmpfs') or []
            if isinstance(raw_tmpfs, dict): raw_tmpfs = [f'{k}:{v}' if v else k for k,v in raw_tmpfs.items()]
            config['tmpfs'] = [x for x in raw_tmpfs if x.split(':')[0] != '/run/wetlab-internal'] + ['/run/wetlab-internal:mode=700']
            health = dict(saved.get('healthcheck') or {})
            old = health.get('test', [])
            probe = 'test -f /run/wetlab-internal/ready'
            if old and old[0] != 'NONE':
                command = old if isinstance(old, str) else old[1] if old[0] == 'CMD-SHELL' else shlex.join(old[1:])
                probe += ' && (' + command + ')'
            health['test'] = ['CMD-SHELL', probe.replace('$','$$')]
            health.setdefault('interval','1s');health.setdefault('timeout','5s');health.setdefault('retries',100)
            health.pop('disable', None)
            config['healthcheck'] = health
    path.write_text(yaml.safe_dump(compose, sort_keys=False))


def restore_managed_mounts(root, manifest, host_mounts, stage):
    """Called before Docker.start, while Harbor's log bind directories are inactive."""
    saved = {m['destination']: m for m in manifest['services']['main']['mounts'] if m['destination'] in MANAGED}
    for current in host_mounts:
        if current['target'] not in saved: continue
        mount = saved[current['target']]
        source = Path(current['source'])
        restored = materialize(root / mount['archive'], stage / current['target'].strip('/').replace('/', '-'), mount)
        source.mkdir(parents=True, exist_ok=True)
        # Copy inside Docker to preserve numeric owner/mode on Linux hosts too.
        docker('run', '--rm', '--network', 'none', '--mount', _helper_mount(restored, '/from', True),
               '--mount', _helper_mount(source, '/to'), HELPER, 'sh', '-c', 'cp -a /from/. /to/')
