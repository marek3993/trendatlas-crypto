"""One dynamic PIT universe; missing prices never become zero returns."""
import io,json,zipfile
import numpy as np
import pandas as pd
from common import HERE,SPEC,digest
import identity

def eligibility(close,quote,observed,allowed=None):
    u=SPEC['universe'];liq=quote.where(observed).rolling(u['liquidity_days'],min_periods=u['liquidity_days']).mean()
    ok=observed&(observed.cumsum()>=u['minimum_observed_days'])&(liq>=u['minimum_quote_usd'])
    if allowed is not None:ok &= allowed
    return ok&(liq.where(ok).rank(axis=1,method='first',ascending=False)<=u['top_n'])

def frames(name,end):
    with zipfile.ZipFile(HERE/name) as z:
        return {n[:-4]:pd.read_csv(io.BytesIO(z.read(n)),index_col=0,parse_dates=True).loc[:end] for n in z.namelist()}

def load(end='2025-12-31 20:00:00'):
    aq=json.loads((HERE/'acquisition.json').read_text())
    for name in ['spot_daily.zip','spot_4h.zip']:assert digest(HERE/name)==aq['input_hashes'][name]
    day_end=pd.Timestamp(end).normalize()-(pd.Timedelta(days=1) if pd.Timestamp(end).hour<20 else pd.Timedelta(0))
    days=pd.date_range(SPEC['data']['start'],pd.Timestamp(end).normalize(),freq='D')
    daily=identity.split(frames('spot_daily.zip',str(day_end)),24);intra=identity.split(frames('spot_4h.zip',end),4)
    all_names=sorted(daily);dc=pd.DataFrame({a:daily[a].close.reindex(days) for a in all_names});dq=pd.DataFrame({a:daily[a].quote_volume.reindex(days) for a in all_names})
    obs=dc.notna()&dc.gt(0)&dq.gt(0);allowed=pd.DataFrame(True,index=days,columns=all_names)
    notices=identity.notices()
    for n in notices:
        if n['symbol'] not in all_names:continue
        bars=days+pd.Timedelta(hours=20)
        disabled=(bars>=pd.Timestamp(n['published_utc']))&(bars+pd.Timedelta(hours=8)>=pd.Timestamp(n['effective_utc'])-pd.Timedelta(hours=72))
        allowed.loc[disabled,n['symbol']]=False
    full_ok=eligibility(dc,dq,obs,allowed)
    required=set(full_ok.columns[full_ok.any()])|{'BTCUSDT'}
    missing=required-set(intra)
    if missing:raise ValueError('Missing required intraday acquisition: '+','.join(sorted(missing)))
    assets=sorted(intra);dates=pd.date_range(SPEC['data']['start'],end,freq='4h')
    p=np.stack([intra[a].reindex(dates)[['open','high','low','close','volume']].to_numpy() for a in assets],axis=1)
    q=np.stack([intra[a].quote_volume.reindex(dates).to_numpy() for a in assets],axis=1)
    idx=days.get_indexer(dates.normalize()-pd.to_timedelta((dates.hour!=20).astype(int),unit='D'))
    ok=full_ok.reindex(columns=assets,fill_value=False);bar_ok=np.zeros((len(dates),len(assets)),bool)
    good=idx>=0;bar_ok[good]=ok.to_numpy()[idx[good]]
    bar_ok &= np.isfinite(p[:,:,:4]).all(axis=2)&(p[:,:,:4]>0).all(axis=2)&(p[:,:,4]>0)
    for n in notices:
        if n['symbol'] in assets:
            disabled=(dates>=pd.Timestamp(n['published_utc']))&(dates+pd.Timedelta(hours=8)>=pd.Timestamp(n['effective_utc'])-pd.Timedelta(hours=72))
            bar_ok[disabled,assets.index(n['symbol'])]=False
    close=dc.reindex(columns=assets);vol=close.pct_change(fill_method=None).rolling(60).std()*np.sqrt(365.25)
    moms={n:close/close.shift(n)-1 for n in SPEC['schema']['lookback']}
    return dict(dates=dates,assets=assets,prices=p,quote=q,eligible=bar_ok,daily_eligible=ok,daily_index=idx,close=close,volume=dq.reindex(columns=assets),vol=vol,momentum=moms,all_daily_symbols=len(all_names),notices=notices)
