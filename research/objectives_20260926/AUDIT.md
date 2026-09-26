# Audit zmeny cieľov a fitness

Dátum: 2026-09-26. Klasifikácia: **D/B**. Rozsah: náhrada výskumného zadania, offline Pareto hodnotiteľ, dôkazové podmienky a regresie. Táto úloha nevykonala nový parameter sweep, walk-forward výskum, sealed vyhodnotenie ani produkčný zásah.

## FILES READ

Povinné SSOT/navigačné súbory boli načítané v predpísanom poradí; rozsiahle JSON registre boli následne prehľadané a relevantné časti znovu načítané:

1. `source_of_truth/README.md`
2. `source_of_truth/master_state.md`
3. `source_of_truth/chat_roles.md`
4. `source_of_truth/project_truth.json`
5. `source_of_truth/export_contract.json`
6. `source_of_truth/paths_registry.json`
7. `source_of_truth/current_issues.md`
8. `canonical/script_registry.json`
9. `canonical/output_registry.json`
10. `canonical/registry_workflow.md`

Ďalšie prečítané súbory, celé alebo cielené časti/search matches:

- `AGENTS.md`, `.gitignore`.
- `research/risk_overlay_20260926/contract.json`, `README.md`, `LEVERAGE_AND_ARCHITECTURE.md`, `run_audit.py`, `test_audit.py`.
- `scripts/research_os_scoring_engine_v1.py`, `research_os/policies/research_os_scoring_policy_v1.json` — vyhľadanie starého skalárneho skórovania; bez úprav.
- `analysis/original_strategy_replay_2026-09-12/VYSLEDOK.md` — historický kontext, nie nový výsledok.
- `tests/test_source_of_truth_json_valid.py`, `tests/test_script_registry_required_fields.py`, `tests/test_script_registry_paths_exist.py`.
- Nové súbory z presného zoznamu nižšie pri implementácii a validácii.
- Zo samostatného worktree `C:/Users/benda/Desktop/trendatlas_causal_baseline_20260926/`: `research/causal_baseline_20260926/DECISION.md`, `research/causal_baseline_20260926/results/comparison.json` (začiatok s metrikami), `source_of_truth/causal_model_performance_contract.json`.

Task „Obnov produkčný baseline“ bol prečítaný na dohľadanie novšieho worktree a výsledkov. Jeho staršie prevádzkové oprávnenia sa neprenášajú do tejto research úlohy. Žiadny Pi príkaz nebol plánovaný ani spustený; runtime runbook sa preto pre túto offline zmenu nepoužil.

## SOURCE OF TRUTH

Nový zdroj pre výskumné ciele: `source_of_truth/research_objectives_contract.json`, podľa výslovnej používateľovej náhrady zadania z 2026-09-26. Existujúce produkčné truth/export kontrakty zostávajú zdrojom produkčnej pravdy. Historické reporty sú dôkazy starších behov, nie víťazi nového výskumu.

Nový kontrakt povoľuje iba research. Nemení official winner, produkčný signál, účet, Pi autoritu ani scheduler. Zahrnutie do SSOT je explicitná zmena výskumných cieľov, nie povýšenie kandidáta.

## Exact root cause

Existujúci zmrazený overlay kontrakt používal výber podľa validation Calmar s CAGR aspoň 90 % baseline a víťaza podľa relatívneho zlepšenia oproti baseline. Neobsahoval novú dvojicu režimov ani kompletné absolútne high-return podmienky. Starý Research OS má samostatné skalárne skóre; nie je určený na automatické použitie pre toto nové zadanie.

Historický model s približne 176,66 % CAGR navyše nemôže slúžiť ako dôkaz splnenia cieľa: audit našiel nesúlad symbolu a ekonomického výnosu a použitie close D filtra na return D. Novšia kauzálna rekonštrukcia ukazuje 31,4471 % CAGR / 40,6292 % DD, ale stále ide o historický proxy, nie OOS/sealed víťaza. Zmena cieľa nie je dôkaz dosiahnuteľnosti.

## Exact contract impact

- Hlavný cieľ 150–200 % CAGR, DD target 20 %, acceptable 30 %, cap 35 %, Sharpe ≥1,5, Calmar ≥4 a ≥75 % kladných WF foldov.
- Robustný režim cap 1,25× / DD 25 %, bez dolnej hranice CAGR; agresívny oddelene 1,25/1,5/2/2,5/3×.
- Exposure = target gross notional/equity, nezávislé od exchange leverage; dynamická redukcia podľa volatility/režimu.
- Feasibility-first Pareto cez 15 metrík; samostatné development populácie. OOS/sealed sa nepoužíva na opätovný výber.
- Všetky požadované stress/koncentračné podmienky a automatické volanie rozšíreného auditu cez replay callback pri CAGR ≥150 %. Bez runnera/dôkazov sa nevyhlási finalista.
- Hash binding zahŕňa dáta, kód, parametre, kontrakt, metriky a nominácie. Chýbajúce dôkazy, zmena metriky alebo nominácie, NaN a neplatné jednotky blokujú prijatie.
- Stop/TP/reentry/rotation požiadavky sú výskumný kontrakt. V tejto zmene sa neimplementoval ani neotestoval nový obchodný stavový automat.
- Vymedzené A/B/C/D; D môže koexistovať s B/C. Nenájdený high-return víťaz neznamená dokázanú nemožnosť cieľa.

## Exact files changed

1. `source_of_truth/research_objectives_contract.json` — nový zdroj výskumného zadania.
2. `source_of_truth/README.md` — odkaz na nový kontrakt a hranicu oprávnenia.
3. `canonical/script_registry.json` — zaregistrovaný offline hodnotiteľ; stdout, žiadne generované output súbory.
4. `scripts/research_objectives.py` — Pareto poradie, numerické a dôkazové kontroly, callback rozšíreného auditu a A/B/C/D pre zmrazených nominantov.
5. `tests/test_research_objectives.py` — 23 nových regresií; syntetické testovacie fixtures.
6. `research/objectives_20260926/README.md` — úplné vysvetlenie zadania, rozhrania, obmedzení a stavu výsledkov.
7. `research/objectives_20260926/AUDIT.md` — tento audit.
8. `research/objectives_20260926/GIT_ADD.txt` — presný staging zoznam.

## Regression test added/updated

23 testov kontroluje hranice každého numerického gate v OOS aj sealed, robustného kandidáta pod 150 %, DD 70 % pred Pareto rankingom, skutočný turnover tradeoff, oddelené populácie, nezávislosť výberu od sealed/OOS, nulové a stratové foldy, skutočnú account exposure namiesto 10× settingu, hash binding, starý kontrakt, zmenené metrics/nominácie, chýbajúci seal, audity bez súborov, neúspešný replay a A/B/C/D bez vymysleného víťaza.

Tieto testy overujú pravidlá hodnotenia. Nedokazujú výkon obchodnej stratégie ani vykonanie vedeckých auditov na reálnych trhových dátach.

## Forbidden old path checked

- Vyhľadané staré `select on validation Calmar` / `>=90% baseline CAGR` v zmrazenom overlay kontrakte. Zachované ako historická evidencia; nový hodnotiteľ ich nečíta.
- Nový hodnotiteľ neimportuje staré Research OS skóre ani produkčný adaptér, nečíta modelové `actual_held_asset`, `current_asset` alebo `effective_market_exposure` ako wallet stav a neodvodzuje reálny PnL z model equity.
- Žiadna úprava `app.py`, frontendov, `scripts/execution/`, `data/`, `outputs/`, autoritatívnych snapshotov, timerov alebo burzových nastavení.
- Pracovný strom už pred úlohou obsahoval početné zmeny dát a outputov aj untracked výskum. Neboli zaradené do tohto zoznamu ani upravované touto úlohou.
- Nespustený refresh, full-refresh, publish ani live-order chain.

## Validation commands/results

1. Priamy parse a assertions nového source kontraktu **pred úpravou consumer kódu** — PASS: ciele, oba režimy, limity, 15 Pareto metrík a nulové produkčné oprávnenie.
2. `python -m unittest discover -s tests -p test_research_objectives.py -v` — **23 PASS**.
3. `python -m unittest discover -s tests -p 'test_script_registry*.py' -v` — **5 PASS**.
4. `python -m unittest discover -s tests -p test_source_of_truth_json_valid.py -v` — **6 PASS**.
5. `git diff --check -- source_of_truth/README.md canonical/script_registry.json` — **PASS**; Git upozorňuje na lokálne LF/CRLF nastavenie.
6. Kontrola whitespace, Python AST, JSON a presného osemsúborového zoznamu — **PASS**. SHA256 starého zmrazeného overlay kontraktu stále súhlasí s pôvodným input manifestom. `python scripts/research_objectives.py --help` — **PASS**.

Globálny `git diff --check` bol tiež spustený a našiel trailing whitespace v už existujúcich zmenených generovaných CSV pod `outputs/`. Neboli opravované; kontrola celého cudzieho pracovného stromu sa nevydáva za čistú. Relevantné 34 testy prešli.

## Exact git add list

Presne osem ciest vyššie je uložených v `research/objectives_20260926/GIT_ADD.txt`. Pripravený príkaz, **nevykonaný**:

```powershell
git add --pathspec-from-file=research/objectives_20260926/GIT_ADD.txt
```

Nepoužiť `git add .`, pretože by zahrnul nesúvisiace dáta, outputy a predchádzajúci výskum.

## Commit message

Navrhnutý: `research: replace objectives with gated robust and aggressive Pareto evaluation`

## Commit hash

**Commit nebol vytvorený.** Zmeny sú lokálne a nestagované. Nič nebolo pushnuté, mergnuté alebo nasadené.

## Aktuálny verdikt

A: nepreukázaný. B/C: neurčené bez nového experimentu. D: žiadny preukázaný platný víťaz s dodanými dôkazmi. Dostupné reporty neurčujú globálnu realistickú hranicu CAGR ani cenu dosiahnutia 150–200 %. Potrebný je samostatný zmrazený experiment s kauzálnymi vstupmi, nákladmi, oddelenými režimami a nepoužitým sealed obdobím. Nižší historický CAGR sa nestáva novým cieľom.
