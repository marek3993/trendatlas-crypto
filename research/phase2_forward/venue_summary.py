"""Read-only collector coverage export; does not turn retrieval into a backtest."""
from collections import defaultdict
import datetime as dt
import json
from pathlib import Path
import sqlite3
import zlib


def summarize():
    root=Path('/var/lib/trendatlas-phase2').resolve()
    db=sqlite3.connect((root/'venue.sqlite').as_uri()+'?mode=ro',uri=True)
    bars=defaultdict(dict);funding=defaultdict(dict);gaps=[];metadata=None;received=None
    for kind,asset,stamp,status,payload in db.execute('SELECT kind,asset,received_utc,status,payload FROM observations ORDER BY id'):
        data=json.loads(zlib.decompress(payload)) if kind!='source_document' or status!='OK' else None
        if status!='OK':gaps.append({'kind':kind,'asset':asset,'received_utc':stamp,'detail':data});continue
        if kind=='metaAndAssetCtxs':metadata=data;received=stamp
        elif kind=='candleSnapshot':
            for v in data:bars[asset][v['t']]=v
        elif kind=='fundingHistory':
            for v in data:funding[asset][v['time']]=v
    def stamp(t):return dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat()
    coverage={}
    for asset,rows in bars.items():
        keys=sorted(rows);rates=sorted(funding[asset])
        coverage[asset]={'bars':len(keys),'first_bar':stamp(keys[0]) if keys else None,
                        'last_bar':stamp(keys[-1]) if keys else None,
                        'missing_hours_inside_retrieved_span':sum((b-a)//3600000-1 for a,b in zip(keys,keys[1:])),
                        'funding_records':len(rates),'first_funding':stamp(rates[0]) if rates else None,
                        'last_funding':stamp(rates[-1]) if rates else None,
                        'funding_backfill_complete':False}
    ctx=[]
    if metadata:
        for asset,row in zip(metadata[0]['universe'],metadata[1]):
            if asset['name'] in bars:
                ctx.append({'asset':asset, 'context':row})
    result={'status':'INCOMPLETE','venue_certification':False,'market_observed_utc':received,
            'all_native_perp_metadata_assets':len(metadata[0]['universe']) if metadata else 0,
            'coverage':coverage,'latest_selected_metadata_and_context':ctx,'retrieval_gaps':gaps,
            'funding_backfill_note':'bounded400hour pages; completeness must be verified after pagination, never assumed',
            'fills':'NOT_CERTIFIED_15minute_books_and_1hour_OHLCV_do_not_prove_all_intrabar_fills',
            'history':'retrieved_before_nominee_freeze_is_not_prospective'}
    db.close();print(json.dumps(result,indent=2))


if __name__=='__main__':summarize()
