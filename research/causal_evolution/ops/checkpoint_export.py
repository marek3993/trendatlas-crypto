"""Read-only operational evidence export; never evaluates or changes a candidate.

SQLite backup gives a consistent snapshot of EACH database. The two databases
and status file are sampled separately while the worker continues; this is not
an atomic cross-database checkpoint and must not replace the live state.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def table(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8', newline='') as handle:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    return dict(exit_code=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    state = Path(args.state).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(output)
    info = dict(started=now(), source=str(state), kind='LIVE_PROGRESS_NOT_FINAL_RESULTS', database_snapshots={})
    with tempfile.TemporaryDirectory(prefix='ta-causal-evidence-') as temporary:
        root = Path(temporary)
        for relative in ('candidates.sqlite', 'mailbox/proposals.sqlite'):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = sqlite3.connect((state / relative).as_uri() + '?mode=ro', uri=True, timeout=30)
            destination = sqlite3.connect(target)
            source.backup(destination, pages=128, sleep=.01)
            assert destination.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            destination.close()
            source.close()
            info['database_snapshots'][relative] = dict(utc=now(), sha256=hashlib.sha256(target.read_bytes()).hexdigest(), integrity='ok')
        for name in ('status.json', 'frozen_manifest.json', 'frozen_finalists.json', 'REPORT.md'):
            path = state / name
            if path.exists():
                (root / name).write_bytes(path.read_bytes())
        db = sqlite3.connect(root / 'candidates.sqlite')
        db.row_factory = sqlite3.Row
        meta = {r[0]: json.loads(r[1]) for r in db.execute('SELECT key,value FROM meta')}
        write(root / 'checkpoint_meta.json', meta)
        write(root / 'candidate_genes.json', [dict(id=r[0], genes=json.loads(r[1])) for r in db.execute('SELECT * FROM candidates ORDER BY id')])
        write(root / 'mutation_lineage.json', [dict(r) for r in db.execute('SELECT * FROM trials ORDER BY created,slot')])
        scores = [dict(run=r[0], generation=r[1], **json.loads(r[2])) for r in db.execute('SELECT run,generation,body FROM scores ORDER BY run,generation,candidate')]
        table(root / 'development.csv', [{k:v for k,v in r.items() if k not in ('folds','vector')} for r in scores])
        table(root / 'development_folds.csv', [dict(run=r['run'], generation=r['generation'], candidate=r['id'], scope=f['scope'], fold=f['fold'], start=f['start'], end=f['end'], **f['metrics']) for r in scores for f in r['folds']])
        table(root / 'trial_counts_by_arm.csv', [dict(r) for r in db.execute('SELECT run,generation,source,COUNT(*) AS slots FROM trials GROUP BY run,generation,source')])
        info['counts'] = {t:db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('candidates','trials','attempts','evaluations','finalists')}
        info['outer_opened'] = meta.get('outer_opened', False)
        info['evaluation_scopes'] = [dict(r) for r in db.execute('SELECT scope,COUNT(*) AS attempts FROM attempts GROUP BY scope')]
        db.close()
        db = sqlite3.connect(root / 'mailbox/proposals.sqlite')
        db.row_factory = sqlite3.Row
        proposals = [{k:json.loads(r[k]) if r[k] and k in ('payload','response','validation','usage') else r[k] for k in r.keys()} for r in db.execute('SELECT * FROM proposals ORDER BY created')]
        write(root / 'deepseek_proposals.json', proposals)
        usages = [r['usage'] for r in proposals if r['usage']]
        info['deepseek'] = dict(calls=sum(x.get('api_call',0) for x in usages), tokens=sum(x.get('total_tokens',0) for x in usages), usd_peak_upper_estimate=sum(x.get('usd',0) for x in usages), accepted=sum(len((r['validation'] or {}).get('accepted',[])) for r in proposals), rejected=[x for r in proposals for x in (r['validation'] or {}).get('rejected',[])])
        db.close()
        units = ('mrv1-production.timer','mrv1-production.service','trendatlas-evolution-worker.service','trendatlas-evolution-dispatch.timer','trendatlas-causal-broker.service','trendatlas-causal-maintain.service','trendatlas-causal-research.slice')
        info['systemd'] = {u:command(['systemctl','show',u,'-p','ActiveState','-p','SubState','-p','Result','-p','MainPID','-p','CPUUsageNSec','-p','CPUQuotaPerSecUSec','-p','TimeoutStartUSec','-p','PrivateNetwork','-p','RestrictAddressFamilies','-p','InaccessiblePaths','-p','LimitAS','-p','LimitMEMLOCK']) for u in units}
        info['production_head'] = command(['git','-C','/opt/market_regime_v1','rev-parse','HEAD'])
        info['unit_hashes'] = {name:hashlib.sha256((Path('/etc/systemd/system') / name).read_bytes()).hexdigest() for name in ('mrv1-production.service','mrv1-production.timer','trendatlas-evolution-dispatch.timer')}
        pid = command(['systemctl','show','trendatlas-evolution-worker.service','-p','MainPID','--value'])['stdout']
        if pid.isdigit() and int(pid):
            status = Path('/proc') / pid / 'status'
            info['worker_memory'] = [line for line in status.read_text().splitlines() if line.startswith(('VmPeak:','VmSize:','VmLck:','VmRSS:','VmSwap:','Threads:'))]
            info['worker_network_namespace'] = str((Path('/proc') / pid / 'ns/net').readlink())
            info['host_network_namespace'] = str(Path('/proc/1/ns/net').readlink())
        info['cgroup_controllers'] = Path('/sys/fs/cgroup/cgroup.controllers').read_text().strip()
        info['finished'] = now()
        write(root / 'snapshot_audit.json', info)
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
    print(json.dumps(dict(output=str(output), bytes=output.stat().st_size, sha256=hashlib.sha256(output.read_bytes()).hexdigest(), **info), sort_keys=True))


if __name__ == '__main__':
    main()
