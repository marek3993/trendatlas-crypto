"""Rebuild all signals from raw inputs, replay, reconcile, export research only."""
from pathlib import Path
import argparse, hashlib, json, platform, sys, time, zipfile
import numpy as np
import pandas as pd
import engine as e
import rules

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def write(path,x):path.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False,default=str)+'\n',encoding='utf-8')
def protected():
    return {p.relative_to(ROOT).as_posix():(p.stat().st_size,p.stat().st_mtime_ns) for name in ['outputs','data','source_of_truth','canonical'] for p in (ROOT/name).rglob('*') if p.is_file()}
def main():
    p=argparse.ArgumentParser();p.add_argument('--double-feedback',action='store_true');args=p.parse_args()
    started=time.time();s=e.spec();before=protected()
    for path,expected in s['source_hashes'].items():assert e.digest(ROOT/path)==expected,path
    freeze=dict(contract_sha256=e.digest(HERE/'contract.json'),input_sha256=e.digest(HERE/'inputs.zip'),code_sha256={x.name:e.digest(x) for x in HERE.glob('*.py')},started_utc=pd.Timestamp.now(tz='UTC').isoformat(),python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__)
    write(HERE/('feedback_freeze.json' if args.double_feedback else 'run_freeze.json'),freeze)
    m=e.load();signals,metadata=rules.build(m,mult=2. if args.double_feedback else 1.)
    out=HERE/('feedback' if args.double_feedback else 'results');out.mkdir(exist_ok=True)
    rows=[];folds=[];window=[]
    with zipfile.ZipFile(out/'ledgers.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name,t in signals.items():
            print('Replay '+name,flush=True)
            run=e.simulate(m,t,start=s['oos_start'],mult=2. if args.double_feedback else 1.,details=True)
            metrics=e.summarize(run)
            if not args.double_feedback:
                stressed=e.summarize(e.simulate(m,t,start=s['oos_start'],mult=2.))
                delayed=e.summarize(e.simulate(m,t,start=s['oos_start'],lag=3))
                metrics.update(double_cost_cagr=stressed['cagr'],double_cost_mdd=stressed['mdd'],delay_cagr=delayed['cagr'])
            for year,val in metrics.pop('fold_returns').items():folds.append(dict(strategy=name,fold=year,net_return=val))
            rows.append(dict(strategy=name,**metrics))
            frame=run['daily'].drop(columns='path')
            z.writestr(name+'/daily.csv',frame.to_csv(index_label='date',float_format='%.15g'))
            z.writestr(name+'/signals.csv',t[['asset','weight']].to_csv(index_label='signal_date',float_format='%.15g'))
            z.writestr(name+'/trades.csv',pd.DataFrame(run['episodes']).to_csv(index=False,float_format='%.15g'))
            z.writestr(name+'/fills.csv',pd.DataFrame(run['fills']).to_csv(index=False,float_format='%.15g'))
            post=e.summarize(e.simulate(m,t,start='2024-01-12',mult=2. if args.double_feedback else 1.))
            post.pop('fold_returns');window.append(dict(strategy=name,**post))
    pd.DataFrame(rows).to_csv(out/'comparison.csv',index=False,float_format='%.12g')
    pd.DataFrame(folds).to_csv(out/'folds.csv',index=False,float_format='%.12g')
    pd.DataFrame(window).to_csv(out/'etf_window.csv',index=False,float_format='%.12g')
    write(out/'source_rule_configs.json',metadata)
    assert before==protected(),'Protected data or production tree modified'
    for name,h in freeze['code_sha256'].items():assert e.digest(HERE/name)==h,name
    write(out/'receipt.json',dict(seconds=time.time()-started,strategies=len(rows),protected_files=len(before),protected_tree_unchanged=True,source_hashes_verified=True,stored_paper_returns_read=False,production_writes=False,freeze_sha256=e.digest(HERE/('feedback_freeze.json' if args.double_feedback else 'run_freeze.json'))))
    print(pd.DataFrame(rows)[['strategy','cagr','mdd','profitable_folds']].to_string(index=False),flush=True)

if __name__=='__main__':main()
