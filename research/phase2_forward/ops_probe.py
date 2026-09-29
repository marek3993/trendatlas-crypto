"""Root-run read-only evidence probe; never reads credential contents."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import zlib


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def command(args):
    r=subprocess.run(args,capture_output=True,text=True,timeout=30)
    return {'exit':r.returncode,'stdout':r.stdout.strip()}


def probe():
    root=Path('/var/lib/trendatlas-research/causal-v1/current').resolve()
    engine=Path('/opt/trendatlas-research/releases/53b6a5336ca1f7ce35b481a017f7e82396f3613c/research/causal_evolution')
    frozen={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()
            and not p.name.endswith(('-shm','-wal','.lock'))}
    code={str(p.relative_to(engine)):sha(p) for p in engine.rglob('*') if p.is_file()
          and p.suffix in ('.py','.json','.zip') and '__pycache__' not in p.parts}
    result={'old_state_root':str(root),'old_files':frozen,'old_engine':code,
            'old_status':json.loads((root/'status.json').read_text()),
            'units':{},'leadpilot':command(['docker','ps','--format','{{.Names}}|{{.Status}}|{{.Image}}']),
            'leadpilot_file_hashes':{}}
    for name in ['trendatlas-research-worker.service','trendatlas-research-dispatch.service',
                 'trendatlas-research-dispatch.timer','trendatlas-phase2-collector.service','trendatlas-phase2-collector.timer']:
        result['units'][name]=command(['systemctl','show',name,'-p','ActiveState','-p','SubState','-p','Result',
            '-p','ExecMainStatus','-p','NRestarts','-p','CPUUsageNSec','-p','MemoryPeak','-p','User',
            '-p','DynamicUser','-p','MemoryMax','-p','CPUQuotaPerSecUSec','-p','InaccessiblePaths',
            '-p','ReadWritePaths','-p','LoadCredential','-p','LoadCredentialEncrypted'])
    lp=Path('/opt/leadpilot')
    for p in lp.glob('*'):
        if p.is_file() and p.suffix in ('.yml','.yaml','.json','.conf'):
            result['leadpilot_file_hashes'][p.name]=sha(p)
    data=Path('/var/lib/trendatlas-phase2')
    if (data/'venue.sqlite').exists():
        db=sqlite3.connect((data/'venue.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0];previous='GENESIS';count=0
        for row in db.execute('SELECT kind,asset,requested_utc,received_utc,request,status,payload,payload_sha256,previous_hash,row_hash FROM observations ORDER BY id'):
            if hashlib.sha256(zlib.decompress(row[6])).hexdigest()!=row[7] or row[8]!=previous:
                raise ValueError('venue_hash_chain_failure')
            canonical=json.dumps(list(row[:6])+[row[7],row[8]],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            if hashlib.sha256(canonical).hexdigest()!=row[9]:raise ValueError('row_hash_failure')
            previous=row[9];count+=1
        result['collector']={'integrity':integrity,'hash_chain_rows_verified':count,
            'rows_by_kind_status':db.execute('SELECT kind,status,count(*) FROM observations GROUP BY kind,status').fetchall(),
            'bytes':sum(p.stat().st_size for p in data.rglob('*') if p.is_file()),
            'manifest':json.loads((data/'collection_manifest.json').read_text()),
            'status':json.loads((data/'status.json').read_text()) if (data/'status.json').exists() else None}
        db.close()
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':probe()
