"""Deterministic tables and standalone SVG curves from persisted evaluations."""
import csv
import json
from pathlib import Path
from .protocol import atomic

def csv_write(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for r in rows:writer.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in r.items()})

def export(s):
    root=s.root;s.export_lineage()
    scores=[dict(run=r[0],generation=r[1],**json.loads(r[2])) for r in s.db.execute('SELECT run,generation,body FROM scores ORDER BY run,generation,candidate')]
    csv_write(root/'development.csv',[{k:v for k,v in r.items() if k not in ('folds','vector')} for r in scores])
    csv_write(root/'development_folds.csv',[dict(run=r['run'],generation=r['generation'],candidate=r['id'],scope=f['scope'],fold=f['fold'],start=f['start'],end=f['end'],**f['metrics']) for r in scores for f in r['folds']])
    events=[{k:json.loads(row[k]) if row[k] and k in ('payload','response','validation','usage') else row[k] for k in row.keys()} for row in s.mail.execute('SELECT * FROM proposals ORDER BY created')]
    atomic(root/'deepseek_proposals.json',events)
    if not (root/'results.json').exists():return
    rows=json.loads((root/'results.json').read_text());folds=json.loads((root/'folds.json').read_text());equity=json.loads((root/'equity.json').read_text())
    flat=[]
    for r in rows:
        flat.append(dict(island=r['island'],seed=r['seed'],arm=r['arm'],slot=r['slot'],candidates=r['candidates'],decision=r['decision'],**r['metrics'],
                         double_cost_cagr=r['stresses']['double_cost']['cagr'],later_bar_cagr=r['stresses']['later_bar']['cagr'],
                         benchmark_cagr=r['benchmark']['cagr'],benchmark_mdd=r['benchmark']['mdd'],benchmark_sharpe=r['benchmark']['sharpe'],benchmark_calmar=r['benchmark']['calmar'],
                         dsr=r['dsr']['probability'],pbo=r['pbo']['pbo'],bootstrap_status=r['bootstrap']['status'],holm_pvalue=r['bootstrap']['holm_pvalue'],
                         rejection_reasons=r['rejection_reasons']))
    csv_write(root/'all_results.csv',flat);csv_write(root/'annual_folds_stresses_capacity.csv',folds);csv_write(root/'equity.csv',equity)
    csv_write(root/'regime_attribution.csv',json.loads((root/'regime_folds.json').read_text()))
    from .statistics import pareto_front
    candidates=[dict(id=str(i),complexity=0,vector=[r['metrics']['cagr'],-r['metrics']['mdd'],r['metrics']['sharpe'],r['metrics']['calmar'],-r['metrics']['turnover'],-r['metrics']['asset_concentration']]) for i,r in enumerate(rows)]
    atomic(root/'pareto_front.json',[rows[i] for i in pareto_front(candidates)])
    # Every line is a frozen walk-forward rule; annual accounts remain separate $100 books.
    groups={}
    for d in equity:groups.setdefault((d['island'],d['arm'],d['seed'],d['slot']),[]).append(d)
    paths=[];colors=['#087f8c','#df6c29','#8057bb','#287c44']
    for k,days in groups.items():
        if k[3]!='C':continue
        values=[];factor=1.;prevyear=None;last=100.
        for d in sorted(days,key=lambda x:x['date']):
            year=d['date'][:4]
            if prevyear is not None and year!=prevyear and d.get('book')!='CONTINUOUS_PRIMARY':factor*=last/100
            values.append(d['nav']*factor);last=d['nav'];prevyear=year
        if not values:continue
        # Log scaling fixed across curves via global range computed below.
        paths.append((k,values))
    import math
    vals=[math.log(max(v,.001)) for _,vs in paths for v in vs];low=min(vals+[math.log(100)]);high=max(vals+[math.log(101)])
    lines=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="680" viewBox="0 0 1100 680">','<rect width="1100" height="680" fill="#fff"/>','<text x="45" y="28" font-family="sans-serif" font-size="19">Frozen walk-forward curves - historical research proxy, not account PnL</text>']
    for k,vs in paths:
        points=' '.join(f'{50+i/max(1,len(vs)-1)*990:.1f},{550-(math.log(max(v,.001))-low)/max(high-low,.001)*490:.1f}' for i,v in enumerate(vs))
        color='#111111' if k[1]=='benchmark' else colors['FGHD'.index(k[0][0])];dash=' stroke-dasharray="5 3"' if k[1]=='deepseek' else ''
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.3" opacity=".65"{dash}/>')
    lines+=['<text x="50" y="590" font-family="sans-serif" font-size="14">F teal / G orange / H purple / D green | solid deterministic, dashed DeepSeek | all 3 search seeds</text>','<text x="50" y="616" font-family="sans-serif" font-size="13">Log equity; continuous cash and quantities across frozen annual rule switches. No invented year-end exit.</text>','</svg>']
    (root/'equity.svg').write_text('\n'.join(lines),encoding='utf-8')
    decision=s.meta('decision');status=s.status();report=['# Frozen causal evolution result','',f"Decision: **{decision['D']}**. Previously studied history is not new sealed evidence.",'',
      '|Island|Arm|Seed|Slot|CAGR|MDD|Sharpe|Calmar|BTC CAGR|Result|','|---|---|---:|---|---:|---:|---:|---:|---:|---|']
    for r in rows:
        m=r['metrics'];report.append(f"|{r['island']}|{r['arm']}|{r['seed']}|{r['slot']}|{m['cagr']:.2%}|{m['mdd']:.2%}|{m['sharpe']:.2f}|{m['calmar']:.2f}|{r['benchmark']['cagr']:.2%}|{r['decision']}|")
    report+=['','Complete metrics/costs/turnover/concentration/stresses: `all_results.csv`. Per-year, venue, capital and stress: `annual_folds_stresses_capacity.csv`. All development attempts: SQLite + `development_folds.csv`.',
              '',f"DeepSeek API calls: {status['deepseek']['calls']}; tokens: {status['deepseek']['tokens']}; cost upper estimate USD {status['deepseek']['usd']:.6f}.",
              '', 'No strategy is deployed. Prospective start 2026-09-27; next scheduled refit 2027-01-01, conditional on 30 new closed UTC days and complete append-only data.',
              '', 'A/B/C decision objects:','```json',json.dumps(decision,indent=2),'```']
    (root/'REPORT.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
