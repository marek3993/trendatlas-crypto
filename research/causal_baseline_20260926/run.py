"""One-command offline replay. All generated files stay inside this research directory."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd
from collect_inputs import extract_verified, sha

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
spec=importlib.util.spec_from_file_location('causal',REPO/'scripts/production/causal_performance.py')
causal=importlib.util.module_from_spec(spec);sys.modules[spec.name]=causal;spec.loader.exec_module(causal)

def save_json(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8',newline='\n')

def prices_from_raw(root):
    rows=[]
    for path in sorted((root/'data/ohlcv').glob('*USDT_1d.csv')):
        frame=pd.read_csv(path)
        coin=causal.asset(path.name.split('_')[0])
        for i,row in enumerate(frame.itertuples(index=False),2):
            rows.append({'asset':coin,'timestamp':pd.Timestamp(row.date,tz='UTC').isoformat(),
                         'price':row.open,'source_file':path.relative_to(root).as_posix(),
                         'source_row':i,'source_column':'open'})
        # The dataset ends at D close. This terminal mark is valuation only:
        # no fill, no new target and no return interval begins at this mark.
        rows.append({'asset':coin,'timestamp':(pd.Timestamp(frame.date.iloc[-1],tz='UTC')+pd.Timedelta(days=1)).isoformat(),
                     'price':float(frame.close.iloc[-1]),'source_file':path.relative_to(root).as_posix(),
                     'source_row':len(frame)+1,'source_column':'close_terminal_boundary_mark_not_fill'})
    return pd.DataFrame(rows)

def metrics(returns, costs=None):
    r=np.asarray(returns,dtype=float);equity=np.cumprod(1+r)
    if not len(r) or not np.isfinite(r).all() or (r<=-1).any():
        raise ValueError('Invalid performance history')
    dd=equity/np.maximum.accumulate(np.r_[1.,equity])[1:]-1
    years=len(r)/365.25;cagr=equity[-1]**(1/years)-1
    std=r.std(ddof=1);down=np.sqrt(np.mean(np.minimum(r,0)**2))
    result={'days':len(r),'total_return_pct':float((equity[-1]-1)*100),'cagr_pct':float(cagr*100),
            'max_drawdown_pct':float(dd.min()*100),'sharpe':float(np.sqrt(365.25)*r.mean()/std) if std else None,
            'sortino':float(np.sqrt(365.25)*r.mean()/down) if down else None,
            'calmar':float(cagr/-dd.min()) if dd.min()<0 else None,'terminal_index':float(equity[-1])}
    if costs is not None:
        result['costs_sum_daily_equity_percentage_points']={c:float(costs[c].sum()*100) for c in costs}
    return result

def declared_inputs(root, manifest):
    snapshot=json.loads((root/'outputs/production/current_strategy_snapshot.json').read_text())
    checked=[]
    for role,entry in snapshot['source_inputs']['files'].items():
        m=manifest['files'].get(entry['path']);ok=m is not None and m['original_sha256']==entry['sha256']
        checked.append({'role':role,'path':entry['path'],'declared_sha256':entry['sha256'],'match':ok})
    if not all(row['match'] for row in checked):
        raise ValueError('Declared original input missing or mismatched')
    return {'declared_direct_inputs':checked,'missing_declared_inputs':[],
            'published_commit':'6fccbc388c1db75f6b46113fac15b7d3232e4123',
            'runtime_code_commit':snapshot['provenance']['git_commit'],
            'upstream_raw_provenance':'Captured raw is hash-pinned here and Phase60 replay is compared with the captured paper. The original publish does not declare hashes of all upstream raw files.',
            'original_generated_at':snapshot['generated_at_utc']}

def diagnostics(root, out, signals, ledger):
    original=pd.read_csv(root/'outputs/production/current_strategy_timeseries.csv')
    gov=pd.read_csv(out/'governance_lineage.csv')
    audit=original[['date','actual_held_asset','effective_market_exposure','return_gross','return_net']].rename(columns={
        'actual_held_asset':'published_asset_label','effective_market_exposure':'published_exposure',
        'return_gross':'published_gross','return_net':'published_net'})
    audit=audit.merge(gov[['date','economic_asset','chosen_asset','executed_regime']],on='date',validate='one_to_one')
    # BTC early-risk layers deliberately override the underlying core. Where
    # those layers are active, BTC is the economic source of the original row.
    audit['original_economic_source_asset']=np.where(original.early_risk_active,'BTC',audit.economic_asset)
    audit.loc[audit.published_exposure.eq(0),'original_economic_source_asset']='CASH'
    audit['asset_label_mismatch']=audit.published_asset_label.ne(audit.original_economic_source_asset)&audit.published_exposure.gt(0)
    audit=audit.merge(ledger[['date','executed_held_asset','signal_data_day','signal_available_at','gross_strategy_return','net_strategy_return','exposure']],on='date',validate='one_to_one')
    audit['removed_net_percentage_points']=(audit.published_net-audit.net_strategy_return)*100
    audit['removed_gross_percentage_points']=(audit.published_gross-audit.gross_strategy_return)*100
    raw_returns={}
    for path in sorted((root/'data/ohlcv').glob('*USDT_1d.csv')):
        raw=pd.read_csv(path).set_index('date')
        raw_returns[causal.asset(path.name.split('_')[0])]=raw.close.pct_change()
    # Diagnostic bridge only, deliberately NOT an executable backtest: retain
    # the published same-day exposure, use the identified asset's raw close move.
    bridge=np.array([0. if r.original_economic_source_asset=='CASH' else
                     r.published_exposure*raw_returns[r.original_economic_source_asset].loc[r.date]
                     for r in audit.itertuples()])
    audit['identity_and_gross_definition_delta_pp']=(audit.published_gross-bridge)*100
    audit['timing_and_executed_exposure_delta_pp']=(bridge-audit.gross_strategy_return)*100
    audit['explicit_cost_delta_pp']=((audit.gross_strategy_return-audit.net_strategy_return)-(audit.published_gross-audit.published_net))*100
    np.testing.assert_allclose(audit[['identity_and_gross_definition_delta_pp','timing_and_executed_exposure_delta_pp','explicit_cost_delta_pp']].sum(axis=1),audit.removed_net_percentage_points,rtol=1e-10,atol=1e-10)
    audit['reason']='causal_timing_and_execution_costs'
    audit.loc[audit.asset_label_mismatch,'reason']='asset_identity_and_causal_timing_and_execution_costs'
    audit.to_csv(out/'daily_comparison.csv',index=False,lineterminator='\n')
    audit.loc[audit.removed_net_percentage_points.gt(1e-9)].to_csv(out/'removed_returns.csv',index=False,lineterminator='\n')
    mismatch=audit.loc[audit.asset_label_mismatch]
    mismatch.groupby(['published_asset_label','original_economic_source_asset']).agg(days=('date','size')).reset_index().to_csv(out/'asset_mapping_audit.csv',index=False,lineterminator='\n')
    costs=ledger[['fees','slippage','borrow','funding']]
    oldcost=original[['fees_daily','slippage_cost_daily','borrow_cost_daily','funding_daily']].copy();oldcost.columns=costs.columns
    summary={'window':{'start':ledger.date.iloc[0],'last_day':ledger.date.iloc[-1]},
             'metric_convention':'365.25 daily periods/year; sample standard deviation; Sortino uses RMS negative returns over ALL days; zero risk-free rate; drawdown includes initial index 1',
             'published':metrics(original.return_net,oldcost),'causal_candidate':metrics(ledger.net_strategy_return,costs),
             'published_snapshot_metrics':json.loads((root/'outputs/production/current_strategy_snapshot.json').read_text())['metrics'],
             'asset_mismatch_days':len(mismatch),'reduced_return_days':int(audit.removed_net_percentage_points.gt(1e-9).sum()),
             'increased_return_days':int(audit.removed_net_percentage_points.lt(-1e-9).sum()),
             'daily_difference_warning':'Signed daily percentage-point differences are not additive total returns and do not uniquely apportion overlapping timing, asset and cost fixes.',
             'attribution_bridge':'Ordered diagnostic: published gross -> original economic asset close/close at published exposure -> causal executed gross -> explicit net costs. The bridge is not an investable series; timing includes changed holdings, exposure drift and open-price convention. Correcting an asset label need not remove a legitimate return.',
             'focus_days':json.loads(audit.loc[audit.date.isin(['2024-12-03','2025-01-07','2026-09-24'])].to_json(orient='records',double_precision=15)),
             'latest_decision':signals.iloc[-1].to_dict(),
             'latest_weekly_candidate':str(gov.chosen_asset.iloc[-1]),
             'latest_economic_base_asset':str(gov.economic_asset.iloc[-1]),
             'no_latest_fill_claim':'Final target is available after the price dataset ends. It earns no return in this ledger.'}
    save_json(out/'comparison.json',summary)

def assemble(root,out,manifest):
    signals=pd.read_csv(out/'signals.csv');prices=prices_from_raw(root)
    original=pd.read_csv(root/'outputs/production/current_strategy_timeseries.csv')
    ledger=causal.build_ledger(signals,prices,start=original.date.iloc[0],end=(pd.Timestamp(original.date.iloc[-1])+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    ledger.to_csv(out/'causal_ledger.csv',index=False,lineterminator='\n')
    prices.to_csv(out/'price_provenance.csv',index=False,lineterminator='\n')
    chart=causal.model_chart(ledger,prices.loc[prices.asset.eq('BTC')])
    chart.to_csv(out/'dashboard_model_chart.csv',index=False,lineterminator='\n')
    periods=ledger.groupby(ledger.transition_flag.cumsum()).agg(start=('return_interval_start','first'),end=('return_interval_end','last'),asset=('executed_held_asset','first'),days=('date','size'),first_ledger_csv_row=('date',lambda x:int(x.index[0])+2),last_ledger_csv_row=('date',lambda x:int(x.index[-1])+2)).reset_index(drop=True)
    periods.to_csv(out/'active_periods.csv',index=False,lineterminator='\n')
    save_json(out/'input_verification.json',declared_inputs(root,manifest))
    diagnostics(root,out,signals,ledger)
    save_json(out/'reproduction_manifest.json',{'bundle_sha256':manifest['bundle_sha256'],
        'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
        'costs':asdict(causal.Costs()),'funding_proxy':'3bp/day full notional; an extra positive stress friction, not measured Hyperliquid funding or a guaranteed upper bound',
        'borrow_proxy':'Legacy 12% annual charge on notional above equity, additional to the funding friction; not a claim about Hyperliquid spot/perpetual financing',
        'position_convention':'Fixed units until an asset or target exposure change. Equity costs cause exposure drift. No free daily rebalance.',
        'execution_convention':'Binance spot daily open-to-open; first daily open after availability; last close is valuation only, no fill',
        'historical_availability':'Archived original build-validation time when captured, otherwise explicit D+1 12:00 UTC schedule assumption. Corrected signals are counterfactual.',
        'point_in_time_limit':'No full historical venue marks/funding or macro revision vintages. Frozen OHLCV and macro data support a reproducible causal schedule candidate, not an exact historical live-execution backtest.',
        'source_sha256':{p.relative_to(REPO).as_posix():sha(p.read_bytes()) for p in [*sorted(HERE.glob('*.py')),HERE/'requirements.txt',REPO/'scripts/production/causal_performance.py',REPO/'source_of_truth/causal_model_performance_contract.json']},
        'result_sha256':{p.name:sha(p.read_bytes()) for p in sorted(out.iterdir()) if p.suffix in ('.csv','.json') and p.name not in ('reproduction_manifest.json','validation.json')}})
    print(json.dumps(json.loads((out/'comparison.json').read_text())['causal_candidate']))

def main(out):
    out=out.resolve()
    if not out.is_relative_to(HERE) or out==HERE:
        raise ValueError('Output must be a subdirectory of this research directory')
    manifest=json.loads((HERE/'input_bundle.manifest.json').read_text())
    (HERE/'scratch').mkdir(exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='replay-',dir=HERE/'scratch'))
    extract_verified(HERE/'input_bundle.zip',manifest,root)
    subprocess.run([sys.executable,str(HERE/'rebuild_signals.py'),'--root',str(root),'--out',str(out)],check=True)
    assemble(root,out,manifest)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=HERE/'results');a=p.parse_args();main(a.out)
