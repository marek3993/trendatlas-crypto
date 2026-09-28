"""Reassemble and verify the immutable final evidence archive; never resumes it."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def restore(destination):
    here=Path(__file__).resolve().parent; index=json.loads((here/'archive/index.json').read_text())
    destination=destination.resolve()
    # Never overwrite an existing snapshot, let alone an active experiment.
    destination.mkdir(parents=True,exist_ok=False)
    archive=destination/'terminal.tar.gz'
    with archive.open('xb') as out:
        for part in index['parts']:
            path=here/'archive'/part['name']
            assert path.stat().st_size==part['bytes'] and sha(path)==part['sha256']
            with path.open('rb') as source:
                while chunk:=source.read(1024*1024):out.write(chunk)
    assert archive.stat().st_size==index['bytes'] and sha(archive)==index['sha256']
    root=destination/'snapshot';root.mkdir()
    with tarfile.open(archive,'r:gz') as bundle:
        for member in bundle.getmembers():
            target=(root/member.name).resolve()
            assert target.is_relative_to(root) and (member.isfile() or member.isdir())
        bundle.extractall(root,filter='data')
    manifest=json.loads((root/'transfer_manifest.json').read_text())
    for name,entry in manifest.items():
        path=root/name
        assert path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256']
    print(json.dumps(dict(snapshot=str(root),files_verified=len(manifest),archive_sha256=index['sha256'])))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True)
    restore(p.parse_args().destination)
