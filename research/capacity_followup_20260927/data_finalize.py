"""Complete acquisition for the identity-aware PIT census before any replay."""
import json,zipfile
import numpy as np
import pandas as pd
import data_prepare as dp,identity,market
from common import HERE,SPEC,digest,write

def main():
    raw=market.frames('spot_daily.zip','2025-12-31');daily=identity.split(raw,24);days=pd.date_range(SPEC['data']['start'],SPEC['data']['end'])
    dc=pd.DataFrame({a:f.close.reindex(days) for a,f in sorted(daily.items())});dq=pd.DataFrame({a:f.quote_volume.reindex(days) for a,f in sorted(daily.items())});obs=dc.notna()&dc.gt(0)&dq.gt(0);allowed=pd.DataFrame(True,index=days,columns=dc.columns)
    for n in identity.notices():
        if n['symbol'] in allowed:
            t=days+pd.Timedelta(hours=20);disabled=(t>=pd.Timestamp(n['published_utc']))&(t+pd.Timedelta(hours=8)>=pd.Timestamp(n['effective_utc'])-pd.Timedelta(hours=72));allowed.loc[disabled,n['symbol']]=False
    ok=market.eligibility(dc,dq,obs,allowed);required=sorted({identity.venue_symbol(a) for a in ok.columns[ok.any()]}|{'BTCUSDT'});intra=market.frames('spot_4h.zip','2025-12-31 20:00:00');missing=sorted(set(required)-set(intra))
    before=digest(HERE/'spot_4h.zip')
    if missing:
        jobs=[]
        for s in missing:
            keys=dp.index(f'data/spot/monthly/klines/{s}/4h/')['keys']
            jobs += [(s,k) for k in keys if k.endswith('.zip') and '2019-01'<=k[-11:-4]<='2025-12']
        intra.update(dp.collect(jobs,'identity_supplement'));dp.store_frames('spot_4h.zip',intra)
    aq=json.loads((HERE/'acquisition.json').read_text());aq['input_hashes']['spot_4h.zip']=digest(HERE/'spot_4h.zip');write(HERE/'acquisition.json',aq)
    write(HERE/'identity_acquisition.json',dict(required_raw_symbols=required,supplemental_symbols=missing,original_intraday_sha256=before,final_intraday_sha256=digest(HERE/'spot_4h.zip'),requests=dp.REQUESTS,downloaded_bytes=dp.BYTES,events=dp.EVENTS,rule='Split denomination epochs; reset observation history. Notices publication-aware. Same original parameter and liquidity contract. No performance consulted.'))
    if dp.INDEXES:
        with zipfile.ZipFile(HERE/'supplemental_indexes.zip','w',zipfile.ZIP_DEFLATED) as z:
            for k,v in dp.INDEXES.items():z.writestr(k+'.json',json.dumps(v))
    assert aq['requests']+dp.REQUESTS<=SPEC['data']['max_requests'] and aq['downloaded_bytes']+dp.BYTES<=SPEC['data']['max_bytes']
    m=market.load();membership=[]
    for a in m['daily_eligible']:
        x=m['daily_eligible'][a]
        if x.any():membership.append(dict(instrument=a,venue_symbol=identity.venue_symbol(a),first_eligible=str(x.index[x][0]),last_eligible=str(x.index[x][-1]),eligible_days=int(x.sum())))
    with zipfile.ZipFile(HERE/'pit_membership.zip','w',zipfile.ZIP_DEFLATED) as z:z.writestr('daily_eligible.csv',m['daily_eligible'].astype(int).to_csv())
    write(HERE/'pit_audit.json',dict(raw_symbols=len(raw),instrument_epochs=len(daily),intraday_instruments=len(m['assets']),eligible_instruments=membership,administrative_notice_coverage='Known named notices only; complete global administrative timeline NOT certified. Missing held prices fail closed; bars give observed listing/cessation and never authorize advance exit.',bar_evidence_not_admin_dates=True))
    print('Identity-aware market ready:',len(m['assets']),'instruments; supplemental',missing,flush=True)

if __name__=='__main__':main()
