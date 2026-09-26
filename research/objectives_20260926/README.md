# Náhrada výskumných cieľov a fitness — 26. 9. 2026

Záväzným zadaním pre ďalší offline výskum je `source_of_truth/research_objectives_contract.json`. Nahrádza skoršie ciele a pravidlá výberu. CAGR **150–200 %** je hlavný cieľ; **20–35 % je iba konzervatívna referencia**. Existujúce zmrazené výsledky a ich kontrakty sa spätne neprepisujú.

| Režim | Maximálna expozícia účtu | Úloha |
|---|---|---|
| Robustný | 1,25× | Najvyšší kauzálny OOS CAGR pri DD ≤25 %; nižší CAGR nie je dôvod na vyradenie |
| Agresívny | Samostatne 1,25 / 1,5 / 2 / 2,5 / 3× | Hľadať OOS CAGR 150–200 % pri cieľovom DD ≤20 %, prijateľnom ≤30 %, absolútnom ≤35 % |

Expozícia je súčet absolútnych notionalov delený modelovaným equity účtu. Burzové nastavenie 10× neurčuje pozíciu. Vyššiu expozíciu riadi volatilita a režim; nepriaznivý trh musí umožniť 1 / 0,75 / 0,5× a CASH. Každý režim a expozičný limit má oddelenú populáciu, rozpočet hľadania a výsledky.

## Fitness a finálny výber

Najprv platnosť dát, časovania, fillov a limity rizika. Potom Pareto hodnotenie CAGR, DD, Calmar, Sharpe, podielu ziskových foldov, najhoršieho foldu, koncentrácie podľa aktíva aj obchodu, turnoveru, nákladov, stability parametrov, oneskoreného fillu, 2× nákladov a vynechania najlepšieho dňa/troch obchodov. Nevzniká jediný súčet váh ani rebríček zoradený iba podľa CAGR. Kandidát 180 % / DD 70 % nemôže poraziť platný 150 % / DD 25 %.

Vnútri walk-forward sa vyberá iba z predchádzajúcich train/validation dát. OOS foldy sú chronologické, neprekrývajú sa a zahŕňajú aj CASH a stratové obdobia. Kandidáti A/B/C a pravidlá rozhodnutia medzi nimi sa zmrazia pred otvorením sealed dát. Po zlyhaní kandidáta sa ten istý seal nepoužíva na výber náhradníka. Finálne Pareto porovnanie je opisom zmrazených výsledkov, nie novým optimalizačným kolom.

Pre úspech v hlavnom cieli musia samostatne OOS aj sealed výsledky spĺňať:

- CAGR ≥150 %, DD ≤35 %, Sharpe ≥1,5 a Calmar ≥4.
- CAGR bez najlepšieho dňa ≥100 %; bez troch najlepších obchodov ≥80 %.
- CAGR pri 2× poplatkoch, fundingových debetoch a sklze ≥100 %.
- Pri vstupe o jeden ďalší realizovateľný bar neskôr zostáva CAGR kladný.
- Jedno aktívum tvorí najviac 35 % a jeden celý obchod najviac 15 % celkového čistého logaritmického rastu.
- V outer WF je aspoň 75 % foldov striktne ziskových a najhorší fold nestratí viac ako 35 %; nulový fold sa nepočíta ako ziskový.
- Vopred určení susedia parametrov prejdú vopred určenou číselnou toleranciou podobnosti.
- Prejdú audity kauzality, identity aktíva, publikovania vstupov, fillov, nákladov, dynamickej expozície a risk stavového automatu.

Podmienky odstránenia dní/obchodov nemenia kalendár ani pravidlá stratégie. Koncentrácia používa celkový čistý log rast, nie súčet iba kladných príspevkov. Partial fills nesmú rozdeliť jeden veľký obchod na malé zdanlivo nezávislé obchody. 2× náklady sa simulujú znovu; zdvojnásobenie fundingových kreditov nesmie umelo vylepšiť záťažový test. Chýbajúci funding nie je pozorovaná nula.

Pri CAGR ≥150 % v ľubovoľnej development/OOS/sealed časti sa automaticky vyžaduje rozšírený anti-lookahead a asset-lineage audit. Platí aj nad 200 %. Chýbajúci alebo neúspešný audit blokuje finalistu.

## Trailing a ochrana

Výskumná matica zahŕňa volatility targeting, zníženie rizika pri rastúcej volatilite, katastrofický ATR stop, partial TP 25/50 %, trailing zvyšku iba smerom k zisku, CASH pri strate trendu, potvrdený odraz pred reentry, zákaz dokupovania pokračujúceho prepadu a cooldown/hysteresis. Normálna rotácia na nový cieľ má okamžitú prioritu pred stavom ochrany starej pozície. Nový cieľ nesmie zdediť jej cooldown, stop ani high-water mark.

Presné ATR parametre, volatilitu, frekvenciu barov, universe, náklady, foldy, tolerancie susedov a rozpočet pokusov musí konkrétny experiment zmraziť pred výsledkami. Táto zmena cieľov nevymýšľa tieto chýbajúce časti pôvodného experimentálneho zadania.

## Implementácia a rozhranie

`scripts/research_objectives.py` je nový offline hodnotiteľ, nie backtest engine. Nevolá produkciu ani sieť a CLI zapisuje iba JSON na stdout. Nie je pripojený k starému Research OS supervisoru alebo jeho promočnému skóre. To by menilo inú automatizáciu; budúci výskumný runner musí tento kontrakt explicitne načítať.

- `pareto_front(candidates, mode=..., exposure_cap=...)` používa výhradne `development` metriky a jednu populáciu. Výstup je predbežný, kým neprejdú vedecké audity.
- `assess(candidate, evidence_root, audit_runner=...)` kontroluje OOS, sealed, riziko a dôkazy. Pri vysokom CAGR automaticky zavolá dodaný replay audit runner so všetkými rozšírenými kontrolami. Bez runnera overí existujúce dôkazy; chýbajúce kontroly zablokujú prijatie. Výnimka runnera zneplatní aj staré passing reports.
- `final_verdict(nominees, candidates, evidence_root, audit_runner=...)` vyhodnotí vopred nominované A/B/C bez opätovného výberu podľa sealed metrík. D môže platiť spolu s B/C.

Kandidát obsahuje `id`, `mode`, `exposure_cap`, `nominee_categories`, `development`, `oos`, `sealed`, `binding` a `audits`. Metriky používajú kľúče z `fitness.objectives`, navyše `max_realized_exposure`; OOS obsahuje všetky `fold_returns`. Fold summary polia v sealed bloku odkazujú na tú istú outer WF sadu, nie na dodatočne vymyslené sealed foldy. Hodnoty sú zlomky, napríklad CAGR 150 % = 1,5 a DD 25 % = kladné 0,25. Calmar musí sedieť s CAGR/DD. NaN, infinity, záporný DD a chýbajúce hodnoty neprejdú.

`binding` obsahuje `candidate_id`, SHA256 vstupov, zdrojového kódu, parametrov, kontraktu a `evaluation_sha256(candidate)` vrátane metrík a nominácií. Každý audit obsahuje `passed`, totožný `binding` a neprázdne `artifacts` s relatívnou `path` a `sha256`. Hodnotiteľ overí skutočné bajty súborov a zakáže únik mimo evidence bundle. Audit `selection_frozen_before_seal` musí doložiť časový záznam nominácií a prístupu k seal. Kontrola hashov sama osebe nedokazuje správnosť metodiky: replay runner a forenzný audit musia vytvoriť obsah dôkazov. Samotné JSON `passed: true` bez artifactov nestačí.

Použitie pripraveného skutočného kandidáta:

```powershell
python scripts/research_objectives.py path/to/frozen_candidate.json
```

Exit 0 znamená, že dodané dôkazy a metriky prešli screeningom. **Neznamená úspech 150 %**, ktorý má samostatné pole `high_return_gates_passed`, ani nasadenie. Exit 2 znamená neplatný/neúplný kandidát. Testy používajú výhradne syntetické fixtures, nie nové trhové výsledky.

## Aktuálny stav výsledkov

| Verdikt | Stav pri tejto zmene zadania |
|---|---|
| A — platný víťaz 150–200 % | Nepreukázaný; nový OOS/sealed experiment neprebehol |
| B — najlepší robustný ≤1,25× | Neurčený; neexistuje nové porovnanie podľa tohto kontraktu |
| C — najlepší Pareto kompromis | Neurčený; chýba zmrazená populácia a nové hodnotenie |
| D — žiadny platne preukázaný víťaz | Áno, pri aktuálne dodaných dôkazoch; nie dôkaz nemožnosti dosiahnuť cieľ |

Starší risk-overlay audit reprodukoval 176,66 % CAGR, ale odhalil nesúlad asset/return a same-day filtrovanie. Novšia rekonštrukcia vo worktree `trendatlas_causal_baseline_20260926`, commit `e3b0ea4073cd02f3a9b1b649c164aea3d26e2188`, uvádza CAGR **31,4471 %**, DD **40,6292 %**, Sharpe **0,7511**, Calmar **0,7740**. Je to historický proxy model s neúplnými point-in-time a venue vstupmi. Nespĺňa nové rizikové limity a nie je nezávislý OOS/sealed dôkaz.

31,45 % sa nepovyšuje na cieľ ani na maximálny reálne dosiahnuteľný výnos. Presnú hranicu testovaného priestoru a cenu vyššieho výnosu možno uviesť až po kauzálnom porovnaní oboch režimov. Už preskúmané historické dáta sa nedajú spätne zapečatiť; pre sealed verdikt treba dosiaľ nepoužité alebo dopredné dáta. Táto úloha zmenila zadanie a jeho kontroly; nepredstiera dokončenie nového výskumu ani funkčného stop/reentry enginu.

Žiadny kandidát sa automaticky nenasadzuje. Produkcia, burzové nastavenie a skutočný účet sa touto zmenou nemenia.
