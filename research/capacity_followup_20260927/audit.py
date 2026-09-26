"""Independent evidence checks; never modifies results or the evaluator."""
import ast,io,json,subprocess,zipfile
import numpy as np
import pandas as pd
import designer,market,signals
from ledger_archive import Evidence
from common import HERE,ROOT,SPEC,digest,write

def main():
    freeze=json.loads((HERE/'engine_data_freeze.json').read_text())
    for name,value in freeze['hashes'].items():assert digest(HERE/name)==value,name
    full=market.load();checks=[]
    for end in ['2022-06-30 20:00:00','2024-06-30 20:00:00']:
        prefix=market.load(end);n=len(prefix['dates']);assert full['assets']==prefix['assets'];np.testing.assert_array_equal(full['eligible'][:n],prefix['eligible'])
        for cfg in designer.grid():
            a=signals.target(full,cfg);b=signals.target(prefix,cfg);np.testing.assert_allclose(a['weights'][:n],b['weights'],rtol=0,atol=0);np.testing.assert_array_equal(a['event'][:n],b['event'])
        checks.append(dict(prefix=end,configurations=len(designer.grid()),eligibility_and_targets='identical'))
    fill_count=order_count=episodes=0;max_participation=0.;sources=set()
    with Evidence() as z:
        for name in z.namelist():
            if name.endswith('fills.json'):
                fills=json.loads(z.read(name));fill_count+=len(fills)
                grouped={};order_fills={}
                for f in fills:
                    assert pd.Timestamp(f['date'])>pd.Timestamp(f['available_at']);assert pd.Timestamp(f['available_at'])==pd.Timestamp(f['signal_at'])+pd.Timedelta(hours=4,seconds=60)
                    assert f['notional']<=.001*f['capacity_quote']+1e-6;assert f['quantity']>0;sources.add(f['asset']);max_participation=max(max_participation,f['notional']/f['capacity_quote'])
                    sign=1 if f['side']=='buy' else -1;mult=2 if '/double/' in name or '/double_partial/' in name else 1
                    assert abs(f['fill_price']/f['reference_price']-(1+sign*.001*mult))<1e-9
                    key=(f['date'],f['asset']);grouped[key]=grouped.get(key,0.)+f['notional'];assert grouped[key]<=.001*f['capacity_quote']+1e-6
                    totals=order_fills.setdefault(f['order_id'],[0.,0.]);totals[0]+=f['quantity'];totals[1]+=f['notional']
                for o in json.loads(z.read(name.replace('fills.json','orders.json'))):
                    totals=order_fills.get(o['id'],[0.,0.]);np.testing.assert_allclose(totals,[o['filled_quantity'],o['filled_notional']],rtol=1e-10,atol=1e-7)
            elif name.endswith('orders.json'):
                orders=json.loads(z.read(name));order_count+=len(orders)
                for o in orders:
                    assert abs(o['filled_quantity']+o['remaining']-o['requested_quantity'])<max(1e-7,o['requested_quantity']*1e-10)
                    if o['filled_quantity']:assert abs(o['average_price']-o['filled_notional']/o['filled_quantity'])<1e-8
                    if o['status']=='FILLED':assert o['remaining']<max(1e-7,o['requested_quantity']*1e-10)
            elif name.endswith('episodes.json'):episodes+=len(json.loads(z.read(name)))
            elif name.endswith('terminal.json'):
                terminal=json.loads(z.read(name))
                if terminal['status']=='VALID':
                    assert not terminal['residual_positions'],'Accepted evidence must actually end flat'
                    np.testing.assert_allclose(terminal['ending_cash'],terminal['ending_nav'],rtol=1e-10,atol=1e-6)
    events=[json.loads(line) for line in (HERE/'results/designer_events.jsonl').read_text().splitlines()]
    for e in events:
        assert e['input_scope']=='development'
        if 'payload' in e:
            p=json.loads(e['payload']['messages'][1]['content']);assert set(p)=={'schema','development','seen_candidate_ids'}
            for r in p['development']:assert set(r)<=set('candidate status cagr mdd sharpe calmar turnover costs double_cost_cagr delayed_cagr benchmark_pass'.split())
            for v in ['Authorization','DEEPSEEK_API_KEY','MRV1_DEEPSEEK_API_KEY']:assert v not in json.dumps(e['payload'])
        for c in e['accepted_proposals']:designer.validate(c)
    dev=json.loads((HERE/'results/development.json').read_text())
    for origin in SPEC['evolution']['origins']:
        for arm in SPEC['evolution']['arms']:
            rows=[r for r in dev if r['arm']==arm and r['origin']==origin];assert len(rows)==22 and len({r['candidate_id'] for r in rows})==22
        seeds={arm:{r['candidate_id']:r for r in dev if r['arm']==arm and r['origin']==origin and r['generation']==0} for arm in SPEC['evolution']['arms']}
        assert set(seeds['deterministic'])==set(seeds['deepseek'])
        for key in seeds['deterministic']:
            for metric in ['status','cagr','mdd','sharpe','calmar','costs','double_cost_cagr','delayed_cagr']:
                assert seeds['deterministic'][key].get(metric)==seeds['deepseek'][key].get(metric)
    finalist=json.loads((HERE/'results/finalists_frozen.json').read_text())
    assert all(pd.Timestamp(e['requested_utc'])<pd.Timestamp(finalist['utc']) for e in events if e.get('api_called'))
    # Production and previous experiments must equal the named starting commit.
    changed=subprocess.check_output(['git','diff',SPEC['source_commit'],'--name-only'],cwd=ROOT,text=True).splitlines();assert all(n.startswith('research/capacity_followup_20260927/') for n in changed),changed
    forbidden=[]
    for name in ['market.py','signals.py','ledger.py','evaluate.py','designer.py','run.py']:
        source=(HERE/name).read_text();tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                for token in ['paper_equity.csv','paper_returns.csv','base_returns.csv','outputs/','actual_held_asset','effective_market_exposure']:
                    if token in node.value:forbidden.append(dict(file=name,value=token))
    assert not forbidden
    result=dict(status='PASS',frozen_inputs_unchanged=True,prefix_checks=checks,checked_fills=fill_count,checked_orders=order_count,checked_episodes=episodes,max_participation=max_participation,filled_instruments=sorted(sources),development_budget_evaluations=len(dev),designer_payload_scope='development whitelist only',forbidden_old_path_hits=forbidden,production_and_ancestor_diff=changed,production_changes=False,live_orders=False,scope_limit='Evidence checks certify causal code/data usage; incomplete historical administrative and tick/lot evidence remains a research limitation, not erased.')
    write(HERE/'validation.json',result);print(json.dumps(result,indent=2))

if __name__=='__main__':main()
