"""Quiesced, verified research backups and read-only exports; root systemd job."""
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime as r
import snapshot

BACKUPS = Path('/var/backups/trendatlas-research')
EXPORTS = Path('/srv/trendatlas-research-export')
TIMERS = ('trendatlas-research-dispatch.timer', 'trendatlas-research-broker.timer')


def ctl(*args, check=True):
    return subprocess.run(['systemctl', *args], check=check, capture_output=True, text=True)


def retained(paths, daily=7, weekly=4):
    """Keep newest snapshot per day/week, including newest unconditionally."""
    paths = sorted(paths, reverse=True)
    days, weeks, keep = set(), set(), set(paths[:1])
    for p in paths:
        day = dt.datetime.strptime(p.name[:8], '%Y%m%d').date()
        week = day.isocalendar()[:2]
        if day not in days and len(days) < daily:
            days.add(day); keep.add(p)
        if week not in weeks and len(weeks) < weekly:
            weeks.add(week); keep.add(p)
    return keep


def safe_prune(root):
    root = root.resolve()
    paths = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and p.name.endswith('Z')]
    # Verify every candidate before any deletion; incomplete snapshots remain for inspection.
    valid = []
    for p in paths:
        try: snapshot.verify(p); valid.append(p)
        except Exception: continue
    for p in set(valid) - retained(valid):
        if p.resolve().parent != root: raise RuntimeError('Unsafe retention path')
        for item in p.rglob('*'):
            item.chmod(0o750 if item.is_dir() else 0o640)
        p.chmod(0o750)
        shutil.rmtree(p)


def run():
    import grp
    active = [t for t in TIMERS if ctl('is-active', '--quiet', t, check=False).returncode == 0]
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup, export = BACKUPS / stamp, EXPORTS / stamp
    try:
        ctl('stop', *TIMERS)
        ctl('stop', 'trendatlas-research-worker.service')
        # Let any in-flight API request finish without terminating the broker.
        deadline = time.monotonic() + 65
        while ctl('is-active', '--quiet', 'trendatlas-research-broker.service', check=False).returncode == 0:
            if time.monotonic() > deadline: raise RuntimeError('Broker did not quiesce')
            time.sleep(1)
        meta = r.legacy.verify(r.STATE, r.ENGINE, r.POLICY)
        if meta.get('status') not in ('CHECKPOINTED', 'SEALED') or meta.get('failure'):
            raise RuntimeError('Backup requires valid checkpoint/terminal result')
        r.legacy.load_engine(r.ENGINE)
        from research.causal_evolution.store import Store
        store = Store(r.STATE.resolve())
        try: validated = r.validate_checkpoint(store)
        finally: store.close()
        snapshot.snapshot(r.STATE, backup)
        evidence = snapshot.verify(backup)
        shutil.copytree(backup, export)
        snapshot.verify(export)
        group = grp.getgrnam('trendatlas-research').gr_gid
        for p in [export, *export.rglob('*')]:
            import os
            os.chown(p, 0, group)
            p.chmod(0o550 if p.is_dir() else 0o440)
        link = EXPORTS / '.latest.tmp'
        link.unlink(missing_ok=True); link.symlink_to(export.name, target_is_directory=True)
        link.replace(EXPORTS / 'latest')
        safe_prune(BACKUPS); safe_prune(EXPORTS)
        usage = shutil.disk_usage(BACKUPS)
        report = dict(utc=stamp, backup=str(backup), export=str(export), verified=evidence,
                      checkpoint=validated, disk_used_percent=100 * usage.used / usage.total,
                      disk_warning=usage.used / usage.total > .75)
        r.atomic(Path('/var/log/trendatlas-research/backup-health.json'), report)
        print(json.dumps(report, sort_keys=True))
    finally:
        if active: ctl('start', *active)


if __name__ == '__main__': run()
