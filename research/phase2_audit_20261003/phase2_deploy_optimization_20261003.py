"""One-time reviewed deployment; run as root only after both research timers quiesce."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

BASE = Path('/opt/trendatlas-research/phase2-development')
RELEASE = BASE / 'releases' / 'broker-opt-7f52ea93ddd77839'
STATE = Path('/var/lib/trendatlas-research-development')
SERVICES = ('trendatlas-phase2-development.service', 'trendatlas-phase2-broker.service')
assert os.geteuid() == 0 and RELEASE.is_dir()
for unit in SERVICES:
    active = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState', '--value'], text=True).strip()
    assert active == 'inactive', (unit, active)
old = (BASE / 'current').resolve()
for name in ('research/phase2_continuous/engine.py', 'source_of_truth/phase2_development_contract.json'):
    assert (old / name).read_bytes() == (RELEASE / name).read_bytes(), name
backup = Path('/var/backups/trendatlas-research-development') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-broker-opt')
backup.mkdir(parents=True, mode=0o700)
db = sqlite3.connect('file:' + (STATE / 'research.sqlite').as_posix() + '?mode=ro', uri=True)
receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'old_release': str(old),
           'new_release': str(RELEASE), 'backup': str(backup),
           'checkpoint': json.loads((STATE / 'status.json').read_text()),
           'evaluations_before': db.execute("SELECT COUNT(*) FROM evaluations WHERE status='COMPLETE'").fetchone()[0],
           'candidates_before': db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],
           'evaluation_contract_sha256': hashlib.sha256((old / 'source_of_truth/phase2_development_contract.json').read_bytes()).hexdigest(),
           'evaluator_sha256': hashlib.sha256((old / 'research/phase2_continuous/engine.py').read_bytes()).hexdigest()}
copy = sqlite3.connect(backup / 'research.sqlite')
db.backup(copy)
assert copy.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
assert copy.execute("SELECT COUNT(*) FROM evaluations WHERE status='COMPLETE'").fetchone()[0] == receipt['evaluations_before']
copy.close(); db.close()
shutil.copy2(STATE / 'status.json', backup / 'status.json')
shutil.copytree(STATE / 'mailbox', backup / 'mailbox')
unit_file = Path('/etc/systemd/system/trendatlas-phase2-broker.service')
shutil.copy2(unit_file, backup / unit_file.name)
for path in RELEASE.rglob('*'):
    os.chmod(path, 0o755 if path.is_dir() else 0o644)
os.chmod(RELEASE, 0o755)
# Build the legacy accounting index once outside the service CPU quota; no credential is loaded.
code = ("import os,sys;os.umask(0o007);sys.path.insert(0," + repr(str(RELEASE)) + ");"
        "from pathlib import Path;from research.phase2_continuous.broker import index_responses;"
        "db=index_responses(Path('/var/lib/trendatlas-research-development/mailbox'));"
        "print('indexed_responses',db.execute('SELECT COUNT(*) FROM responses').fetchone()[0]);db.close()")
subprocess.run(['sudo', '-n', '-u', 'trendatlas-research-broker', '-g', 'trendatlas-research',
                'env', 'OPENBLAS_NUM_THREADS=1', 'OMP_NUM_THREADS=1',
                '/opt/trendatlas-research/venvs/causal-v1/bin/python3', '-I', '-B', '-c', code], check=True)
check = ("import sys;sys.path.insert(0," + repr(str(RELEASE)) + ");"
         "from research.phase2_continuous.runtime import connect,verify_chain;"
         "db=connect('/var/lib/trendatlas-research-development');verify_chain(db);db.close();"
         "print('sqlite_and_audit_chain_ok')")
subprocess.run(['sudo', '-n', '-u', 'trendatlas-research', 'env', 'OPENBLAS_NUM_THREADS=1',
                '/opt/trendatlas-research/venvs/causal-v1/bin/python3', '-I', '-B', '-c', check], check=True)
temp = BASE / 'current.broker-opt'
assert not temp.exists() and not temp.is_symlink()
temp.symlink_to(RELEASE, target_is_directory=True)
os.replace(temp, BASE / 'current')
shutil.copyfile(RELEASE / 'deploy/systemd/trendatlas-phase2-broker.service', unit_file)
os.chmod(unit_file, 0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
receipt['switched_utc'] = datetime.now(timezone.utc).isoformat()
(backup / 'deployment_receipt.json').write_text(json.dumps(receipt, sort_keys=True))
subprocess.run(['systemctl', 'start', 'trendatlas-phase2-development.timer', 'trendatlas-phase2-broker.timer'], check=True)
print(json.dumps(receipt, sort_keys=True))
