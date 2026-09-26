"""Read original or byte-identical-member partitioned evidence archives."""
import json,zipfile
from common import HERE,sha

class Evidence:
    def __init__(self):
        original=HERE/'results/replay_ledgers.zip';manifest=HERE/'results/ledger_partitions.json'
        self.manifest=json.loads(manifest.read_text()) if manifest.exists() else None
        paths=sorted((HERE/'results').glob('replay_ledgers.part*.zip')) if self.manifest else [original]
        self.zips=[zipfile.ZipFile(p) for p in paths];self.members={n:z for z in self.zips for n in z.namelist()}
        assert len(self.members)==sum(len(z.namelist()) for z in self.zips)
    def namelist(self):return list(self.members)
    def read(self,name):
        data=self.members[name].read(name)
        if self.manifest:assert sha(data)==self.manifest['members'][name]['sha256']
        return data
    def __enter__(self):return self
    def __exit__(self,*args):
        for z in self.zips:z.close()
