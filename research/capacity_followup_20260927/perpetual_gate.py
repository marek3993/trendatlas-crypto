"""Venue-specific evidence gate. Never substitute spot or today's margin table."""
import io,json,zipfile
import pandas as pd
from common import HERE,SPEC,write,digest

def ranges(index,step):
    index=pd.DatetimeIndex(index).sort_values()
    if not len(index):return []
    groups=[];start=prior=index[0]
    for d in index[1:]:
        if d-prior!=step:groups.append([str(start),str(prior)]);start=d
        prior=d
    groups.append([str(start),str(prior)]);return groups

def funding_coverage(frame,start,end):
    # Coverage tolerance only: preserve every raw millisecond timestamp/rate.
    f=frame.copy();f['time']=pd.to_datetime(f.calc_time,unit='ms');f=f.sort_values('time');missing=[];transitions=[]
    for before,now in zip(f.iloc[:-1].itertuples(),f.iloc[1:].itertuples()):
        if now.time<start or before.time>end:continue
        if before.funding_interval_hours!=now.funding_interval_hours:transitions.append(dict(at=str(now.time),before_hours=int(before.funding_interval_hours),after_hours=int(now.funding_interval_hours)))
        step=pd.Timedelta(hours=max(before.funding_interval_hours,now.funding_interval_hours));lo=before.time.floor('s')+step;hi=now.time.floor('s')-step
        if lo<=hi:missing.append([str(max(start,lo)),str(min(end,hi))])
    if len(f):
        first,last=f.time.iloc[0],f.time.iloc[-1]
        if first.floor('s')>start:missing.insert(0,[str(start),str(first.floor('s')-pd.Timedelta(seconds=1))])
        if last+pd.Timedelta(hours=float(f.funding_interval_hours.iloc[-1]))<end:missing.append([str(last),str(end)])
    else:missing=[[str(start),str(end)]]
    return missing,transitions

def main():
    period=SPEC['D']['required_period'];start=pd.Timestamp(period[0]);end=pd.Timestamp(period[1])+pd.Timedelta(hours=20)
    evidence=[]
    for name in ['perp_trade','perp_mark','funding']:
        with zipfile.ZipFile(HERE/(name+'.zip')) as z:
            for symbol in SPEC['data']['perpetual_symbols']:
                f=pd.read_csv(io.BytesIO(z.read(symbol+'.csv'))) if symbol+'.csv' in z.namelist() else pd.DataFrame()
                transition=[]
                if name=='funding':
                    dates=pd.DatetimeIndex(pd.to_datetime(f.calc_time,unit='ms')) if len(f) else pd.DatetimeIndex([]);step=pd.Timedelta(hours=8)
                    gaps,transition=funding_coverage(f,start,end)
                else:
                    dates=pd.DatetimeIndex(pd.to_datetime(f.date)) if len(f) else pd.DatetimeIndex([]);step=pd.Timedelta(hours=4)
                expected=pd.date_range(start,end,freq=step);actual=dates[(dates>=start)&(dates<=end)]
                evidence.append(dict(symbol=symbol,component=name,rows=len(actual),first=str(actual.min()) if len(actual) else None,last=str(actual.max()) if len(actual) else None,missing_intervals=gaps if name=='funding' else ranges(expected.difference(actual),step),interval_changes=transition,note='Actual millisecond timestamps/rates retained. Coverage tolerates subsecond scheduling and uses recorded variable intervals; transitions are explicit, not zero-filled.' if name=='funding' else 'Actual venue archive, not spot',bundle_sha256=digest(HERE/(name+'.zip'))))
    missing=[]
    for symbol in SPEC['data']['perpetual_symbols']:
        for component in ['versioned_maintenance_margin_brackets','versioned_liquidation_insurance_fee_rules','certified_listing_delisting_timeline','historical_account_fee_tier_and_symbol_filters']:
            missing.append(dict(symbol=symbol,component=component,missing_intervals=[[str(start),str(end+pd.Timedelta(hours=4))]],reason='No complete versioned historical evidence acquired; present-day values cannot certify this interval.'))
    source=[dict(url='https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Notional-and-Leverage-Brackets',finding='Authenticated USER_DATA endpoint gives brackets; no documented historical as-of argument. Not called; no account credential loaded.'),dict(url='https://www.binance.com/en/support/announcement/detail/86cf9aa472574b8cb2e05bb751c2a9a6',finding='BTCUSDT bracket update 2021-03-18 proves version changes exist.'),dict(url='https://www.binance.com/en/support/announcement/detail/f55d25695ca8453ab4c132c1fd4dc36a',finding='Further BTCUSDT bracket update 2021-06-22; isolated announcements do not establish complete series.'),dict(url='https://www.binance.com/en/support/announcement/detail/10a8048af25140489a1b9c65d822031a',finding='Multiple perpetual tier changes 2022-06-16.'),dict(url='https://github.com/binance/binance-public-data',finding='Public trade/mark/funding archives do not certify historical account margin and liquidation tables.')]
    recipes=[dict(name='long_short_cross_sectional_momentum',rules='Monthly 90d momentum divided by 60d volatility; top2 long, bottom2 short, inverse-vol weights, gross1 net0; distinct long/short cashflows, timestamp funding required.'),dict(name='BTC_long_cash_short_SMA200',rules='BTC daily close above SMA200 for 7 consecutive days: +1; below for 7: -1; otherwise retain last confirmed regime, start CASH. Daily decision, delayed venue fill.'),dict(name='beta_neutral_top_bottom',rules='Monthly 90d momentum top2/bottom2; 180d venue daily BTC betas and vol60; solve nonnegative leg weights for zero estimated BTC beta, gross<=1; infeasible solution CASH.'),dict(name='funding_aware',rules='Same long/short cross-sectional base; only published trailing7d actual funding may remove a leg whose adverse annualized funding exceeds positive annualized90d signed momentum. No future funding sign available to selector.')]
    for recipe in recipes:recipe.update(status='NOT_RUN',performance=None,reason='Historical venue risk/administrative evidence incomplete; data gate run, no fabricated strategy returns.')
    result=dict(family='D',status='NOT_RUN',required_period=period,price_funding_evidence=evidence,missing_contract_evidence=missing,sources=source,recipes=recipes,spot_used_as_perpetual=False,current_margin_assumed_historical=False)
    write(HERE/'perpetual_data_gate.json',result);return result

if __name__=='__main__':main()
