"""Pi fencing and retirement, invoked only by the operator coordinator."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
from datetime import datetime, timezone

STATE=Path('/var/lib/trendatlas-migration')
FENCE=Path('/etc/systemd/system/mrv1-production.service.d/90-migration-fence.conf')
PATTERNS=('mrv1-','trendatlas-','research_os_pi','home-dashboard-kiosk','/opt/market_regime_v1','/opt/home_automation')


def run(*args,allowed=(0,)):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode not in allowed: raise RuntimeError('Pi operation failed: '+args[0])
    return p.stdout.strip()


def matching(text): return any(p in text.lower() for p in PATTERNS)


def inventory():
    import pwd
    units=[]
    for row in run('systemctl','list-unit-files','--no-legend','--no-pager').splitlines():
        unit=row.split()[0]
        # Audited independent voice application; shared user/dependencies are not ownership.
        if unit=='ai-hologram.service': continue
        if not unit.endswith(('.service','.timer','.socket','.path')): continue
        fragment=run('systemctl','show',unit,'-p','FragmentPath','--value',allowed=(0,1))
        if not fragment:
            fragment=next((str(p) for base in ('/etc/systemd/system','/usr/lib/systemd/system','/lib/systemd/system')
                if (p:=Path(base)/unit).is_file()),'')
        contents=Path(fragment).read_text(errors='replace') if fragment and Path(fragment).is_file() else ''
        if matching(unit+'\n'+contents): units.append(unit)
    cron={}
    for user in pwd.getpwall():
        if user.pw_uid==0 or 1000<=user.pw_uid<65534:
            content=run('crontab','-u',user.pw_name,'-l',allowed=(0,1))
            if matching(content): cron[user.pw_name]=content
    cron_files=[str(p) for directory in ('/etc/cron.d','/etc/cron.hourly','/etc/cron.daily','/etc/cron.weekly','/etc/cron.monthly')
        for p in Path(directory).glob('*') if p.is_file() and matching(p.read_text(errors='replace'))]
    user_units=[str(p) for base in [Path('/etc/systemd/user'),*Path('/home').glob('*/.config/systemd/user')]
        for p in base.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix in {'.service','.timer','.path','.socket'} and matching(p.name+'\n'+p.read_text(errors='replace'))]
    return {'units':sorted(units),'cron_users':cron,'cron_files':cron_files,'user_units':user_units}


def idle():
    return run('systemctl','show','mrv1-production.service','-p','ActiveState','--value') in {'inactive','failed'}


def verify_fenced():
    if not idle() or run('systemctl','is-enabled','mrv1-production.timer',allowed=(0,1)) not in {'disabled','masked'} or not FENCE.exists():
        raise RuntimeError('Pi production fence is not established')
    if run('systemctl','show','mrv1-production.timer','-p','ActiveState','--value')!='inactive': raise RuntimeError('Pi timer still active')


def readback():
    stage=STATE/'replay'
    run('systemd-run','--quiet','--wait','--pipe','--collect','--uid=trendatlas',
        '-p','EnvironmentFile=/etc/default/trendatlas-multi-account',
        '-p','WorkingDirectory='+str(stage/'web'),
        '-p','Environment=TRENDATLAS_AUTHORITY_REPOSITORY_ROOT=/opt/market_regime_v1',
        '/opt/market_regime_v1/.runtime/node-v22.23.2-linux-arm64/bin/node','--conditions=react-server','--import','tsx',
        str(stage/'web/scripts/production-migration-readback.ts'),str(STATE/'readback.json'))
    d=json.loads((STATE/'readback.json').read_text())
    identity=sorted([{'master':a['masterAddress'].lower(),'signer':a['signerFingerprint']} for a in d['accounts']],key=lambda a:a['master'])
    return {'identity':identity,'target':d['target'],'journal_sha256':d['journal']['sha256'],
        'nonce_watermarks':d['journal']['tables']['multi_account_agent_nonces'],
        'only_live_host':not FENCE.exists() and run('systemctl','is-enabled','mrv1-production.timer',allowed=(0,1))=='enabled',
        'plans':[a['plan'] for a in d['accounts']]}


def verify_retirement_proof(record, boot_id, unit_states, credential_exists):
    if record['old_boot_id']==boot_id: raise RuntimeError('Pi has not rebooted')
    if credential_exists: raise RuntimeError('plaintext trading credential remains')
    for unit in record['plan']['units']:
        if unit_states.get(unit) not in {('masked','inactive'),('masked','failed')}:
            raise RuntimeError('Pi autostart not retired')
    return {'reboot_verified':True,'trading_credential_removed':True}


def encrypted_archive(plan):
    paths=[Path('/etc/default/trendatlas-multi-account'),Path('/etc/credstore.encrypted'),
           Path('/opt/market_regime_v1/execution/config'),Path('/opt/market_regime_v1/outputs/execution/execution_journal'),
           STATE/'readback.json']
    paths += [Path(run('systemctl','show',u,'-p','FragmentPath','--value')) for u in plan['units']]
    paths += [Path(p) for p in plan['cron_files']+plan['user_units']]
    manifest={}; buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as archive:
        for path in paths:
            if path.exists():
                archive.add(path,arcname=str(path).lstrip('/'),recursive=True)
                for f in path.rglob('*') if path.is_dir() else [path]:
                    if f.is_file(): manifest[str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
        raw=json.dumps({'manifest':manifest,'inventory':plan},sort_keys=True).encode()
        info=tarfile.TarInfo('manifest.json'); info.size=len(raw); archive.addfile(info,io.BytesIO(raw))
    data=buf.getvalue(); target=STATE/'rollback.cred'
    encrypted=subprocess.run(['systemd-creds','encrypt','--with-key=host','--name=trendatlas-rollback','-',str(target)],input=data,capture_output=True)
    if encrypted.returncode: raise RuntimeError('rollback archive encryption failed')
    verified=subprocess.run(['systemd-creds','decrypt','--name=trendatlas-rollback',str(target),'-'],capture_output=True)
    if verified.returncode or hashlib.sha256(verified.stdout).digest()!=hashlib.sha256(data).digest(): raise RuntimeError('encrypted archive roundtrip failed')
    target.chmod(0o600)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def retire(receipt):
    verify_fenced()
    if receipt.get('verified') is not True: raise RuntimeError('verified VPS cutover receipt required')
    plan=inventory(); digest=encrypted_archive(plan)
    (STATE/'retirement.json').write_text(json.dumps({'phase':'ARCHIVED','archive_sha256':digest,'plan':plan,'old_boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))
    backup=STATE/'retired-units'; backup.mkdir(exist_ok=True)
    for unit in plan['units']:
        run('systemctl','disable','--now',unit,allowed=(0,1))
        path=Path('/etc/systemd/system')/unit
        if path.exists() and not path.is_symlink(): path.rename(backup/unit)
        run('systemctl','mask',unit)
    for user,content in plan['cron_users'].items():
        filtered='\n'.join(line for line in content.splitlines() if not matching(line))+'\n'
        p=subprocess.run(['crontab','-u',user,'-'],input=filtered,text=True,capture_output=True)
        if p.returncode: raise RuntimeError('user cron retirement failed')
    for item in plan['cron_files']:
        p=Path(item); p.write_text('\n'.join(line for line in p.read_text().splitlines() if not matching(line))+'\n')
    for item in plan['user_units']:
        p=Path(item); p.rename(backup/('user-'+hashlib.sha256(item.encode()).hexdigest()[:12]+'-'+p.name)); p.symlink_to('/dev/null')
    # Only known active credential path; no repository/data removal.
    Path('/etc/default/trendatlas-multi-account').unlink(missing_ok=True)
    run('systemctl','daemon-reload')
    for unit in plan['units']:
        if run('systemctl','show',unit,'-p','ActiveState','--value') not in {'inactive','failed'}: raise RuntimeError('retired unit still active')
    run('systemctl','reboot')


def main():
    p=argparse.ArgumentParser(); p.add_argument('action'); p.add_argument('--receipt',type=Path); p.add_argument('--execute-cleanup',action='store_true'); a=p.parse_args()
    if os.geteuid()!=0: raise RuntimeError('root required')
    STATE.mkdir(mode=0o700,exist_ok=True)
    if a.action=='wait-idle':
        for _ in range(180):
            if idle(): return
            time.sleep(5)
        raise RuntimeError('Pi production did not become idle')
    elif a.action=='fence':
        if not idle(): raise RuntimeError('Pi still running')
        run('systemctl','disable','--now','mrv1-production.timer')
        FENCE.parent.mkdir(exist_ok=True); FENCE.write_text('[Service]\nExecCondition=/usr/bin/false\n')
        run('systemctl','daemon-reload'); verify_fenced()
    elif a.action=='verify-fenced': verify_fenced()
    elif a.action=='restore':
        FENCE.unlink(missing_ok=True); run('systemctl','daemon-reload'); run('systemctl','enable','--now','mrv1-production.timer')
    elif a.action=='inventory': print(json.dumps(inventory()))
    elif a.action=='readback': print(json.dumps(readback()))
    elif a.action=='retire':
        if not a.execute_cleanup or not a.receipt: raise RuntimeError('operator cleanup confirmation and receipt required')
        retire(json.loads(a.receipt.read_text()))
    elif a.action=='verify-reboot':
        record=json.loads((STATE/'retirement.json').read_text())
        states={u:(run('systemctl','is-enabled',u,allowed=(0,1)),run('systemctl','show',u,'-p','ActiveState','--value')) for u in record['plan']['units']}
        print(json.dumps(verify_retirement_proof(record,Path('/proc/sys/kernel/random/boot_id').read_text().strip(),states,Path('/etc/default/trendatlas-multi-account').exists())))
    else: raise RuntimeError('unsupported Pi action')

if __name__=='__main__': main()
