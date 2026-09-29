"""Strict replay comparison. Difference magnitudes are evidence, never tolerances."""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def unchanged_history(before, after):
    """Require every historical non-diagnostic cell and current snapshot unchanged."""
    old, new = json.loads(before['timeseries']), json.loads(after['timeseries'])
    if old['columns'] != new['columns'] or old['index'] != new['index'] or len(old['data']) != len(new['data']):
        return False
    indexes = [i for i, name in enumerate(old['columns'])
               if name not in {'rolling_vol_30d', 'rolling_sharpe_90d'}]
    if any(left[i] != right[i] for left, right in zip(old['data'], new['data']) for i in indexes):
        return False
    snapshots = [copy.deepcopy(payload['snapshot']) for payload in (before, after)]
    for snapshot in snapshots:
        snapshot.pop('source_inputs', None)
        snapshot.pop('provenance', None)
    return snapshots[0] == snapshots[1]


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
    canonical_exact = all(a.get(key)==b.get(key) for key in ('diagnostic_units','csv_sha256'))
    exact=sa==sb and same_shape and not differences and planner_a==planner_b and canonical_exact
    return {'status':'PASS' if exact else 'BLOCKED','comparison':'exact',
        'current_snapshot_exact':sa==sb,'planner_exact':planner_a==planner_b,
        'timeseries_shape_equal':same_shape,'full_timeseries_exact':same_shape and not differences,
        'canonical_serialization_exact':canonical_exact,
        'differences':differences,'new_tolerance_introduced':False}


def main():
    p=argparse.ArgumentParser(); p.add_argument('pi_core',type=Path);p.add_argument('vps_core',type=Path)
    p.add_argument('pi_planner',type=Path);p.add_argument('vps_planner',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--previous-pi-core',type=Path);p.add_argument('--previous-vps-core',type=Path)
    a=p.parse_args(); paths=[a.pi_core,a.vps_core,a.pi_planner,a.vps_planner]
    payloads=[json.loads(x.read_text(encoding='utf-8')) for x in paths]
    report=compare(*payloads)
    previous=[a.previous_pi_core,a.previous_vps_core]
    if any(previous):
        if not all(previous): p.error('both previous architecture core artifacts are required')
        report['historical_non_diagnostic_and_snapshot_unchanged']=all(
            unchanged_history(json.loads(path.read_text(encoding='utf-8')),current)
            for path,current in zip(previous,payloads[:2]))
        if not report['historical_non_diagnostic_and_snapshot_unchanged']: report['status']='BLOCKED'
        report['previous_sha256']={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in previous}
    report['input_sha256']={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
    a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if report['status']=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
