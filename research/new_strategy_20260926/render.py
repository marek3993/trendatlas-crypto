"""Read-only reporting of frozen development and outer OOS; never selection."""
import io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from common import HERE,write
import evaluate as ev

OUT=HERE/'results'
def read(name):return json.loads((OUT/name).read_text())
def pct(x):return '—' if x is None else f'{x*100:.2f}'
def number(x):return '—' if x is None else f'{x:.2f}'
def table(rows):
    lines=['| Rodina / variant | Stav | CAGR % | MDD % | Sharpe | Calmar | Turnover/rok | Náklady %/rok | Obchody | Držanie dni | Ziskové foldy | Najhorší fold % | 2× CAGR % | +1 bar CAGR % | Bez naj dňa % | Bez top3 % | Max podiel aktíva | Max podiel obchodu |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        vals=[r['family'],r['status'],pct(r.get('cagr')),pct(-r['mdd']) if 'mdd' in r else '—',number(r.get('sharpe')),number(r.get('calmar')),number(r.get('turnover')),pct(r.get('costs')),str(r.get('trades','—')),number(r.get('median_holding')),f"{r['profitable_folds']}/{r['fold_count']}" if 'fold_count' in r else '—',pct(r.get('worst_fold')),pct(r.get('double_cost_cagr')),pct(r.get('delayed_cagr')),pct(r.get('without_best_day')),pct(r.get('without_three_trades')),pct(r.get('asset_concentration')),pct(r.get('trade_concentration'))]
        lines.append('| '+' | '.join(vals)+' |')
    return lines

def main():
    family=read('family_results.json');folds=read('oos_folds.json');ablations=read('ablations.json');final=read('finalists_frozen.json');neighbors=read('neighbors.json');receipt=read('receipt.json')
    references={r['family']:r for r in read('baseline_stresses.json')};family=[references.get(r['family'],r) for r in family]
    final_neighbors=read('finalist_neighbors.json')['summary']
    trials=[json.loads(x) for x in (OUT/'development.jsonl').read_text().splitlines()]
    flat=[]
    for r in trials:
        flat.append({**{k:v for k,v in r.items() if not isinstance(v,(dict,list))},'rules':json.dumps(r['candidate'],sort_keys=True)})
    pd.DataFrame(flat).to_csv(OUT/'development.csv',index=False)
    pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in family]).to_csv(OUT/'family_results.csv',index=False)
    # All fronts, including infeasible ones, are clearly distinguished.
    fronts=[]
    for origin in [2022,2023,2024,2025,2026]:
        for f in ['A','B','C']:
            pool=[r for r in trials if r['origin']==origin and r['candidate']['family']==f and r['status']=='VALID']
            for rank,rows in enumerate(ev.fronts(pool)):
                for r in rows:fronts.append(dict(r,origin=origin,family=f,pareto_rank=rank,development_feasible=ev.feasible(r)))
    write(OUT/'pareto_fronts.json',fronts)
    pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in fronts]).to_csv(OUT/'pareto_fronts.csv',index=False)
    ns=[]
    for origin in [2022,2023,2024,2025,2026]:
        for f in ['A','B','C']:
            parent=read(f'origin_{origin}_{f}_frozen.json')['champion'];kids=[r for r in neighbors if r['origin']==origin and r['parent_id']==parent['candidate_id']]
            good=[r for r in kids if r['status']=='VALID'];qualified=[r for r in good if r['cagr']>0 and r['mdd']<=.35]
            median=float(np.median([r['cagr'] for r in good])) if good else None
            passed=parent['status']=='VALID' and parent['cagr']>0 and len(qualified)/len(kids)>=.75 and median is not None and median>=.75*parent['cagr']
            ns.append(dict(origin=origin,family=f,parent_id=parent['candidate_id'],neighbors=len(kids),valid=len(good),qualified=len(qualified),median_cagr=median,passed=passed))
    write(OUT/'neighbor_summary.json',ns)
    valid=[r for r in family if r['family'] in ['A','B','C'] and r['status']=='VALID']
    oosfront=ev.fronts([dict(r,candidate_id=r['family']) for r in valid])[0] if valid else []
    write(OUT/'oos_pareto_descriptive.json',oosfront)
    criteria={}
    for r in valid:
        criteria[r['family']]=dict(cagr=r['cagr']>=1.5,mdd=r['mdd']<=.35,sharpe=r['sharpe']>=1.5,calmar=r['calmar']>=4.,double_cost=r['double_cost_cagr']>=1.,delay=r['delayed_cagr']>0,without_best_day=r['without_best_day']>=1.,without_three_trades=r['without_three_trades']>=.8,asset_concentration=r['asset_concentration'] is not None and r['asset_concentration']<=.35,trade_concentration=r['trade_concentration'] is not None and r['trade_concentration']<=.15,fold_fraction=r['profitable_folds']/r['fold_count']>=.75)
    decision=dict(verdict='REJECT',main_goal_pass=False,validated_replacement=False,forward_evidence='NOT_YET_AVAILABLE',criteria=criteria,finalists=final['slots'],reason='No prospective sealed evidence; any failed numeric, execution or venue gate remains a failure. Development nominees are not a deployable winner.')
    write(HERE/'decision.json',decision)
    lines=['# TrendAtlas — nový strategický research framework','', '**Rozhodnutie: REJECT pre potvrdenú náhradu produkčnej stratégie.** Framework bol implementovaný, otestovaný a reálne spustený. Výsledky nižšie sú nové výpočty; staré CAGR ani paper equity nevstupujú do stratégie, výberu alebo účtovania.','',
      f'Rozpočet: **{receipt["unique_search_evaluations"]} kandidátskych hodnotení**, 3 oddelené rodiny × 5 vývojových počiatkov × 4 generácie; populácia 10, 6 preživších, 4 nové mutácie. Ďalej {receipt["neighbor_evaluations"]} susedných konfigurácií, {receipt["ablation_evaluations"]} ablácií a {receipt["outer_fold_evaluations"]} zmrazených ročných OOS testov. Pri vykonateľných kandidátoch sa replay zopakoval s 2× nákladmi a s fillom o jeden 4h bar neskôr; nevykonateľné kandidáty končia explicitným zamietnutím. Samostatne sa overili aj stresy referenčných baseline a susedia finálnych nominantov.','',
      '## Dátový model a rozsah','',
      'Spot na Binance, 20 párov vybraných iba podľa uzavretého decembra 2020 z celého archívneho zoznamu USDT symbolov. Do rozhodnutí vstupuje posledných 30 dokončených dní quote-volume, hranica 10 miliónov USD/deň, top10 v tomto pevnom kohorte a minimálne 365 pozorovaných dní. Kohorta nepridáva neskorších víťazov a nevyhadzuje neskôr zaniknuté aktíva. Ide o vopred daný kohortový universe, nie celý kryptotrh.','',
      'Surové 4h archívy majú overený SHA256 poskytovateľa. Samostatná evidencia prvého obchodovaného minútového baru zachytáva začiatok histórie každého konkrétneho páru. Administratívne listing oznámenia nie sú kompletne certifikované. EOS delisting používa oznámenie publikované 14. 5. 2025 a účinnosť 26. 5. 2025 03:00 UTC; jeho výnos sa nespája s tickerom A. [Oznámenie Binance](https://www.binance.com/en/support/announcement/detail/1e89a9ca957c4b0ca7502e60b993e201).','',
      'Denný close D je dostupný D+1 00:01 UTC; fill pri nasledujúcom zachytenom 4h open, obvykle D+1 04:00 UTC. Aj 4h signál čaká na ukončenie sviečky, minútovú latenciu a ďalšie otvorenie. Poplatok 10 bp a nepriaznivý sklz 10 bp na každej strane; spot funding 0. Počiatočný kapitál 10 000 USD, limit účasti 0,1% posledného dostupného 4h quote-volume vrátane výstupov; rast kapitálu sa pri OOS prenáša do tohto limitu. Chýbajúci fill alebo prekročenie kapacity znamená REJECT, nie fiktívny obchod. Sklz je konzervatívny predpoklad, nie historický order-book dôkaz.','',
      'Skutočné časované Binance USD-M funding sadzby boli stiahnuté pre BTC, ETH, BNB, XRP a SOL a uchované oddelene. **Perpetual varianty a rodina D sa neskórujú:** chýba kompletné spojenie trade/mark cien a historických maintenance/liquidation pravidiel. Spot ceny a nulový funding ich nesmú nahradiť. Hyperliquid infraštruktúra zostáva nedotknutá; tieto spot výsledky sa na Hyperliquid automaticky neprenášajú.','',
      'Oficiálne zdroje dát: [Binance public data](https://github.com/binance/binance-public-data), [Hyperliquid historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data). Presná evidencia je v `cohort.json`, `listing_evidence.json`, `venue_notices.json`, `data_audit.json` a archívnom manifeste.','',
      '## Spoločné chronologické OOS výsledky','',
      'Roky 2022–2025. Každý testovaný rok má vlastného víťaza vybraného iba z predchádzajúceho validačného roka; história pred ním slúži na warmup a pevné pravidlá. Parametre sa nevyberajú podľa OOS. Tabuľka hodnotí tento walk-forward postup, **nie neskoršieho statického finalistu**. Výnosy sú čisté, MDD zahŕňa konzervatívnu intrabar cestu high→low; Sharpe používa UTC denné výnosy a 365,25 dní.','']
    lines+=table(family)
    lines+=['', 'Výsledok rodiny B znamená zlyhanie realizovateľnosti celého predpísaného testu pri danom kapitále a objemovom limite; nejde o platný odhad jej CAGR ani o dôkaz, že momentum nemá alpha. `execution_stage` v strojových výsledkoch rozlišuje nominálny replay, dvojnásobné náklady a oneskorený fill. Rozpočet ani kapacitný limit sa po pozorovaní zlyhaní neupravovali.', '', 'Universe sa smie prvýkrát použiť až po uzavretí decembra 2020: najskorší signálový bar 31. 12. 2020 20:00 UTC, dostupnosť 1. 1. 2021 00:01, fill 04:00. Staršie dáta slúžia iba na warmup. Publikovaná nedostupnosť aktíva sa maskuje pred liquidity rankingom aj pri intraday admission.']
    lines+=['','Náklady = ročný súčet poplatkov, sklzu a funding debitov/NAV. Turnover počíta obe rotačné strany. Kompletný obchod je flat-to-flat epizóda; pri ročnom predpísanom výstupe sa uzatvára. Bez najlepšieho dňa a bez top3 obchodov znamená prepočet CAGR s odstráneným čistým denným výnosom alebo zosúladenými log-príspevkami celých epizód. Podiel aktíva/obchodu používa kladný príspevok delený celkovým čistým log rastom; pri nekladnom raste je neplatný, nie nula.','',
      'Rodina B má pri niektorých kandidátoch nedostatočnú realizovateľnú kapacitu pri zmrazenom kapitále. Zamietnuté foldy zostávajú viditeľné; nezostavuje sa výhodná krivka vynechaním zlyhaného roka. Podrobnosti: `results/execution_rejections.json` a všetky vývojové zamietnutia v `results/development.csv`.','',
      '## Každý ročný fold a presné pravidlá','', '| Rodina | OOS rok | Kandidát | Stav | CAGR % | MDD % | 2× CAGR % | +1 bar CAGR % | Pravidlá |','|---|---:|---|---|---:|---:|---:|---:|---|']
    for r in folds:lines.append('| '+' | '.join([r['family'],str(r['year']),r['candidate_id'],r['status'],pct(r.get('cagr')),pct(-r['mdd']) if 'mdd' in r else '—',pct(r.get('double_cost_cagr')),pct(r.get('delayed_cagr')),json.dumps(r['candidate'],sort_keys=True)])+' |')
    lines+=['','## Rodiny','',
      '- **A Regime trend:** BTC nad pomalým priemerom a fast MA nad slow MA; breadth je podiel dostupných likvidných coinov nad rovnakým slow MA. Zapnutie aj vypnutie vyžaduje daný počet po sebe idúcich dní. Revízia týždenne alebo mesačne; long BTC/CASH.',
      '- **B Cross-sectional momentum:** pozitívne 30/90/180/365-dňové momentum alebo priemer všetkých štyroch; voliteľne delené max(0,1, anualizovaná vol60). Vyberá jeden dostupný coin týždenne/mesačne. Strata kladného momenta alebo spôsobilosti vedie do CASH bez predčasného výberu ďalšieho coinu.',
      '- **C Multi-timeframe:** potvrdený denný BTC režim nad SMA, 4h vstup nad EMA alebo nad predchádzajúce maximum daného počtu barov, výstup pod 4h EMA. Všetky fills až po latencii; 1× spot/CASH.',
      '- **D Long/short:** NOT_RUN_DATA_GATE. Žiadne fiktívne short/funding/liquidation výsledky.',
      '- **E Ensemble:** členom môže byť iba rodina s aspoň dvoma predchádzajúcimi OOS foldmi a samostatným splnením baseline gate. Kombinácia vyžaduje zhodu všetkých oprávnených členov na rovnakom konkrétnom aktíve, inak CASH. Slabé alebo zamietnuté rodiny sa neskladajú.','',
      '## Ablácie','', 'Kontrasty používajú zmrazené pravidlá každého ročného nominanta. Nevracajú sa do mutácií ani výberu. Žiadne ETF, leverage, TP, trailing stop alebo cooldown neboli pridané.','',
      '| Rodina | Rok | Odobratá/zmenená zložka | Stav | CAGR % | MDD % | Δ CAGR pp proti rodičovi | Δ MDD pp, kladné horšie |','|---|---:|---|---|---:|---:|---:|---:|']
    for r in ablations:
        parent=next(x for x in folds if x['family']==r['family'] and x['year']==r['year']);validpair=r['status']==parent['status']=='VALID'
        lines.append('| '+' | '.join([r['family'],str(r['year']),r['ablation'],r['status'],pct(r.get('cagr')),pct(-r['mdd']) if 'mdd' in r else '—',pct(r['cagr']-parent['cagr']) if validpair else '—',pct(r['mdd']-parent['mdd']) if validpair else '—'])+' |')
    lines+=['', 'Interpretácia: prínos breadth a pomalého potvrdenia sa musí posudzovať po jednotlivých rokoch; zmiešané rozdiely nepreukazujú stabilnú alpha. V rodine C porovnanie s denným režimom bez intraday vrstvy testuje, či 4h vstupy platia za svoj dodatočný turnover. Nevýhodný kontrast neoprávňuje spätne premenovať lepšiu abláciu na OOS víťaza. Rodina B pri odmietnutej realizovateľnosti neposkytuje platný kontrast výnosu.']
    lines+=['','## Pareto front a zmrazení finalisti','', 'Úplné vývojové fronty po rodinách/počiatkoch sú v `results/pareto_fronts.csv`; finálny vývojový rok je 2025. OOS front je iba opis už zmrazených ročných postupov a neslúži na nový výber. Fitness je viacrozmerné Pareto s feasibility-first poradím; samotné CAGR nie je fitness.','',
      '| Slot | Kandidát | Rodina | Vývojový CAGR 2025 % | Vývojový MDD % | 2× CAGR % | Pravidlá |','|---|---|---|---:|---:|---:|---|']
    for slot,r in final['slots'].items():
        if not r:lines.append(f'| {slot} | žiadny spôsobilý nominant | — | — | — | — | — |')
        else:lines.append('| '+' | '.join([slot,r['candidate_id'],r['candidate']['family'],pct(r['cagr']),pct(-r['mdd']),pct(r['double_cost_cagr']),json.dumps(r['candidate'],sort_keys=True)])+' |')
    lines+=['','Slot B označuje najlepší vývojový robustný kandidát s MDD≤25%; aggressive_diagnostic je kandidát s najvyšším CAGR na vývojovom Pareto fronte a môže byť zamietnutý. Ide o **nominácie, nie OOS potvrdenie týchto konkrétnych pravidiel**. A/B/C boli zmrazené pred otvorením OOS výsledkov v tomto runneri a pred akýmikoľvek forward dátami. Už skúmanú históriu neoznačujeme za nový vedecký seal. Prospektívne okno začína 27. 9. 2026; zatiaľ nebolo otvorené.','',
      '## Susedné parametre','', '| Výber pre rok | Rodina | Platné / všetky susedné varianty | Kvalifikované | Medián CAGR % | Stabilita |','|---:|---|---:|---:|---:|---|']
    for r in ns:lines.append(f'| {r["origin"]} | {r["family"]} | {r["valid"]}/{r["neighbors"]} | {r["qualified"]} | {pct(r["median_cagr"])} | {"PASS" if r["passed"] else "REJECT"} |')
    lines+=['','Finálni nominanti, samostatná kontrola susedov bez opätovného výberu:','']
    for r in final_neighbors:lines.append(f'- {r["candidate_id"]}: {r["qualified"]}/{r["neighbors"]} kvalifikovaných susedov, medián CAGR {pct(r["median_cagr"])}%, stabilita **{"PASS" if r["passed"] else "REJECT"}**. Sloty: {", ".join(r["slots"])}.')
    lines+=['','## Equity a náklady','', '![Čerstvé walk-forward equity krivky](equity.png)','',
      'Všetky jednotlivé poplatky/fills, konkrétne symboly, signálové časy, dostupnosť a kompletné epizódy sú v `results/ledgers.zip`. Agregované fee/slippage/funding sú v CSV a JSON; spot nemá funding kredit ani debit. Neexistuje zamieňanie modelovej equity za účet.','',
      '## DeepSeek a hranice výsledku','',
      f'DeepSeek API volania: **{receipt["api_calls"]}**. Pri nedostupnom API kľúči bežali deterministické mutácie. Integrácia posiela iba whitelist vývojových metrík a schému; vyžaduje striktne validovaný JSON so štyrmi návrhmi. Extra kľúče, chybná rodina/typ/hodnota, duplicitné kľúče a nefinálne čísla sa odmietajú. Model nemá tools ani prístup k súborom, evaluatoru, produkcii, objednávkam, OOS alebo sealed výsledkom. [DeepSeek JSON dokumentácia](https://api-docs.deepseek.com/guides/json_mode/).','',
      'Cieľ 150–200% CAGR sa neznižuje. PASS vyžaduje aj MDD≤35%, Sharpe≥1,5, Calmar≥4 a všetky stresové, koncentráčne a prospektívne dôkazy. Chýbajúci alebo zlyhaný dôkaz zostáva REJECT. Výsledok nie je dôkaz nemožnosti dosiahnuť cieľ inou stratégiou; je hranicou tohto zmrazeného experimentu.','',
      'Reprodukcia, FILES READ, SOURCE OF TRUTH, koreňové príčiny, zakázané staré cesty a presný rozsah zmien: [AUDIT.md](AUDIT.md). Presný staging zoznam: [GIT_ADD.txt](GIT_ADD.txt). Produkcia, dashboard, execution planner, Hyperliquid integrácia, účty, Pi timery a reconciliácia zostali bez zmeny.','']
    (HERE/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,5.5));z=zipfile.ZipFile(OUT/'ledgers.zip')
    for name,label in [('A','Regime trend'),('B','Cross-sectional momentum'),('C','Multi-timeframe trend'),('baseline_BTC_hold','BTC spot hold'),('baseline_BTC_SMA200','BTC SMA200')]:
        frames=[];nav=1.
        for year in [2022,2023,2024,2025]:
            key=f'{name}/{year}/bars.csv'
            if key not in z.namelist():frames=[];break
            d=pd.read_csv(io.BytesIO(z.read(key)),index_col=0,parse_dates=True);d.equity*=nav;nav=d.equity.iloc[-1];frames.append(d)
        if frames:d=pd.concat(frames);ax.plot(d.index,d.equity,label=label,lw=1.5)
    ax.set(yscale='log',title='TrendAtlas: frozen walk-forward spot research',ylabel='Simulated capital (initial = 1, log scale)');ax.grid(alpha=.2);ax.legend(ncol=2)
    fig.text(.01,.01,'2022–2025 | D+1 / 4h causal fills | fees + adverse slippage | incomplete families excluded, never stitched over a failed fold',fontsize=8)
    fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(HERE/'equity.png',dpi=170);plt.close(fig)
    print('Report rendered. Verdict: REJECT')

if __name__=='__main__':main()
