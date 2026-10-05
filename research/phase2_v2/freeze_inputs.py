"""Merge authorized market slices into a new, immutable research-only bundle."""
import csv
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from .contract import load
from .inputs import guarded_rows

def freeze(root,destination=None):
    root=Path(root);c=load();destination=Path(destination) if destination else root/'frozen'
    if (destination/'manifest.json').exists():raise RuntimeError('frozen_bundle_already_exists')
    destination.mkdir(exist_ok=True)
    old=Path('/opt/trendatlas-research/releases/53b6a5336ca1f7ce35b481a017f7e82396f3613c/research/causal_evolution/inputs')
    # Public exact quote volumes win over local volume approximations.
    frames={};sources=[]
    for path in (root/'local_spot_daily.zip',old/'spot_daily.zip',root/'public_spot_daily.zip'):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                with z.open(name) as stream:rows=list(guarded_rows(stream,c))
                frame=frames.setdefault(name,{})
                for row in rows:frame[row['date'][:10]]=row
        sources.append({'source':str(path),'scope':'authorized_slice_only'})
    with zipfile.ZipFile(destination/'spot_daily.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,rows in sorted(frames.items()):
            if not rows:continue
            buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=['date','open','high','low','close','quote_volume'])
            w.writeheader();w.writerows({k:r[k] for k in w.fieldnames} for d,r in sorted(rows.items()))
            z.writestr(name,buf.getvalue())
    for name in ('identity_events.json','venue_notices.json'):
        events=json.loads((old/name).read_text())
        events=[e for e in events if e.get('effective_utc','')[:10]<=c['authorized_development'][-1][1]]
        (destination/name).write_text(json.dumps(events,indent=2))
    shutil.copyfile(root/'production_targets.csv',destination/'production_targets.csv')
    manifest={'contract_sha256':hashlib.sha256((Path(__file__).resolve().parents[2]/'source_of_truth/phase2_v2_contract.json').read_bytes()).hexdigest(),
        'source_slices':sources,'development':c['authorized_development'],'excluded':['2026-09-26'],
        'outer':'LOCKED','forward_2027':'SEALED','historical_outer':'NONE_PREVIOUSLY_SEEN',
        'assets':len(frames),'first':min(min(r) for r in frames.values() if r),'last':max(max(r) for r in frames.values() if r),
        'local_proxy_warning':'local-only rows use volume*close, public rows use exact quote volume; survivorship and venue certification remain unproven',
        'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir() if p.is_file()}}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('source_slices','files')}))

if __name__=='__main__':freeze(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)
