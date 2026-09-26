"""Fresh OOS/stress/neighbor replay and independent samples of the full grid."""
import shutil
from datetime import datetime,timezone
from common import *
from search import search,spec_checked,window_metrics
from signals import Controller
from replay import simulate

def main():
    spec=spec_checked();source=HERE/'results';target=ROOT/'scratch/phase2_reproduction'
    target.mkdir(parents=True,exist_ok=True)
    for part in spec['partitions']:
        name=f"grid_{part['id']}.json";shutil.copyfile(source/name,target/name)
    search(target,6)
    compared={}
    for p in target.iterdir():
        if not p.is_file() or p.name.startswith('grid_'):continue
        a=sha(p);b=sha(source/p.name);assert a==b,p.name;compared[p.name]=a
    m=enhanced_market();fresh=[]
    for part in spec['partitions']:
        cache=read(source/f"grid_{part['id']}.json")['records']
        for index in [0,33,65]:
            p=spec['variants'][index]
            for label,mult,delay in [('normal',1,0),('double_cost',2,0),('delay',1,1)]:
                r=simulate(m,no_risk(),part['cap'],start=spec['history_start'],end='2025-12-31',controller=Controller(p),cost_multiplier=mult,delay=delay)
                windows={'development':spec['development']};windows.update({str(y):[f'{y}-01-01',f'{y}-12-31'] for y in range(2020,2026)})
                for name,(start,end) in windows.items():
                    met=e.summarize(r,start,end);stored=cache[p['id']][name]
                    if label=='normal':
                        for k in ['cagr','max_drawdown','sharpe','turnover','cost_drag','without_top_three_trades_cagr']:assert abs(met[k]-stored[k])<1e-12,(part,p['id'],name,k)
                    else:assert abs(met['cagr']-stored['double_cost_cagr' if label=='double_cost' else 'delayed_entry_cagr'])<1e-12
                fresh.append(dict(partition=part['id'],variant=p['id'],scenario=label,matched=True))
    write(source/'reproduction.json',dict(completed_at=datetime.now(timezone.utc).isoformat(),bitwise_identical_files=compared,fresh_full_history_scenarios=fresh,
      scope='Full repeated OOS, all overlays, 2x costs, entry delay and neighbors using unchanged grid cache; 54 independent full-history grid scenario checks. Not a second exhaustive full grid search.'))
    print('PASS:',len(compared),'bitwise-identical files;',len(fresh),'fresh full-history scenarios')

if __name__=='__main__':main()
