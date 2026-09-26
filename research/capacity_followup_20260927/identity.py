"""Symbol is insufficient when the same exchange ticker is reused.

Instrument epochs split observed data; never adjust prices, carry quantity,
splice returns, or grant new denomination the old denomination's warmup.
Historical notices only disable admission after their publication.
"""
import json
import pandas as pd
from common import HERE

def events():return json.loads((HERE/'identity_events.json').read_text())
def split(frames,hours):
    result=dict(frames)
    for e in events():
        s=e['symbol']
        if s not in result:continue
        f=result.pop(s);halt=pd.Timestamp(e['effective_utc']);restart=pd.Timestamp(e['new_start'])
        result[s+'@original']=f.loc[f.index+pd.Timedelta(hours=hours)<=halt]
        result[s+'@'+restart.strftime('%Y%m%d')]=f.loc[f.index>=restart]
    return result
def notices():
    ordinary=json.loads((HERE/'venue_notices.json').read_text())
    return ordinary+[dict(e,symbol=e['symbol']+'@original') for e in events()]
def venue_symbol(asset):return asset.split('@')[0]
