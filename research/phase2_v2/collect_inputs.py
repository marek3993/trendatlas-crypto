"""Read-only public Binance development acquisition, no credentials/account APIs."""
import csv
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

END = '2026-09-25'
def ms(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)

def main(root):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    source=Path('/opt/trendatlas-research/releases/53b6a5336ca1f7ce35b481a017f7e82396f3613c/research/causal_evolution/inputs')
    with zipfile.ZipFile(source/'spot_daily.zip') as z:
        symbols={n.removesuffix('.csv') for n in z.namelist()}
    with zipfile.ZipFile(root/'local_spot_daily.zip') as z:
        symbols.update(n.removesuffix('.csv') for n in z.namelist())
    out=root/'public';out.mkdir(exist_ok=True)
    def collect_symbol(symbol):
        records=[]
        for start,end,label in [('2018-05-05','2018-12-31','2018'),('2026-01-01',END,'2026')]:
            result=out/(symbol+'-'+label+'.json')
            if result.exists():
                records.append(json.loads(result.read_text())['audit']);continue
            params={'symbol':symbol,'interval':'1d','startTime':ms(start),'endTime':ms(end)+86400000-1,'limit':1000}
            url='https://api.binance.com/api/v3/klines?'+urllib.parse.urlencode(params)
            audit={'symbol':symbol,'start':start,'end':end,'source_url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat()}
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url,timeout=20) as r: data=json.load(r)
                    audit['state']='COMPLETE';break
                except urllib.error.HTTPError as e:
                    if e.code==400:
                        body=json.loads(e.read())
                        if body.get('code') != -1121: raise
                        audit.update(state='SYMBOL_UNAVAILABLE',code=-1121);data=[];break
                    if e.code not in (429,500,502,503,504) or attempt==2: raise
                    time.sleep(min(30,2**(attempt+1)))
            if any(not ms(start)<=int(row[0])<=ms(end) or int(row[6])>ms(end)+86400000-1 for row in data):
                raise ValueError('public_response_outside_development')
            audit.update(rows=len(data),last_open_time=data[-1][0] if data else None)
            result.write_text(json.dumps({'audit':audit,'bars':data}))
            records.append(audit)
            time.sleep(.05)
        return records
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for batch in pool.map(collect_symbol, sorted(symbols)):
            records.extend(batch)
            if len(records)%40==0:
                print(json.dumps({'collected':len(records),'planned':len(symbols)*2}),flush=True)
    with zipfile.ZipFile(root/'public_spot_daily.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for symbol in sorted(symbols):
            rows=[]
            for label in ('2018','2026'):
                data=json.loads((out/(symbol+'-'+label+'.json')).read_text())['bars']
                rows += [[datetime.fromtimestamp(b[0]/1000,timezone.utc).strftime('%Y-%m-%d'),*b[1:5],b[7]] for b in data]
            if rows:
                buf=io.StringIO();w=csv.writer(buf);w.writerow(['date','open','high','low','close','quote_volume']);w.writerows(rows)
                z.writestr(symbol+'.csv',buf.getvalue())
    manifest={'end':END,'symbols':len(symbols),'public_requests':records,
        'outer_read':False,'forward_read':False,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.zip')}}
    (root/'public_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'complete':True,'symbols':len(symbols),'rows':sum(x['rows'] for x in records)}))

if __name__=='__main__': main(sys.argv[1])
