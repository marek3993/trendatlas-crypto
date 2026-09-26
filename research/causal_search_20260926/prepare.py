"""Freeze public inputs and complete search design before any market replay."""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import platform
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASSETS = ['ADA','AVAX','BNB','BTC','DOGE','DOT','ETH','LINK','LTC','SOL','TRX','XRP']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def variants():
    risks = [
        dict(name='rotation', catastrophic=0, trail=0, tp=0, tp_atr=2, cooldown=0),
        *[dict(name=f'cat{k}', catastrophic=k, trail=0, tp=0, tp_atr=2, cooldown=3) for k in [3,4,5]],
        *[dict(name=f'trail{k}', catastrophic=0, trail=k, tp=0, tp_atr=2, cooldown=3) for k in [2,3,4]],
        dict(name='tp25', catastrophic=0, trail=3, tp=.25, tp_atr=2, cooldown=3),
        dict(name='tp50', catastrophic=0, trail=3, tp=.5, tp_atr=3, cooldown=3),
        dict(name='cooldown', catastrophic=4, trail=0, tp=0, tp_atr=2, cooldown=7),
        dict(name='combo25', catastrophic=4, trail=3, tp=.25, tp_atr=2, cooldown=3),
        dict(name='combo50', catastrophic=3, trail=2, tp=.5, tp_atr=3, cooldown=7),
    ]
    result=[]
    for mom, trend, vol, risk in itertools.product([21,63,126], ['own100','own200','market200'], [.2,.4,.6], risks):
        p=dict(momentum=mom, trend=trend, vol_target=vol, **risk)
        p['id']=f'm{mom}_{trend}_v{int(vol*100)}_{risk["name"]}'
        result.append(p)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-bundle',type=Path,required=True)
    parser.add_argument('--source-manifest',type=Path,required=True);args=parser.parse_args()
    if (HERE/'pre_registration.json').exists() or (HERE/'inputs.zip').exists():
        raise FileExistsError('Existing freeze cannot be replaced')
    source_manifest=json.loads(args.source_manifest.read_text(encoding='utf-8'))
    assert digest(args.source_bundle.read_bytes())==source_manifest['bundle_sha256']
    paths={};identity=[]
    with zipfile.ZipFile(args.source_bundle) as src, zipfile.ZipFile(HERE/'inputs.zip','w',compression=zipfile.ZIP_DEFLATED) as dst:
        for asset in ASSETS:
            path=f'data/ohlcv/{asset}USDT_1d.csv';data=src.read(path)
            assert digest(data)==source_manifest['files'][path]['sha256']
            name=f'{asset}USDT_1d.csv';info=zipfile.ZipInfo(name,(2026,9,26,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            dst.writestr(info,data);paths[name]=digest(data)
            identity.append(dict(asset=asset,symbol=asset+'USDT',venue='Binance',instrument='spot',quote='USDT',member=name,
                                 identity_rule='Exact member filename and symbol key; no BASE, aliases, synthetic returns or relabeling.'))
    contract=ROOT/'source_of_truth/research_objectives_contract.json'
    spec=dict(schema_version=1,classification=['D','B'],scope='offline_research_only',seed=20260926,
        contract_path='source_of_truth/research_objectives_contract.json',contract_sha256=digest(contract.read_bytes()),
        input_bundle_sha256=digest((HERE/'inputs.zip').read_bytes()),input_members=paths,identity=identity,
        source_bundle_sha256=source_manifest['bundle_sha256'],source_capture=source_manifest['capture_utc'],
        history_start='2018-08-01',history_end='2026-09-25',last_market_bar_in_inputs='2026-09-25',
        development=['2018-08-01','2020-12-31'],
        folds=[dict(id=str(y),train_start='2018-08-01',train_end=f'{y-2}-12-31',validation_start=f'{y-1}-01-01',validation_end=f'{y-1}-12-31',
                    test_start=f'{y}-01-01',test_end=f'{y}-12-31' if y<2026 else '2026-09-25') for y in range(2021,2027)],
        variants=variants(),partitions=[dict(id='robust_1.25',mode='robust',cap=1.25,dd_cap=.25)]+
            [dict(id=f'aggressive_{cap:g}',mode='aggressive',cap=cap,dd_cap=.35) for cap in [1.25,1.5,2,2.5,3]],
        budgets=dict(variants_per_partition=324,nominal_replays_per_partition=324,double_cost_replays_per_partition=324,
                     delayed_replays_per_partition=324,neighbor_replays_per_partition=18,random_search=0,adaptive_new_trials=0),
        selectors=['growth','calmar','defensive'],
        selection='Pareto on prior-calendar-year validation metrics only, with declared regime DD/exposure feasibility. growth: highest CAGR then DD; calmar: highest Calmar then DD; defensive: smallest DD then CAGR, requiring positive CAGR. No feasible positive candidate => CASH. Six partitions, three predeclared adaptive policies each. Parameter updates only on Jan 1. Warm starts do not carry hypothetical selection profits.',
        oos_reporting='Each policy chooses parameters using earlier validation only. Fixed-grid OOS rankings are forbidden. The observed best among the 18 policies is a research comparison, not sealed proof. Pre-seal forward nominees are chosen using development metrics, never OOS outcomes.',
        fold_accounting='Reset CASH at known calendar boundaries, charge exit at prior close and new entry at next open; all alternatives get identical boundaries. No label fitting; indicators use prior data with 252-bar admission.',
        timing=dict(feature_lag_bars=2,signal_available='Close D available at D+1 00:00:01 UTC; first subsequent captured daily open is D+2. Stress adds one bar.',
                    atr='Wilder 14 from completed bars; entry ATR frozen for TP/catastrophe; trailing updated from completed bars only; strictly monotonic.',
                    fill='Executable proxy spot daily OHLC; try O-H-L-C and O-L-H-C with preexisting thresholds and keep worse terminal equity; stop gaps at open; no same-bar reentry.',
                    missing='No forward-filled active prices; missing or nonpositive OHLC invalidates inputs. New asset eligible only after 252 observed closed bars.'),
        costs=dict(fee_bps=4.5,slippage_bps=10,funding_annual_debit=.12,funding_basis='entire held notional',
                   funding_is_proxy=True,borrow_annual=0,double_multiplier=2,liquidation_fee_bps=50,maintenance_ratio=.05,
                   model='Linear long marked exposure on spot price proxy. Not historical Hyperliquid perps, oracle/mark, funding, liquidity or contract listings.'),
        sizing=dict(headroom=.9,vol_window=20,vol_slow_window=60,vol_floor=.10,
                    target='min(cap * .9, annual volatility target / realized volatility). Leverage above 1 only if BTC and asset trends healthy. BTC weak caps at .5; vol20/vol60 >1.3 caps .75, >1.8 caps .5. Risk-off trend => CASH.',
                    exposure_guard='At adverse continuous path crossing of gross notional/equity cap, exit; adverse opening gaps may breach cap and are flagged. Margin insolvency is recorded, never clipped into a healthy result.',
                    increases='No averaging down: same-position increases allowed only above last add price and with confirmed rebound; no restoration after partial TP.'),
        rotation=dict(rank='Largest positive close/momentum-close minus one, eligible symbols only. Current position retained unless challenger score exceeds held score by 5 percent.',
                      priority='New target immediately overrides old cooldown/TP/trailing state. Close old before opening new. CASH always allowed.'),
        reentry=dict(confirm='Two rising completed closes and last close above EMA20 after stop, plus per-position cooldown. No refill during ongoing decline.',trail_activation_atr=1),
        parameter_neighbors=dict(axes=['momentum adjacent grid','vol_target adjacent grid'],require='All existing axial adjacent grid points, same trend/risk family.',
                                 similarity='Neighbor positive CAGR and >=70% center CAGR with DD <= center DD + 0.10. Stability = passing neighbors / all neighbors; all needed for high-return success.',
                                 additional_finalist_replays='ATR, trail and TP thresholds multiplied by 0.8 and 1.2; momentum/vol also perturbed for six total per selector; no retuning or selection from neighbors.'),
        metrics=dict(cagr='elapsed UTC days /365.25, net account equity',drawdown='worst event equity across conservative path; includes initial equity',
                     sharpe='daily sample SD; zero risk-free; sqrt(365.25)',log_growth='Each marked price/cost event log(Eafter/Ebefore), attributed to concrete asset and flat-to-flat episode; partial TP stays in same episode.',
                     removed_trades='Subtract top three positive complete episode log contributions from total log growth, retaining dates; diagnostic omission, not changed capital allocation replay.',
                     risk_stress='Re-run entire engine at 2x fees/slippage/funding and +1 entry bar. Fold selection remains frozen from nominal validation.'),
        sealed=dict(historical_available=False,reason='Supplied repository history has been repeatedly inspected; no untouched historical seal claimed.',
                    forward_start='2026-09-27',forward_end='2027-09-26',paper_only=True,freeze_before_new_data=True,
                    refit_during_forward_seal=False,first_signal='After immutable finalist record; no retroactive signals or fills.'),
        limitations=['Fixed present-day universe is survivor-biased; listing-time admission does not reconstruct delisted coins.',
                     'Spot OHLC plus funding/slippage proxies cannot validate exchange-specific fills or funding.',
                     'Historical OOS is chronological computational OOS, not unseen research history.',
                     'All 1944 nominal variant trials and their costs/delay/neighbor tests count toward multiple testing.'],
        python=platform.python_version())
    write_json(HERE/'pre_registration.json',spec)
    print(json.dumps({'variants_per_partition':len(spec['variants']),'partitions':6,'nominal_trials':len(spec['variants'])*6,
                      'pre_registration_sha256':digest((HERE/'pre_registration.json').read_bytes())}))


if __name__=='__main__': main()
