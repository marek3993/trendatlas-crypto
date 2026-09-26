"""Freeze public research inputs; never copy account/runtime output or paper PnL."""
from pathlib import Path
import hashlib, io, json, sys, zipfile
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = ['BTC','ETH','BNB','XRP','SOL','ADA','DOGE','LINK','AVAX','LTC','TRX','DOT']
EXTRA = ['APT','BCH','ICP','STX','XTZ','NEO','HBAR']
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p, x): Path(p).write_text(json.dumps(x, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')

def main(source):
    assert not (HERE/'contract.json').exists(), 'Immutable freeze already exists'
    paths={}; coverage=[]
    with zipfile.ZipFile(HERE/'inputs.zip','w',zipfile.ZIP_DEFLATED) as z:
        for a in CORE+EXTRA:
            rel=f'data/{"ohlcv" if a in CORE else "ohlcv_phase67_top100"}/{a}USDT_1d.csv'
            raw=(source/rel).read_bytes(); f=pd.read_csv(io.BytesIO(raw)); dates=pd.to_datetime(f.iloc[:,0])
            name=f'{a}.csv';z.writestr(name,raw);paths[name]={'source':rel,'sha256':hashlib.sha256(raw).hexdigest()}
            coverage.append(dict(asset=a,first=str(dates.min().date()),last=str(dates.max().date()),rows=len(f)))
        for name,rel in [('macro.csv','data/macro/global_liquidity_weekly.csv'),('etf.csv','outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel/btc_etf_flow_daily_panel.csv')]:
            raw=(source/rel).read_bytes();z.writestr(name,raw);paths[name]={'source':rel,'sha256':hashlib.sha256(raw).hexdigest()}
    end=min(x['last'] for x in coverage)
    source_paths=[ROOT/'phase60_selective_restore_robustness.py',ROOT/'phase61_final_compare.py']
    source_paths+=list((ROOT/'src/market_regime_v1').glob('*.py'))
    source_paths += [ROOT/'scripts'/n for n in ['phase62_btc_overlay.py','phase63_btc_participation_overlay.py','phase66e_probation_governance.py','phase66g_production_candidate_live.py','phase67j_final_narrow_validation_pack.py','phase68g_portfolio_exposure_leverage_validation.py','phase68h_dynamic_leverage_ladder_candidate.py','phase68j_tail_risk_guardrail_check.py','dev_only_phase68g_etf_flow_impulse_probe.py','dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity.py','dev_only_production_core_btc_candidate_persistence_early_risk_compare.py','approved_strategy_net_export_helper.py']]
    source_paths+=list((ROOT/'scripts/production/strategy_adapters').glob('phase68g*.py'))
    spec=dict(schema_version=1,classification=['D','B'],scope='offline research only',orders_allowed=False,production_changes_allowed=False,
      history_start='2018-08-01',oos_start='2021-01-01',end=end,
      folds=[dict(id=str(y),train_start='2018-08-01',train_end=f'{y-2}-12-31',validation_start=f'{y-1}-01-01',validation_end=f'{y-1}-12-31',test_start=f'{y}-01-01',test_end=min(f'{y}-12-31',end)) for y in range(2021,int(end[:4])+1)],
      optimization='none; source-pinned rules and one predeclared representative per phase-2 family; no parameter search or OOS winner refit',
      phase2=dict(lookback=90,schedule='monthly',vol_target=.4,cap=1.25,min_hold=30,hysteresis=.10,ensemble_lookbacks=[30,90,180]),
      costs=dict(fee_bps=4.5,slippage_bps=10,funding_annual_debit=.12,maintenance_ratio=.05,liquidation_fee_bps=50),
      timing='Close D signal assumed available D+1 00:00:01 UTC, fill D+2 open. No D+1 open can precede its signal. ETF uses explicit D+1 session availability; additional bar sensitivity is reported.',
      accounting='Concrete single-asset linear exposure marked on spot OHLC. Daily rebalance to post-cost target exposure including drift. Fees on actual adverse fill notional; funding debit on open held notional, 12% annual proxy. Liquidate at maintenance crossing, adverse gaps at open. Conservative high-before-low intraday DD. Exit at every year end and final end, charge costs. Shadow selection portfolios use this same ledger and costs; only completed shadow returns enter rules.',
      universe=dict(assets=CORE+EXTRA,admission='260 observed complete positive OHLCV bars, positive volume and current raw bar; never future full-file history. All models share this availability mask; historical model-specific exclusions remain explicit experimental treatments.',runtime_shortlist=['NEO','DOGE','STX','APT','HBAR','LINK'],ssot_shortlist=['APT','BCH','DOGE','ICP','STX','XTZ'],core_exclusions=['LTC','SOL'],unverified='Complete historical exchange listings/delistings, historical shortlist vintages and survivorship-free pool unavailable. This is causal admission within frozen archival cohort, NOT certified point-in-time market universe.'),
      corrections=['No stored paper returns/metrics are inputs','Resolve BASE through explicit source target and every named target through its own prices','All nested shadows D+2 fills with uniform costs','DD deterioration = baseline signed DD minus candidate signed DD; prepend initial equity and include first return','Anchor weekly scheduling independent of terminal length','No price forward/back fill; fail on missing held quotes'],
      ablations=dict(A='source phase61 selector alone',B='A + phase63 BTC/risk permission + trend permission wrapper at 1x',C='B + phase66g soft governance + phase67j challenger governance BEFORE pruning',D='C + LTC/SOL exclusion in phase66 and NEO exclusion in reference shortlist',E='D + 1.25 exposure, plus separate persistence bridge E_persistence',F='E_persistence + ETF entry with zero cooldown',G='F + 15-day cooldown = current corrected literal-asset route',H='G with base rotation selector replaced by volatility-adjusted 90d momentum; every dependent shadow/permission recomputed',I='G with same original score selector on monthly schedule, 30-day minimum hold and 10 score-point hysteresis; immediate risk exit'),
      identity='Phase68 uses nonblank phase66 weekly chosen_asset even if that challenger signal is inactive, otherwise phase67 reference policy. BASE is resolved to underlying source target; named coin always earns that coin return. Separate economic-route sensitivity uses true phase66 executed target.',
      metrics=dict(cagr='365.25 elapsed UTC years including cash',mdd='intraday conservative event drawdown with initial equity',sharpe='sample SD daily; zero risk free',turnover='annual executed absolute fill notional / prefill equity, both legs',costs='annual sum cost debit / precharge equity; not compounded drag',trades='complete same-asset flat-to-flat episodes; resizing never splits episode',remove_best_day='replace largest net daily return with zero retaining calendar',remove_three_trades='subtract top 3 positive complete episode log contributions, retaining calendar',double_cost='rerun accounting at 2x fees, adverse slippage and funding debit with frozen signals; second full dependent-rule rebuild sensitivity'),
      inference='Paired deltas are conditional path-dependent ablations, not additive causal effects. Compare both full history folds and ETF-available window. Chronological algorithmic OOS, NOT untouched historical or sealed evidence. All selected historical masks and parameters have prior research selection bias.',
      decision_rule='KEEP only if current net CAGR positive, MDD<=35%, 2x cost CAGR positive and >=75% profitable folds. SELECTOR replacement only if H or I meets these gates and dominates current risk/stress with positive growth in >=4 of 6 folds; otherwise REPLACE_STRATEGY as research architecture recommendation, not deployment approval or proof of a validated replacement.',
      input_members=paths,coverage=coverage,input_bundle_sha256=sha(HERE/'inputs.zip'),source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in source_paths},
      evidence_gaps=['No historical macro release vintages','ETF first publication timestamps and revision vintages absent','No venue-specific historical order book or perp funding/listing history','No untouched holdout; no validated deployable winner can be declared'])
    write(HERE/'contract.json',spec)
    pd.DataFrame(coverage).to_csv(HERE/'coverage.csv',index=False)
    # Keep user-amended objectives as read-only provenance, not production SSOT.
    (HERE/'objectives_reference.json').write_bytes((source/'source_of_truth/research_objectives_contract.json').read_bytes())
    print(json.dumps({'end':end,'assets':len(coverage),'contract_sha256':sha(HERE/'contract.json')}))

if __name__=='__main__': main(Path(sys.argv[1]).resolve())
