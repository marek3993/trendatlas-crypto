"""One timestamped universe contract shared by every family; no PnL input."""
import io,json,zipfile
import numpy as np
import pandas as pd
from common import HERE,SPEC,digest,write

def eligibility(close,quote,observed,allowed=None):
    u=SPEC['universe'];count=observed.cumsum()
    liq=quote.where(observed).rolling(u['liquidity_window_days'],min_periods=u['liquidity_window_days']).mean()
    ok=(count>=u['minimum_observed_days'])&observed&(liq>=u['minimum_mean_quote_usd'])
    if allowed is not None:ok &= allowed
    rank=liq.where(ok).rank(axis=1,ascending=False,method='first')
    return ok&(rank<=u['liquidity_top_n'])

def load(end='2025-12-31 20:00:00'):
    aq=json.loads((HERE/'acquisition.json').read_text());assert digest(HERE/'market_inputs.zip')==aq['market_inputs_sha256']
    assets=sorted(aq['spot_symbols']);dates=pd.date_range(SPEC['data']['start'],end,freq='4h')
    raw={};funding={}
    with zipfile.ZipFile(HERE/'market_inputs.zip') as z:
        for a in assets:
            f=pd.read_csv(io.BytesIO(z.read('spot/'+a+'.csv')),index_col=0,parse_dates=True);raw[a]=f.loc[:end]
        for a in aq['funding_symbols']:funding[a]=pd.read_csv(io.BytesIO(z.read('funding/'+a+'.csv')))
    p=np.stack([raw[a].reindex(dates)[['open','high','low','close','volume']].to_numpy() for a in assets],axis=1)
    quote=np.stack([raw[a].quote_volume.reindex(dates).to_numpy() for a in assets],axis=1)
    observed={};daily={}
    for a in assets:
        f=raw[a].reindex(dates);g=f.groupby(f.index.normalize())
        daily[a]=g.agg(dict(open='first',high='max',low='min',close='last',volume='sum',quote_volume='sum'))
        # Incomplete UTC days cannot provide a daily signal or liquidity rank.
        valid=g.close.count().eq(6)&daily[a].volume.gt(0)
        daily[a].loc[~valid,:]=np.nan;observed[a]=valid
    dc=pd.DataFrame({a:f.close for a,f in daily.items()});dq=pd.DataFrame({a:f.quote_volume for a,f in daily.items()})
    notices=json.loads((HERE/'venue_notices.json').read_text()) if (HERE/'venue_notices.json').exists() else []
    allowed=pd.DataFrame(True,index=dc.index,columns=assets)
    daily_signal_bars=dc.index+pd.Timedelta(hours=20)
    for n in notices:
        if n['symbol'] not in assets:continue
        disabled=(daily_signal_bars>=pd.Timestamp(n['published_utc']))&(daily_signal_bars+pd.Timedelta(hours=8)>=pd.Timestamp(n['effective_utc'])-pd.Timedelta(days=2))
        allowed.loc[disabled,n['symbol']]=False
    # Known venue unavailability must be masked BEFORE the liquidity ranking.
    obs=pd.DataFrame(observed);ok=eligibility(dc,dq,obs,allowed)
    # Rows are signal bars. Only the 20:00 bar knows its own completed daily
    # close; earlier bars know yesterday's daily close. No partial-day data.
    daily_index=dates.normalize()-pd.to_timedelta((dates.hour!=20).astype(int),unit='D')
    idx=dc.index.get_indexer(daily_index);eligible=np.zeros((len(dates),len(assets)),bool)
    valid=idx>=0;eligible[valid]=ok.to_numpy()[idx[valid]]
    quoted=np.isfinite(p[:,:,:4]).all(axis=2)&(p[:,:,:4]>0).all(axis=2)&(p[:,:,4]>0)
    eligible &= quoted
    # The December cohort becomes known only after December's final close.
    # Earlier history can warm indicators but cannot authorize a trade target.
    eligible[dates<pd.Timestamp(SPEC['universe']['cohort_asof'])+pd.Timedelta(hours=20)]=False
    for n in notices:
        if n['symbol'] not in assets:continue
        # After publication, disable NEW decisions before last tradable hour.
        disabled=(dates>=pd.Timestamp(n['published_utc']))&(dates+pd.Timedelta(hours=8)>=pd.Timestamp(n['effective_utc'])-pd.Timedelta(days=2))
        eligible[disabled,assets.index(n['symbol'])]=False
    m=dict(dates=dates,assets=assets,prices=p,quote=quote,eligible=eligible,raw=raw,daily=daily,close=dc,daily_eligible=ok,daily_index=idx,funding=funding,notices=notices)
    return m

def prefix(m,end):return load(end)

def evidence():
    m=load();rows=[]
    for a in m['assets']:
        f=m['raw'][a];missing=m['dates'][~np.isfinite(m['prices'][:,m['assets'].index(a),0])]
        rows.append(dict(symbol=a,venue='Binance spot',first_observed=str(f.index[0]),last_observed=str(f.index[-1]),missing_4h_bars=len(missing),administrative_listing_date='UNVERIFIED; first bar is observational lower bound',delisting_notice=next((n for n in m['notices'] if n['symbol']==a),None)))
    funding=[]
    for a,f in m['funding'].items():
        ts=pd.to_datetime(f.calc_time,unit='ms');funding.append(dict(symbol=a,venue='Binance USD-M',events=len(f),first=str(ts.min()),last=str(ts.max()),negative_events=int((f.last_funding_rate<0).sum()),rate_min=float(f.last_funding_rate.min()),rate_max=float(f.last_funding_rate.max()),used_for_spot=False))
    write(HERE/'data_audit.json',dict(symbols=rows,actual_funding=funding,perpetual_status='BLOCKED_MISSING_HISTORICAL_MARGIN_AND_MATCHED_MARK_TRADE_QUOTES',D_status='NOT_RUN_DATA_GATE',historical_pit_scope='Ex-ante December2020 cohort with observed admission and trailing liquidity; administrative listing evidence incomplete',forward_opened=False))
