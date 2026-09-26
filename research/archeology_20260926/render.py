"""Render only this run's fresh ledger results and paired ablation evidence."""
from pathlib import Path
import io, json, zipfile
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PAIRS=[('BTC/trend permission','A_selector','B_permission'),('soft governance only','B_permission','C1_soft_governance_only'),('reference governor before pruning','C1_soft_governance_only','C_soft_filters'),('pruning combined','C_soft_filters','D_pruning'),('core LTC/SOL pruning','C_soft_filters','S_NEO_only_not_pruned'),('NEO pruning only','S_NEO_only_not_pruned','D_pruning'),('1.25x exposure','D_pruning','E_exposure_125'),('BTC persistence bridge','E_exposure_125','E_persistence_bridge'),('ETF early entry','E_persistence_bridge','F_ETF_no_cooldown'),('15-day cooldown','F_ETF_no_cooldown','G_current'),('replace selector','G_current','H_replace_selector'),('slow rotation + hysteresis','G_current','I_slow_hysteresis')]
def block_band(a,b):
    delta=np.log1p(b)-np.log1p(a);n=len(delta);block=min(30,n);rng=np.random.default_rng(20260926)
    starts=rng.integers(0,n-block+1,size=(2000,int(np.ceil(n/block))))
    idx=(starts[:,:,None]+np.arange(block)).reshape(2000,-1)[:,:n]
    bands=np.quantile(delta[idx].mean(axis=1)*365.25,[.025,.975])
    return bands.tolist()
def main():
    f=pd.read_csv(HERE/'results/comparison.csv').set_index('strategy');stress=pd.read_csv(HERE/'feedback/comparison.csv').set_index('strategy')
    post=pd.read_csv(HERE/'results/etf_window.csv').set_index('strategy');folds=pd.read_csv(HERE/'results/folds.csv')
    z=zipfile.ZipFile(HERE/'results/ledgers.zip')
    def daily(n):return pd.read_csv(io.BytesIO(z.read(n+'/daily.csv')),index_col=0,parse_dates=True)
    rows=[]
    for label,a,b in PAIRS:
        da,db=daily(a),daily(b);lo,hi=block_band(da.net_return.to_numpy(),db.net_return.to_numpy())
        rows.append(dict(layer=label,parent=a,child=b,delta_cagr_pp=(f.loc[b,'cagr']-f.loc[a,'cagr'])*100,delta_mdd_pp=(f.loc[b,'mdd']-f.loc[a,'mdd'])*100,delta_turnover=f.loc[b,'turnover']-f.loc[a,'turnover'],delta_cost_pp=(f.loc[b,'costs']-f.loc[a,'costs'])*100,annual_log_growth_difference_low=lo,annual_log_growth_difference_high=hi))
    ab=pd.DataFrame(rows);ab.to_csv(HERE/'ablation_deltas.csv',index=False,float_format='%.12g')
    current=f.loc['G_current'];h=f.loc['H_replace_selector'];slow=f.loc['I_slow_hysteresis']
    def feasible(r):return r.cagr>0 and r.mdd<=.35 and r.double_cost_cagr>0 and r.profitable_folds/r.fold_count>=.75
    if feasible(current):verdict='KEEP_AND_TUNE_CURRENT'
    elif any(feasible(r) and r.cagr>current.cagr and r.mdd<current.mdd and r.double_cost_cagr>current.double_cost_cagr for r in [h,slow]):verdict='REPLACE_SELECTOR_KEEP_INFRASTRUCTURE'
    else:verdict='REPLACE_STRATEGY'
    (HERE/'decision.json').write_text(json.dumps(dict(verdict=verdict,scope='research architecture recommendation only',deployment_allowed=False,validated_replacement=False,reason='Current and both selector-only replacements fail predeclared drawdown/fold robustness criteria.',data_pit_certification='UNVERIFIED',sealed_evidence=False),indent=2)+'\n')
    lines=['# TrendAtlas — strategy archaeology a spoločný causal replay','',f'**Verdikt: {verdict}.** Súčasná stratégia ani obidve výmeny selectora neprešli vopred určenými limitmi drawdownu a ziskových foldov. Toto je verdikt pre ďalší výskum architektúry; žiadna otestovaná náhrada tu nie je potvrdená na nasadenie.','',
      f'Súčasná stratégia: CAGR **{current.cagr*100:.2f}%**, intradenný MDD **−{current.mdd*100:.2f}%**, Sharpe **{current.sharpe:.2f}**, ziskové foldy **{int(current.profitable_folds)}/{int(current.fold_count)}**. Pri 2× nákladoch a rovnakých signáloch CAGR **{current.double_cost_cagr*100:.2f}%**, po vynechaní troch najlepších celých obchodov **{current.without_three_trades*100:.2f}%**.','',
      'Všetky výsledky boli vypočítané odznova z kódu a zmrazených OHLC/ETF/makro vstupov. Staré paper returns, snapshot equity ani uložené súhrnné metriky nie sú vstupom do rozhodnutí ani PnL.','',
      '## Rozsah a presnosť záveru','',
      'Spoločné testovanie: **1. 1. 2021 – 6. 4. 2026**, päť celých ročných foldov a čiastočný rok 2026. Rovnaké hranice, účtované výstupy na konci roka, nulový úrok CASH, žiadny nový parameter search. Train/validation hranice sú v contract.json; zdrojové online týždenné governance používajú iba už dokončenú minulosť. Ide o chronologické výpočtové OOS na už skúmanej histórii, nie o nový nedotknutý holdout.','',
      'Spoločný panel má 19 aktív a prijatie až po 260 dokončených kladných OHLCV pozorovaniach. BCH/ICP/XTZ končia 6. 4. 2026, preto celý spoločný test končí v tento deň. Modelové masky univerza sú explicitné experimentálne vrstvy. Kompletný historický zoznam delistovaných coinov, makro vintages a pôvodné časy publikácie/revízie ETF chýbajú. **Plná point-in-time platnosť historického trhu zostáva NEOVERENÁ.** Prefix/future-mutation testy overujú kauzalitu výpočtu na zachytených dátach, túto medzeru neodstraňujú.','',
      'Plnenie: signál z close D, dostupnosť predpokladaná až D+1 00:00:01 UTC, preto fill pri D+2 open; 4.5 bp fee, 10 bp nepriaznivý sklz na každom fillovanom notionali, 12% p.a. funding debit na celom držanom notionali. Spot OHLC sú cenový proxy pre lineárnu expozíciu; nejde o overené historické perp/listing/order-book/funding dáta konkrétnej burzy. Margin crossing a náklady likvidácie sa simulujú. Všetky modely vrátane vnútorných shadow portfólií používajú ten istý engine. Denné sizing/rebalancing konvencie sú harmonizované, nie prevzaté z chybných paper účtovaní.','',
      '![Spoločný replay modelového kapitálu](equity.png)','', '## Jedna spoločná tabuľka','',
      'CAGR, MDD, náklady a stresy sú v %. MDD je záporná strata z konzervatívnej intradennej OHLC cesty, nie iba close-to-close. Turnover je × NAV/rok vrátane oboch rotačných strán. Náklady sú ročný súčet debitov/pre-charge NAV, nie zložený rozdiel CAGR. Obchod je úplná rovnaká aktívová epizóda; resizing ju nedelí. Držanie je v dňoch. Ziskový fold má výnos striktne >0. Tri posledné stresové stĺpce uvádzajú CAGR.','',
      '| Stratégia / ablation | CAGR | MDD | Sharpe | Calmar | Turnover | Náklady | Obchody | Medián držania | Ziskové foldy | Najhorší fold | 2× náklady | Bez naj dňa | Bez top3 obchodov |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in f.iterrows():
        lines.append(f'| {n} | {r.cagr*100:.2f} | {-r.mdd*100:.2f} | {r.sharpe:.2f} | {r.calmar:.2f} | {r.turnover:.2f} | {r.costs*100:.2f} | {int(r.trades)} | {r.median_holding:.1f} | {int(r.profitable_folds)}/{int(r.fold_count)} | {r.worst_fold*100:.2f} | {r.double_cost_cagr*100:.2f} | {r.without_best_day*100:.2f} | {r.without_three_trades*100:.2f} |')
    lines+=['','A=phase61 core; G=current; E=secondary fallback; E_persistence_bridge=softer fallback. Tieto aliasy nie sú nezávislé objavy. Phase62 používa source-named default; každá Phase2 rodina má jednu vopred určenú konfiguráciu. Tabuľka nie je grid search a nevyhodnocuje všetky historické parametrové varianty. S_ sú presne pomenované citlivosti, nie nové optimalizované stratégie.','',
      '## Ktoré vrstvy pomáhajú','',
      '| Pridaná / vymenená vrstva | Δ CAGR pp | Δ MDD pp (kladné = horšie) | Δ turnover/rok | Δ náklady pp/rok | 95% pásmo ročného log-growth rozdielu |','|---|---:|---:|---:|---:|---|']
    for r in ab.itertuples():lines.append(f'| {r.layer} | {r.delta_cagr_pp:+.2f} | {r.delta_mdd_pp:+.2f} | {r.delta_turnover:+.2f} | {r.delta_cost_pp:+.2f} | [{r.annual_log_growth_difference_low*100:+.2f}, {r.annual_log_growth_difference_high*100:+.2f}] pp |')
    lines+=['','Rozdiely sú párové path-dependent replay kontrasty, nie sčítateľné kauzálne efekty. Pásma sú 2000 párových moving-block bootstrap replikácií s 30-dňovým blokom a pevným seedom; nejde o nápravu historického výberového skreslenia alebo dôkaz stability mimo tohto obdobia.','',
      f'- **Výnos pochádza najmä zo základnej rotácie:** A má {f.loc["A_selector","cagr"]*100:.2f}% CAGR, ale aj {f.loc["A_selector","mdd"]*100:.2f}% MDD. Nie je to potvrdený bezpečný kandidát.',
      '- **BTC/trend permission:** v tomto reťazci znižuje výnos a aktivitu; samotná kombinácia B neznižuje najhorší intradenný drawdown oproti A. Samostatná historická Phase62 má odlišný, priaznivejší risk/return profil, ale nespĺňa 35% DD limit.',
      '- **Soft filtre:** C1 oproti B nepridávajú výnos ani ochranu najhoršieho DD; širšia referencia pred pruningom (C) zlepšuje výnos aj DD oproti C1. Tento rozdiel nesmie byť pripísaný samotným soft filtrom.',
      '- **Pruning:** spoločné odstránenie LTC/SOL v soft-governance a NEO v referencii zhoršuje hlavný nominálny výsledok. Samostatný NEO kontrast je nulový; z tohto obdobia nemožno pripísať prínos odstráneniu NEO. Pri plnej spätnej väzbe 2× nákladov sa rozdiel môže vytratiť, čo ukazuje nestabilitu výberových vrstiev.',
      '- **Expozícia1.25×:** len malý prírastok CAGR oproti D za vyšší DD a turnover ; 1.5× a dynamický rebrík ďalej zvyšujú riziko. Tail-risk G2 čiastočne zlepšuje rodičov, žiadna kombinácia neposkytuje robustnú náhradu.',
      '- **ETF a cooldown:** v tomto spoločnom prehratí znižujú CAGR. V období od januára 2024 ETF bez cooldownu znižuje MDD o približne 1.40 pp, ale cooldown ho následne zvyšuje približne o 1.54 pp. ETF vrstva pridáva ďalšie obchody; cooldown časť aktivity odoberá, ale odoberá aj výnos. Nejde o dôkaz, že nemôžu pomôcť v inom období, ani o potvrdený prínos v tomto období.',
      f'- **Stačí selector? Nie podľa testov H/I.** H má MDD {h.mdd*100:.2f}%, I {slow.mdd*100:.2f}%; I výrazne znižuje turnover, ale nerieši robustnosť a koncentráciu. Zníženie počtu rotácií samo nestačí.',
      '- **Ktorá vrstva iba pridáva turnover?** Za drahú bez dostatočnej kompenzácie sa tu javí najmä zvýšená expozícia a ETF early-entry; presné delty sú vyššie. Soft governor samotný je prakticky neutrálny až škodlivý. Cooldown turnover nezvyšuje; jeho problémom je stratený výnos.','',
      '## ETF obdobie a nákladová spätná väzba','',
      '| Variant | CAGR od 12. 1. 2024 | MDD od 12. 1. 2024 | Turnover/rok | Obchody | 2× náklady + nové causal rozhodnutia: celý OOS CAGR |','|---|---:|---:|---:|---:|---:|']
    for n in ['E_exposure_125','E_persistence_bridge','F_ETF_no_cooldown','G_current','S_ETF_extra_day','H_replace_selector','I_slow_hysteresis']:
        r=post.loc[n];lines.append(f'| {n} | {r.cagr*100:.2f} | {-r.mdd*100:.2f} | {r.turnover:.2f} | {int(r.trades)} | {stress.loc[n,"cagr"]*100:.2f} |')
    lines+=['','Hlavný 2× stĺpec drží signály fixné a znovu prepočíta fills/NAV. Posledný stĺpec vyššie navyše znovu prepočíta všetky závislé shadow portfóliá/governance/trend permission. Vyšší výsledok pri tejto druhej variante nie je výhodou vyšších poplatkov; znamená, že poplatky menia rozhodnutia závislé od minulého PnL. Výber medzi nimi podľa lepšieho výsledku nie je povolený.','',
      '## Ročné foldy vybraných variantov','',
      '| Variant | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 do 6. 4. |','|---|---:|---:|---:|---:|---:|---:|']
    for n in ['A_selector','phase62_btc_overlay_default','G_current','H_replace_selector','I_slow_hysteresis','phase2_vol_adjusted','phase2_regime_allocation','phase2_slow_hysteresis','phase2_ensemble']:
        row=folds[folds.strategy.eq(n)].set_index('fold').net_return;lines.append('| '+n+' | '+' | '.join(f'{row.loc[y]*100:.2f}%' for y in range(2021,2027))+' |')
    lines+=['','## Rozhodnutie','',
      f'**{verdict}**. Nepokračovať iba ladením aktuálnych prahov a neprezentovať H/I ako vyriešenie stratégie. Zachovať použiteľné dátové/exekučné rozhrania, ale návrh novej stratégie musí vychádzať z čistého asset-resolved účtovania a prejsť nezávislým forward/OOS testom. Žiadna zo štyroch Phase2 reprezentácií nie je týmto výsledkom potvrdená ako produkčná náhrada.','',
      'Voľba2 nevyhrala, preto sa nevytvára ani nenasadzuje current_strategy_v2 z nepreukázaných vrstiev. Produkcia, Pi timery, účet a živé objednávky zostali mimo rozsahu.','',
      'Pravidlá a zdrojová línia: [ARCHAEOLOGY.md](ARCHAEOLOGY.md). Kontrakt: [contract.json](contract.json). Úplné CSV: [comparison.csv](results/comparison.csv). Jednotlivé signály, fillovanie, denné účtovanie a celé obchody sú v [ledgers.zip](results/ledgers.zip). Regresie a limity dokazovania sú v [AUDIT.md](AUDIT.md).','']
    (HERE/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    # Compact chart of fresh, fold-reset equity. Linear labels explicitly show
    # simulated capital rather than a real account.
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,5.5))
    for n,label in [('A_selector','Core rotation'),('phase62_btc_overlay_default','Phase62 BTC overlay'),('G_current','Current'),('H_replace_selector','Selector replacement'),('I_slow_hysteresis','Slow rotation')]:
        d=daily(n);ax.plot(d.index,d.equity,label=label,lw=1.6)
    ax.set(yscale='log',ylabel='Simulated capital (initial = 1, log scale)',title='TrendAtlas: common causal replay, fees + slippage + funding')
    ax.grid(alpha=.2);ax.legend(ncol=2);fig.text(.01,.01,'2021-01-01 to 2026-04-06 | D+2 daily fills | archived cohort / funding proxies | not certified venue or sealed OOS evidence',fontsize=8)
    fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(HERE/'equity.png',dpi=160);plt.close(fig)
    print(verdict)
if __name__=='__main__':main()
