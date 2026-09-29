"""Strict replay comparison. Difference magnitudes are evidence, never tolerances."""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def compare(a,b,planner_a,planner_b):
    sa,sb=copy.deepcopy(a['snapshot']),copy.deepcopy(b['snapshot'])
    # Host paths, source file mtimes and Git/build metadata are provenance, not math.
    for s in (sa,sb):
        s.pop('source_inputs',None); s.pop('provenance',None)
    x,y=json.loads(a['timeseries']),json.loads(b['timeseries'])
    differences={}
    same_shape=x['columns']==y['columns'] and x['index']==y['index'] and len(x['data'])==len(y['data'])
    if same_shape:
        for left,right in zip(x['data'],y['data']):
            for i,(u,v) in enumerate(zip(left,right)):
                if u!=v:
                    entry=differences.setdefault(x['columns'][i],{'count':0,'max_absolute_difference':0})
                    entry['count']+=1
                    if isinstance(u,(int,float)) and isinstance(v,(int,float)):
                        entry['max_absolute_difference']=max(entry['max_absolute_difference'],abs(u-v))
    exact=sa==sb and same_shape and not differences and planner_a==planner_b
    return {'status':'PASS' if exact else 'BLOCKED','comparison':'exact',
        'current_snapshot_exact':sa==sb,'planner_exact':planner_a==planner_b,
        'timeseries_shape_equal':same_shape,'full_timeseries_exact':same_shape and not differences,
        'differences':differences,'new_tolerance_introduced':False}


def main():
    p=argparse.ArgumentParser(); p.add_argument('pi_core',type=Path);p.add_argument('vps_core',type=Path)
    p.add_argument('pi_planner',type=Path);p.add_argument('vps_planner',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); paths=[a.pi_core,a.vps_core,a.pi_planner,a.vps_planner]
    report=compare(*(json.loads(x.read_text()) for x in paths))
    report['input_sha256']={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['status']=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
