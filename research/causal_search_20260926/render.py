"""Render actual completed research outputs to exportable charts and report."""
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent


def main():
    out=HERE/'results';result=json.loads((out/'results.json').read_text());table=pd.read_csv(out/'pareto_table.csv')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,1,figsize=(13,9),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    selected=[]
    for name in [result['B_observed_best_robust'],result['C_observed_aggressive_pareto']]:
        if name and name not in selected:selected.append(name)
    # Also show all partition growth policies to expose leverage tradeoffs.
    selected+= [p['id'] for p in result['policies'] if p['selector']=='growth' and p['id'] not in selected]
    for i,name in enumerate(selected):
        f=pd.read_csv(out/f'{name}_equity.csv',parse_dates=['date']);eq=f.equity.to_numpy()
        label=name.replace('aggressive_','Aggressive ').replace('robust_','Robust ').replace('__',' / ')
        axes[0].plot(f.date,eq,label=label,linewidth=2 if i<2 else 1,alpha=1 if i<2 else .55)
        axes[1].plot(f.date,(eq/np.maximum.accumulate(np.r_[1,eq])[1:]-1)*100,linewidth=2 if i<2 else 1,alpha=1 if i<2 else .55)
    axes[0].set_yscale('log');axes[0].set_ylabel('Net model equity (start = 1)');axes[0].legend(fontsize=8,ncol=2)
    axes[1].set_ylabel('Daily-close drawdown (%)');axes[1].set_xlabel('Chronological OOS period')
    axes[0].set_title('Walk-forward research: 2021-01-01 to 2026-09-25\nSpot execution and funding proxies; no historical sealed test',loc='left')
    for ax in axes:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(out/'equity_curves.png',dpi=160);fig.savefig(out/'equity_curves.svg');plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,7))
    colors={'growth':'#2864b4','calmar':'#dd8b24','defensive':'#32956e'}
    for p in result['policies']:
        m=p['oos'];selector=p['selector'];color=colors[selector]
        ax.scatter(m['max_drawdown']*100,m['cagr']*100,c=color,marker='o' if p['mode']=='robust' else '^',
                   s=80 if p['descriptive_oos_pareto'] else 40,alpha=1 if p['risk_feasible'] else .3)
        ax.annotate(p['id'].replace('aggressive_','A').replace('robust_','R').replace('__','/'),
                    (m['max_drawdown']*100,m['cagr']*100),xytext=(4,4),textcoords='offset points',fontsize=7)
    ax.axvline(25,color='#32956e',linestyle='--',alpha=.6,label='Robust DD cap 25%')
    ax.axvline(35,color='#a64949',linestyle='--',alpha=.6,label='Absolute DD cap 35%')
    ax.axhline(150,color='#555555',linestyle=':',label='CAGR target floor 150%')
    ax.set_xlabel('Maximum event drawdown (%)');ax.set_ylabel('Net OOS CAGR (%)');ax.set_title('Observed OOS frontier — 18 predeclared adaptive policies',loc='left')
    ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(out/'pareto_frontier.png',dpi=160);fig.savefig(out/'pareto_frontier.svg');plt.close(fig)
    rows=[]
    for p in result['policies']:
        m=p['oos'];rows.append('| '+ ' | '.join([p['id'],f'{100*m["cagr"]:.2f}%',f'{100*m["max_drawdown"]:.2f}%',f'{m["sharpe"]:.2f}',f'{m["calmar"]:.2f}',f'{100*m["profitable_fold_fraction"]:.0f}%',str(p['risk_feasible'])])+' |')
    lines=['# Skutocne vykonany offline vyskum','',
        '1 944 nominalnych kombinacii v siestich oddelenych rozpoctoch; 3 888 development stresovych prehrati. Kazda OOS politika ma navyse 2x naklady, +1 bar a sest susednych prehrati. Ziadne nahodne alebo dodatocne hladanie po vysledkoch.','',
        '**Ciel 150-200 % CAGR sa nemeni. Ziadny vysledok tu nie je realny account PnL ani sealed dokaz.**','',
        '| Politika | OOS CAGR | Max. event DD | Sharpe | Calmar | Ziskove foldy | Risk limity |',
        '|---|---:|---:|---:|---:|---:|---|',*rows,'',
        f'Pozorovany najlepsi robustny kandidat: `{result["B_observed_best_robust"]}`.',
        f'Pozorovany agresivny Pareto kompromis: `{result["C_observed_aggressive_pareto"]}`.','',
        f'Politiky, ktore presli vsetkymi ciselne meratelnymi OOS high-return podmienkami: {result["oos_numeric_passes"]}.',
        '**A: ziadny platne potvrdeny sealed vitaz. D: plati.** B/C su podmienene historicke proxy vysledky.','',
        'Forward nominacie boli zvolene z development dat pred vypoctom OOS metrik a su ine pole ako popisny OOS rebricek. OOS vitaz ich automaticky nenahradza.',
        'Zmrazene forward nominacie: `'+json.dumps({k:result['forward_nominees'][k] for k in ['A','B','C']})+'`.','',
        '## Stresy najlepsich pozorovanych politik','',
        '| Politika | Zakladny CAGR | 2x naklady | +1 realizovatelny bar | Bez najlepsieho dna | Bez top 3 obchodov | Koncentracia aktivum / obchod | Susedia |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in [result['B_observed_best_robust'],result['C_observed_aggressive_pareto']]:
        if name:
            m=next(p['oos'] for p in result['policies'] if p['id']==name)
            lines.append('| '+name+' | '+' | '.join(f'{100*m[k]:.2f}%' for k in ['cagr','double_cost_cagr','delayed_entry_cagr','without_best_day_cagr','without_top_three_trades_cagr'])+f' | {100*m["asset_log_growth_share"]:.1f}% / {100*m["trade_log_growth_share"]:.1f}% | {m["parameter_stability"]*6:.0f}/6 |')
    lines+=['','## Rozsah zaveru','',
        'Krivky obsahuju 6 chronologickych OOS foldov od 2021 do 2026 (posledny je neuplny). Parametre kazdeho roka sa volia z predchadzajuceho validation roka cez Pareto a vopred urcenu selection funkciu. Pri nulovom platnom vybere sa drzi CASH. Indikatory mozu pouzit iba starsie data; fill je najskor D+2 open.',
        'MDD v tabulke zahrna intradenne OHLC eventy. Spodny panel equity grafu ukazuje denny close DD; jeho minimum preto moze byt mensie nez tabulkovy event DD.',
        'Rozsirene audity sa realne vykonali pre vsetkych 18 politik, aj pod 150 %. Subor expanded_audits.json rozlisuje prejdene price-causality/lineage kontroly od chybajucich historickych venue/PIT-universe dokazov.',
        'Funding je konzervativny proxy debit 12 % rocne z celeho opening notionalu, poplatok 4,5 bp a sklz 10 bp na kazdu zobchodovanu stranu. Nie su to historicke Hyperliquid fills/funding. Preto sa vysledok nemoze vydavat za vykonatelny venue-specific dokaz.',
        'Universe je pevnych 12 existujucich minci; 252-bar admission riesi dostupnost dat, nie survivorship delistovanych aktiv. Historicke data uz boli pouzite v predoslom vyskumne.',
        'Tabulka je pozorovana hranica tohto zmrazeneho priestoru a predpokladov, nie globalna maximalna dosiahnutelnost. Vyssia expozicia sa neposudzuje ako nova zasluha signalov; jej cenu vidno v DD, nakladoch a stresoch.',
        'Nepouzite historicke sealed data neboli predstierane. Forward-sealed paper plan je pripraveny pre 2026-09-27 az 2027-09-26; nic sa neposiela na burzu.','',
        '## Reprodukcia','',
        '```powershell','python -m pip install -r research/causal_search_20260926/requirements.txt',
        'python -m unittest discover -s research/causal_search_20260926 -p "test_*.py" -v',
        'python research/causal_search_20260926/run.py --out scratch/reproduction --cache scratch/reproduction_cache',
        'python research/causal_search_20260926/render.py',
        'python research/causal_search_20260926/paper.py --init',
        'python research/causal_search_20260926/paper.py --prices-dir path/to/new_daily_bars','```','',
        'inputs.zip a pre_registration.json su commitnute. Reprodukcia nepotrebuje ine worktree, siet ani produkcne outputs. --init nevytvori nove nominacie, ak forward seal uz existuje; overi jeho hashe.']
    (HERE/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')


if __name__=='__main__':main()
