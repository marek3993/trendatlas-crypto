"""Public checksummed archive census; no current-survivor list or PnL inputs."""
import concurrent.futures as cf,io,json,threading,time,urllib.request,urllib.parse,xml.etree.ElementTree as ET,zipfile
import numpy as np
import pandas as pd
from common import HERE,PARENT,SPEC,sha,digest,write
CACHE=HERE/'archive';CACHE.mkdir(exist_ok=True)
LOCK=threading.Lock();REQUESTS=0;BYTES=0;EVENTS=[];INDEXES={}
BASE='https://data.binance.vision/'
OLD=zipfile.ZipFile(PARENT/'archive_evidence.zip')
OLD_NAMES=set(OLD.namelist())

def get(url):
    global REQUESTS,BYTES
    for attempt in range(SPEC['data']['retries']+1):
        try:
            with LOCK:
                REQUESTS+=1
                if REQUESTS>SPEC['data']['max_requests']:raise RuntimeError('Frozen request budget')
            request=urllib.request.Request(urllib.parse.quote(url,safe=':/?&=%'),headers={'User-Agent':'TrendAtlas-research-only/2'})
            with urllib.request.urlopen(request,timeout=30) as r:b=r.read()
            with LOCK:
                BYTES+=len(b)
                if BYTES>SPEC['data']['max_bytes']:raise RuntimeError('Frozen byte budget')
            return b
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            if attempt==SPEC['data']['retries']:raise
        except Exception:
            if attempt==SPEC['data']['retries']:raise
        time.sleep(.3*(attempt+1))

def index(prefix,delimiter=None):
    tag=sha((prefix+str(delimiter)).encode());path=CACHE/(tag+'.index.json')
    if path.exists():
        x=json.loads(path.read_text());INDEXES[tag]=x;return x
    marker='';keys=[];prefixes=[];pages=[]
    while True:
        args=dict(prefix=prefix,marker=marker,**{'max-keys':1000})
        if delimiter:args['delimiter']=delimiter
        url='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?'+urllib.parse.urlencode(args)
        b=get(url);rt=ET.fromstring(b);ns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
        keys += [x.text for x in rt.findall('s:Contents/s:Key',ns)]
        prefixes += [x.text for x in rt.findall('s:CommonPrefixes/s:Prefix',ns)]
        pages.append(dict(url=url,sha256=sha(b),raw_xml=b.decode()))
        if rt.find('s:IsTruncated',ns).text=='false':break
        marker=rt.find('s:NextMarker',ns).text
    x=dict(prefix=prefix,keys=keys,prefixes=prefixes,pages=pages);write(path,x);INDEXES[tag]=x;return x

def archive(key):
    filename=key.replace('/','__');path=CACHE/filename;meta=path.with_suffix('.metadata.json');absent=path.with_suffix('.absent.json')
    if absent.exists():
        row=json.loads(absent.read_text());EVENTS.append(row);return None
    if not path.exists():
        old='archive/'+filename
        if old in OLD_NAMES:
            b=OLD.read(old);row=json.loads(OLD.read(old[:-4]+'.metadata.json'));assert sha(b)==row['sha256'];path.write_bytes(b);write(meta,row)
        else:
            b=get(BASE+key)
            if b is None:
                row=dict(key=key,status='404');write(absent,row);EVENTS.append(row);return None
            checksum=get(BASE+key+'.CHECKSUM')
            if checksum is None or sha(b)!=checksum.decode().split()[0]:raise ValueError('Archive checksum '+key)
            row=dict(key=key,status='verified',sha256=sha(b),checksum=checksum.decode().strip(),bytes=len(b));path.write_bytes(b);write(meta,row)
    b=path.read_bytes();row=json.loads(meta.read_text());assert sha(b)==row['sha256'];EVENTS.append(row);return b

def frame(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:f=pd.read_csv(z.open(z.namelist()[0]),header=None)
    f=f[pd.to_numeric(f.iloc[:,0],errors='coerce').notna()].copy();ts=pd.to_numeric(f.iloc[:,0]);unit='us' if ts.max()>1e14 else 'ms'
    f.index=pd.to_datetime(ts,unit=unit);out=f.iloc[:,[1,2,3,4,5,7]].astype(float);out.columns=['open','high','low','close','volume','quote_volume'];out.index.name='date'
    assert out.index.is_unique and (out.high>=out[['open','low','close']].max(axis=1)).all() and (out.low<=out[['open','high','close']].min(axis=1)).all()
    return out

def eligible(close,quote,observed,allowed=None):
    u=SPEC['universe'];liq=quote.where(observed).rolling(u['liquidity_days'],min_periods=u['liquidity_days']).mean()
    ok=observed&(observed.cumsum()>=u['minimum_observed_days'])&(liq>=u['minimum_quote_usd'])
    if allowed is not None:ok &= allowed
    ranks=liq.where(ok).rank(axis=1,method='first',ascending=False)
    return ok&(ranks<=u['top_n'])

def collect(jobs,kind):
    parts={}
    def one(job):
        symbol,key=job;b=archive(key)
        if b is None:return symbol,None
        if kind=='funding':
            with zipfile.ZipFile(io.BytesIO(b)) as z:f=pd.read_csv(z.open(z.namelist()[0]))
        else:f=frame(b)
        return symbol,f
    with cf.ThreadPoolExecutor(max_workers=SPEC['data']['workers']) as pool:
        for i,(symbol,f) in enumerate(pool.map(one,jobs)):
            if f is not None:parts.setdefault(symbol,[]).append(f)
            if i%500==0:print(kind,i+1,'/',len(jobs),'network_MB',round(BYTES/1e6,1),flush=True)
    out={}
    for symbol,items in parts.items():
        f=pd.concat(items)
        if kind=='funding':f=f.sort_values('calc_time');assert f.calc_time.is_unique
        else:f=f.sort_index();assert f.index.is_unique
        out[symbol]=f
    return out

def store_frames(name,frames,index=True):
    with zipfile.ZipFile(HERE/name,'w',zipfile.ZIP_DEFLATED) as z:
        for s,f in sorted(frames.items()):z.writestr(s+'.csv',f.to_csv(index=index,float_format='%.12g'))

def main():
    start=time.time();freeze=json.loads((HERE/'protocol_freeze.json').read_text());assert digest(HERE/'contract.json')==freeze['contract_sha256']
    prefixes=index('data/spot/monthly/klines/','/')['prefixes'];symbols=sorted(s.rstrip('/').split('/')[-1] for s in prefixes if s.rstrip('/').endswith('USDT'))
    u=SPEC['universe'];symbols=[s for s in symbols if s[:-4] not in u['stable_bases'] and not s[:-4].endswith(tuple(u['exclude_suffixes']))]
    listings={};jobs=[]
    def listing(s):return s,index(f'data/spot/monthly/klines/{s}/1d/')
    with cf.ThreadPoolExecutor(max_workers=SPEC['data']['workers']) as pool:
        for s,x in pool.map(listing,symbols):
            keys=[k for k in x['keys'] if k.endswith('.zip')];listings[s]=dict(first_archive_month=min(keys).split('-')[-2]+'-'+min(keys).split('-')[-1][:2] if keys else None)
            for key in keys:
                month=key[-11:-4]
                if '2019-01'<=month<='2025-12':jobs.append((s,key))
    write(HERE/'census.json',dict(symbols=symbols,monthly_daily_archives=len(jobs),method='All archived prefixes including ceased symbols, no current exchangeInfo'))
    daily=collect(jobs,'spot_daily');store_frames('spot_daily.zip',daily)
    dates=pd.date_range(SPEC['data']['start'],SPEC['data']['end'],freq='D');close=pd.DataFrame({s:f.close.reindex(dates) for s,f in sorted(daily.items())});quote=pd.DataFrame({s:f.quote_volume.reindex(dates) for s,f in sorted(daily.items())})
    observed=close.notna()&close.gt(0)&quote.gt(0);ok=eligible(close,quote,observed)
    selected=list(ok.columns[ok.any()]);write(HERE/'intraday_acquisition_universe.json',dict(symbols=selected,rule='Data acquisition union only; never substitute this list for dynamic daily eligibility',first_eligible={s:str(ok.index[ok[s]][0]) for s in selected}))
    jobs4=[(s,k.replace('/1d/','/4h/').replace('-1d-','-4h-')) for s,k in jobs if s in selected]
    intraday=collect(jobs4,'spot_4h');store_frames('spot_4h.zip',intraday)
    for s,f in daily.items():
        listings[s].update(first_observed_daily=str(f.index[0]),last_observed_daily=str(f.index[-1]),daily_rows=len(f),first_4h_observed=str(intraday[s].index[0]) if s in intraday else None,last_4h_observed=str(intraday[s].index[-1]) if s in intraday else None,administrative_dates='NOT_CERTIFIED_BY_BAR_EVIDENCE')
    write(HERE/'listing_observations.json',listings)
    months=pd.period_range('2019-01','2025-12',freq='M').astype(str)
    for kind,folder in [('perp_trade','klines'),('perp_mark','markPriceKlines'),('funding','fundingRate')]:
        j=[]
        for s in SPEC['data']['perpetual_symbols']:
            for month in months:
                key=f'data/futures/um/monthly/{folder}/{s}/4h/{s}-4h-{month}.zip' if kind!='funding' else f'data/futures/um/monthly/{folder}/{s}/{s}-fundingRate-{month}.zip'
                j.append((s,key))
        store_frames(kind+'.zip',collect(j,kind),index=kind!='funding')
    with zipfile.ZipFile(HERE/'indexes.zip','w',zipfile.ZIP_DEFLATED) as z:
        for k,v in sorted(INDEXES.items()):z.writestr(k+'.json',json.dumps(v,ensure_ascii=False))
    write(HERE/'acquisition.json',dict(seconds=time.time()-start,requests=REQUESTS,downloaded_bytes=BYTES,events=EVENTS,input_hashes={n:digest(HERE/n) for n in ['spot_daily.zip','spot_4h.zip','perp_trade.zip','perp_mark.zip','funding.zip','indexes.zip']},contract_sha256=digest(HERE/'contract.json')))
    print('Data acquisition completed:',len(daily),'historical symbols,',len(selected),'eligible intraday symbols',flush=True)

if __name__=='__main__':main()
