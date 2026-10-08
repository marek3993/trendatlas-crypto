"""Install a read-only result observer alongside the frozen research release."""
import hashlib
import json
import os
from pathlib import Path
import grp
import subprocess
import sys
import zipfile


def main(package):
    package = Path(package); revision = hashlib.sha256(package.read_bytes()).hexdigest()[:16]
    base = Path('/opt/trendatlas-research/anomaly-lab/releases/c23fc478faf29b8a')
    root = Path('/opt/trendatlas-research/anomaly-lab/reporting')/revision
    root.mkdir(parents=True, exist_ok=False)
    allowed = {'scripts/anomaly_lab_report_consumer.py', 'source_of_truth/anomaly_lab_reporting_contract.json', 'tests/test_anomaly_lab_reporting.py'}
    with zipfile.ZipFile(package) as z:
        if set(z.namelist()) != allowed: raise ValueError('reporting_package_scope')
        for name in allowed:
            p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(z.read(name))
    (root/'tests/__init__.py').write_text('')
    gid = grp.getgrnam('trendatlas-research').gr_gid
    for p in (root.parent, root, *root.rglob('*')):
        os.chown(p, 0, gid); p.chmod(0o750 if p.is_dir() else 0o640)
    py = '/opt/trendatlas-research/venvs/causal-v1/bin/python'
    subprocess.run(['sudo', '-u', 'trendatlas-anomaly', py, '-B', '-m', 'unittest', 'tests.test_anomaly_lab_reporting', '-q'], cwd=root, check=True)
    command = [py, '-I', '-B', str(root/'scripts/anomaly_lab_report_consumer.py'), '--release', str(base),
               '--root', '/var/lib/trendatlas-anomaly-lab', '--contract', str(root/'source_of_truth/anomaly_lab_reporting_contract.json')]
    subprocess.run(['sudo', '-u', 'trendatlas-anomaly', *command], check=True)
    drop = Path('/etc/systemd/system/trendatlas-anomaly-lab.service.d'); drop.mkdir(exist_ok=True)
    target = drop/'20-read-only-report.conf'
    if target.exists(): raise ValueError('existing_observer_never_overwritten')
    target.write_text('[Service]\nExecStartPost='+' '.join(command)+'\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print(json.dumps({'reporting_release': str(root), 'frozen_experiment_changed': False, 'worker_restarted': False,
                      'next_timer_tick_runs_observer': True, 'report': '/var/lib/trendatlas-anomaly-lab/discovery_report.json'}))


if __name__ == '__main__': main(sys.argv[1])
