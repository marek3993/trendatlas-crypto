"""Repeat selected real replays and compare to the committed evidence, offline."""
import json
import numpy as np
import evaluate,ledger,market,signals
from common import HERE,write

def main():
    rows=json.loads((HERE/'results/outer_folds.json').read_text());m=market.load();checked=[]
    selected=[r for r in rows if r['year']==2023 and r['initial_capital'] in [100,1000000] and r['label'] in ['BTC_SMA200','B_deterministic','B_deepseek']]
    for r in selected:
        t=signals.benchmark(m) if r['candidate'] is None else signals.target(m,r['candidate'])
        try:
            run=evaluate.replay(m,t,r['year'],capital=r['capital_start'],mult=2 if r['stage']=='double' else 1,lag=3 if r['stage']=='delayed' else 2);actual=ledger.summarize(run);assert r['status']=='VALID'
            for k in ['cagr','mdd','sharpe','calmar','costs','fee_usd','slippage_usd','entry_fill_ratio','trades']:np.testing.assert_allclose(actual[k],r[k],rtol=1e-12,atol=1e-12)
        except ledger.UnsafeExecution as exc:assert r['status']=='UNSAFE_EXECUTION' and str(exc)==r['reason']
        checked.append(dict(label=r['label'],capital=r['initial_capital'],stage=r['stage'],year=r['year'],status='MATCH'))
    write(HERE/'reproduction_check.json',dict(status='PASS',replays=checked));print('Reproduced',len(checked),'saved real-data replays without network or API')

if __name__=='__main__':main()
