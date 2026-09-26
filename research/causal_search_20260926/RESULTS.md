# Skutocne vykonany offline vyskum

1 944 nominalnych kombinacii v siestich oddelenych rozpoctoch; 3 888 development stresovych prehrati. Kazda OOS politika ma navyse 2x naklady, +1 bar a sest susednych prehrati. Ziadne nahodne alebo dodatocne hladanie po vysledkoch.

**Ciel 150-200 % CAGR sa nemeni. Ziadny vysledok tu nie je realny account PnL ani sealed dokaz.**

| Politika | OOS CAGR | Max. event DD | Sharpe | Calmar | Ziskove foldy | Risk limity |
|---|---:|---:|---:|---:|---:|---|
| robust_1.25__growth | 2.99% | 76.11% | 0.25 | 0.04 | 67% | False |
| robust_1.25__calmar | 6.50% | 71.81% | 0.36 | 0.09 | 67% | False |
| robust_1.25__defensive | 3.49% | 35.96% | 0.31 | 0.10 | 50% | False |
| aggressive_1.25__growth | 0.19% | 74.17% | 0.19 | 0.00 | 33% | False |
| aggressive_1.25__calmar | 5.38% | 69.51% | 0.32 | 0.08 | 50% | False |
| aggressive_1.25__defensive | 3.49% | 35.96% | 0.31 | 0.10 | 50% | False |
| aggressive_1.5__growth | 1.40% | 74.64% | 0.23 | 0.02 | 33% | False |
| aggressive_1.5__calmar | 1.91% | 74.64% | 0.22 | 0.03 | 50% | False |
| aggressive_1.5__defensive | 3.49% | 35.96% | 0.31 | 0.10 | 50% | False |
| aggressive_2__growth | 7.27% | 68.40% | 0.37 | 0.11 | 50% | False |
| aggressive_2__calmar | 7.69% | 68.40% | 0.39 | 0.11 | 67% | False |
| aggressive_2__defensive | 3.49% | 35.96% | 0.31 | 0.10 | 50% | False |
| aggressive_2.5__growth | 3.23% | 73.91% | 0.28 | 0.04 | 33% | False |
| aggressive_2.5__calmar | 9.04% | 66.86% | 0.43 | 0.14 | 67% | False |
| aggressive_2.5__defensive | 3.49% | 35.96% | 0.31 | 0.10 | 50% | False |
| aggressive_3__growth | 3.21% | 73.81% | 0.28 | 0.04 | 33% | False |
| aggressive_3__calmar | 3.97% | 73.81% | 0.28 | 0.05 | 67% | False |
| aggressive_3__defensive | 3.49% | 35.96% | 0.31 | 0.10 | 50% | False |

Pozorovany najlepsi robustny kandidat: `None`.
Pozorovany agresivny Pareto kompromis: `None`.

Politiky, ktore presli vsetkymi ciselne meratelnymi OOS high-return podmienkami: [].
**A: ziadny platne potvrdeny sealed vitaz. D: plati.** B/C su podmienene historicke proxy vysledky.

Forward nominacie boli zvolene z development dat pred vypoctom OOS metrik a su ine pole ako popisny OOS rebricek. OOS vitaz ich automaticky nenahradza.
Zmrazene forward nominacie: `{"A": null, "B": "robust_1.25__calmar", "C": "aggressive_3__calmar"}`.

## Stresy pozorovanych referencii (pri nesplneni limitov su vyradene)

| Politika | Zakladny CAGR | 2x naklady | +1 realizovatelny bar | Bez najlepsieho dna | Bez top 3 obchodov | Koncentracia aktivum / obchod | Susedia |
|---|---:|---:|---:|---:|---:|---:|---:|
| robust_1.25__calmar | 6.50% | -2.85% | 9.05% | 4.15% | -6.39% | 156.7% / 96.1% | 3/6 |
| robust_1.25__defensive | 3.49% | -1.57% | 3.16% | 2.32% | -1.51% | 151.0% / 61.8% | 3/6 |
| aggressive_2.5__calmar | 9.04% | -0.78% | 5.73% | 5.13% | -6.68% | 150.0% / 83.3% | 5/6 |

## Rozsah zaveru

Krivky obsahuju 6 chronologickych OOS foldov od 2021 do 2026 (posledny je neuplny). Parametre kazdeho roka sa volia z predchadzajuceho validation roka cez Pareto a vopred urcenu selection funkciu. Pri nulovom platnom vybere sa drzi CASH. Indikatory mozu pouzit iba starsie data; fill je najskor D+2 open.
MDD v tabulke zahrna intradenne OHLC eventy. Spodny panel equity grafu ukazuje denny close DD; jeho minimum preto moze byt mensie nez tabulkovy event DD.
Rozsirene audity sa realne vykonali pre vsetkych 18 politik, aj pod 150 %. Subor expanded_audits.json rozlisuje prejdene price-causality/lineage kontroly od chybajucich historickych venue/PIT-universe dokazov.
Funding je konzervativny proxy debit 12 % rocne z celeho opening notionalu, poplatok 4,5 bp a sklz 10 bp na kazdu zobchodovanu stranu. Nie su to historicke Hyperliquid fills/funding. Preto sa vysledok nemoze vydavat za vykonatelny venue-specific dokaz.
Universe je pevnych 12 existujucich minci; 252-bar admission riesi dostupnost dat, nie survivorship delistovanych aktiv. Historicke data uz boli pouzite v predoslom vyskumne.
Tabulka je pozorovana hranica tohto zmrazeneho priestoru a predpokladov, nie globalna maximalna dosiahnutelnost. Vyssia expozicia sa neposudzuje ako nova zasluha signalov; jej cenu vidno v DD, nakladoch a stresoch.
Nepouzite historicke sealed data neboli predstierane. Forward-sealed paper plan je pripraveny pre 2026-09-27 az 2027-09-26; nic sa neposiela na burzu.

## Reprodukcia

```powershell
python -m pip install -r research/causal_search_20260926/requirements.txt
python -m unittest discover -s research/causal_search_20260926 -p "test_*.py" -v
python research/causal_search_20260926/run.py --out scratch/reproduction --cache scratch/reproduction_cache
python research/causal_search_20260926/finalize.py --out scratch/reproduction
python research/causal_search_20260926/render.py --out scratch/reproduction --report scratch/reproduction/RESULTS.md
python research/causal_search_20260926/paper.py --init
python research/causal_search_20260926/paper.py --prices-dir path/to/new_daily_bars
```

inputs.zip a pre_registration.json su commitnute. Reprodukcia nepotrebuje ine worktree, siet ani produkcne outputs. --init nevytvori nove nominacie, ak forward seal uz existuje; overi jeho hashe.
