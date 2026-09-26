"""Full event-lineage audit of every nominal validation/development CAGR >=150%."""
from common import *
from search import spec_checked
from replay import simulate
from signals import Controller
from finalize import verify_arithmetic

def main():
    out=HERE/'results';s=spec_checked();m=enhanced_market();vm={p['id']:p for p in s['variants']}
    rows=read(out/'audits.json')['high_development_and_validation'];cache={};answer=[]
    columns=['date','asset','episode','log_growth','cost_fraction','turnover','event','price','quantity_change','equity_after']
    for k,v in enumerate(rows):
        part=next(p for p in s['partitions'] if p['id']==v['partition']);key=(part['cap'],v['variant'],v['window'])
        if key not in cache:
            start,end=s['development'] if v['window']=='development' else [v['window']+'-01-01',v['window']+'-12-31']
            runs=[]
            for y in range(pd.Timestamp(start).year,pd.Timestamp(end).year+1):
                lo=max(start,f'{y}-01-01');hi=min(end,f'{y}-12-31')
                runs.append(simulate(m,no_risk(),part['cap'],start=lo,end=hi,controller=Controller(vm[v['variant']]),ledger=True))
            r=e.stitch(runs);met=metrics(r);assert abs(met['cagr']-v['cagr'])<1e-9
            ev=pd.DataFrame(r['events'],columns=columns);count=verify_arithmetic(ev,s)
            for event in ev.itertuples():
                i=m.dates.get_loc(event.date);a=m.assets.index(event.asset);_,h,l,_=m.prices[i,a]
                assert l-1e-8<=event.price<=h+1e-8
            assert abs(ev.log_growth.sum()-met['net_log_growth'])<1e-8
            cache[key]=dict(event_count=count,cagr_reproduced=met['cagr'],price_symbol_lineage=True,quantity_cost_funding_arithmetic=True,
                            accounting_log_reconciliation=True,realized_max_exposure=met['max_realized_exposure'],venue_proof=False,point_in_time_universe=False,sealed=False)
        answer.append(dict(partition=v['partition'],variant=v['variant'],window=v['window'],**cache[key]))
        if k%40==39:print('High-return complete event lineage',k+1,'/',len(rows),flush=True)
    write(out/'high_return_lineage.json',dict(code_sha256=sha(Path(__file__)),unique_full_window_replays=len(cache),audited_rows=answer))
    print('PASS:',len(rows),'high-return development/validation rows,',len(cache),'unique full-window replays')

if __name__=='__main__':main()
