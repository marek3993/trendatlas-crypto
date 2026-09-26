"""Independent arithmetic plus actual truncated-data/future-mutation replays."""
from functools import lru_cache
from common import *
from search import spec_checked,replay_policy,OVERLAYS
from replay import simulate
from signals import Controller
from finalize import verify_arithmetic
from scripts import research_objectives as objectives

def main():
    out=HERE/'results';spec=spec_checked();result=read(out/'results.json');choices=read(out/'choices_before_oos.json')
    vm={p['id']:p for p in spec['variants']};m=enhanced_market();checks={};cache={};actual_probes=0
    table=pd.read_csv(out/'validation_scores.csv');assert len(table)==6*66*7
    folds=pd.read_csv(out/'oos_folds.csv');assert len(folds)==84*6
    assert len(result['policies'])==84
    @lru_cache(maxsize=24)
    def altered_markets(cut):
        stop=m.dates.searchsorted(pd.Timestamp(cut),side='right')
        raw={a:pd.DataFrame(m.prices[:stop,j],index=m.dates[:stop],columns=['open','high','low','close']).dropna() for j,a in enumerate(m.assets)}
        truncated=enhanced_market(e.market_from_frames(raw))
        raw={a:pd.DataFrame(m.prices[:,j].copy(),index=m.dates,columns=['open','high','low','close']).dropna() for j,a in enumerate(m.assets)}
        for f in raw.values():f.loc[f.index>cut]*=3.17
        future=enhanced_market(e.market_from_frames(raw))
        return truncated,future
    def probe(p,cap,start,end,risk):
        nonlocal actual_probes
        key=json.dumps([p,cap,start,end,risk],sort_keys=True)
        if key in cache:return cache[key]
        cut=str(min(pd.Timestamp(start)+pd.Timedelta(days=120),pd.Timestamp(end)).date())
        short,future=altered_markets(cut)
        kw=dict(start=start,end=cut)
        ref=simulate(m,risk,cap,controller=Controller(p),**kw)
        prefix=simulate(short,risk,cap,controller=Controller(p),**kw)
        perturbed=simulate(future,risk,cap,controller=Controller(p),**kw)
        assert np.array_equal(ref['rows'],prefix['rows']) and ref['signals']==prefix['signals'],'Prefix leakage'
        assert np.array_equal(ref['rows'],perturbed['rows']) and ref['signals']==perturbed['signals'],'Future leakage'
        actual_probes+=2
        cache[key]=dict(start=start,probe_end=cut,prefix_recomputed_from_raw=True,future_prices_multiplied_3_17=True,passed=True)
        return cache[key]
    for ix,p in enumerate(result['policies']):
        name=p['id'];base=p['partition']+'__'+p['selector'];risk=OVERLAYS[p['overlay']] if p['overlay'] else no_risk()
        evidence=[]
        for f in spec['folds']:
            selected=choices[base][f['id']]
            assert f['validation_end']<f['test_start']
            if selected:evidence.append(probe(vm[selected],p['cap'],f['test_start'],f['test_end'],risk))
        ev=pd.read_csv(out/f'{name}_events.csv');curve=pd.read_csv(out/f'{name}_equity.csv');signals=pd.read_csv(out/f'{name}_signals.csv')
        count=verify_arithmetic(ev,spec) if len(ev) else 0
        total=float(np.log1p(curve.net_return).sum());assert abs(total-ev.log_growth.sum())<1e-8
        ev_eq=np.r_[1,np.exp(np.cumsum(ev.log_growth.to_numpy()))];dd=float(np.max(1-ev_eq/np.maximum.accumulate(ev_eq)))
        assert abs(dd-p['oos']['max_drawdown'])<1e-9,(name,dd,p['oos']['max_drawdown'])
        equity=np.cumprod(1+curve.net_return);assert np.allclose(equity,curve.equity,atol=1e-12)
        if len(ev):
            ev['key']=ev.date.str[:4]+'/'+ev.episode.astype(str)
            groups=ev.groupby('key').log_growth.sum().sort_values(ascending=False)
            omission=np.exp((total-groups[groups>0].head(3).sum())/(len(curve)/365.25))-1
            assert abs(omission-p['oos']['without_top_three_trades_cagr'])<1e-9
            assert ev.groupby('key').asset.nunique().max()==1
        for v in signals.itertuples():assert pd.Timestamp(v.fill_day)-pd.Timestamp(v.source_day)>=pd.Timedelta(days=2)
        pending=None;reentries=0
        for v in ev.itertuples():
            i=m.dates.get_loc(v.date);a=m.assets.index(v.asset);o,h,l,c=m.prices[i,a]
            assert l-1e-8<=v.price<=h+1e-8,(name,v.date,v.asset,v.price)
            if v.event in ('stop','exposure_guard','liquidation'):pending=(v.asset,pd.Timestamp(v.date))
            elif v.event=='entry':
                if pending and pending[0]==v.asset and pending[1].year==pd.Timestamp(v.date).year:
                    assert (pd.Timestamp(v.date)-pending[1]).days>=4
                    assert m.features['rebound'][i-2,a];reentries+=1
                pending=None
        checks[name]=dict(replay_probes=evidence,independent_event_count=count,raw_asset_price_lineage=True,
            quantity_price_fee_funding_arithmetic=True,log_growth_and_daily_equity=True,event_drawdown=True,
            flat_to_flat_omission=True,source_at_least_two_days_before_fill=True,confirmed_post_exit_reentries=reentries,
            point_in_time_universe=False,observed_signal_publication_timestamps=False,historical_venue_funding_and_fills=False,
            historical_sealed_evidence=False,simulated_event_exposure_cap=p['oos']['max_realized_exposure']<=p['cap']+1e-12)
        if ix%14==13:print('Audited OOS partition',p['partition'],flush=True)
    # Every high nominal development/annual validation row, not just selected
    # finalists, receives an executed structural audit. Validation is not OOS.
    high=[]
    for v in table[table.cagr>=1.5].itertuples():
        start,end=spec['development'] if v.window=='development' else (f'{v.window}-01-01',f'{v.window}-12-31')
        part=next(p for p in spec['partitions'] if p['id']==v.partition)
        proof=probe(vm[v.variant],part['cap'],start,end,no_risk())
        high.append(dict(partition=v.partition,variant=v.variant,window=v.window,cagr=v.cagr,structural_audit=proof,
                         finalist_status='BLOCKED: validation-only return; missing PIT universe, observed venue execution and sealed evidence'))
    write(out/'audits.json',dict(search_sha256=sha(HERE/'search_freeze.json'),audit_code_sha256=sha(Path(__file__)),
        checks=checks,high_development_and_validation=high,unique_recomputed_prefix_and_future_probes=actual_probes,
        unique_probe_settings=len(cache),budget_counts=dict(variants=396,grid_scenarios=1188,grid_metric_windows=2772,oos_policies=84,oos_folds=504,neighbors=252),
        immutable_legacy=True,no_seal=True))
    # The objective evaluator must also see missing evidence, not only numbers.
    screening={}
    for p in result['policies']:
        screening[p['id']]=dict(feasibility=objectives.feasibility(dict(mode=p['mode'],exposure_cap=p['cap']),p['oos'],objectives.load_contract()),
          oos_high_return_failures=p['high_return_failures'],sealed='MISSING',accepted_A=False,
          evidence_gaps=['historical sealed evaluation','point-in-time delisted universe','observed publication timestamps','venue funding and fills'])
    write(out/'screening.json',screening)
    print('PASS: all 84 ledgers and 504 folds;',actual_probes,'actual prefix/future probes;',len(high),'high validation/development rows audited',flush=True)

if __name__=='__main__':main()
