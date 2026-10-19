"""Operator installer runtime, embedded by build_installer.py. No key is embedded."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path('/opt/trendatlas-clean')
STATE = Path('/var/lib/trendatlas-clean')
INSTALL = Path('/var/lib/trendatlas-clean-install')
CONFIG = Path('/etc/trendatlas-clean/policy.json')
OLD = Path('/opt/trendatlas-production/current')
UNIT = 'trendatlas-clean-production'
SYSTEMD = Path('/etc/systemd/system')


def emit(phase, **fields):
    print(json.dumps({'phase':phase,'time_utc':datetime.now(timezone.utc).isoformat(), **fields}),flush=True)


def run(args, **kw):
    # Arguments contain paths/public config only. Never echo credentials or SDK exceptions.
    result=subprocess.run([str(x) for x in args], check=False, **kw)
    if result.returncode:
        raise RuntimeError('COMMAND_FAILED:'+str(args[0])+':'+str(result.returncode))
    return result


def capture(args):
    return run(args,capture_output=True,text=True).stdout.strip()


def atomic_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.clean-install-')
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(value,out,indent=2,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
        os.chmod(tmp,0o640);os.replace(tmp,path)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()


def unpack(body, destination):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        manifest=json.loads(archive.read('BUNDLE_MANIFEST.json'))
        names=set(archive.namelist())
        if names != set(manifest)|{'BUNDLE_MANIFEST.json'}:
            raise ValueError('BUNDLE_MANIFEST_MISMATCH')
        for name,digest in manifest.items():
            p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or archive.getinfo(name).external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError('UNSAFE_BUNDLE_PATH')
            data=archive.read(name)
            if hashlib.sha256(data).hexdigest()!=digest:
                raise ValueError('BUNDLE_FILE_HASH_MISMATCH')
            path=destination.joinpath(*p.parts);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (destination/'BUNDLE_MANIFEST.json').write_bytes(archive.read('BUNDLE_MANIFEST.json'))
    return manifest


def old_disabled():
    flags=json.loads((OLD/'execution/config/execution_mode.json').read_text())
    if flags.get('kill_switch') is not True or flags.get('trading_enabled') is not False:
        raise ValueError('PHASE68G_IS_NOT_DISABLED')
    for kind in ('timer','service'):
        active=subprocess.run(['systemctl','is-active','mrv1-production.'+kind],capture_output=True,text=True).stdout.strip()
        if active not in {'inactive','failed'}:
            raise ValueError('PHASE68G_STILL_ACTIVE')


def python_runtime(args):
    candidates=[args.python] if args.python else [str(OLD/'.venv/bin/python'),'/usr/bin/python3.12','/usr/bin/python3.13',sys.executable]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():continue
        p=subprocess.run([candidate,'-c','import sys; print("%d.%d"%sys.version_info[:2])'],capture_output=True,text=True)
        if p.returncode==0 and p.stdout.strip() in {'3.11','3.12','3.13'}:
            base=subprocess.check_output([candidate,'-c','import sys; print(sys._base_executable)'],text=True).strip()
            resolved=str(Path(base).resolve())
            if resolved.startswith('/usr/') or resolved.startswith(str(ROOT/'python')+'/'):
                return resolved
    # Ubuntu 26.04 may supply Python 3.14. Keep the validated pandas runtime
    # isolated; never replace Ubuntu's interpreter or the old production venv.
    emit('INSTALL_ISOLATED_PYTHON_312')
    run(['apt-get','update','-qq'])
    run(['apt-get','install','-y','-qq','python3-venv','ca-certificates'])
    bootstrap=ROOT/'bootstrap-venv'
    run([sys.executable,'-m','venv',bootstrap])
    run([bootstrap/'bin/python','-m','pip','install','--disable-pip-version-check','uv==0.9.2'])
    env=dict(os.environ,UV_PYTHON_INSTALL_DIR=str(ROOT/'python'),UV_CACHE_DIR=str(ROOT/'uv-cache'))
    run([bootstrap/'bin/uv','python','install','3.12'],env=env)
    return subprocess.check_output(
        [str(bootstrap/'bin/uv'),'python','find','3.12'],env=env,text=True).strip()



def environment_source():
    path=Path('/etc/trendatlas-production/multi-account.env')
    stat=path.stat()
    if not path.is_file() or stat.st_uid!=0 or stat.st_mode & 0o007:
        raise ValueError('MULTI_ACCOUNT_ENV_MUST_BE_ROOT_OWNED_NOT_WORLD_READABLE')
    # systemd parses the existing file. Do not source, print, copy or rewrite it.
    return path


def node_runtime():
    candidates=[shutil.which('node'),'/usr/bin/node','/usr/local/bin/node',str(OLD/'node/bin/node')]
    for node in candidates:
        if not node or not Path(node).is_file():continue
        result=subprocess.run([node,'--version'],capture_output=True,text=True)
        if result.returncode==0 and re.match(r'^v(22|24)\.',result.stdout.strip()):return str(Path(node).resolve())
    raise ValueError('SUPPORTED_NODE_22_OR_24_NOT_FOUND')


def systemd_worker(release,node,envfile,no_submit=True):
    args=['systemd-run','--quiet','--wait','--collect','--unit=clean-preflight-'+str(os.getpid()),
          '--uid=trendatlas-clean','--gid=trendatlas-clean',
          '--property=EnvironmentFile='+str(envfile),'--property=WorkingDirectory='+str(release/'web'),
          '--property=UMask=0077','--setenv=TRENDATLAS_CLEAN_WORKER=1',
          '--setenv=TRENDATLAS_CLEAN_STATE_DIR='+str(STATE/'state'),
          '--setenv=TRENDATLAS_CLEAN_CONFIG='+str(CONFIG),
          node,'--conditions=react-server','--import','tsx','scripts/run-clean-multi-account.ts']
    if no_submit:args.append('--no-submit')
    run(args)


def install(args):
    INSTALL.mkdir(parents=True,exist_ok=True);os.chmod(INSTALL,0o700)
    if any(subprocess.run(['systemctl','is-active',UNIT+'.'+suffix],capture_output=True,text=True).stdout.strip()=='active' for suffix in ('service','timer')):
        emit('CLEAN_ALREADY_ACTIVE_READBACK_ONLY',status_path=str(INSTALL/'status.json'));return
    report={'source_commit':args.source_commit,'bundle_sha256':BUNDLE_SHA256,'status':'INSTALLING_MULTI_ACCOUNT','live_activation_possible':False}
    atomic_json(INSTALL/'status.json',report)
    old_disabled();envfile=environment_source();node=node_runtime()
    for suffix in ('timer','service'):
        if subprocess.run(['systemctl','is-active',UNIT+'.'+suffix],capture_output=True,text=True).stdout.strip()=='active':
            raise ValueError('CLEAN_ALREADY_ACTIVE_USE_EXISTING_JOURNAL')
    payload=base64.b64decode(BUNDLE_B64)
    if hashlib.sha256(payload).hexdigest()!=BUNDLE_SHA256:raise ValueError('BUNDLE_HASH_MISMATCH')
    release=ROOT/'releases'/args.source_commit
    if not release.exists():
        staging=ROOT/'releases'/('.staging-'+args.source_commit);staging.mkdir(parents=True,exist_ok=True)
        manifest=unpack(payload,staging)
        atomic_json(staging/'SOURCE.json',{'source_commit':args.source_commit,'bundle_sha256':BUNDLE_SHA256,'files':manifest})
        staging.rename(release)
    else:
        source=json.loads((release/'SOURCE.json').read_text())
        if source['bundle_sha256']!=BUNDLE_SHA256:raise ValueError('EXISTING_RELEASE_HAS_OTHER_BUNDLE')
        for name,digest in source['files'].items():
            if hashlib.sha256((release/name).read_bytes()).hexdigest()!=digest:raise ValueError('EXISTING_RELEASE_MODIFIED')
    config=json.loads((release/'execution/config/clean_5050_policy.json').read_text())
    config.update(kill_switch=True,trading_enabled=False);atomic_json(CONFIG,config)
    runtime=python_runtime(args);run([runtime,'-m','venv',release/'.venv']);py=release/'.venv/bin/python'
    run([py,'-m','pip','install','--disable-pip-version-check','-r',release/'requirements-clean-execution.txt'])
    env=dict(os.environ,PYTHONPATH=str(release/'src'),PATH=str(Path(node).parent)+os.pathsep+os.environ.get('PATH',''))
    npm=shutil.which('npm',path=env['PATH'])
    if not npm:raise ValueError('NPM_NOT_FOUND')
    emit('RUN_SIGNAL_AND_MULTI_ACCOUNT_TESTS')
    run([py,'-m','unittest','discover','-s','tests','-p','test_clean_5050*.py','-v'],cwd=release,env=env)
    run([npm,'ci','--no-audit','--no-fund'],cwd=release/'web',env=env)
    for task in ('test','typecheck','build'):run([npm,'run',task],cwd=release/'web',env=env)
    emit('VERIFY_18_CHECKPOINTS_AND_SIGNAL_TIMING')
    validation_data=STATE/'validation-data'
    run([py,release/'scripts/research/fetch_clean_5050_data.py','--data-dir',validation_data,'--end','2026-10-17'],env=env)
    run([py,release/'scripts/research/validate_clean_5050.py','--data-dir',validation_data,'--end','2026-10-17','--output-dir',STATE/'validation-results','--prefix-tests','25'],env=env)
    validation=json.loads((STATE/'validation-results/validation.json').read_text())
    if not validation.get('passed') or validation.get('checkpoint_matches')!=18:raise ValueError('HISTORICAL_REFERENCE_VALIDATION_FAILED')
    emit('BUILD_CURRENT_SIGNAL_AND_COST_METRICS')
    if not (STATE/'data').exists():shutil.copytree(validation_data,STATE/'data')
    run([py,release/'scripts/production/run_clean_5050.py','--data-dir',STATE/'data','--state-dir',STATE/'state','--universe','all','--refresh'],env=env)
    try:identity=pwd.getpwnam('trendatlas-clean')
    except KeyError:
        run(['useradd','--system','--home-dir',STATE,'--shell','/usr/sbin/nologin','trendatlas-clean']);identity=pwd.getpwnam('trendatlas-clean')
    run(['chown','-R','trendatlas-clean:trendatlas-clean',STATE]);run(['chmod','-R','a+rX',release])
    ROOT.chmod(0o755);(ROOT/'releases').chmod(0o755)
    if (ROOT/'python').exists():run(['chmod','-R','a+rX',ROOT/'python'])
    os.chown(CONFIG,0,identity.pw_gid);os.chmod(CONFIG,0o640);os.chmod(CONFIG.parent,0o750);os.chown(CONFIG.parent,0,identity.pw_gid)
    old_disabled();emit('READ_ONLY_MULTI_ACCOUNT_PREFLIGHT')
    systemd_worker(release,node,envfile)
    preflight=json.loads((STATE/'state/multi_account_preflight.json').read_text())
    if not preflight.get('preflight_passed') or preflight.get('account_count',0)<1:raise ValueError('MULTI_ACCOUNT_PREFLIGHT_FAILED')
    old_disabled()
    current=ROOT/'current';temp=ROOT/'.current-next'
    if temp.is_symlink():temp.unlink()
    temp.symlink_to(release,target_is_directory=True);os.replace(temp,current)
    # A prior failed single-key installer may have left this exact drop-in.
    drop=SYSTEMD/(UNIT+'.service.d/10-credential.conf')
    if drop.exists():drop.unlink()
    for suffix in ('service','timer'):
        body=(release/('deploy/systemd/'+UNIT+'.'+suffix)).read_text().replace('@NODE@',node)
        (SYSTEMD/(UNIT+'.'+suffix)).write_text(body)
    run(['systemctl','daemon-reload']);run(['systemd-analyze','verify',SYSTEMD/(UNIT+'.service'),SYSTEMD/(UNIT+'.timer')])
    report.update(status='TESTED_MULTI_ACCOUNT_NOT_ACTIVATED',account_count=preflight['account_count'])
    atomic_json(INSTALL/'status.json',report)
    if not args.activate_live:emit(report['status']);return
    for unit in ('mrv1-production.timer','trendatlas-clean-signal.timer'):
        if subprocess.run(['systemctl','cat',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:run(['systemctl','disable','--now',unit])
    old_disabled()
    config.update(kill_switch=False,trading_enabled=True);atomic_json(CONFIG,config);os.chown(CONFIG,0,identity.pw_gid)
    report.update(status='ACTIVATING_MULTI_ACCOUNT',live_activation_possible=True);atomic_json(INSTALL/'status.json',report)
    run(['systemctl','enable','--now',UNIT+'.timer']);run(['systemctl','start',UNIT+'.service'])
    receipt=json.loads((STATE/'state/multi_account_receipt.json').read_text())
    if not receipt.get('all_accounts_aligned'):raise ValueError('ACCOUNT_RECONCILIATION_INCOMPLETE_SEE_RECEIPT')
    report.update(status='CLEAN_MULTI_ACCOUNT_LIVE_AND_ALIGNED',old_phase68g_disabled=True,receipt=str(STATE/'state/multi_account_receipt.json'))
    atomic_json(INSTALL/'status.json',report);emit(report['status'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit',required=True);parser.add_argument('--activate-live',action='store_true');parser.add_argument('--foreground',action='store_true');parser.add_argument('--python');args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('SUDO_REQUIRED')
    if not re.fullmatch('[0-9a-f]{40}',args.source_commit):raise ValueError('FULL_SOURCE_COMMIT_REQUIRED')
    INSTALL.mkdir(parents=True,exist_ok=True);os.chmod(INSTALL,0o700)
    if not args.foreground:
        script=INSTALL/('bootstrap-multi-'+args.source_commit+'.py')
        script.write_text('BUNDLE_B64='+repr(BUNDLE_B64)+'\nBUNDLE_SHA256='+repr(BUNDLE_SHA256)+'\nRUNTIME_SOURCE='+repr(RUNTIME_SOURCE)+'\nexec(compile(RUNTIME_SOURCE,"bootstrap_multi_account","exec"))\n');os.chmod(script,0o600)
        cmd=['systemd-run','--unit=trendatlas-clean-install-'+args.source_commit[:12]+'-'+str(os.getpid()),'--property=Type=exec','--property=UMask=0077',sys.executable,script,'--source-commit',args.source_commit,'--foreground']
        if args.activate_live:cmd.append('--activate-live')
        if args.python:cmd.extend(['--python',args.python])
        run(cmd);emit('INSTALL_SCHEDULED_ON_VPS',status_path=str(INSTALL/'status.json'),continues_without_laptop=True);return
    # Never run two installers concurrently.
    import fcntl
    with (INSTALL/'install.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:install(args)
        except BaseException as exc:
            p=INSTALL/'status.json';report=json.loads(p.read_text()) if p.exists() else {}
            report.update(status='INSTALL_FAILED_RECONCILE_REQUIRED' if report.get('live_activation_possible') else 'INSTALL_FAILED_BEFORE_ACTIVATION',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__)
            atomic_json(p,report);emit(report['status'],reason=report['reason']);raise SystemExit(2)

if __name__=='__main__':main()
