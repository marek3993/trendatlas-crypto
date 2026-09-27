"""Reproducible evidence manifest; archive partitioning without changing member bytes."""
import argparse,json,zipfile
from common import HERE,ROOT,digest,write,now,sha

def main(restore=False):
    out=HERE/'results';src=out/'ledgers.zip'
    if restore:
        manifest=json.loads((out/'ledger_partitions.json').read_text())
        # Recreate member content rather than ZIP metadata; verify every member.
        with zipfile.ZipFile(src,'w',zipfile.ZIP_DEFLATED) as z:
            for part in manifest['parts']:
                path=out/part['file'];assert digest(path)==part['sha256']
                with zipfile.ZipFile(path) as p:
                    for n in p.namelist():
                        b=p.read(n);assert sha(b)==manifest['members'][n];z.writestr(n,b)
        print('Restored unchanged uncompressed evidence; ZIP container timestamps can differ');return
    assert (out/'completed.json').exists()
    with zipfile.ZipFile(src) as z:
        files=z.namelist();assert len(files)==len(set(files));members={};parts=[];part=None;size=0;counter=0
        for n in files:
            info=z.getinfo(n)
            if part is None or size+info.compress_size>35000000:
                if part is not None:part.close();parts[-1]['sha256']=digest(out/parts[-1]['file'])
                counter+=1;name=f'ledgers.part{counter:02}.zip';part=zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED);parts.append(dict(file=name));size=0
            b=z.read(n);part.writestr(n,b);members[n]=sha(b);size+=info.compress_size
        if part:part.close();parts[-1]['sha256']=digest(out/parts[-1]['file'])
    write(out/'ledger_partitions.json',dict(utc=now(),original_sha256=digest(src),parts=parts,members=members,rule='Member bytes unchanged; restored ZIP container may differ in timestamp metadata.'))
    excluded={'archive','cache','__pycache__'}
    paths=[p for p in HERE.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(HERE).parts) and p.name not in {'ledgers.zip','artifact_manifest.json','GIT_ADD.txt'}]
    paths+= [HERE/'artifact_manifest.json',HERE/'GIT_ADD.txt']
    names=sorted(str(p.relative_to(ROOT)).replace('\\','/') for p in paths)
    (HERE/'GIT_ADD.txt').write_text('\n'.join(names)+'\n',encoding='utf-8')
    write(HERE/'artifact_manifest.json',dict(utc=now(),files={str(p.relative_to(HERE)).replace('\\','/'):dict(sha256=digest(p),bytes=p.stat().st_size) for p in paths if p.exists() and p.name!='artifact_manifest.json'}))
    print('PACKAGED',len(names),'paths',len(parts),'ledger parts')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--restore-ledgers',action='store_true');main(p.parse_args().restore_ledgers)
