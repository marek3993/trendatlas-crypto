"""Required reference stresses and FINAL nominee neighbors, no reselection."""
import json
from common import HERE,write
import market,signals,designer,evaluate as ev

def main():
    out=HERE/'results';final=json.loads((out/'finalists_frozen.json').read_text());m=market.load();stressed=[]
    for name in ['CASH','BTC_hold','BTC_SMA200']:
        t=signals.baseline(m,name);runs={k:{} for k in ['nominal','double','delayed']}
        for year in [2022,2023,2024,2025]:
            for k,cost,lag in [('nominal',1.,2),('double',2.,2),('delayed',1.,3)]:
                scale=1.
                for r in runs[k].values():scale*=r['daily'].equity.iloc[-1]
                runs[k][year]=ev.replay(m,t,year,mult=cost,lag=lag,capital_scale=scale)
        base,_=ev.stitch(runs['nominal']);d,_=ev.stitch(runs['double']);late,_=ev.stitch(runs['delayed'])
        base.update(family='baseline_'+name,status='VALID',double_cost_cagr=d['cagr'],double_cost_mdd=d['mdd'],delayed_cagr=late['cagr'],delayed_mdd=late['mdd']);stressed.append(base)
    write(out/'baseline_stresses.json',stressed)
    rows=[];seen=set();summary=[]
    for slot,parent in final['slots'].items():
        if parent is None or parent['candidate_id'] in seen:continue
        seen.add(parent['candidate_id']);local=[]
        for cfg in designer.neighbors(parent['candidate']):
            row=ev.evaluate(m,cfg,2025,scope='finalist_validation_neighbor');row.update(parent_id=parent['candidate_id'],slot=slot);rows.append(row);local.append(row)
        import numpy as np
        good=[r for r in local if r['status']=='VALID'];qualified=[r for r in good if r['cagr']>0 and r['mdd']<=.35]
        median=float(np.median([r['cagr'] for r in good])) if good else None
        passed=len(qualified)/len(local)>=.75 and median is not None and median>=.75*parent['cagr'] and parent['cagr']>0
        summary.append(dict(candidate_id=parent['candidate_id'],slots=[s for s,r in final['slots'].items() if r and r['candidate_id']==parent['candidate_id']],neighbors=len(local),valid=len(good),qualified=len(qualified),median_cagr=median,passed=passed))
    write(out/'finalist_neighbors.json',dict(rows=rows,summary=summary,nominees_reselected=False))
    print('Reference stresses and final nominee neighbor tests complete; nominees unchanged')

if __name__=='__main__':main()
