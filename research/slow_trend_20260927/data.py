"""One historical census, exact identities, separate spot/perpetual observations."""
import io,json,zipfile,importlib.util
import numpy as np
import pandas as pd
from common import HERE,OLD,SPEC,digest,write,now

def frames(path,end='2025-12-31 20:00'):
    with zipfile.ZipFile(path) as z:
        return {n[:-4]:pd.read_csv(io.BytesIO(z.read(n)),index_col=0,parse_dates=True).loc[:end] for n in z.namelist()}
def split(fs,hours):
    out=dict(fs)
    for e in json.loads((OLD/'identity_events.json').read_text()):
        if e['symbol'] not in out:continue
        f=out.pop(e['symbol']);halt=pd.Timestamp(e['effective_utc']);restart=pd.Timestamp(e['new_start'])
        out[e['symbol']+'@original']=f.loc[f.index+pd.Timedelta(hours=hours)<=halt]
        out[e['symbol']+'@'+restart.strftime('%Y%m%d')]=f.loc[f.index>=restart]
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

def acquire():
    freeze=json.loads((HERE/'protocol_freeze.json').read_text());assert digest(HERE/'contract.json')==freeze['contract_sha256']
    u=daily_universe();needed=sorted(set(u['eligible'].columns[u['eligible'].any()])|{'BTCUSDT','ETHUSDT'})
    raw=sorted({a.split('@')[0] for a in needed})
    write(HERE/'acquisition_universe.json',dict(utc=now(),identities=needed,symbols=raw,rule=SPEC['universe']['rule'],selection_input='prices and volume only; no performance',all_daily_identities=len(u['close'].columns)))
    # Reuse audited checksummed download/parser utilities, with THIS experiment's cache/budget.
    spec=importlib.util.spec_from_file_location('archive_acquisition',OLD/'data_prepare.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
    months=pd.period_range('2019-01','2025-12',freq='M').astype(str)
    events=[]
    for kind,folder in [('perp_trade','klines'),('perp_mark','markPriceKlines'),('funding','fundingRate')]:
        target=HERE/(kind+'.zip')
        if target.exists():continue
        old_names=set(zipfile.ZipFile(OLD/(kind+'.zip')).namelist())
        extra=[s for s in raw if s+'.csv' not in old_names]
        jobs=[(s,f'data/futures/um/monthly/{folder}/{s}/4h/{s}-4h-{month}.zip' if kind!='funding' else f'data/futures/um/monthly/{folder}/{s}/{s}-fundingRate-{month}.zip') for s in extra for month in months]
        out=a.collect(jobs,kind)
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            with zipfile.ZipFile(OLD/(kind+'.zip')) as prior:
                for name in sorted(old_names):z.writestr(name,prior.read(name))
            for s,f in sorted(out.items()):z.writestr(s+'.csv',f.to_csv(index=kind!='funding',float_format='%.12g'))
        events+=a.EVENTS;a.EVENTS.clear()
        write(HERE/(kind+'_acquisition.json'),dict(utc=now(),events=events,sha256=digest(target),reuse_source=str((OLD/(kind+'.zip')).relative_to(HERE.parents[1])),reuse_sha256=digest(OLD/(kind+'.zip'))))
    write(HERE/'data_freeze.json',dict(utc=now(),inputs={str(p.relative_to(HERE.parents[1])):digest(p) for p in [OLD/'spot_daily.zip',OLD/'spot_4h.zip',OLD/'identity_events.json',OLD/'venue_notices.json',HERE/'perp_trade.zip',HERE/'perp_mark.zip',HERE/'funding.zip']}))
    print('ACQUISITION COMPLETE',len(raw),'symbols',flush=True)

def load(track,end='2025-12-31'):
    u=daily_universe(end);days=u['close'].index;dates=pd.date_range('2019-01-01',pd.Timestamp(end)+pd.Timedelta(hours=20),freq='4h')
    names=sorted(set(u['eligible'].columns[u['eligible'].any()])|{'BTCUSDT','ETHUSDT'})
    source=OLD/'spot_4h.zip' if track=='spot' else HERE/'perp_trade.zip'
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
        mf=split(frames(HERE/'perp_mark.zip',end+' 20:00'),4)
        for j,a in enumerate(names):
            mm=mf.get(a,pd.DataFrame(columns=['open','high','low','close'])).reindex(dates)[['open','high','low','close']].to_numpy(float)
            missing=~np.isfinite(mm).all(axis=1);mark_missing[:,j]=missing
            mark[:,j]=np.where(missing[:,None],p[:,j,:4],mm)
        rawfund={}
        with zipfile.ZipFile(HERE/'funding.zip') as z:
            for n in z.namelist():rawfund[n[:-4]]=pd.read_csv(io.BytesIO(z.read(n)))
        for j,a in enumerate(names):
            f=rawfund.get(a.split('@')[0])
            if f is None:continue
            epoch=intra[a].index
            for r in f.itertuples():
                t=pd.Timestamp(r.calc_time,unit='ms')
                if epoch[0]<=t<epoch[-1]+pd.Timedelta(hours=4) and t<=dates[-1]+pd.Timedelta(hours=4):funding.append((t,j,float(r.last_funding_rate)))
    return dict(track=track,assets=names,days=days,dates=dates,prices=p,quote=quote,mark=mark,mark_missing=mark_missing,funding=sorted(funding),close=close,high=high,low=low,eligible=ok,base=base,liquidity=u['liquidity'].reindex(columns=names),rank=u['rank'].reindex(columns=names),vol=close.pct_change(fill_method=None).rolling(60).std()*np.sqrt(365.25),daily_returns=close.pct_change(fill_method=None))

if __name__=='__main__':acquire()
