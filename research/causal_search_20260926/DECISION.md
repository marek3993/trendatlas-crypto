# Výsledný verdikt

**Cieľ 150–200 % CAGR zostáva nezmenený. Platný víťaz A nebol potvrdený.**

Reálne prebehlo 1 944 variantov v šiestich oddelených rozpočtoch a ich 3 888 nákladových/vstupných stresov. OOS porovnáva 18 vopred určených adaptačných politík, každú v šiestich chronologických foldoch od 2021-01-01 do 2026-09-25. Nehodnotí najlepší dodatočne vybraný pevný variant na celom OOS.

| Kategória | Výsledok | OOS CAGR | Maximum DD | Sharpe | Calmar |
|---|---|---:|---:|---:|---:|
| A | Žiadny potvrdený víťaz 150–200 % | — | — | — | — |
| B | Žiadna politika v limitoch režimu | — | — | — | — |
| C | Žiadna politika v limitoch režimu | — | — | — | — |
| D | Žiadny platný high-return víťaz | — | — | — | — |

B je najvyšší pozorovaný CAGR pri robustnom limite 1,25× a DD ≤25 %. C je vopred deklarovaný výber podľa najvyššieho Calmar z rizikovo prípustného agresívneho OOS Pareto frontu. Ide o opisné historické porovnanie; neposúva zmrazené forward nominácie.

Najvyšší OOS CAGR zo všetkých 18 politík: **9.04 %**, DD **66.86 %**, `aggressive_2.5__calmar`. Počet politík s CAGR aspoň 150 %: **0**. Počet prechodov všetkých numerických high-return podmienok: **0**.

Najlepší nameraný kandidát v robustnej skupine podľa CAGR: **6.50 % / DD 71.81 %**. Je vyradený pre drawdown. Najnižší drawdown zo všetkých politík: **35.96 %**, pri CAGR **3.49 %**. Ani tento výsledok neprešiel. Prípustný Pareto front je prázdny; žiadny z nasledujúcich diagnostických príkladov sa nepovyšuje na víťaza.

## Pozorovaná hranica výnosu a drawdownu

| Režim | Povolený DD v tomto porovnaní | Najlepší pozorovaný CAGR | Skutočný DD | Politika |
|---|---:|---:|---:|---|
| robust | 20.00 % | žiadna | — | — |
| robust | 25.00 % | žiadna | — | — |
| robust (mimo robustného DD limitu) | 30.00 % | žiadna | — | — |
| robust (mimo robustného DD limitu) | 35.00 % | žiadna | — | — |
| aggressive | 20.00 % | žiadna | — | — |
| aggressive | 25.00 % | žiadna | — | — |
| aggressive | 30.00 % | žiadna | — | — |
| aggressive | 35.00 % | žiadna | — | — |

Táto hranica platí pre zmrazený priestor testov. Nie je dôkazom globálneho maxima trhu. Ak vyšší limit expozície nepridal výnos, tabuľka ho za výhodu nepovažuje. Cena vyššieho výnosu sa dá tvrdiť iba tam, kde ju ukazuje konkrétna dvojica zmeraných výsledkov; z týchto behov nemožno dopočítať, koľko páky by spoľahlivo prinieslo 150 %.

Konkrétny pozorovaný kompromis: prechod z 3.49 % na 9.04 % CAGR znamenal zvýšenie DD z 35.96 % na 66.86 % (+30.90 percentuálneho bodu). Obe politiky sú pri dvojnásobných nákladoch stratové. Ani uvoľnenie DD na túto úroveň sa k cieľu 150 % nepriblížilo.

## Samostatné expozičné režimy

| Režim | Politika growth: CAGR | DD | Maximum skutočnej expozície | Ročný turnover | Ročný súčet nákladov / equity |
|---|---:|---:|---:|---:|---:|
| robust 1.25× | 2.99 % | 76.11 % | 1.1418× | 44.53× | 10.00 % |
| aggressive 1.25× | 0.19 % | 74.17 % | 1.1437× | 43.98× | 10.42 % |
| aggressive 1.5× | 1.40 % | 74.64 % | 1.3783× | 45.70× | 10.86 % |
| aggressive 2× | 7.27 % | 68.40 % | 1.8484× | 52.36× | 12.44 % |
| aggressive 2.5× | 3.23 % | 73.91 % | 2.3209× | 52.72× | 12.46 % |
| aggressive 3× | 3.21 % | 73.81 % | 2.6015× | 53.00× | 12.52 % |

Turnover je súčet zobchodovaného notionalu / equity za rok. Nákladový údaj je súčet eventových nákladových podielov za rok, nie presný rozdiel CAGR medzi beznákladovým a nákladovým modelom.

## Stresy a stabilita vyradených diagnostických referencií

### robust_1.25__calmar

- CAGR pri 2× poplatkoch, sklze a fundingu: **-2.85 %**.
- CAGR pri vstupe o jeden realizovateľný bar neskôr: **9.05 %**.
- Bez najlepšieho dňa: **4.15 %**; bez top 3 obchodov: **-6.39 %**.
- Najväčší podiel aktíva na čistom log raste: **156.69 %**; obchodu: **96.15 %**.
- Podiel nad 100 % znamená, že zisky daného aktíva/obchodu čiastočne vymazali straty ostatných; menovateľom je čistý logaritmický rast.
- Ziskové foldy: **4/6**; najhorší fold **-28.25 %**; susedia **3/6**.
- Nesplnené numerické high-return podmienky: `cagr, max_drawdown, sharpe, calmar, without_best_day_cagr, without_top_three_trades_cagr, double_cost_cagr, asset_log_growth_share, trade_log_growth_share, profitable_fold_fraction, parameter_neighbors`.

| Fold | Zvolený variant | Čistý výnos foldu | Max. DD foldu |
|---|---|---:|---:|
| 2021 | m21_own200_v60_combo50 | 76.19 % | 40.04 % |
| 2022 | m63_market200_v60_rotation | -10.06 % | 22.22 % |
| 2023 | m21_market200_v60_trail2 | -28.25 % | 59.84 % |
| 2024 | m126_own100_v20_trail4 | 4.39 % | 19.84 % |
| 2025 | m126_own200_v20_cat4 | 11.97 % | 13.55 % |
| 2026 | m126_own200_v20_cat3 | 7.94 % | 10.25 % |

### robust_1.25__defensive

- CAGR pri 2× poplatkoch, sklze a fundingu: **-1.57 %**.
- CAGR pri vstupe o jeden realizovateľný bar neskôr: **3.16 %**.
- Bez najlepšieho dňa: **2.32 %**; bez top 3 obchodov: **-1.51 %**.
- Najväčší podiel aktíva na čistom log raste: **150.95 %**; obchodu: **61.79 %**.
- Podiel nad 100 % znamená, že zisky daného aktíva/obchodu čiastočne vymazali straty ostatných; menovateľom je čistý logaritmický rast.
- Ziskové foldy: **3/6**; najhorší fold **-13.04 %**; susedia **3/6**.
- Nesplnené numerické high-return podmienky: `cagr, max_drawdown, sharpe, calmar, without_best_day_cagr, without_top_three_trades_cagr, double_cost_cagr, asset_log_growth_share, trade_log_growth_share, profitable_fold_fraction, parameter_neighbors`.

| Fold | Zvolený variant | Čistý výnos foldu | Max. DD foldu |
|---|---|---:|---:|
| 2021 | m21_own200_v20_combo50 | 22.74 % | 16.14 % |
| 2022 | m63_market200_v20_tp50 | -3.33 % | 7.96 % |
| 2023 | m21_market200_v20_combo50 | -13.04 % | 28.61 % |
| 2024 | m126_own200_v20_combo50 | 11.71 % | 14.26 % |
| 2025 | m126_own200_v20_combo25 | -2.19 % | 16.28 % |
| 2026 | m126_own200_v20_cat3 | 7.94 % | 10.25 % |

### aggressive_2.5__calmar

- CAGR pri 2× poplatkoch, sklze a fundingu: **-0.78 %**.
- CAGR pri vstupe o jeden realizovateľný bar neskôr: **5.73 %**.
- Bez najlepšieho dňa: **5.13 %**; bez top 3 obchodov: **-6.68 %**.
- Najväčší podiel aktíva na čistom log raste: **149.97 %**; obchodu: **83.33 %**.
- Podiel nad 100 % znamená, že zisky daného aktíva/obchodu čiastočne vymazali straty ostatných; menovateľom je čistý logaritmický rast.
- Ziskové foldy: **4/6**; najhorší fold **-22.00 %**; susedia **5/6**.
- Nesplnené numerické high-return podmienky: `cagr, max_drawdown, sharpe, calmar, without_best_day_cagr, without_top_three_trades_cagr, double_cost_cagr, asset_log_growth_share, trade_log_growth_share, profitable_fold_fraction, parameter_neighbors`.

| Fold | Zvolený variant | Čistý výnos foldu | Max. DD foldu |
|---|---|---:|---:|
| 2021 | m21_own200_v60_cat4 | 66.87 % | 41.12 % |
| 2022 | m126_market200_v60_rotation | 0.00 % | 0.00 % |
| 2023 | m21_market200_v60_trail2 | -22.00 % | 56.91 % |
| 2024 | m126_own100_v20_trail4 | 4.39 % | 19.84 % |
| 2025 | m126_own200_v20_cat4 | 11.97 % | 13.55 % |
| 2026 | m126_own200_v20_cat3 | 7.94 % | 10.25 % |

## Audity a nový sealed interval

Rozšírený anti-lookahead a asset-lineage audit prebehol pre všetkých 18 politík: prepočet indikátorov z odrezaného prefixu, zmena budúcich cien, kontrola D+2 dostupnosti, konkrétneho aktíva a OHLC fillov, logaritmického PnL a samostatné účtovanie quantity × zmena ceny mínus náklady. Detailné výsledky sú v `results/expanded_audits.json` a `results/verification.json`.

Historický sealed test neexistuje. Výnosy sú podmienené pevným survivor universe a spotovým/funding proxy; nezávislá historická identita obchodovateľných derivátov, likvidita a venue funding nie sú preukázané. Tieto dôkazové podmienky zostali neúspešné, aj keby numerický výsledok prekročil cieľ.

Zmrazené forward nominácie: `{"A": null, "B": "robust_1.25__calmar", "C": "aggressive_3__calmar"}`. Sú to nominácie z development fázy, ktoré neprešli OOS limitmi; zostávajú len diagnostickými paper kandidátmi, nie schválenými finalistami. Prospektívny paper interval je 2026-09-27 až 2027-09-26, bez refitu. Stav po zmrazení je WAITING_FOR_FUTURE_DATA; žiadne budúce výsledky neboli vygenerované.

Úplná [Pareto tabuľka](results/pareto_table.csv), [všetky politiky](RESULTS.md), [equity krivky](results/equity_curves.png), [Pareto graf](results/pareto_frontier.png), [reprodukčné príkazy](README.md) a [technický audit](AUDIT.md).
