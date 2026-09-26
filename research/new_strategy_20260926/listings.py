"""First archived minute bars supply symbol-specific listing evidence."""
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
import json,xml.etree.ElementTree as ET
import acquire
from common import HERE,write

def one(symbol):
    prefix=f'data/spot/monthly/klines/{symbol}/1m/'
    url='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?'+urlencode({'prefix':prefix,'max-keys':2})
    b=acquire.get(url);rt=ET.fromstring(b);ns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
    keys=[x.text for x in rt.findall('s:Contents/s:Key',ns) if x.text.endswith('.zip')]
    if not keys:return dict(symbol=symbol,status='UNVERIFIED_NO_FIRST_ARCHIVE')
    key=keys[0];raw=acquire.archive(key);f=acquire.frame(raw);valid=f[f.volume>0]
    return dict(symbol=symbol,first_traded_minute_utc=str(valid.index[0]),source_url=acquire.BASE+key,archive_sha256=acquire.sha(raw),index_url=url,index_sha256=acquire.sha(b),status='OBSERVED_FIRST_MINUTE_NOT_ADMINISTRATIVE_ANNOUNCEMENT')

if __name__=='__main__':
    syms=json.loads((HERE/'cohort.json').read_text())['symbols']
    with ThreadPoolExecutor(max_workers=8) as ex:rows=list(ex.map(one,syms))
    write(HERE/'listing_evidence.json',rows);write(HERE/'listing_acquisition.json',dict(events=acquire.EVENTS,requests=acquire.COUNT,bytes=acquire.BYTES))
    print('Listing evidence captured for',len(rows))
