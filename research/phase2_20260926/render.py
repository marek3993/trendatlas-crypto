"""Render completed measurements; never selects or re-runs strategy parameters."""
from common import *
from search import FAMILIES
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LABELS={'cross_sectional':'Cross-sectional momentum','dual_momentum':'Dual momentum','relative_strength':'Weekly/monthly relative strength',
 'breakout':'Breakout / trend following','vol_adjusted':'Volatility-adjusted momentum','ensemble':'Ensemble','regime_allocation':'BTC / altcoin / CASH','slow_hysteresis':'Pomalá rotácia + hysterézia'}
def pct(x):return f'{x*100:.2f} %'
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])

def main():
    out=HERE/'results';diag=HERE/'diagnostics';r=read(out/'results.json');pol={p['id']:p for p in r['policies']};b=read(diag/'metrics.json')
    bench=[v for v in b if v['kind'].startswith('benchmark')];base=[p for p in r['policies'] if p['overlay'] is None]
    feasible=[p for p in base if p['feasible'] and p['oos']['cagr']>0]
    best=max(feasible,key=lambda p:(p['oos']['calmar'],-p['cap'])) if feasible else None
    raw=max(base,key=lambda p:p['oos']['cagr']);robust=[p for p in base if p['mode']=='robust'];closest=min(robust,key=lambda p:p['oos']['max_drawdown'])
    overlay_rows=[]
    for p in r['policies']:
        if not p['overlay']:continue
        baseline=pol[p['partition']+'__all_calmar']['oos'];x=p['oos']
        overlay_rows.append(dict(policy=p['id'],partition=p['partition'],overlay=p['overlay'],base_cagr=baseline['cagr'],cagr=x['cagr'],delta_cagr=x['cagr']-baseline['cagr'],base_dd=baseline['max_drawdown'],max_drawdown=x['max_drawdown'],delta_dd=x['max_drawdown']-baseline['max_drawdown']))
    pd.DataFrame(overlay_rows).to_csv(out/'overlay_deltas.csv',index=False)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    series=[('BTC_SMA200',diag,'BTC SMA200'),('equal_weight',diag,'Equal weight (annual)'),('aggressive_2.5__calmar',diag,'Phase 1 best return'),(best['id'],out,'Phase 2 feasible compromise'),(raw['id'],out,'Phase 2 highest return'),(closest['id'],out,'Phase 2 lowest DD')]
    fig,axes=plt.subplots(2,1,figsize=(13,9),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for name,folder,label in series:
        f=pd.read_csv(folder/f'{name}_equity.csv',parse_dates=['date']);eq=f.equity.to_numpy()
        line=axes[0].plot(f.date,eq,label=label,linewidth=1.8)[0]
        axes[1].plot(f.date,100*(eq/np.maximum.accumulate(np.r_[1,eq])[1:]-1),color=line.get_color(),linewidth=1.5)
    axes[0].set_yscale('log');axes[0].set_ylabel('Net simulated equity (start = 1)');axes[0].legend(ncol=2,fontsize=9)
    axes[0].set_title('Phase 2: chronological walk-forward, 2021-01-01 to 2026-09-25\nSame fees/slippage/funding proxy; annual fold resets; no historical seal',loc='left')
    axes[1].set_ylabel('Daily-close drawdown (%)');axes[1].set_xlabel('UTC date')
    for ax in axes:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(out/'equity_curves.png',dpi=160);fig.savefig(out/'equity_curves.svg');plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,7))
    for mode,color in [('robust','#2673b8'),('aggressive','#e2902d')]:
        subset=[p for p in base if p['mode']==mode]
        ax.scatter([p['oos']['max_drawdown']*100 for p in subset],[p['oos']['cagr']*100 for p in subset],c=color,label=mode,alpha=.7,s=48)
    for v in bench:
        ax.scatter(v['max_drawdown']*100,v['cagr']*100,marker='x',s=80,c='#343434')
        ax.annotate(v['id'],(v['max_drawdown']*100,v['cagr']*100),xytext=(4,5),textcoords='offset points',fontsize=8)
    ax.axvline(25,linestyle=':',color='#2673b8',label='Robust DD cap 25%');ax.axvline(35,linestyle=':',color='#e2902d',label='Absolute DD cap 35%')
    ax.annotate('Observed feasible compromise\n19.01% CAGR / 31.61% DD',(best['oos']['max_drawdown']*100,best['oos']['cagr']*100),xytext=(15,50),textcoords='offset points',arrowprops={'arrowstyle':'->'},fontsize=9)
    ax.set(xlabel='Maximum intrabar event drawdown (%)',ylabel='CAGR (%)',title='All 60 frozen base policies and 6 benchmarks\n150% target is far above every OOS result (not rescaled into this view)')
    ax.grid(alpha=.2);ax.legend(loc='lower left',ncol=2,fontsize=9);fig.tight_layout();fig.savefig(out/'pareto.png',dpi=160);fig.savefig(out/'pareto.svg');plt.close(fig)
    families=[]
    for family in FAMILIES:
        row=[LABELS[family]]
        for part in ['robust_1.25','aggressive_1.25','aggressive_1.5','aggressive_2','aggressive_2.5','aggressive_3']:
            p=pol[part+'__'+family];x=p['oos'];row.append(f"{x['cagr']*100:.2f} / {x['max_drawdown']*100:.2f}"+(' ✓' if p['feasible'] else ''))
        families.append(row)
    stress_ids=[best['id'],raw['id'],closest['id'],r['nominations']['B'],r['nominations']['C']]
    stress=[]
    for name in dict.fromkeys(stress_ids):
        p=pol[name];x=p['oos'];stress.append([name,pct(x['cagr']),pct(x['double_cost_cagr']),pct(x['delayed_entry_cagr']),pct(x['without_best_day_cagr']),pct(x['without_top_three_trades_cagr']),f"{round(x['parameter_stability']*3)}/3"])
    text=f'''# Druhá fáza: výsledky skutočne vykonaného výskumu

Cieľ **150–200 % CAGR neprešiel**. Najlepší pozorovaný Pareto kompromis spĺňajúci absolútny drawdownový strop je **{pct(best['oos']['cagr'])} CAGR / {pct(best['oos']['max_drawdown'])} MDD** pri limite expozície **{best['cap']}×**. Ide o mesačné volatility-adjusted momentum, bez trailing stopu. Nie je to schválený ani sealed víťaz.

V robustnom režime neprešla žiadna aktívna politika limitom MDD 25 %. Najbližšie bolo BTC/altcoin/CASH s {pct(closest['oos']['cagr'])} CAGR a {pct(closest['oos']['max_drawdown'])} MDD. CASH má 0 % výnos aj drawdown. Najvyšší CAGR novej rodiny bol {pct(raw['oos']['cagr'])}, ale s {pct(raw['oos']['max_drawdown'])} drawdownom.

## Benchmarky a pôvodná stratégia

OOS interval: **2021-01-01 až 2026-09-25**, šesť chronologických foldov; rok 2026 je neúplný. Všetky primárne porovnania používajú 4,5 bp fee + 10 bp sklz na každú stranu a 12 % p.a. fundingový debit z celého držaného notionalu. Funding je konzervatívny modelový predpoklad, nie nameraná historická sadzba.

{table(['Benchmark','CAGR','MDD','Sharpe','Calmar','Obrat / rok'],[[v['id'],pct(v['cagr']),pct(v['max_drawdown']),f"{v['sharpe']:.3f}",f"{v['calmar']:.3f}",f"{v['turnover']:.2f}×"] for v in bench])}

BTC_hold drží fixný počet jednotiek medzi ročnými hranicami; nie je denne rebalancovaný. Ročné uzavretie a nový vstup sú kvôli zhodným foldom spoplatnené. Kvôli požiadavke rovnakých nákladov aj tento benchmark platí rovnaký fundingový proxy; **nejde o bežný nefinancovaný spot buy-and-hold**. Vstup je 1×, následný drift expozície z fundingových debitov je vykázaný (BTC maximum 1,2614×); benchmarkový ochranný strop je 3×. Koš sa rovnomerne rozdelí iba medzi aktíva prijaté pred začiatkom foldu a do konca roka drží samostatné sleeves. Jeho intradenný MDD je konzervatívny súčet súčasných extrémov; presné spoločné intradenné poradie z denných dát nepoznáme.

**BTC SMA200 porazil najvýnosnejšiu pôvodnú politiku súčasne v CAGR aj drawdowne:** 10,25 % / 61,19 % oproti 9,04 % / 66,86 %. Equal-weight koš má 28,53 % CAGR, teda vyšší výnos než všetky pôvodné aj nové politiky, ale MDD 92,20 %. Nie je preto víťazom pri zadaných rizikových limitoch. Jednoduchý benchmark **neporazil všetky nové stratégie v pomere výnos/riziko**: nový prípustný kompromis má Calmar 0,602, koš 0,309 a BTC SMA200 0,168. Vysoký Sharpe/Calmar cieľ však neplní ani nový kompromis.

## Prečo pôvodná rodina zlyhávala

Diagnostikovaných bolo všetkých 18 politík prvej fázy. Nový vstup pre riadenie signálov reprodukoval ich pôvodné denné výnosy s odchýlkou pod 1e-13. Nepredstierame tým rekonštrukciu samostatnej živej produkčnej stratégie.

Pri pôvodnom robustnom Calmar variante:

- **40,10× obratu ročne:** vstupy 19,54×, rotácie na výstupe 16,00×, stopy 2,61×, dorovnávanie expozície 1,35×, partial TP 0,38× a ročné uzavretia 0,21×. Hlavnou príčinou obratu bola častá zmena víťaza rebríčka, nie denné dorovnávanie.
- 199 vstupov, približne **34,71 ročne**, medián držania iba **3 dni**. Stratu vykázalo 56,78 % epizód. Denný rebríček s relatívnou 5 % hysteréziou často menil víťaza, hoci momentum pozeralo desiatky dní dozadu.
- **Výber aktíva:** v 56,88 % zo 160 epizód s presným open-to-open porovnaním zvolené aktívum zaostalo za BTC v rovnakom intervale; medián rozdielu bol −0,52 p. b. Príspevky BNB −0,3042 a ADA −0,1933 log jednotky výrazne mazali zisky. TRX vytvoril +0,5656 log jednotky, viac než celý čistý log rast portfólia. Výnos bol krehký a koncentrovaný.
- **Vstupy a výstupy:** medián výnosu aktíva za 30 dní pred vstupom bol +22,11 %, za nasledujúcich sedem dní od vstupu −0,22 %. To je opis naháňania predchádzajúceho rastu, nie dôkaz, že by sa dal obchod realizovať skôr. Dodatočný realizovateľný bar vstupu zlepšil CAGR 6,50 → 9,05 %; posun všetkých signálov o bar ho zlepšil na 15,13 %. Nie je teda obhájiteľné viniť iba príliš neskorý fill. Výsledok je citlivý na timing a whipsaw.
- **Ochranné mechanizmy:** odstránenie ATR/trailing/TP pri rovnakých zvolených parametroch dalo CAGR 8,79 % a MDD 71,90 %. Riziko sa nevyriešilo. Kontrola zachovania pôvodného cooldownu dala identické výsledky.
- **Náklady:** ročný súčet debitov voči equity tvoril fee 1,80 %, sklz 4,01 % a funding 3,36 % — spolu 9,17 %. Bez všetkých nákladov CAGR stúpol na 16,74 %, ale MDD zostal 64,62 %. Poplatky zhoršovali stratégiu, nevytvorili celý problém.
- **Režimy:** BTC pod SMA200 priniesol −0,2761 log jednotky, nad SMA200 pri vysokej volatilite ďalších −0,0433. Bežný rastový režim zarobil +0,6804. Najväčší pokles záverečnej equity trval od 2021-11-22 do 2023-10-18; riziko sa kumulovalo cez viac ročných foldov.

Agresívny growth variant pri strope 3× mal 53,00× obratu, približne 12,52 % ročných debitov a MDD 73,81 %. Aj bez nákladov ostal MDD 66,99 %. Ochrany reagujú až po vzniku nepriaznivého pohybu a nezabránia sérii strát pri rotáciách. Veľký obrat preto neznamená účinné obmedzenie drawdownu.

Účtovné log príspevky sú aditívne. Kontrafaktuály **bez nákladov / bez stopov / bez resize / BTC náhrada / oneskorenie sa nesčítavajú**: menia equity, veľkosť ďalších pozícií a ďalšie udalosti. BTC náhrada drží pôvodné časovanie povolenia a cieľovú expozíciu, ale zároveň zlučuje rotácie medzi altcoinmi; nie je to čistý efekt výberu aktíva. Presné porovnanie výberu poskytujú samostatné open-to-open epizódy, bez hindsight obchodovania.

## Nové rodiny: výnos / drawdown

Každá bunka je **CAGR % / MDD %** zmrazenej walk-forward politiky danej rodiny, bez ochranného overlay. ✓ znamená splnenie rizikového a expozičného stropu príslušného režimu, nie úspech hlavného cieľa.

{table(['Rodina','Robust 1,25×','Aggr. 1,25×','Aggr. 1,5×','Aggr. 2×','Aggr. 2,5×','Aggr. 3×'],families)}

Preskúmaných bolo 66 variantov na režim, spolu **396 kandidátov**, 1 188 základných/stresových historických replayov, 60 základných OOS politík a 24 samostatných overlay politík. Vyhodnotenie obsahuje 504 OOS foldov a 252 susedných replayov. Rozpočty boli oddelené; nebola pridaná adaptívna druhá mriežka.

Mesačné okná sú explicitne 30/90/180/365 kalendárnych dní. Weekly/monthly znamená nedeľný/mesačný koniec signálneho dňa, realizovaný po dostupnosti dát. Breakout používa vlastný stav prelomenia predchádzajúceho maxima a výstupu pod minimum; ensemble kombinuje viac momentum okien, trend a breakout. Pomalá rodina má 30/60-dňový minimálny holding a 0,10 absolútnu hysteréziu skóre; strata absolútneho momentum má prednosť pred holdingom.

Každý nasledujúci rok vyberá variant výhradne z predchádzajúceho validačného roka cez feasibility-first Pareto nad všetkými 15 cieľmi, potom pevný Calmar/CAGR tie-break. Nedostupný prípustný pozitívny základ znamená CASH, ktorý zostáva súčasťou výsledku. Žiadna voľba nepoužíva výsledok nasledujúceho testovaného roka. Medzirodinný výber `all_calmar` sám dopadol horšie než niektoré jednotlivé rodiny — viac možností neviedlo k lepšej generalizácii.

## Najlepší pozorovaný kompromis a stresy

`{best['id']}`: Sharpe **{best['oos']['sharpe']:.3f}**, Calmar **{best['oos']['calmar']:.3f}**, ziskové foldy **4/6**, najhorší fold **{pct(best['oos']['worst_fold_return'])}**, obrat **{best['oos']['turnover']:.2f}×** ročne. Skutočná maximálna simulovaná expozícia bola **{best['oos']['max_realized_exposure']:.4f}×**; vyššie stropy 2–3× tento výsledok nezlepšili. Rovnaký výsledok pri vyšších stropoch nie je dôkaz prínosu vyššieho leverage.

{table(['Politika','CAGR','2× náklady','Vstup +1 bar','Bez top dňa','Bez top 3 obchodov','Susedia'],stress)}

Pri prípustnom kompromise najväčšie aktívum tvorí **32,11 %** čistého log rastu, ale najväčší obchod **31,96 %**, nad limitom 15 %. Susedia prešli **2/3**; štruktúrny sused neprešiel. Foldovosť 66,67 %, Sharpe 1,041, Calmar 0,602 aj stresové CAGR sú pod hlavnými cieľmi. Nejde o robustne potvrdeného víťaza 150–200 %.

Pri vyššom pozorovanom výnose 25,80 % treba v testovanom súbore obetovať drawdownový strop: MDD 39,55 %, najväčšie aktívum 50,41 % a obchod 35,38 % log rastu. Ani tento kompromis sa nepribližuje cieľu 150 %. Z týchto dát nemožno poctivo odvodiť, aká ďalšia páka alebo zmena parametrov by ho bezpečne dosiahla; žiadna taká extrapolácia sa nevydáva za výsledok.

## Samostatný prínos stopov a partial TP

Overlay sa aplikoval iba na vopred vybraný pozitívny validačný základ `all_calmar`, bez opätovnej voľby variantov. Porovnané boli ATR4 catastrophe, ATR3 trail, 25 % TP + trail a 50 % TP + trail. **Všetkých 24 párov zhoršilo CAGR aj MDD** oproti svojmu identickému základu. Tento záver sa týka testovaných párov; nie je dôkazom, že stop nemôže fungovať v inej stratégii.

{table(['Robust 1,25× základ/overlay','CAGR','MDD'],[[p['overlay'] or 'Bez overlay',pct(p['oos']['cagr']),pct(p['oos']['max_drawdown'])] for p in r['policies'] if p['partition']=='robust_1.25' and p['selector']=='all_calmar'])}

## Integrita a verdikt

Použitý je identický zmrazený Binance spot OHLCV balík a 12 konkrétnych USDT symbolov, s 252 dokončenými barmi pred prijatím. Nie sú spájané aliasy ani prenášané výnosy iného aktíva. Universe je však historicky preživší výber; chýba úplná point-in-time história delistovaných aktív.

Signál z dňa D je konzervatívne dostupný až D+1 00:00:01 UTC, preto najbližší zachytený realizovateľný denný open je **D+2**. D+1 open by predpokladal nemožnú nulovú latenciu. Oneskorený vstup je D+3, s uloženým rozhodnutím, expiráciou supersedovaných cieľov a nezmeneným časovaním výstupov. Oba OHLC priebehy sú prepočítané; účtuje sa horší výsledok. Výška expozície je notional/equity, nie exchange leverage setting.

Audit nezávisle rekonštruoval množstvá, ceny, poplatky, funding, dennú equity, intradenný drawdown a celé epizódy všetkých 84 OOS politík. Uskutočnil 984 prefix/future-mutation replayov. Všetkých 198 development/ročných validačných riadkov nad 150 % má samostatný rozšírený audit; **ročný validačný zisk nie je OOS úspech 150 %**. Historické venue fills, funding a pozorované publikačné timestampy zostávajú chýbajúcim dôkazom.

- **A:** žiadny víťaz 150–200 %; žiadny OOS výsledok sa nedostal na 150 %.
- **B:** žiadny aktívny kandidát pod MDD 25 % pri strope 1,25×; najnižší pozorovaný MDD 26,28 % už limit prekračuje.
- **C:** pozorovaný, dodatočne opisovaný Pareto kompromis 19,01 % / 31,61 %; nesmie sa zamieňať so sealed finalistom.
- **D:** žiadny platný vysokovýnosový víťaz. Vopred nominované B/C politiky `all_calmar` v OOS neprešli; nenahrádzajú sa spätne pozorovaným víťazom.

História už bola skúmaná v prvej fáze. Toto je chronologický algoritmický OOS výskum na opakovane použitej histórii, **nie nedotknutá historická sealed evaluácia**. Žiadne sealed výsledky sa nevymýšľajú. Pozorovaná hranica platí iba pre tento zmrazený priestor a model nákladov; nie je globálnym limitom možných stratégií. Žiadny merge, deploy ani živý obchod.

## Artefakty a reprodukcia

- [Benchmarky](diagnostics/benchmarks.csv), [nákladová/asset/režimová atribúcia](diagnostics/attribution.csv), [kontrafaktuály](diagnostics/ablations.csv), [epizódy a timing](diagnostics/episode_timing.csv).
- [Kompletná Pareto tabuľka](results/pareto_table.csv), [OOS foldy](results/oos_folds.csv), [susedia](results/neighbors.csv), [overlay rozdiely](results/overlay_deltas.csv).
- [Zmrazené voľby](results/choices_before_oos.json), [nominácie](results/nominees_before_oos.json), [audit](results/audits.json), [audit vysokých validačných výsledkov](results/high_return_lineage.json), [reprodukcia](results/reproduction.json).
- [Equity krivky](results/equity_curves.png), [Pareto graf](results/pareto.png). Drawdown panel equity grafu je close-to-close; tabuľky a Pareto používajú intradenný event MDD.

```powershell
python -m unittest discover -s research/phase2_20260926 -p test_phase2.py -v
python research/phase2_20260926/diagnose.py run
python research/phase2_20260926/diagnostic_details.py
# Prázdny adresár vykoná celú mriežku; existujúci cache je viazaný hashom.
python research/phase2_20260926/search.py run --workers 6 --out scratch/phase2_fresh
python research/phase2_20260926/audit.py
python research/phase2_20260926/audit_high_lineage.py
python research/phase2_20260926/reproduce.py
python research/phase2_20260926/render.py
```

Python 3.12.10, numpy 2.4.1, pandas 3.0.2; pre grafy matplotlib 3.10.8. Existujúce freeze súbory sa neregenerujú ani neupravujú. Report/audit čítajú commitnuté `results`; čerstvý kompletný runner do `scratch/phase2_fresh` umožňuje nezávislé porovnanie bez prepísania pôvodného dôkazu.
'''
    (HERE/'RESULTS.md').write_text(text,encoding='utf-8')
    # SVG writers leave trailing spaces in metadata/style; normalize for diff checks.
    for p in out.glob('*.svg'):p.write_text('\n'.join(line.rstrip() for line in p.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    assert all(v['delta_cagr']<0 and v['delta_dd']>0 for v in overlay_rows)
    write(out/'decision.json',dict(A=None,B=None,C_observed=best['id'],D=True,highest_observed=raw['id'],lowest_robust_dd=closest['id'],
       frozen_nominees_passed=False,observed_comparison_is_not_reselection=True,all_24_overlays_worsened_cagr_and_dd=True,
       benchmark_highest_raw_cagr='equal_weight',benchmark_dominates_all_new_on_return_and_risk=False))
    print('Rendered report, equity and Pareto plots; all 24 overlay deltas verified')

if __name__=='__main__':main()
