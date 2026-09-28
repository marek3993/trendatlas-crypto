"""Plot recorded continuous NAV only; no strategy execution or selection."""
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parent
books=defaultdict(list)
with (root/'raw/equity.csv').open(encoding='utf-8') as f:
    for r in csv.DictReader(f):books[(r['island'],r['arm'],r['seed'],r['slot'])].append(r)
fig,axes=plt.subplots(2,2,figsize=(13,8),layout='constrained')
colors={'deepseek':'#3270b5','deterministic':'#19a390','benchmark':'#e29d21'}
for ax,(island,title) in zip(axes.flat,[('F_spot','F | Time-series trend'),('G_spot','G | Core / satellite'),('H_spot','H | Diversified trend'),('D_perp','D | Actual perpetual data, conservative proxy')]):
    seen=set()
    for (family,arm,seed,slot),days in books.items():
        if family!=island:continue
        ax.plot([dt.date.fromisoformat(r['date']) for r in days],[float(r['nav']) for r in days],color=colors[arm],alpha=.4,lw=1,label=arm if arm not in seen else '_')
        seen.add(arm)
    track=island.split('_')[1];days=books[('BTC_'+track,'benchmark','0','C')]
    ax.plot([dt.date.fromisoformat(r['date']) for r in days],[float(r['nav']) for r in days],color=colors['benchmark'],lw=2.3,label='BTC SMA200 (same track)')
    ax.axhline(100,color='#999',ls=':',lw=.8)
    ax.set_title(title+' — all 18 rows REJECT',fontsize=10)
    ax.set_ylabel('Account NAV (USD); initial capital $100')
    ax.grid(alpha=.18);ax.legend(fontsize=8,loc='upper left');ax.tick_params(axis='x',labelrotation=20)
fig.suptitle('Frozen causal cycle | 2024–2025 continuous accounts\nPreviously studied history; no new globally sealed or forward evidence',fontsize=13)
fig.savefig(root/'equity_overview.png',dpi=160)
fig.savefig(root/'equity_overview.svg',metadata={'Date':None})
svg=root/'equity_overview.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8',newline='\n')
print('Wrote equity_overview.png and equity_overview.svg from recorded NAV')
