"""Bounded, read-only public archive acquisition; writes ONLY this research tree."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
import hashlib, io, json, threading, time, zipfile, xml.etree.ElementTree as ET
import pandas as pd

HERE=Path(__file__).resolve().parent
SPEC=json.loads((HERE/'contract.json').read_text())
RAW=HERE/'archive';RAW.mkdir(exist_ok=True)
BASE='https://data.binance.vision/'
LOCK=threading.Lock();COUNT=0;BYTES=0;EVENTS=[]

def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8',newline='\n')
def get(url):
    global COUNT,BYTES
    with LOCK:
        COUNT+=1
        if COUNT>SPEC['data']['acquisition_budget']['max_archive_requests']:raise RuntimeError('Request budget exhausted')
    for attempt in range(3):
        try:
            with urlopen(Request(quote(url,safe=':/?&=%'),headers={'User-Agent':'TrendAtlas-offline-research/1'}),timeout=25) as r:b=r.read()
            with LOCK:
                BYTES+=len(b)
                if BYTES>SPEC['data']['acquisition_budget']['max_bytes']:raise RuntimeError('Byte budget exhausted')
            return b
        except Exception as exc:
            if getattr(exc,'code',None)==404:return None
            if attempt==2:raise
            time.sleep(.2*(attempt+1))

def archive(key):
    path=RAW/key.replace('/','__')
    meta=path.with_suffix('.metadata.json');absent=path.with_suffix('.absent.json')
    if absent.exists():
        with LOCK:EVENTS.append(json.loads(absent.read_text()))
        return None
    if path.exists():
        b=path.read_bytes()
        if meta.exists():
            row=json.loads(meta.read_text());assert sha(b)==row['sha256']
        else:
            ck=get(BASE+key+'.CHECKSUM');assert ck is not None and sha(b)==ck.decode().split()[0]
            row=dict(key=key,status='verified',sha256=sha(b),bytes=len(b),checksum=ck.decode().strip());write(meta,row)
        with LOCK:EVENTS.append(row)
        return b
    b=get(BASE+key)
    if b is None:
        row=dict(key=key,status='not_present_404');write(absent,row)
        with LOCK:EVENTS.append(row)
        return None
    ck=get(BASE+key+'.CHECKSUM')
    if ck is None or sha(b)!=ck.decode().split()[0]:raise ValueError('Checksum failure '+key)
    path.write_bytes(b)
    row=dict(key=key,status='verified',sha256=sha(b),bytes=len(b),checksum=ck.decode().strip());write(meta,row)
    with LOCK:EVENTS.append(row)
    return b

def frame(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        f=pd.read_csv(z.open(z.namelist()[0]),header=None)
    f=f[pd.to_numeric(f.iloc[:,0],errors='coerce').notna()].copy()
    ts=pd.to_numeric(f.iloc[:,0]);unit='us' if ts.max()>1e14 else 'ms'
    f.index=pd.to_datetime(ts,unit=unit);f.index.name='date'
    out=f.iloc[:,[1,2,3,4,5,7]].astype(float);out.columns=['open','high','low','close','volume','quote_volume']
    assert out.index.is_unique
    assert (out.high>=out[['open','low','close']].max(axis=1)).all()
    assert (out.low<=out[['open','high','close']].min(axis=1)).all()
    return out

def census():
    dest=HERE/'archive_census.json'
    if dest.exists():return json.loads(dest.read_text())['symbols']
    prefix='data/spot/monthly/klines/';marker='';symbols=[];pages=[]
    while True:
        url='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?'+urlencode(dict(prefix=prefix,delimiter='/',marker=marker))
        b=get(url);root=ET.fromstring(b);pages.append(dict(url=url,sha256=sha(b)))
        ns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
        for x in root.findall('s:CommonPrefixes/s:Prefix',ns):
            name=x.text.rstrip('/').split('/')[-1]
            if name.endswith('USDT'):symbols.append(name)
        if root.find('s:IsTruncated',ns).text=='false':break
        marker=root.find('s:NextMarker',ns).text
    write(dest,dict(symbols=sorted(set(symbols)),pages=pages,method='Archive prefixes, not current exchangeInfo; no current-live filter'))
    return sorted(set(symbols))

def choose():
    dest=HERE/'cohort.json'
    if dest.exists():return json.loads(dest.read_text())['symbols']
    symbols=census();stable=SPEC['universe']['stable_bases']
    symbols=[s for s in symbols if s[:-4] not in stable and not s[:-4].endswith(('UP','DOWN','BULL','BEAR'))]
    rows=[]
    def probe(s):
        b=archive(f'data/spot/monthly/klines/{s}/1d/{s}-1d-2020-12.zip')
        if b is None:return None
        f=frame(b);return dict(symbol=s,rows=len(f),quote_volume=float(f.quote_volume.sum()))
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs={ex.submit(probe,s):s for s in symbols}
        for i,fut in enumerate(as_completed(fs)):
            row=fut.result()
            if row:rows.append(row)
            if i%100==0:print(f'Cohort evidence {i+1}/{len(fs)}',flush=True)
    ranked=sorted([r for r in rows if r['rows']>=28],key=lambda r:(-r['quote_volume'],r['symbol']))
    chosen=[r['symbol'] for r in ranked[:20]]
    write(dest,dict(asof=SPEC['universe']['cohort_asof'],symbols=chosen,all_observed=rows,ranking=ranked,selection_uses_future=False))
    return chosen

def main():
    start=time.time();symbols=choose();print('Frozen cohort: '+', '.join(symbols),flush=True)
    months=pd.period_range('2019-01','2025-12',freq='M').astype(str)
    jobs=[('spot',s,d) for s in symbols for d in months]
    # Real contract funding is captured separately; it never enters spot PnL.
    jobs += [('funding',s,d) for s in ['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT'] for d in months]
    data={};fund={}
    def one(job):
        kind,s,d=job
        key=f'data/spot/monthly/klines/{s}/4h/{s}-4h-{d}.zip' if kind=='spot' else f'data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{d}.zip'
        return kind,s,d,archive(key)
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs=[ex.submit(one,j) for j in jobs]
        for i,fut in enumerate(as_completed(fs)):
            kind,s,d,b=fut.result()
            if b:
                if kind=='spot':data.setdefault(s,[]).append(frame(b))
                else:
                    with zipfile.ZipFile(io.BytesIO(b)) as z:f=pd.read_csv(z.open(z.namelist()[0]))
                    fund.setdefault(s,[]).append(f)
            if i%200==0:print(f'Archive evidence {i+1}/{len(fs)}; downloaded {BYTES/1e6:.1f} MB',flush=True)
    with zipfile.ZipFile(HERE/'market_inputs.zip','w',zipfile.ZIP_DEFLATED) as z:
        coverage=[]
        for s,parts in sorted(data.items()):
            f=pd.concat(parts).sort_index();assert f.index.is_unique
            z.writestr('spot/'+s+'.csv',f.to_csv(float_format='%.12g'))
            coverage.append(dict(symbol=s,rows=len(f),first=str(f.index[0]),last=str(f.index[-1]),gaps=int((f.index.to_series().diff()>pd.Timedelta(hours=4)).sum())))
        for s,parts in sorted(fund.items()):
            f=pd.concat(parts).sort_values('calc_time');assert f.calc_time.is_unique
            z.writestr('funding/'+s+'.csv',f.to_csv(index=False,float_format='%.12g'))
    write(HERE/'coverage.json',coverage)
    write(HERE/'acquisition.json',dict(requests=COUNT,bytes=BYTES,seconds=time.time()-start,events=EVENTS,market_inputs_sha256=sha((HERE/'market_inputs.zip').read_bytes()),contract_sha256=sha((HERE/'contract.json').read_bytes()),spot_symbols=symbols,funding_symbols=sorted(fund)))
    print('Acquisition complete. '+str(coverage),flush=True)

if __name__=='__main__':main()
