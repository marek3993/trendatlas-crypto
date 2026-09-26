"""Immutable forward-sealed paper evaluation. Offline inputs; no order API.

--init freezes nominees before future prices exist. --prices-dir accepts an
append-only snapshot of new daily spot bars; revising accepted bars is rejected.
This evaluates a frozen hypothetical policy, not observed exchange fills.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd
import engine
from prepare import write_json,digest

HERE=Path(__file__).resolve().parent


def policy_hashes():
    spec,_=engine.load_spec()
    assert digest((HERE/'inputs.zip').read_bytes())==spec['input_bundle_sha256'],'Frozen history bundle changed'
    files=[HERE/'paper.py',HERE/'engine.py',HERE/'pre_registration.json',HERE/'inputs.zip',engine.ROOT/spec['contract_path']]
    return {p.relative_to(engine.ROOT).as_posix():digest(p.read_bytes()) for p in files}


def init(out,results):
    out.mkdir(parents=True,exist_ok=True);path=out/'forward_seal.json'
    if path.exists():
        old=json.loads(path.read_text());assert old['source_hashes']==policy_hashes(),'Frozen paper code changed';return old
    spec,_=engine.load_spec();nomination=results/'nominees_before_oos.json'
    nominees=json.loads(nomination.read_text());now=datetime.now(timezone.utc)
    if now.date()>=pd.Timestamp(spec['sealed']['forward_start']).date():
        raise ValueError('Freeze date has passed: do not backdate. Pre-register a new prospective interval explicitly.')
    candidates={}
    observed=json.loads((results/'results.json').read_text())
    for category in ['A','B','C']:
        name=nominees[category]
        if name:
            partition=name.split('__')[0];part=next(x for x in spec['partitions'] if x['id']==partition)
            policy=next(p for p in observed['policies'] if p['id']==name)
            candidates[category]=dict(id=name,parameters=nominees['parameters_for_forward'][name],cap=part['cap'],mode=part['mode'],
                oos_risk_feasible=policy['risk_feasible'],oos_numeric_high_return_passed=policy['oos_numeric_high_return_passed'],
                status='PROVISIONAL_DIAGNOSTIC_ONLY' if policy['risk_feasible'] else 'OOS_REJECTED_DIAGNOSTIC_ONLY')
    seal=dict(schema_version=1,frozen_at_utc=now.isoformat(),start=spec['sealed']['forward_start'],end=spec['sealed']['forward_end'],
              source_hashes=policy_hashes(),nomination_sha256=digest(nomination.read_bytes()),
              historical_oos_results_sha256=digest((results/'results.json').read_bytes()),
              input_bundle_sha256=spec['input_bundle_sha256'],candidates=candidates,refit_allowed=False,
              production=False,orders=False,kind='hypothetical_forward_sealed_spot_and_cost_proxy',
              status='WAITING_FOR_FUTURE_DATA',historical_seal=False,
              note='Nominees derive from the pre-OOS development selection. Observed OOS leaders do not replace them. No return claim before new bars; no real account PnL.',
              interim_valuation='Each as-of snapshot is a hypothetical liquidation-value replay with terminal exit costs. It is not an append-only fill ledger; interim liquidation assumptions are not actual orders. Only the completed sealed interval is the final evaluation.')
    write_json(path,seal);return seal


def evaluate(seal,prices_dir,out,*,today=None):
    assert seal['source_hashes']==policy_hashes(),'Frozen source fingerprint mismatch'
    spec,_=engine.load_spec();today=today or datetime.now(timezone.utc).date()
    cutoff=pd.Timestamp(spec['last_market_bar_in_inputs']);frames={};daily_hashes={}
    with zipfile.ZipFile(HERE/'inputs.zip') as z:
        for identity in spec['identity']:
            name=identity['member'];old=pd.read_csv(z.open(name),parse_dates=['date']).set_index('date')
            path=prices_dir/name
            if not path.is_file():raise ValueError(f'Missing new-bar source: {name}')
            fresh=pd.read_csv(path,parse_dates=['date']).set_index('date').sort_index()
            if not fresh.index.is_unique:raise ValueError('Duplicate future bars')
            fresh=fresh[fresh.index>cutoff]
            if fresh.empty:raise ValueError('No future bars; no zero-filled sealed result')
            if any(fresh.index.date>=today):raise ValueError('Incomplete/current/future UTC bars cannot be evaluated')
            if not fresh.index.equals(pd.date_range(cutoff+pd.Timedelta(days=1),fresh.index[-1])):raise ValueError('Forward bars must be contiguous from frozen cutoff')
            values=fresh[['open','high','low','close']]
            if not np.isfinite(values).all().all() or not (values>0).all().all():raise ValueError('Invalid forward OHLC')
            if not (fresh.high>=fresh[['open','close','low']].max(axis=1)).all() or not (fresh.low<=fresh[['open','close','high']].min(axis=1)).all():raise ValueError('Inconsistent forward OHLC')
            for date,row in values.iterrows():
                key=name+':'+str(date.date());daily_hashes[key]=digest(json.dumps(row.tolist(),separators=(',',':')).encode())
            frames[identity['asset']]=pd.concat([old,fresh])
    ends={f.index[-1] for f in frames.values()}
    if len(ends)!=1:raise ValueError('All assets require the same completed cutoff')
    end=min(next(iter(ends)),pd.Timestamp(seal['end']))
    if end<pd.Timestamp(seal['start']):raise ValueError('Forward interval has not begun')
    for previous in sorted(out.glob('asof_*.json')):
        data=json.loads(previous.read_text())
        if any(daily_hashes.get(k)!=v for k,v in data['accepted_bar_hashes'].items()):raise ValueError('A previously accepted sealed bar was changed or removed')
    m=engine.market_from_frames(frames);evaluations={}
    for category,candidate in seal['candidates'].items():
        if candidate['parameters'] is None:
            evaluations[category]=dict(status='FROZEN_CASH',cagr=0.0);continue
        p=candidate['parameters'];normal=engine.simulate(m,p,candidate['cap'],start=seal['start'],end=str(end.date()))
        stress=engine.simulate(m,p,candidate['cap'],start=seal['start'],end=str(end.date()),cost_multiplier=2)
        delayed=engine.simulate(m,p,candidate['cap'],start=seal['start'],end=str(end.date()),delay=1)
        metrics=engine.summarize(normal);metrics['double_cost_cagr']=engine.summarize(stress)['cagr'];metrics['delayed_entry_cagr']=engine.summarize(delayed)['cagr']
        evaluations[category]=dict(id=candidate['id'],metrics=metrics,accepted_as_winner=False,
                                   reason='Seal incomplete or independent venue/universe evidence missing; paper proxy never auto-promotes.')
    record=dict(asof=str(end.date()),seal_sha256=digest((out/'forward_seal.json').read_bytes()),
                status='SEALED_INTERVAL_COMPLETE_REVIEW_REQUIRED' if end==pd.Timestamp(seal['end']) else 'FORWARD_PAPER_IN_PROGRESS',
                accepted_bar_hashes=daily_hashes,evaluations=evaluations,orders=False)
    path=out/f'asof_{end.date()}.json'
    if path.exists():
        if json.loads(path.read_text())!=record:raise ValueError('Immutable as-of evaluation already exists with different content')
    else:write_json(path,record)
    return record


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--init',action='store_true');parser.add_argument('--prices-dir',type=Path)
    parser.add_argument('--results',type=Path,default=HERE/'results');args=parser.parse_args()
    out=HERE/'paper';seal=init(out,args.results)
    if args.prices_dir:
        result=evaluate(seal,args.prices_dir,out);print(json.dumps({'status':result['status'],'asof':result['asof']}))
    else:print(json.dumps({'status':seal['status'],'start':seal['start'],'end':seal['end'],'nominees':list(seal['candidates'])}))


if __name__=='__main__':main()
