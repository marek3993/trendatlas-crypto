"""One historical census, exact identities, separate spot/perpetual observations."""
import io,json,zipfile,importlib.util
import numpy as np
import pandas as pd
from .common import HERE,OLD,SPEC,digest,write,now

def frames(path,end='2025-12-31 20:00'):
    with zipfile.ZipFile(path) as z:
        return {n[:-4]:pd.read_csv(io.BytesIO(z.read(n)),index_col=0,parse_dates=True).loc[:end] for n in z.namelist()}
def split(fs,hours):
    out=dict(fs)
    groups={}
    for e in json.loads((OLD/'identity_events.json').read_text()):groups.setdefault(e['symbol'],[]).append(e)
    for symbol,events in groups.items():
        if symbol not in out:continue
        f=out.pop(symbol);lower=None;name=symbol+'@original'
        for e in sorted(events,key=lambda e:e['effective_utc']):
            halt=pd.Timestamp(e['effective_utc']);restart=pd.Timestamp(e['new_start'])
            segment=f if lower is None else f.loc[f.index>=lower]
            out[name]=segment.loc[segment.index+pd.Timedelta(hours=hours)<=halt]
            name=symbol+'@'+restart.strftime('%Y%m%d');lower=restart
        out[name]=f.loc[f.index>=lower]
    return out
def daily_universe(end='2025-12-31'):
    f=split(frames(OLD/'spot_daily.zip',end),24);days=pd.date_range('2019-01-01',end,freq='D')
    close=pd.DataFrame({a:d.close.reindex(days) for a,d in sorted(f.items())});quote=pd.DataFrame({a:d.quote_volume.reindex(days) for a,d in sorted(f.items())})
    observed=close.gt(0)&quote.gt(0);liq=quote.where(observed).rolling(30,min_periods=30).mean()
    base=observed&(observed.cumsum()>=365)&liq.ge(1e7)
    notices=json.loads((OLD/'venue_notices.json').read_text())+[dict(e,symbol=e['symbol']+'@original') for e in json.loads((OLD/'identity_events.json').read_text())]
    for n in notices:
        if n['symbol'] in base:
            known=(days+pd.Timedelta(days=1)>=pd.Timestamp(n['published_utc']))&(days+pd.Timedelta(days=1,hours=4)>=pd.Timestamp(n['effective_utc'])-pd.Timedelta(hours=72))
            base.loc[known,n['symbol']]=False
    rank=liq.where(base).rank(axis=1,ascending=False,method='first')
    return dict(close=close,quote=quote,base=base,eligible=base&rank.le(5),liquidity=liq,rank=rank,notices=notices)

def load(track,end='2025-12-31'):
    u=daily_universe(end);days=u['close'].index;dates=pd.date_range('2019-01-01',pd.Timestamp(end)+pd.Timedelta(hours=20),freq='4h')
    names=sorted(set(u['eligible'].columns[u['eligible'].any()])|{'BTCUSDT','ETHUSDT'})
    source=OLD/'spot_4h.zip' if track=='spot' else OLD/'perp_trade.zip'
    intra=split(frames(source,end+' 20:00'),4)
    names=[a for a in names if a in intra and len(intra[a])]
    p=np.stack([intra[a].reindex(dates)[['open','high','low','close','volume']].to_numpy() for a in names],axis=1)
    quote=np.stack([intra[a].quote_volume.reindex(dates).to_numpy() for a in names],axis=1)
    close=u['close'].reindex(columns=names);base=u['base'].reindex(columns=names);ok=u['eligible'].reindex(columns=names)
    high=pd.DataFrame(p[:,:,1],index=dates,columns=names).resample('D').max();low=pd.DataFrame(p[:,:,2],index=dates,columns=names).resample('D').min()
    mark=p[:,:,:4].copy();mark_missing=np.zeros(p.shape[:2],bool);funding=[]
    if track=='perp':
        count=pd.DataFrame(p[:,:,3],index=dates,columns=names).resample('D').count()
        close=pd.DataFrame(p[:,:,3],index=dates,columns=names).resample('D').last().where(count==6)
        own_obs=close.notna();base=base&own_obs&(own_obs.cumsum()>=365);ok=ok&base
        mf=split(frames(OLD/'perp_mark.zip',end+' 20:00'),4)
        for j,a in enumerate(names):
            mm=mf.get(a,pd.DataFrame(columns=['open','high','low','close'])).reindex(dates)[['open','high','low','close']].to_numpy(float)
            missing=~np.isfinite(mm).all(axis=1);mark_missing[:,j]=missing
            mark[:,j]=np.where(missing[:,None],p[:,j,:4],mm)
        rawfund={}
        with zipfile.ZipFile(OLD/'funding.zip') as z:
            for n in z.namelist():rawfund[n[:-4]]=pd.read_csv(io.BytesIO(z.read(n)))
        for j,a in enumerate(names):
            f=rawfund.get(a.split('@')[0])
            if f is None:continue
            epoch=intra[a].index
            for r in f.itertuples():
                t=pd.Timestamp(r.calc_time,unit='ms')
                if epoch[0]<=t<epoch[-1]+pd.Timedelta(hours=4) and t<=dates[-1]+pd.Timedelta(hours=4):funding.append((t,j,float(r.last_funding_rate)))
    return dict(track=track,assets=names,days=days,dates=dates,prices=p,quote=quote,mark=mark,mark_missing=mark_missing,funding=sorted(funding),close=close,high=high,low=low,eligible=ok,base=base,liquidity=u['liquidity'].reindex(columns=names),rank=u['rank'].reindex(columns=names),vol=close.pct_change(fill_method=None).rolling(60).std()*np.sqrt(365.25),daily_returns=close.pct_change(fill_method=None))


