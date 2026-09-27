"""Independent reruns of saved primary finalists/benchmarks, without API or tuning."""
import json
import numpy as np
from common import HERE,config,write,now
from data import load
from signals import targets
from ledger import replay

def main():
    out=HERE/'results';assert (out/'completed.json').exists()
    saved={r['candidate_id']:r for r in json.loads((out/'oos.json').read_text())};final=json.loads((out/'finalists_frozen.json').read_text());markets={t:load(t) for t in ['spot','perp']};checks=[]
    for identity in ['BTC_SMA200_spot','BTC_SMA200_perp']+list(final['unique']):
        row=saved[identity];c=row['candidate'];m=markets[row['track']];t=targets(m,c or config(),benchmark=c is None)
        r=replay(m,t,'2023-01-01','2025-12-31',gross_limit=c['gross'] if c and c['family']=='D' else 1.)['metrics']
        errors={}
        for k,v in r.items():
            if isinstance(v,(float,int)) and not isinstance(v,bool):
                err=abs(v-row[k]);assert err<max(1e-9,abs(v)*1e-10),(identity,k,err);errors[k]=err
            else:assert v==row[k],(identity,k)
        checks.append(dict(candidate_id=identity,max_numeric_error=max(errors.values()),metrics_checked=len(r)));print('REPRODUCED',identity,flush=True)
    # Newly recomputed historical context only; never a designer input.
    contextual=[]
    for track in ['spot','perp']:
        m=markets[track];t=targets(m,config(),benchmark=True);r=replay(m,t,'2022-01-01','2025-12-31')
        contextual.append(dict(track=track,period=['2022-01-01','2025-12-31'],**r['metrics'],folds=r['folds']))
    write(out/'benchmark_2022_2025_context.json',contextual)
    write(HERE/'reproduction_check.json',dict(utc=now(),status='PASS',checks=checks,api_calls=0,old_pnl_inputs=0))

if __name__=='__main__':main()
