"""Descriptive episode/timing anatomy; never used to select new variants."""
from common import *
from diagnose import REPRESENTATIVES,legacy_replay
from replay import simulate

def main():
    out=HERE/'diagnostics';m=enhanced_market();btc=m.assets.index('BTC');summaries=[];episodes=[]
    for name in REPRESENTATIVES:
        events=pd.read_csv(out/f'{name}_events.csv');curve=pd.read_csv(out/f'{name}_equity.csv');years=len(curve)/365.25
        events['key']=events.date.str[:4]+'/'+events.episode.astype(str)
        for key,g in events.groupby('key',sort=False):
            en=g[g.event=='entry'];ex=g[g.event.isin(['rotation','stop','exposure_guard','boundary_exit','liquidation'])]
            if en.empty or ex.empty:continue
            first,last=en.iloc[0],ex.iloc[-1];i=m.dates.get_loc(first.date);j=m.dates.get_loc(last.date);a=m.assets.index(first.asset)
            exact_open_pair=last.event=='rotation'
            actual=last.price/first.price-1
            btc_ret=m.prices[j,btc,0]/m.prices[i,btc,0]-1 if exact_open_pair else None
            end=min(j+7,len(m.dates)-1)
            episodes.append(dict(policy=name,episode=key,asset=first.asset,entry=first.date,exit=last.date,
                days=(pd.Timestamp(last.date)-pd.Timestamp(first.date)).days,exit_reason=last.event,net_log_growth=g.log_growth.sum(),
                raw_asset_return=actual,matched_BTC_open_return=btc_ret,
                matched_asset_minus_BTC=actual-btc_ret if btc_ret is not None else None,
                preceding_30_day_return=m.prices[i-2,a,3]/m.prices[i-32,a,3]-1,
                following_entry_7_day_raw_return=m.prices[min(i+7,len(m.dates)-1),a,3]/first.price-1,
                following_exit_7_day_raw_return=m.prices[end,a,3]/last.price-1))
        local=pd.DataFrame([v for v in episodes if v['policy']==name]);open_pairs=local.dropna(subset=['matched_asset_minus_BTC'])
        eq=curve.equity.to_numpy();peak=np.maximum.accumulate(np.r_[1,eq])[1:];trough=int(np.argmax(1-eq/peak));top=int(np.argmax(eq[:trough+1]))
        summaries.append(dict(policy=name,entries=len(local),entries_per_year=len(local)/years,median_holding_days=float(local.days.median()),
          losing_episode_fraction=float((local.net_log_growth<0).mean()),exact_open_comparison_episodes=len(open_pairs),
          fraction_underperforming_BTC_same_entry_exit=float((open_pairs.matched_asset_minus_BTC<0).mean()),
          median_matched_asset_minus_BTC=float(open_pairs.matched_asset_minus_BTC.median()),
          median_pre_entry_30_day_raw_return=float(local.preceding_30_day_return.median()),
          median_post_entry_7_day_raw_return=float(local.following_entry_7_day_raw_return.median()),
          median_post_exit_7_day_raw_return=float(local.following_exit_7_day_raw_return.median()),
          close_equity_peak=curve.date.iloc[top],close_equity_trough=curve.date.iloc[trough],
          close_equity_drawdown=float(1-eq[trough]/peak[trough])))
    pd.DataFrame(episodes).to_csv(out/'episode_timing.csv',index=False)
    pd.DataFrame(summaries).to_csv(out/'episode_summary.csv',index=False)
    # Check that removing the overlays did not derive its result from changing
    # cooldown: the original diagnostic preset normalizes it to three days.
    check={};spec=legacy_spec();vm={p['id']:p for p in spec['variants']};choices=read(OLD/'results/walk_forward_choices.json')
    for name in REPRESENTATIVES:
        cap=float(name.split('__')[0].split('_')[1]);runs=[]
        for f in spec['folds']:
            selected=choices[name][f['id']]['variant']
            if selected is None:r=cash_run(m,f['test_start'],f['test_end'])
            else:
                p=dict(vm[selected]);p.update(catastrophic=0,trail=0,tp=0)
                r=simulate(m,p,cap,start=f['test_start'],end=f['test_end'])
            runs.append(r)
        strict=e.stitch(runs);original=legacy_replay(m,name,'no_protection')
        error=float(np.max(np.abs(strict['rows']-original['rows'])))
        check[name]=dict(max_array_error=error,strict_preserved_cooldown_metrics=metrics(strict))
        assert error<1e-12,(name,'Cooldown influenced no-protection diagnostic')
    write(out/'no_protection_isolation_check.json',check)
    print(pd.DataFrame(summaries).to_string(index=False))

if __name__=='__main__':main()
