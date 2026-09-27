"""Bounded public-archive collector. Separate from strategy/order processes.

Only completely closed archive months are admitted, since timestamped funding
is published monthly. No exchange credentials, spot-for-perp substitution or
current exchangeInfo universe. Intermediate snapshots are never evaluator input.
"""
import datetime as dt
import hashlib
import io
import json
import re
import shutil
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from .protocol import atomic, digest, utc, HERE

STABLE={'USDC','BUSD','TUSD','USDP','PAX','DAI','SUSD','USDS','USDSB','UST','USTC','USDT','BIDR','IDRT','EUR','GBP','AUD','RUB','BRL','TRY','UAH','NGN','BVND','VAI','FDUSD','USDE','USD1','AEUR','EURI'}
ROOT_URL='https://data.binance.vision/'
INDEX_URL='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision'
FILES=('spot_daily.zip','spot_4h.zip','perp_trade.zip','perp_mark.zip','funding.zip','identity_events.json','venue_notices.json')

class StopActivation(Exception):pass

class Collector:
    def __init__(self,root,max_requests=240):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.requests=0;self.bytes=0;self.max_requests=max_requests
        self.db=sqlite3.connect(self.root/'acquisition.sqlite');self.db.row_factory=sqlite3.Row
        self.db.executescript('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS responses(url TEXT PRIMARY KEY,status INTEGER,sha256 TEXT,bytes INTEGER,path TEXT,received TEXT);')

    def fetch(self,url):
        temperatures=[int(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
        if temperatures and max(temperatures)>=75:raise StopActivation('public-data thermal guard')
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in ('data.binance.vision','s3-ap-northeast-1.amazonaws.com') or parsed.username or parsed.password:raise ValueError('Unapproved public-data URL')
        if parsed.hostname=='s3-ap-northeast-1.amazonaws.com' and parsed.path!='/data.binance.vision':raise ValueError('Unapproved S3 bucket')
        cached=self.db.execute('SELECT * FROM responses WHERE url=?',(url,)).fetchone()
        if cached:
            if cached['status']==404:return None
            p=self.root/cached['path']
            if p.exists():
                b=p.read_bytes()
                if hashlib.sha256(b).hexdigest()!=cached['sha256']:raise RuntimeError('Archive changed on disk')
                return b
        if self.requests>=self.max_requests or self.bytes>=60*1024**2:raise StopActivation('public-data activation budget')
        if shutil.disk_usage(self.root).free<1100*1024**2:raise StopActivation('public-data disk reserve')
        self.requests+=1
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise ValueError('Public-data redirect forbidden')
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'TrendAtlas-causal-research/1'})
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as r:b=r.read(16*1024**2+1)
            if len(b)>16*1024**2:raise ValueError('Unexpected archive size')
        except urllib.error.HTTPError as e:
            if e.code!=404:raise
            with self.db:self.db.execute('INSERT OR REPLACE INTO responses VALUES(?,?,?,?,?,?)',(url,404,None,0,None,utc()))
            return None
        self.bytes+=len(b);name=hashlib.sha256(url.encode()).hexdigest()+'.bin';(self.root/name).write_bytes(b)
        with self.db:self.db.execute('INSERT OR REPLACE INTO responses VALUES(?,?,?,?,?,?)',(url,200,hashlib.sha256(b).hexdigest(),len(b),name,utc()))
        return b

    def census(self):
        result=[];marker='';ns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
        while True:
            url=INDEX_URL+'?'+urllib.parse.urlencode(dict(prefix='data/spot/monthly/klines/',delimiter='/',marker=marker,**{'max-keys':1000}))
            doc=ET.fromstring(self.fetch(url));result += [x.text.rstrip('/').split('/')[-1] for x in doc.findall('s:CommonPrefixes/s:Prefix',ns)]
            if doc.find('s:IsTruncated',ns).text=='false':break
            marker=doc.find('s:NextMarker',ns).text
        return sorted(s for s in set(result) if re.fullmatch(r'[A-Z0-9]+USDT',s) and s[:-4] not in STABLE and not s[:-4].endswith(('UP','DOWN','BULL','BEAR')))

    def archive(self,key):
        b=self.fetch(ROOT_URL+key)
        if b is None:return None
        check=self.fetch(ROOT_URL+key+'.CHECKSUM')
        if check is None or hashlib.sha256(b).hexdigest()!=check.decode().split()[0]:raise ValueError('Official checksum mismatch')
        return b

def raw_frame(b,funding=False):
    import pandas as pd
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        if len(z.namelist())!=1:raise ValueError('Unexpected archive members')
        f=pd.read_csv(z.open(z.namelist()[0]),header=0 if funding else None)
    if funding:
        if not {'calc_time','last_funding_rate'}<=set(f):raise ValueError('Funding schema')
        return f
    f=f[pd.to_numeric(f.iloc[:,0],errors='coerce').notna()].copy();ts=pd.to_numeric(f.iloc[:,0]);unit='us' if ts.max()>1e14 else 'ms'
    f.index=pd.to_datetime(ts,unit=unit);out=f.iloc[:,[1,2,3,4,5,7]].astype(float);out.columns=['open','high','low','close','volume','quote_volume'];out.index.name='date'
    if not out.index.is_unique or not (out.high>=out[['open','low','close']].max(axis=1)).all() or not (out.low<=out[['open','high','close']].min(axis=1)).all():raise ValueError('Invalid candle accounting')
    return out

def append_zip(source,output,symbols,months,kind,collector):
    import pandas as pd
    with zipfile.ZipFile(source) as old:
        previous={n[:-4]:old.read(n) for n in old.namelist()}
    temp=output.with_suffix('.tmp.zip')
    # A completed output is immutable; activation resume rebuilds only an unfinished ZIP.
    if output.exists():return
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as dest:
        for symbol in sorted(set(symbols)|set(previous)):
            f=pd.read_csv(io.BytesIO(previous[symbol]),index_col=None if kind=='funding' else 0,parse_dates=False if kind=='funding' else [0]) if symbol in previous else None
            parts=[] if f is None else [f]
            if symbol in symbols:
                for month in months:
                    if kind=='spot_daily':key=f'data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip'
                    elif kind=='spot_4h':key=f'data/spot/monthly/klines/{symbol}/4h/{symbol}-4h-{month}.zip'
                    elif kind=='funding':key=f'data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip'
                    else:
                        folder='klines' if kind=='perp_trade' else 'markPriceKlines';key=f'data/futures/um/monthly/{folder}/{symbol}/4h/{symbol}-4h-{month}.zip'
                    b=collector.archive(key)
                    if b is not None:parts.append(raw_frame(b,kind=='funding'))
            if not parts:continue
            joined=pd.concat(parts)
            if kind=='funding':
                joined=joined.sort_values('calc_time')
                if not joined.calc_time.is_unique:raise ValueError('Funding duplicate timestamp')
            else:
                joined=joined.sort_index()
                if not joined.index.is_unique:raise ValueError('Duplicate price timestamp')
            dest.writestr(symbol+'.csv',joined.to_csv(index=kind!='funding',float_format='%.12g'))
    temp.replace(output)

def collect_months(feed_root,source,source_end,through,parent_fingerprint,max_requests=240):
    """Publishes only complete immutable dataset manifests, with source evidence."""
    import pandas as pd
    feed_root=Path(feed_root);source=Path(source);destination=feed_root/'datasets'/through
    manifest_path=destination/'dataset.json'
    if manifest_path.exists():return json.loads(manifest_path.read_text())
    destination.mkdir(parents=True,exist_ok=True)
    collector=Collector(feed_root/'staging'/through,max_requests)
    try:
        symbols=collector.census();months=pd.period_range(pd.Timestamp(source_end)+pd.Timedelta(days=1),through,freq='M').astype(str)
        for name in ('identity_events.json','venue_notices.json'):shutil.copyfile(source/name,destination/name)
        append_zip(source/'spot_daily.zip',destination/'spot_daily.zip',symbols,months,'spot_daily',collector)
        # Public bars cannot certify corporate/token actions. Conservatively split
        # new reappearances/discontinuities instead of transferring an old asset's
        # quantity into a possibly different token. New epochs re-warm for365days.
        events=json.loads((destination/'identity_events.json').read_text())
        with zipfile.ZipFile(destination/'spot_daily.zip') as z:
            for name in z.namelist():
                f=pd.read_csv(z.open(name),index_col=0,parse_dates=True).sort_index()
                gaps=f.index.to_series().diff().dt.total_seconds()>2*86400
                ratio=f.close/f.close.shift(1);discontinuity=(ratio>5)|(ratio<.2)
                for date in f.index[(gaps|discontinuity).to_numpy() & (f.index>pd.Timestamp(source_end))]:
                    event=dict(symbol=name[:-4],effective_utc=str(date),new_start=str(date),published_utc=str(date+pd.Timedelta(days=1)),
                               status='OBSERVED_REAPPEARANCE_UNVERIFIED_IDENTITY_QUARANTINE',reason='new gap>2days or price ratio outside[.2,5]; never assume asset continuity')
                    if not any(e['symbol']==event['symbol'] and e['new_start']==event['new_start'] for e in events):events.append(event)
        atomic(destination/'identity_events.json',events)
        from .vendor import data
        saved=data.OLD;data.OLD=destination
        try:u=data.daily_universe(through)
        finally:data.OLD=saved
        active=sorted(set(u['eligible'].columns[u['eligible'].any()])|{'BTCUSDT','ETHUSDT'})
        active=sorted(set(s.split('@')[0] for s in active))
        for kind in ('spot_4h','perp_trade','perp_mark','funding'):
            # Newly eligible symbols need their own complete historical intraday archive.
            with zipfile.ZipFile(source/(kind+'.zip')) as z:old_symbols={n[:-4] for n in z.namelist()}
            new=set(active)-old_symbols
            if new:
                # Separate source extension keeps the old history byte-equivalent for existing assets.
                extension=destination/(kind+'.extended.zip')
                old_months=pd.period_range('2019-01',source_end,freq='M').astype(str)
                append_zip(source/(kind+'.zip'),extension,new,old_months,kind,collector)
                input_path=extension
            else:input_path=source/(kind+'.zip')
            append_zip(input_path,destination/(kind+'.zip'),active,months,kind,collector)
        hashes={n:hashlib.sha256((destination/n).read_bytes()).hexdigest() for n in FILES}
        evidence=[dict(r) for r in collector.db.execute('SELECT url,status,sha256,bytes,received FROM responses ORDER BY url')]
        atomic(destination/'source_evidence.json',evidence)
        result=dict(closed_through=through,parent_fingerprint=parent_fingerprint,fingerprint=digest(hashes),files=hashes,
                    coverage_complete=True,coverage_contract='all published monthly archives attempted; 404 and per-symbol gaps retained, never zero-filled; D conservative proxy only',
                    symbols=symbols,observed_symbols=active,directory=str(destination.resolve()),created_utc=utc(),
                    venue_certified=False,fees_margin_certification='NOT_AVAILABLE_PROXY_ONLY')
        atomic(manifest_path,result);atomic(feed_root/'latest_dataset.json',result)
        return result
    finally:collector.db.close()
