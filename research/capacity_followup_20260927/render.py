"""Report saved results; no strategy selection from outer results."""
import io,json,sys,zipfile
import numpy as np
import pandas as pd
import evaluate as ev
from ledger_archive import Evidence
from common import HERE,SPEC,write,cid

def read(name):return json.loads((HERE/name).read_text())
def pct(x):return '—' if x is None else f'{100*x:.2f}%'
def num(x):return '—' if x is None else f'{x:.2f}'
def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(str(x) for x in r)+' |' for r in rows)+'\n'
def rules(c):
    if c is None:return 'Žiadny spôsobilý kandidát.'
    return f"{'Priemer 30/90/180/365d' if c['blend'] else str(c['lookback'])+'d'} momentum; {'delené vol60' if c['vol_adjusted'] else 'surové poradie'}; {'absolute+relative (momentum>0)' if c['absolute'] else 'relative-only'}; top {c['top_k']}; {'inverse-vol60' if c['top_k']>1 else '100% do víťaza'}; {c['cadence']}."

def main():
    agg=read('results/aggregate.json');folds=read('results/outer_folds.json');dev=read('results/development.json');nei=read('results/neighbors.json');final=read('results/finalists_frozen.json');ai=read('results/deepseek_summary.json');pit=read('pit_audit.json');pg=read('perpetual_data_gate.json');receipt=read('results/run_completed.json');decisions=[];flat=[]
    ns=[]
    for (arm,origin,parent),group in pd.DataFrame(nei).groupby(['arm','origin','parent_id']):
        rows=group.to_dict('records');valid=[r for r in rows if r['status']=='VALID'];good=[r for r in valid if r.get('cagr',-1)>0 and r.get('mdd',1)<=.35];p=next(r for r in dev if r['arm']==arm and r['origin']==origin and r['candidate_id']==parent);median=float(np.median([r['cagr'] for r in valid])) if valid else None
        passed=len(good)/len(rows)>=.75 and p.get('cagr',-1)>0 and median is not None and median>=.75*p['cagr']
        ns.append(dict(arm=arm,origin=int(origin),parent_id=parent,total=len(rows),executable=len(valid),positive_low_dd=len(good),median_cagr=median,passed=passed))
    write(HERE/'results/neighbor_summary.json',ns)
    for a in agg:
        nominal=a.get('nominal');row=dict(nominal or {});row.update(label=a['label'],capital=a['capital'],status=a['status']);row['double_cost_cagr']=(a.get('double') or {}).get('cagr');row['delayed_cagr']=(a.get('delayed') or {}).get('cagr');bench=next(b for b in agg if b['label']=='BTC_SMA200' and b['capital']==a['capital'])
        comparison=ev.benchmark_gate(dict(nominal or {},status=a['status']),dict(bench.get('nominal') or {},status=bench['status']),outer=True);row['benchmark_pass']=comparison['passed'];row['benchmark_comparison']=comparison
        if a['label'].startswith('B_') and not a['label'].startswith('panel'):
            arm=a['label'][2:];neighbor_pass=all(n['passed'] for n in ns if n['arm']==arm and n['origin'] in SPEC['stress']['folds'])
        else:neighbor_pass=None
        t=SPEC['targets'];gates=dict(execution=a['status']=='VALID',benchmark=comparison['passed'],cagr=row.get('cagr',-1)>=t['cagr_min'],mdd=row.get('mdd',1)<=t['mdd_max'],sharpe=row.get('sharpe',-1)>=t['sharpe_min'],calmar=row.get('calmar',-1)>=t['calmar_min'],folds=row.get('profitable_folds',0)>=3,double_cost=(row.get('double_cost_cagr') or -1)>=t['double_cost_cagr_min'],delayed=(row.get('delayed_cagr') or -1)>0,no_best_day=row.get('without_best_day',-1)>=t['without_best_day_min'],no_top3=row.get('without_three_trades',-1)>=t['without_top3_min'],asset_concentration=row.get('asset_concentration') is not None and row['asset_concentration']<=t['max_asset_log_share'],trade_concentration=row.get('trade_concentration') is not None and row['trade_concentration']<=t['max_trade_log_share'],neighbors=neighbor_pass is True)
        gates['development_feasible']=all(ev.feasible(final['walk_forward_champions'][a['label'][2:]][str(y)]) for y in SPEC['stress']['folds']) if a['label'] in ['B_deterministic','B_deepseek'] else False
        row['decision']='BENCHMARK' if a['label']=='BTC_SMA200' else 'PASS' if all(gates.values()) else 'REJECT';decisions.append(dict(label=a['label'],capital=a['capital'],decision=row['decision'],gates=gates,benchmark=comparison));flat.append(row)
    write(HERE/'decision.json',dict(overall='PASS' if any(d['decision']=='PASS' and d['capital']==100 and d['label'].startswith('B_') for d in decisions) else 'REJECT',rows=decisions,A='ARCHIVED_REJECT',C='ARCHIVED_REJECT_NO_NEW_MUTATION',D=pg['status'],E='NOT_RUN_NO_TWO_INDEPENDENT_QUALIFIED_FAMILIES',production_winner=False))
    write(HERE/'results/common_table.json',flat);pd.DataFrame(flat).drop(columns=['asset_log_growth','asset_dollar_pnl','unfilled_quantity_by_asset','residual_positions','benchmark_comparison'],errors='ignore').to_csv(HERE/'results/common_table.csv',index=False)
    pd.DataFrame(folds).to_csv(HERE/'results/annual_folds.csv',index=False)
    capacities=[]
    for label in sorted({a['label'] for a in agg}):
        rows=[a for a in agg if a['label']==label];safe=[a['capital'] for a in rows if a['status']=='VALID'];faithful=[a['capital'] for a in rows if a['status']=='VALID' and a['stress_tested'] and all(a[s]['entry_fill_ratio']>=.95 for s in ['nominal','double','delayed'])]
        capacities.append(dict(label=label,max_execution_safe_tested_usd=max(safe) if safe else None,max_faithful_stress_tested_usd=max(faithful) if faithful else None,scope='Lower bound on tested grid; not interpolated maximum; Binance research assumptions, not Hyperliquid live capacity'))
    write(HERE/'results/capacity_summary.json',capacities)
    primary=[r for r in flat if r['capital']==100];mapping={cid(c):c for c in __import__('designer').panel()}
    aliases={'BTC_SMA200':'BTC SMA200','B_deterministic':'B WF deterministic','B_deepseek':'B WF DeepSeek'}
    for i,c in enumerate(__import__('designer').panel(),1):aliases['panel_'+cid(c)]=f'P{i:02d}'
    h=['$100 / stratégia','CAGR','MDD','Sharpe','Calmar','turn/rok','náklady/rok','obchody','hold d','+foldy','najhorší','2× nákl.','+bar','bez best day','bez top3','stav']
    rows=[]
    for r in primary:
        rows.append([aliases[r['label']],pct(r.get('cagr')),pct(r.get('mdd')),num(r.get('sharpe')),num(r.get('calmar')),num(r.get('turnover')),pct(r.get('costs')),r.get('trades','—'),num(r.get('median_holding')),str(r.get('profitable_folds','—'))+'/4',pct(r.get('worst_fold')),pct(r.get('double_cost_cagr')),pct(r.get('delayed_cagr')),pct(r.get('without_best_day')),pct(r.get('without_three_trades')),r['decision']+' / '+r['status']])
    lines=['# TrendAtlas — zmrazený capacity follow-up','',f"Zdrojový commit `{SPEC['source_commit']}`. Nový experiment, pôvodné výsledky nemení. Primárny kapitál **100 USD**. Rozhodnutie: **{read('decision.json')['overall']}**. Žiadny merge, deploy, Pi zásah ani živý obchod.",'', '## Spoločná tabuľka', '',table(h,rows),'Náklady sú súčet poplatkov a sklzu ako anualizovaný súčet podielov z aktuálneho NAV. Spot funding = 0. Turnover je ročný jednosmerný zobchodovaný notional/NAV, obchody sú úplné asset epizódy od nuly do nuly. MDD je konzervatívny OHLC portfóliový drawdown; Sharpe z denných výnosov. Bez top3 odoberá tri najväčšie úplné epizódy podľa reconciliovanej log atribúcie; nejde o nový simulovaný rebalancing. „—“ znamená chýbajúci úplný bezpečne uzatvorený replay, nikdy nulový výnos.','', 'Všetkých 135 kombinácií stratégie/kapitálu obsahuje `results/common_table.csv`; každý spustený ročný fold a jeho dôvod zlyhania je v `results/annual_folds.csv`. Po zlyhaní compounding reťazca pokračujú ďalšie roky ako samostatné diagnostiky s pôvodným kapitálom a nevstupujú do spoločného CAGR.','', '## Rodiny','', '- A: pôvodný REJECT archivovaný; žiadny nový výpočet ani mutácia.','- B: nová kapacitná realizácia, 24 vopred určených variantov a dva rovnako rozpočtované walk-forward evolučné postupy.','- C: ARCHIVED_REJECT podľa predchádzajúceho experimentu; žiadna ďalšia optimalizácia.','- D: NOT_RUN. Verejné venue trade/mark/funding dáta stiahnuté a skontrolované, ale historický risk kontrakt nie je kompletný.','- E: NOT_RUN. Nie sú dve nezávisle kvalifikované rodiny B/D; dva varianty B sa nepreznačujú na dve rodiny.','', '## Presné spoločné pravidlá a PIT identita','',f"Archívny census zahŕňa {pit['raw_symbols']} historických USDT symbolov; {pit['instrument_epochs']} identít po rozdelení ticker reuse. Do intraday rámca vstúpilo {pit['intraday_instruments']} identít. Denný rolling30 priemer quote volume ≥10 mil. USD, aspoň365 pozorovaných denných barov danej identity, top10 likvidita. Žiadny dnešný survivor zoznam. Nové identity po redenominácii začínajú vlastný warmup; ceny ani výnosy sa nespájajú.",'','Signalizácia po uzavretom UTC dni, explicitná publikačná latencia60s. Najskorší 4h open je nasledujúci deň04:00 (lag2), stress08:00 (lag3). Weekly = nedeľný close; monthly = kalendárny month-end. Strata PIT eligibility alebo povinného kladného momentum generuje výstup, náhrada až pri plánovanom rozhodnutí. Volatilita je60d annualizovaná, floor0,1. Chýbajúci člen topK necháva svoj podiel v CASH. BTC benchmark: close>SMA200 long, inak CASH, identický execution kontrakt.','', 'Objednávka má fixné množstvo, 0,1% posledného publikovaného 4h quote-volume na symbol/bar, realizovaný vlastný open ±10bp, fee10bp za fill. Vstup TTL6 barov, exit18; sell pred buy, spoločný cash budget. Čiastočný fill eviduje množstvo, cenu a zvyšok. Entry residual sa zruší, exit residual nikdy fiktívne neuzavrie. Ročný výstup je vopred plánovaný18 barov pred koncom, stress o bar neskôr.','', 'Minimálny notional10 USD a zostatok >0,01 USD pri uzatvorení sú vopred zmrazené konzervatívne predpoklady; pri100 USD môžu dust zostatky blokovať bezpečne uzatvorený výkon. Lot/tick presnosť a kompletné historické admin oznámenia nie sú certifikované. Toto je model kapacity Binance spot, nie potvrdená kapacita živého Hyperliquid účtu.','', '## Vopred zmrazené komponentové porovnania','']
    lines.append(table(['ID','Konfigurácia','CAGR100','MDD100','Cost100'],[[aliases['panel_'+key],rules(c),pct(next(r for r in primary if r['label']=='panel_'+key).get('cagr')),pct(next(r for r in primary if r['label']=='panel_'+key).get('mdd')),pct(next(r for r in primary if r['label']=='panel_'+key).get('costs'))] for key,c in mapping.items()]))
    lines += ['Každý pár s odlišným jediným parametrom je ablation v pevnom90d paneli. Nevyberá sa nový víťaz podľa OOS panelu. Kvantitatívne párové rozdiely sú v `results/ablations.json`.','', '## Finalisti a Pareto','']
    pareto=[]
    for arm,slots in final['finalists'].items():
        lines += [f'### {arm}','']
        for slot,r in slots.items():
            lines.append(f"- {slot}: "+('žiadny spôsobilý kandidát.' if r is None else f"`{r['candidate_id']}` — {rules(r['candidate'])} Development2025 CAGR {pct(r.get('cagr'))}, MDD {pct(r.get('mdd'))}, Sharpe {num(r.get('sharpe'))}; benchmark {'PASS' if r.get('benchmark_pass') else 'REJECT'}, execution {r['status']}."))
        for origin in SPEC['evolution']['origins']:
            rr=[r for r in dev if r['arm']==arm and r['origin']==origin]
            for rank,front in enumerate(ev.fronts(rr)):
                for r in front:pareto.append(dict(r,pareto_rank=rank))
        lines.append('')
    write(HERE/'results/pareto_front.json',pareto);pd.DataFrame(pareto).to_csv(HERE/'results/pareto_front.csv',index=False)
    lines += ['Robustný/agresívny sú označenia predom určených development výberov, nie certifikovaní víťazi. Ich pravidlá na forward sú zmrazené pred outer replay. Žiadne nové forward/sealed dáta neboli otvorené. Roky2022–2025 sú historické chronologické outer foldy; rok2021 development prvého originu. Predchádzajúci rok neskoršieho originu slúži ako jeho development; API nedostáva outer výsledky ani kompletnú OOS tabuľku.','', '## Kapacita a náklady','']
    lines.append(table(['Postup','max bezpečný testovaný USD','max ≥95% fill aj stres USD'],[[aliases.get(r['label'],r['label']),r['max_execution_safe_tested_usd'],r['max_faithful_stress_tested_usd']] for r in capacities if not r['label'].startswith('panel')]))
    lines.append(table(['Postup','kapitál','CAGR','MDD','fill%','partials','feeUSD','slipUSD','fundUSD','status'],[[aliases[r['label']],r['capital'],pct(r.get('cagr')),pct(r.get('mdd')),pct(r.get('entry_fill_ratio')),r.get('partial_fills','—'),num(r.get('fee_usd')),num(r.get('slippage_usd')),num(r.get('funding_usd')),r['status']] for r in flat if not r['label'].startswith('panel')]))
    lines += ['Maximum znamená najvyšší bod z mriežky100/1k/10k/100k/1m, bez extrapolácie. Kapacita sa posudzuje nezávisle od dosiahnutia alpha cieľa. Panel má cost/delay stres iba pre100 USD; jeho väčšie kapitály nie sú vydávané za plne stresovo certifikované.','', '## Ročné OOS foldy','']
    lines.append(table(['Postup','rok','CAGR','MDD','Sharpe','cost/rok','status'],[[aliases[r['label']],r['year'],pct(r.get('cagr')),pct(r.get('mdd')),num(r.get('sharpe')),pct(r.get('costs')),r['status']] for r in folds if r['initial_capital']==100 and r['stage']=='nominal' and not r['label'].startswith('panel')]))
    lines += ['## Susedné parametre a koncentrácia','',table(['arm','origin','parent','pozitívne/DD≤35','medián CAGR','PASS'],[[n['arm'],n['origin'],n['parent_id'],f"{n['positive_low_dd']}/{n['total']}",pct(n['median_cagr']),n['passed']] for n in ns]),'Čisté log príspevky aj podiel z hrubých kladných príspevkov podľa aktíva/obchodu sú v spoločnej tabuľke JSON. Kompletná dollar PnL a fee/slippage atribúcia je v ledgeroch; čistý podiel pri celkovej strate je nedefinovaný, nie vynulovaný.','', '## DeepSeek — skutočné volania','',f"API volania: **{ai['calls']}**; odpovede s usage: **{ai['successful_responses']}**; tokeny: **{ai['total_tokens']}**; tarifný odhad ceny **${ai['estimated_usd']:.6f}**, rezervovaný konzervatívny horný rozpočet **${ai['reserved_upper_usd']:.6f}**. Prijaté návrhy: {ai['accepted_proposals']}, odmietnuté: {ai['rejected_proposals']}. Model `{SPEC['deepseek']['model']}`, thinking disabled, maximálne15 volaní/2000 output tokenov a1 USD. Cena je odhad podľa času a usage, nie faktúra.",'','Každá vetva má110 development kandidátov (5originov×22), populáciu10,6preživších a4mutácie,4generácie. Neúspešné alebo duplicitné návrhy nahradí deterministická mutácia; žiadny dodatočný evaluation budget. Raw JSON odpovede, whitelist payload, prijaté/odmietnuté návrhy a dôvody sú v `results/designer_events.jsonl`. Kľúč ani autorizácia sa neukladajú. [Oficiálny cenník](https://api-docs.deepseek.com/quick_start/pricing).','']
    lines.append(table(['origin','det dev CAGR','AI dev CAGR','det OOS CAGR','AI OOS CAGR'],[[y,pct(final['walk_forward_champions']['deterministic'][str(y)].get('cagr')),pct(final['walk_forward_champions']['deepseek'][str(y)].get('cagr')),pct(next((r.get('cagr') for r in folds if r['label']=='B_deterministic' and r['initial_capital']==100 and r['stage']=='nominal' and r['year']==y),None)),pct(next((r.get('cagr') for r in folds if r['label']=='B_deepseek' and r['initial_capital']==100 and r['stage']=='nominal' and r['year']==y),None))] for y in SPEC['evolution']['origins']]))
    lines += ['Akceptovaný návrh znamená schema-valid nový kandidát, nie úspešnú alpha. Rozdiel dvoch vetiev v jednom pevnom seede nie je dôkaz všeobecnej prevahy AI.','', '## Rodina D: presná dátová medzera','', 'Pre BTCUSDT,ETHUSDT,BNBUSDT,XRPUSDT,SOLUSDT chýba úplná verzovaná história maintenance margin brackets, liquidation/insurance pravidiel a sadzieb, certifikovaných listing/delisting dátumov a historických account fee tier/symbol filtrov pre **2021-01-01 00:00 až2026-01-01 00:00 UTC**. Každý chýbajúci4h price alebo8h funding interval je osobitne vypísaný v `perpetual_data_gate.json`. Verejné cenové archívy tieto risk podklady nenahrádzajú. Dátový gate sa reálne spustil; štyri stratégie sa nevydávajú za odsimulované.','',table(['variant','stav','pravidlá'],[[r['name'],r['status'],r['rules']] for r in pg['recipes']]),'[Binance bracket API](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Notional-and-Leverage-Brackets) je autentifikovaný aktuálny endpoint, nie verzovaný historický zdroj. Nebol zavolaný a exchange/account kľúče sa nečítali. [Historická zmena margin tierov](https://www.binance.com/en/support/announcement/detail/86cf9aa472574b8cb2e05bb751c2a9a6) dokladá, prečo aktuálna tabuľka nestačí.','', '## Reprodukcia a audit','',f"Výpočet: {receipt['development_evaluations']} development, {receipt['neighbor_evaluations']} neighbor a {receipt['outer_fold_replays']} ročných outer replayov; {receipt['seconds']:.1f}s runtime. Príkazy v README, FILES READ/SOURCE OF TRUTH/root cause/contract impact/git add v AUDIT.md. CenaAPI sa pri offline reprodukcii neúčtuje; použijú sa uložené validované návrhy.",'', '![Equity](equity.png)','']
    ablations=[]
    configs=list(mapping.items())
    for i,(aid,a) in enumerate(configs):
        for bid,b in configs[i+1:]:
            diff=[k for k in a if a[k]!=b[k]]
            if len(diff)!=1:continue
            for capital in SPEC['accounts_usd']:
                ar=next(r for r in flat if r['label']=='panel_'+aid and r['capital']==capital);br=next(r for r in flat if r['label']=='panel_'+bid and r['capital']==capital)
                ablations.append(dict(from_id=aid,to_id=bid,component=diff[0],from_value=a[diff[0]],to_value=b[diff[0]],capital=capital,from_status=ar['status'],to_status=br['status'],delta={k:br[k]-ar[k] for k in ['cagr','mdd','sharpe','calmar','turnover','costs'] if k in ar and k in br}))
    write(HERE/'results/ablations.json',ablations)
    lines[4:4]=[
        '**B je REJECT aj v prípadoch, ktoré kapacita dovolí dokončiť.** Pri primárnych100 USD prejde nominálny replay iba P05 a P07; P07 zlyhá pri2× nákladoch. P05 má3,93% CAGR,92,33% MDD a po odstránení troch najlepších obchodov −40,75% CAGR. Ani jediný úplný nominálny variant z pevného panelu pri10 000 USD neprekonal benchmark gate; najvyšší CAGR je5,26% a najnižší MDD stále80,67%. Tieto väčšie účty sú diagnostika kapacity, nemenia primárny100 USD track.',
        '',
        '**Zlyhania vykonania majú konkrétne príčiny.** Deterministický WF pri100 USD zostal19.6.2023 s RNDR zostatkom9,35 USD pod zmrazeným10 USD minimom; pri1 000 USD obdobne PEOPLE9,69 USD v auguste2024. Pri10k/100k USD sa uzatvorí, ale dosahuje približne −36% CAGR a96% MDD. DeepSeek WF držal pôvodnú LUNA pri májovom zastavení2022, kde ďalší realistický fill chýba, a preto nemá úplný bezpečný4-ročný výsledok pri žiadnom testovanom kapitáli. Nejde o tvrdenie, že živý Hyperliquid účet má tieto spot minimum-notional pravidlá.',
        '',
        '**Komponentové výsledky sú podmienené dokončiteľnými párovými replaymi.** Pri10k USD volatility-adjusted ranking zlepšil CAGR vo všetkých7 dostupných pároch o4,30–20,93 percentuálneho bodu;6/7 párov znížilo MDD. Stále nevytvoril kvalifikovanú stratégiu. Monthly cadence znížila ročné náklady vo všetkých6 porovnateľných pároch o3,60–4,40 bodu, ale výnos a drawdown sa zlepšovali len v časti párov. Top3 oproti top1 znížilo MDD vo všetkých4 dokončiteľných pároch, výnos zlepšilo v2/4. Absolute filter v2 priamo porovnateľných pároch zhoršil CAGR aj MDD; neúplné ďalšie páry neumožňujú zovšeobecniť tento smer. Neuzatvoriteľné varianty zostávajú explicitne zlyhané, nie vynechané zo zoznamu.',
        '',
        '**Najlepší zmrazený robustný slot podľa development drawdownu** je deterministický `B_2c32e4a6ac0b`:30d momentum/vol60, absolute+relative, top3 inverse-vol, monthly. Má však development MDD41,85%, takže zostáva REJECT. **Agresívny slot** oboch vetiev je `B_41999f301120`:90d momentum/vol60, absolute+relative, jeden víťaz, weekly; development CAGR93,77%, MDD65,55%, REJECT. Nejde o nasaditeľnú current_strategy_v2 ani o víťazov vybraných z OOS.',
        '',
        'Kauzálny audit overil65 719 fillov,43 633 objednávok, identické signály všetkých120 povolených konfigurácií na dvoch skrátených históriách a skutočne nulové koncové pozície všetkých úspešných replayov.18 samostatne zopakovaných reálnych replayov súhlasí. Dollar PnL, náklady a koncentrácia turnoveru podľa aktíva aj epizódy sú v `results/concentration.json`. Prvý technicky neúspešný pokus je zachovaný v `attempts/`; žiadny parameter nebol upravený podľa výsledkov.',
        ''
    ]
    (HERE/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    try:import matplotlib
    except ImportError:
        sys.path.append('C:/Users/benda/AppData/Local/Temp/ta-archeology-plot-deps');import matplotlib
    matplotlib.use('Agg');import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(12,8),constrained_layout=True)
    with Evidence() as z:
        for label in ['BTC_SMA200','B_deterministic','B_deepseek']:
            name=f'{label}/100/nominal_equity.csv'
            if name in z.namelist():
                x=pd.read_csv(io.BytesIO(z.read(name)),index_col=0,parse_dates=True).equity;axes[0].plot(x.index,x,label=aliases[label]);axes[1].plot(x.index,x/x.cummax()-1,label=aliases[label])
        for a in primary:
            if a['label'].startswith('panel'):
                name=f"{a['label']}/100/nominal_equity.csv"
                if name in z.namelist():
                    x=pd.read_csv(io.BytesIO(z.read(name)),index_col=0,parse_dates=True).equity;axes[0].plot(x.index,x,alpha=.65,lw=.9,label=aliases[a['label']]+' nominal');axes[1].plot(x.index,x/x.cummax()-1,alpha=.65,lw=.9,label=aliases[a['label']]+' nominal')
    axes[0].set_title('100 USD | OOS net equity | BTC SMA200 and nominal panel replays');axes[0].set_yscale('log');axes[0].set_ylabel('NAV / initial NAV');axes[0].legend();axes[1].set_title('Close-to-close drawdown (table uses conservative intrabar MDD)');axes[1].set_ylabel('Drawdown');axes[1].legend()
    for ax in axes:ax.grid(alpha=.2)
    fig.savefig(HERE/'equity.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(2,4,figsize=(16,7),constrained_layout=True)
    with Evidence() as z:
        for i,label in enumerate(['B_deterministic','B_deepseek']):
            for j,year in enumerate(SPEC['stress']['folds']):
                meta=next(r for r in folds if r['label']==label and r['year']==year and r['initial_capital']==100 and r['stage']=='nominal');stage='nominal' if meta['status']=='VALID' else 'nominal_partial';name=f'{label}/100/{year}/{stage}/bars.csv'
                x=pd.read_csv(io.BytesIO(z.read(name)),index_col=0,parse_dates=True).equity;ax=axes[i,j];ax.plot(x.index,x,label='actual ledger through last mark');ax.axhline(1,color='grey',lw=.7);ax.set_title(f"{aliases[label]} | {year}\n{meta['status']}",fontsize=10);ax.tick_params(axis='x',rotation=30);ax.grid(alpha=.2)
                if meta['status']!='VALID':ax.plot(x.index[-1],x.iloc[-1],'rx');ax.text(.02,.03,'Truncated: unresolved position; no fabricated exit',transform=ax.transAxes,fontsize=7)
                ax.set_ylabel('NAV / fold starting NAV')
    fig.suptitle('Primary 100 USD track | separate annual folds; failed chains are not concatenated')
    fig.savefig(HERE/'fold_equity.png',dpi=150);plt.close(fig)
    with (HERE/'REPORT.md').open('a',encoding='utf-8') as f:f.write('\n![Annual fold equity, including truncated failures](fold_equity.png)\n')
    print('Report rendered:',read('decision.json')['overall'])

if __name__=='__main__':main()
