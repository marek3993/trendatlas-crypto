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
    return manifest


def credential_spec():
    raw=capture(['systemctl','show','mrv1-production.service','--property=LoadCredentialEncrypted','--value'])
    specs=[x for x in raw.split() if x.startswith('hyperliquid-agent-private-key:')]
    if len(specs)!=1:
        raise ValueError('EXISTING_NAMED_ENCRYPTED_CREDENTIAL_NOT_FOUND')
    # Only an encrypted source path is handed to systemd. Never decrypt/copy its contents.
    spec=specs[0]
    source=spec.split(':',1)[1]
    if not source.startswith('/') or '\n' in source or not Path(source).is_file():
        raise ValueError('ENCRYPTED_CREDENTIAL_SOURCE_UNAVAILABLE')
    return spec


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


def install(args):
    INSTALL.mkdir(parents=True,exist_ok=True);os.chmod(INSTALL,0o700)
    report={'source_commit':args.source_commit,'bundle_sha256':BUNDLE_SHA256,'status':'INSTALLING','live_activation_possible':False}
    atomic_json(INSTALL/'status.json',report)
    old_disabled()
    spec=credential_spec()
    payload=base64.b64decode(BUNDLE_B64)
    if hashlib.sha256(payload).hexdigest()!=BUNDLE_SHA256:raise ValueError('BUNDLE_HASH_MISMATCH')
    release=ROOT/'releases'/args.source_commit
    if not release.exists():
        staging=ROOT/'releases'/('.staging-'+args.source_commit)
        staging.mkdir(parents=True,exist_ok=True)
        manifest=unpack(payload,staging)
        atomic_json(staging/'SOURCE.json',{'source_commit':args.source_commit,'bundle_sha256':BUNDLE_SHA256,'files':manifest})
        staging.rename(release)
    else:
        source=json.loads((release/'SOURCE.json').read_text())
        if source['bundle_sha256']!=BUNDLE_SHA256:raise ValueError('EXISTING_RELEASE_HAS_OTHER_BUNDLE')
        for name,digest in source['files'].items():
            if hashlib.sha256((release/name).read_bytes()).hexdigest()!=digest:raise ValueError('EXISTING_RELEASE_MODIFIED')
    if not CONFIG.exists():atomic_json(CONFIG,json.loads((release/'execution/config/clean_5050_policy.json').read_text()))
    elif subprocess.run(['systemctl','is-active',UNIT+'.timer'],capture_output=True,text=True).stdout.strip()=='active':
        raise ValueError('CLEAN_ALREADY_ACTIVE_USE_EXISTING_JOURNAL_DO_NOT_REINSTALL_LIVE')
    config=json.loads(CONFIG.read_text());config.update(kill_switch=True,trading_enabled=False);atomic_json(CONFIG,config)
    ROOT.chmod(0o755);(ROOT/'releases').chmod(0o755);release.chmod(0o755)
    runtime=python_runtime(args)
    run([runtime,'-m','venv',release/'.venv'])
    py=release/'.venv/bin/python'
    emit('INSTALL_DEPENDENCIES')
    run([py,'-m','pip','install','--disable-pip-version-check','-r',release/'requirements-clean-execution.txt'])
    run(['chmod','-R','a+rX',release])
    if (ROOT/'python').exists():run(['chmod','-R','a+rX',ROOT/'python'])
    emit('RUN_UNIT_AND_EXCHANGE_SIMULATION_TESTS')
    env=dict(os.environ,PYTHONPATH=str(release/'src'))
    run([py,'-m','unittest','discover','-s','tests','-p','test_clean_5050*.py','-v'],cwd=release,env=env)
    emit('FETCH_FROZEN_59_AND_VALIDATE_18_CHECKPOINTS')
    validation_data=STATE/'validation-data'
    run([py,release/'scripts/research/fetch_clean_5050_data.py','--data-dir',validation_data,'--end','2026-10-17'],env=env)
    run([py,release/'scripts/research/validate_clean_5050.py','--data-dir',validation_data,'--end','2026-10-17',
         '--output-dir',STATE/'validation-results','--prefix-tests','25'],env=env)
    result=json.loads((STATE/'validation-results/validation.json').read_text())
    if not result.get('passed') or result['checkpoint_matches']!=18:
        raise ValueError('HISTORICAL_REFERENCE_VALIDATION_FAILED')
    emit('BUILD_CURRENT_FULL_UNIVERSE_SIGNAL')
    STATE.mkdir(parents=True,exist_ok=True)
    if not (STATE/'data').exists():shutil.copytree(validation_data,STATE/'data')
    run([py,release/'scripts/production/run_clean_5050.py','--data-dir',STATE/'data','--state-dir',STATE/'state','--universe','all','--refresh'],env=env)
    old_disabled()
    try:identity=pwd.getpwnam('trendatlas-clean')
    except KeyError:
        run(['useradd','--system','--home-dir',STATE,'--shell','/usr/sbin/nologin','trendatlas-clean'])
        identity=pwd.getpwnam('trendatlas-clean')
    run(['chown','-R','trendatlas-clean:trendatlas-clean',STATE])
    os.chown(CONFIG,0,identity.pw_gid);os.chmod(CONFIG,0o640)
    os.chmod(CONFIG.parent,0o750);os.chown(CONFIG.parent,0,identity.pw_gid)
    emit('VERIFY_SIGNER_AND_READ_ONLY_ACCOUNT_PLAN')
    verifyunit='trendatlas-clean-preflight-'+str(os.getpid())
    run(['systemd-run','--quiet','--wait','--collect','--unit='+verifyunit,'--uid=trendatlas-clean','--gid=trendatlas-clean',
         '--property=LoadCredentialEncrypted='+spec,'--property=UMask=0077',
         py,release/'scripts/production/execute_clean_5050.py','--signal',STATE/'state/signal.json',
         '--state-dir',STATE/'state','--config',CONFIG,'--verify-signer-only'])
    preflight=json.loads((STATE/'state/execution_preflight.json').read_text())
    if not preflight.get('signer_verified'):raise ValueError('SIGNER_PREFLIGHT_FAILED')
    # Genuine missing ENTRY markets are reported, but must not suppress needed EXITs.
    report['entry_blockers']=preflight['plan']['entry_blockers']
    report['exit_blockers']=preflight['plan']['exit_blockers']
    old_disabled()
    # Install new unit paths only after all tests. The old kill switch is never cleared.
    current=ROOT/'current';temp=ROOT/'.current-next'
    if temp.is_symlink():temp.unlink()
    temp.symlink_to(release,target_is_directory=True);os.replace(temp,current)
    for suffix in ('service','timer'):
        shutil.copy2(release/('deploy/systemd/'+UNIT+'.'+suffix),SYSTEMD/(UNIT+'.'+suffix))
    drop=SYSTEMD/(UNIT+'.service.d');drop.mkdir(exist_ok=True)
    (drop/'10-credential.conf').write_text('[Service]\nLoadCredentialEncrypted='+spec+'\n')
    os.chmod(drop/'10-credential.conf',0o600)
    run(['systemctl','daemon-reload'])
    run(['systemd-analyze','verify',SYSTEMD/(UNIT+'.service'),SYSTEMD/(UNIT+'.timer')])
    if not args.activate_live:
        report['status']='TESTED_NOT_ACTIVATED';atomic_json(INSTALL/'status.json',report);emit(report['status']);return
    # Retire the obsolete signal-only unit, never research or other services.
    for unit in ('mrv1-production.timer','trendatlas-clean-signal.timer'):
        if subprocess.run(['systemctl','cat',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            run(['systemctl','disable','--now',unit])
    old_disabled()
    config.update(kill_switch=False,trading_enabled=True);atomic_json(CONFIG,config)
    os.chown(CONFIG,0,identity.pw_gid)
    report.update(status='ACTIVATING',live_activation_possible=True);atomic_json(INSTALL/'status.json',report)
    run(['systemctl','enable','--now',UNIT+'.timer'])
    # Start the canonical new service once. It produces a fresh signal then
    # reconciles the account. Repeated starts use the same-day durable journal.
    run(['systemctl','start',UNIT+'.service'])
    receipt=json.loads((STATE/'state/execution_receipt.json').read_text())
    if not receipt.get('account_aligned',receipt.get('readback',{}).get('aligned',False)):
        raise ValueError('LIVE_RECONCILIATION_NOT_COMPLETE_CHECK_RECEIPT')
    report.update(status='CLEAN_LIVE_AND_ALIGNED',receipt_path=str(STATE/'state/execution_receipt.json'),
                  old_phase68g_disabled=True,timer=capture(['systemctl','is-enabled',UNIT+'.timer']),
                  next_trigger=capture(['systemctl','show',UNIT+'.timer','--property=NextElapseUSecRealtime','--value']))
    atomic_json(INSTALL/'status.json',report);emit(report['status'],**{k:v for k,v in report.items() if k!='status'})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--activate-live',action='store_true')
    parser.add_argument('--foreground',action='store_true')
    parser.add_argument('--python')
    args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('SUDO_REQUIRED')
    if not re.fullmatch('[0-9a-f]{40}',args.source_commit):raise ValueError('FULL_SOURCE_COMMIT_REQUIRED')
    if not args.foreground:
        INSTALL.mkdir(parents=True,exist_ok=True);os.chmod(INSTALL,0o700)
        path=INSTALL/'bootstrap.py'
        path.write_text('BUNDLE_B64='+repr(BUNDLE_B64)+'\nBUNDLE_SHA256='+repr(BUNDLE_SHA256)+'\nRUNTIME_SOURCE='+repr(RUNTIME_SOURCE)+'\nexec(compile(RUNTIME_SOURCE,"bootstrap_runtime","exec"))\n')
        os.chmod(path,0o600)
        cmd=['systemd-run','--unit=trendatlas-clean-install','--property=Type=exec','--property=UMask=0077',
             sys.executable,path,'--source-commit',args.source_commit,'--foreground']
        if args.activate_live:cmd.append('--activate-live')
        if args.python:cmd.extend(['--python',args.python])
        run(cmd)
        emit('INSTALL_SCHEDULED_ON_VPS',continues_without_laptop=True,
             watch='sudo journalctl -fu trendatlas-clean-install.service',status=str(INSTALL/'status.json'))
        return
    try:install(args)
    except BaseException as exc:
        p=INSTALL/'status.json'
        report=json.loads(p.read_text()) if p.exists() else {}
        report.update(status='INSTALL_FAILED_RECONCILE_REQUIRED' if report.get('live_activation_possible') else 'INSTALL_FAILED_BEFORE_ACTIVATION',
                      error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__)
        atomic_json(p,report);emit(report['status'],reason=report['reason']);raise SystemExit(2)


if __name__=='__main__':main()
