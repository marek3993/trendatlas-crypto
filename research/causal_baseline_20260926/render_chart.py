"""Render only the verified causal model chart; no account data is loaded."""
from pathlib import Path
import argparse
import sys
import json
import pandas as pd
import numpy as np

HERE=Path(__file__).resolve().parent
# Optional isolated plotting dependencies used on the reconstruction workstation.
if (HERE/'scratch/plotdeps').exists():
    sys.path.append(str(HERE/'scratch/plotdeps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main(root):
    chart=pd.read_csv(root/'dashboard_model_chart.csv')
    ledger=pd.read_csv(root/'causal_ledger.csv')
    np.testing.assert_allclose(chart.model_index,(1+ledger.net_strategy_return).cumprod(),rtol=1e-12,atol=1e-12)
    summary=json.loads((root/'comparison.json').read_text())['causal_candidate']
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'svg.hashsalt':'trendatlas-causal-20260926'})
    fig,(ax,ddax)=plt.subplots(2,1,figsize=(13,8),sharex=True,gridspec_kw={'height_ratios':[3,1]},layout='constrained')
    fig.set_facecolor('#f8fafc')
    dates=pd.to_datetime(chart.date)
    ax.plot(dates,chart.model_index,color='#087f8c',lw=2,label='Model po nákladoch')
    ax.plot(dates,chart.btc_index,color='#d88b17',lw=1.5,label='BTC')
    ax.set_yscale('log');ax.set_ylabel('Index, začiatok = 1 · logaritmická os')
    ax.set_title('Modelový vývoj a BTC',loc='left',fontsize=20,fontweight='bold',pad=34)
    ax.legend(loc='upper left',frameon=False);ax.grid(alpha=.18)
    equity=chart.model_index.to_numpy();drawdown=(equity/np.maximum.accumulate(np.r_[1.,equity])[1:]-1)*100
    ddax.fill_between(dates,drawdown,0,color='#087f8c',alpha=.2);ddax.plot(dates,drawdown,color='#087f8c',lw=1)
    ddax.set_ylabel('Pokles modelu (%)');ddax.grid(alpha=.18)
    ax.text(0,1.015,f"CAGR {summary['cagr_pct']:.2f} %   |   Celkový výnos {summary['total_return_pct']:.2f} %   |   Najväčší pokles {summary['max_drawdown_pct']:.2f} %",fontsize=10,transform=ax.transAxes,va='bottom')
    fig.supxlabel('Denný spotový cenový proxy model vrátane nákladov. Nejde o výnos účtu ani o historické burzové plnenia.',fontsize=9)
    fig.savefig(root/'dashboard_model_chart.png',dpi=150,metadata={'Software':'TrendAtlas causal research'})
    fig.savefig(root/'dashboard_model_chart.svg',metadata={'Date':None})
    svg=root/'dashboard_model_chart.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8',newline='\n')
    plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=HERE/'results');main(p.parse_args().results)
