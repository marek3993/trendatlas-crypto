"""Partition large evidence ZIP for Git hosting, preserving every member byte."""
import zipfile
from common import HERE,digest,sha,write

def main():
    src=HERE/'results/replay_ledgers.zip';assert (HERE/'results/run_completed.json').exists()
    assert not list((HERE/'results').glob('replay_ledgers.part*.zip')),'Evidence already partitioned'
    members={};parts=[];current=None;size=0
    with zipfile.ZipFile(src) as source:
        for info in source.infolist():
            if current is None or size+info.compress_size>35_000_000:
                if current:current.close()
                part=HERE/f'results/replay_ledgers.part{len(parts)+1:02d}.zip';parts.append(part);current=zipfile.ZipFile(part,'w',zipfile.ZIP_DEFLATED,compresslevel=9);size=0
            raw=source.read(info.filename);current.writestr(info.filename,raw);members[info.filename]=dict(part=part.name,sha256=sha(raw),bytes=len(raw));size+=info.compress_size
    if current:current.close()
    write(HERE/'results/ledger_partitions.json',dict(original_zip_sha256=digest(src),member_bytes_unchanged=True,members=members,parts={p.name:dict(sha256=digest(p),bytes=p.stat().st_size) for p in parts}))
    print('Partitioned',len(members),'unchanged members into',len(parts),'archives')

if __name__=='__main__':main()
