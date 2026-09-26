# Druhá fáza: výsledky skutočne vykonaného výskumu

Cieľ **150–200 % CAGR neprešiel**. Najlepší pozorovaný Pareto kompromis spĺňajúci absolútny drawdownový strop je **19.01 % CAGR / 31.61 % MDD** pri limite expozície **1.5×**. Ide o mesačné volatility-adjusted momentum, bez trailing stopu. Nie je to schválený ani sealed víťaz.

V robustnom režime neprešla žiadna aktívna politika limitom MDD 25 %. Najbližšie bolo BTC/altcoin/CASH s 9.11 % CAGR a 26.28 % MDD. CASH má 0 % výnos aj drawdown. Najvyšší CAGR novej rodiny bol 25.80 %, ale s 39.55 % drawdownom.

## Benchmarky a pôvodná stratégia

OOS interval: **2021-01-01 až 2026-09-25**, šesť chronologických foldov; rok 2026 je neúplný. Všetky primárne porovnania používajú 4,5 bp fee + 10 bp sklz na každú stranu a 12 % p.a. fundingový debit z celého držaného notionalu. Funding je konzervatívny modelový predpoklad, nie nameraná historická sadzba.

| Benchmark | CAGR | MDD | Sharpe | Calmar | Obrat / rok |
| --- | --- | --- | --- | --- | --- |
| BTC_hold | 5.11 % | 83.24 % | 0.386 | 0.061 | 2.24× |
| BTC_SMA200 | 10.25 % | 61.19 % | 0.441 | 0.168 | 10.18× |
| momentum_weekly | 7.60 % | 91.41 % | 0.530 | 0.083 | 34.96× |
| momentum_monthly | 10.69 % | 96.88 % | 0.568 | 0.110 | 15.07× |
| CASH | 0.00 % | 0.00 % | 0.000 | 0.000 | 0.00× |
| equal_weight | 28.53 % | 92.20 % | 0.713 | 0.309 | 2.23× |

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

| Rodina | Robust 1,25× | Aggr. 1,25× | Aggr. 1,5× | Aggr. 2× | Aggr. 2,5× | Aggr. 3× |
| --- | --- | --- | --- | --- | --- | --- |
| Cross-sectional momentum | 3.98 / 54.35 | -1.74 / 67.00 | -2.39 / 67.00 | -2.41 / 67.00 | -2.41 / 67.00 | -2.41 / 67.00 |
| Dual momentum | -0.10 / 44.34 | -2.47 / 52.54 | -3.02 / 54.07 | -2.97 / 53.91 | -2.97 / 53.91 | -2.97 / 53.91 |
| Weekly/monthly relative strength | 10.54 / 41.59 | 9.46 / 47.80 | 8.68 / 47.80 | 7.66 / 46.39 | 7.66 / 46.39 | 7.66 / 46.39 |
| Breakout / trend following | 8.49 / 28.52 | 7.14 / 40.60 | 7.09 / 40.60 | 7.09 / 40.60 | 7.09 / 40.60 | 7.09 / 40.60 |
| Volatility-adjusted momentum | 25.80 / 39.55 | 22.97 / 40.97 | 19.01 / 31.61 ✓ | 19.01 / 31.61 ✓ | 19.01 / 31.61 ✓ | 19.01 / 31.61 ✓ |
| Ensemble | 13.04 / 30.27 | 8.07 / 37.81 | 8.07 / 37.81 | 8.91 / 37.81 | 8.91 / 37.81 | 8.91 / 37.81 |
| BTC / altcoin / CASH | 9.11 / 26.28 | 16.09 / 43.10 | 15.93 / 44.10 | 16.08 / 44.61 | 16.08 / 44.61 | 16.08 / 44.61 |
| Pomalá rotácia + hysterézia | 20.03 / 46.41 | 16.12 / 47.64 | 17.07 / 49.15 | 13.97 / 56.16 | 13.87 / 38.57 | 13.87 / 38.57 |

Preskúmaných bolo 66 variantov na režim, spolu **396 kandidátov**, 1 188 základných/stresových historických replayov, 60 základných OOS politík a 24 samostatných overlay politík. Vyhodnotenie obsahuje 504 OOS foldov a 252 susedných replayov. Rozpočty boli oddelené; nebola pridaná adaptívna druhá mriežka.

Mesačné okná sú explicitne 30/90/180/365 kalendárnych dní. Weekly/monthly znamená nedeľný/mesačný koniec signálneho dňa, realizovaný po dostupnosti dát. Breakout používa vlastný stav prelomenia predchádzajúceho maxima a výstupu pod minimum; ensemble kombinuje viac momentum okien, trend a breakout. Pomalá rodina má 30/60-dňový minimálny holding a 0,10 absolútnu hysteréziu skóre; strata absolútneho momentum má prednosť pred holdingom.

Každý nasledujúci rok vyberá variant výhradne z predchádzajúceho validačného roka cez feasibility-first Pareto nad všetkými 15 cieľmi, potom pevný Calmar/CAGR tie-break. Nedostupný prípustný pozitívny základ znamená CASH, ktorý zostáva súčasťou výsledku. Žiadna voľba nepoužíva výsledok nasledujúceho testovaného roka. Medzirodinný výber `all_calmar` sám dopadol horšie než niektoré jednotlivé rodiny — viac možností neviedlo k lepšej generalizácii.

## Najlepší pozorovaný kompromis a stresy

`aggressive_1.5__vol_adjusted`: Sharpe **1.041**, Calmar **0.602**, ziskové foldy **4/6**, najhorší fold **-23.80 %**, obrat **4.40×** ročne. Skutočná maximálna simulovaná expozícia bola **1.2937×**; vyššie stropy 2–3× tento výsledok nezlepšili. Rovnaký výsledok pri vyšších stropoch nie je dôkaz prínosu vyššieho leverage.

| Politika | CAGR | 2× náklady | Vstup +1 bar | Bez top dňa | Bez top 3 obchodov | Susedia |
| --- | --- | --- | --- | --- | --- | --- |
| aggressive_1.5__vol_adjusted | 19.01 % | 15.69 % | 16.89 % | 16.70 % | 6.49 % | 2/3 |
| robust_1.25__vol_adjusted | 25.80 % | 21.64 % | 21.09 % | 22.93 % | 6.63 % | 2/3 |
| robust_1.25__regime_allocation | 9.11 % | 6.56 % | 11.73 % | 8.00 % | 1.13 % | 3/3 |
| robust_1.25__all_calmar | 2.34 % | -1.02 % | 8.03 % | -1.02 % | -8.33 % | 3/3 |
| aggressive_1.25__all_calmar | 5.87 % | 2.32 % | 12.10 % | 2.40 % | -5.35 % | 2/3 |

Pri prípustnom kompromise najväčšie aktívum tvorí **32,11 %** čistého log rastu, ale najväčší obchod **31,96 %**, nad limitom 15 %. Susedia prešli **2/3**; štruktúrny sused neprešiel. Foldovosť 66,67 %, Sharpe 1,041, Calmar 0,602 aj stresové CAGR sú pod hlavnými cieľmi. Nejde o robustne potvrdeného víťaza 150–200 %.

Pri vyššom pozorovanom výnose 25,80 % treba v testovanom súbore obetovať drawdownový strop: MDD 39,55 %, najväčšie aktívum 50,41 % a obchod 35,38 % log rastu. Ani tento kompromis sa nepribližuje cieľu 150 %. Z týchto dát nemožno poctivo odvodiť, aká ďalšia páka alebo zmena parametrov by ho bezpečne dosiahla; žiadna taká extrapolácia sa nevydáva za výsledok.

## Samostatný prínos stopov a partial TP

Overlay sa aplikoval iba na vopred vybraný pozitívny validačný základ `all_calmar`, bez opätovnej voľby variantov. Porovnané boli ATR4 catastrophe, ATR3 trail, 25 % TP + trail a 50 % TP + trail. **Všetkých 24 párov zhoršilo CAGR aj MDD** oproti svojmu identickému základu. Tento záver sa týka testovaných párov; nie je dôkazom, že stop nemôže fungovať v inej stratégii.

| Robust 1,25× základ/overlay | CAGR | MDD |
| --- | --- | --- |
| Bez overlay | 2.34 % | 56.79 % |
| cat4 | -4.22 % | 64.67 % |
| trail3 | -5.91 % | 66.59 % |
| tp25_trail3 | -7.56 % | 66.79 % |
| tp50_trail3 | -8.81 % | 66.57 % |

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
