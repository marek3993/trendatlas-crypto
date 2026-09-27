"""Read-only recovery evidence; compares live SQLite with pre-repair backup."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime


def command(*args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    return dict(code=r.returncode, stdout=r.stdout.strip(), stderr=r.stderr.strip())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--backup', required=True)
    args = p.parse_args()
    backup = Path(args.backup)
    baseline = json.loads((backup/'backup_audit.json').read_text())
    meta = runtime.verify(runtime.STATE, runtime.ENGINE)
    live = runtime.readonly(runtime.STATE/'candidates.sqlite')
    db = sqlite3.connect(':memory:')
    live.backup(db); live.close()
    old = runtime.readonly(backup/'candidates.sqlite', immutable=True)
    preserved = {}
    for table, key in (('evaluations','cache_key'), ('attempts','id'), ('trials','slot'),
                       ('candidates','id'), ('populations','run,generation'), ('scores','run,generation,candidate')):
        # Original attempt rows were all COMPLETE; all must stay byte-for-byte identical.
        before = set(old.execute('SELECT * FROM '+table))
        after = set(db.execute('SELECT * FROM '+table))
        preserved[table] = dict(original=len(before), preserved=len(before & after), unchanged=before <= after)
    production = {name:dict(before=h, after=runtime.sha(name), unchanged=runtime.sha(name)==h)
                  for name,h in baseline['production_hashes'].items()}
    status = json.loads((runtime.STATE/'status.json').read_text())
    mail = runtime.readonly(runtime.STATE/'mailbox/proposals.sqlite')
    result = dict(status=status, sqlite_status=runtime.metadata(db).get('status'),
        outer_opened=runtime.metadata(db).get('outer_opened',False),
        experiment_id=meta['experiment_id'], fingerprint=meta['fingerprint'],
        engine_commit=runtime.POLICY['engine_commit'], manifest_sha256=runtime.sha(runtime.STATE/'frozen_manifest.json'),
        engine_and_raw_hashes_verified=True, retained=preserved,
        integrity=db.execute('PRAGMA integrity_check').fetchall(),
        mail_integrity=mail.execute('PRAGMA integrity_check').fetchall(),
        counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('evaluations','attempts','candidates','trials','finalists')},
        attempt_status=db.execute('SELECT status,count(*) FROM attempts GROUP BY status').fetchall(),
        duplicate_completed=db.execute("SELECT cache_key,count(*) FROM attempts WHERE status='COMPLETE' GROUP BY cache_key HAVING count(*)>1").fetchall(),
        events=[json.loads(r[0]) for r in db.execute('SELECT body FROM orchestration_events ORDER BY id')],
        production_hashes=production, production_head=command('git','-C','/opt/market_regime_v1','rev-parse','HEAD'),
        production_status_unchanged=command('git','-C','/opt/market_regime_v1','status','--porcelain')['stdout']==baseline['production_status'].strip(),
        systemd={name:command('systemctl','show',name,'-p','ActiveState','-p','SubState','-p','Result','-p','MainPID',
            '-p','ExecMainCode','-p','ExecMainStatus','-p','RuntimeMaxUSec','-p','TimeoutStopUSec','-p','TimeoutStartUSec')
            for name in ('mrv1-production.timer','mrv1-production.service','trendatlas-evolution-worker.service',
                         'trendatlas-evolution-dispatch.service','trendatlas-causal-broker.service','trendatlas-causal-maintain.service')})
    print(json.dumps(result, indent=2, sort_keys=True))
    old.close(); db.close(); mail.close()


if __name__ == '__main__':
    main()
