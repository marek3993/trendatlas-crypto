"""Create an exact staging list and content manifest; never stages or commits."""
from common import HERE,ROOT,digest,write

def main():
    assert (HERE/'results/run_completed.json').exists()
    assert (HERE/'validation.json').exists() and (HERE/'reproduction_check.json').exists()
    files=[p for p in HERE.rglob('*') if p.is_file() and not {'archive','cache','__pycache__'}&set(p.relative_to(HERE).parts) and p.suffix!='.pyc' and not (p.name=='replay_ledgers.zip' and (HERE/'results/ledger_partitions.json').exists())]
    files=sorted(set(files+[HERE/'GIT_ADD.txt',HERE/'artifact_manifest.json']))
    assert all(p.resolve().is_relative_to(HERE.resolve()) for p in files)
    (HERE/'GIT_ADD.txt').write_text('\n'.join(p.relative_to(ROOT).as_posix() for p in files)+'\n',encoding='utf-8',newline='\n')
    for p in files:
        if p.exists() and p.stat().st_size>=100_000_000:raise ValueError('Git host file limit: '+str(p))
    write(HERE/'artifact_manifest.json',dict(files={p.relative_to(HERE).as_posix():dict(sha256=digest(p),bytes=p.stat().st_size) for p in files if p.name!='artifact_manifest.json'},manifest_self_hash_omitted=True))
    print('Exact staging list:',len(files),'files')

if __name__=='__main__':main()
