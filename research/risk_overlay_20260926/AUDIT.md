# Audit research balíka

## FILES READ

Pôvodný checkout: povinné súbory boli prečítané pred analýzou. Po zistení novšieho main boli skontrolované ich zmeny a aktuálne runtime kontrakty; research checkout stojí na aktuálnom main 6fccbc388c1db75f6b46113fac15b7d3232e4123. AGENTS.md je v oboch rovnaký.

- `AGENTS.md`
- `source_of_truth/README.md`
- `source_of_truth/master_state.md`
- `source_of_truth/chat_roles.md`
- `source_of_truth/project_truth.json`
- `source_of_truth/export_contract.json`
- `source_of_truth/paths_registry.json`
- `source_of_truth/current_issues.md`
- `canonical/script_registry.json`
- `canonical/output_registry.json`
- `canonical/registry_workflow.md`
- `source_of_truth/pi_codex_runtime_workflow.md`

Ďalšie čítané zdroje: produkčný ETF adaptér, BTC-persistence a 1,25× adaptéry, build_current_strategy_snapshot.py, staged_candidate_promotion_support.py, approved_strategy_net_export_helper.py, ETF probe/cooldown/rebuild moduly, phase66g_production_candidate_live.py a jeho manifest/asset quality, aktuálny production_execution.py, run_trendatlas_production.py, submit_controlled_real_order.py, hyperliquid_read_only_snapshot.py, live_order_policy.json, tests/test_production_execution.py a vybrané pasáže run_dry_execution_bridge.py. Presné vstupné súbory sú enumerované v input_manifest.json a local_input_manifest.json; skutočne importované produkčné moduly a ich hashe v oboch run manifestoch. Binárne balíky obsahujú presné čítané verzie dát. Starší lokálny analysis/strategy_review_2026-09-12/ANALYZA_STRATEGIE.md a analysis/strategy_validation_2026-09-12/AUDIT.md slúžili iba ako kontext; ich výsledky sa neprijali bez nezávislého overenia.

Externé primárne zdroje: Hyperliquid TP/SL, margining, liquidation, funding, fees, account abstraction a info endpoint. Priame odkazy a relevantné tvrdenia sú v LEVERAGE_AND_ARCHITECTURE.md. Jednorazové /info dotazy: clearinghouseState, spotClearinghouseState, userAbstraction, userFees, meta; bez podpisov, credentialov a exchange mutation endpointu.

## SOURCE OF TRUTH

Aktuálny model určuje project_truth/export_contract: phase68g_etf_flow_impulse_early_risk_cooldown_15. Aktuálny produkčný výstup je Production Core zo vzdialeného main pre 2026-09-25. Kanonická exekúcia: run_trendatlas_production.py / production_execution.py, fresh account equity × validated target exposure. Výskumný contract.json je neautoritatívny a bol validovaný pred novými výpočtami. Výsledky neprepisujú SSOT, nezakladajú winner promotion a nie sú account PnL.

## Exact root cause

B: aktuálny publikovaný snapshot do 2026-09-25 nemá v Gite kompletný zhodný vstupný snapshot; raw BTC končí 2026-05-05 a durable BTC fallback 2026-05-08. Nezmenený adapter preto reprodukciu odmietne. Hashe odlišné iba kvôli CRLF/LF sú označené osobitne a nie sú prezentované ako semantický drift.

D: oddelený starší lokálny augustový archív sa numericky reprodukuje, ale 2024-12-03 nesie DOGE výnos TRX a ETF close filter rozhoduje o výnose toho istého dňa. BASE nemá jednoznačný rozklad na obchodované mince. Nie je dostupná kompletná Hyperliquid mark/funding história. Dôkazy sú local_results.json, local_asset_return_diagnostics.csv a detekčné testy.

C: aktuálny planner pri otvorenom stop príkaze blokuje cez conflicting_open_order. Overlay sa preto nesmie len pripojiť bez budúcej úpravy lifecycle kontraktu. Kanonický sizing je nezávislý od exchange leverage. Repo politika už má 2×, exchange AVAX má 10×; NO_ACTION nevytvára leverage-update step. Nasadená Pi policy sa nečítala; príčina driftu nie je dokázaná. Legacy spot+perp sčítavanie nie je označené za chybu aktuálnej produkčnej cesty.

## Exact contract impact

Len research package. Žiadne zmeny produkčnej matematiky, executora, API kontraktov, allowlistu, schvaľovania, timerov, account state ani authority snapshotov. Nový kontrakt explicitne rozlišuje current a local archív, reprodukciu od ekonomickej validity, chýbajúce výsledky od nuly a modelový výkon od account PnL. Offline kód nemá runtime import do produkcie. Validátor zastaví iba tento výskum; nejde o nový execution gate.

## Exact files changed

Všetky súbory sú nové a iba pod research/risk_overlay_20260926:

- `.gitattributes`
- `.gitignore`
- `AUDIT.md`
- `LEVERAGE_AND_ARCHITECTURE.md`
- `README.md`
- `contract.json`
- `exchange_readonly_capture.json`
- `frozen_inputs.zip`
- `input_manifest.json`
- `leverage_audit.py`
- `leverage_results.json`
- `local_asset_return_diagnostics.csv`
- `local_baseline_reproduced.csv`
- `local_frozen_inputs.zip`
- `local_input_manifest.json`
- `local_results.json`
- `local_run_manifest.json`
- `results.json`
- `run_audit.py`
- `run_manifest.json`
- `test_audit.py`
- `validate_research.py`
- `validation.json`

Pôvodný špinavý pracovný strom s dátami a analysis nebol revertovaný, refreshovaný ani pridaný do commitu. Aktuálny research checkout bol vytvorený izolovane z origin/main. ZIP sú research dôkazy, nie manuálne zmeny alebo commity produkčných data/outputs. Politika v execution/config ostala nedotknutá.

## Regression test added/updated

23 deterministických testov v test_audit.py. Overujú dátový mismatch, korupciu bundle, presnosť porovnania stĺpcov/dní/NaN, pozorovanú DOGE/TRX nezhodu, existujúce same-day filtrovanie na syntetickej sérii, oddelenie chybného baseline od overlay výsledkov, zákaz exchange mutation v read-only klientovi, kanonické unified equity a sizing pri 2×/10×, BTC → AVAX, AVAX → ETH, AVAX → CASH, NO_ACTION a starý leverage, margin pri policy strope a existujúci konflikt otvoreného reduce-only triggeru. Detekčné testy potvrdzujú problém, nepredstierajú produkčnú opravu. Nový overlay engine po zlyhaní baseline nebol implementovaný.

## Forbidden old path checked

outputs/execution/app_snapshot/*, outputs/app_refresh_pipeline/*, outputs/execution/full_auto_scheduler/*, outputs/execution/runtime_health/* a outputs/execution/live_status/* neboli zdrojom autority alebo náhradným baseline. Starý manual submit planner nebol považovaný za kanonický automatický executor. /opt/home_automation sa nepoužilo. Žiadne Pi SSH, publish-existing, full-refresh, live submit, cancel, leverage update alebo manuálna úprava authority snapshotu. heavy_refresh_steps=skipped, live_order_chain=not_invoked.

## Validation commands/results

- `python research/risk_overlay_20260926/validate_research.py`: PASS; oba výsledky deterministické pri opakovaní, 23/23 testov, pôvodné chránené vstupy zhodné, produkčný diff prázdny, bez siete.
- `python research/risk_overlay_20260926/run_audit.py`: očakávaný procesný exit 2, aktuálna reprodukcia odmietnutá. Nie je to úspešný backtest.
- `python research/risk_overlay_20260926/run_audit.py --source local`: očakávaný exit 2, lokálny augustový export numericky sedí, ekonomické predpoklady neprešli.
- `python research/risk_overlay_20260926/test_audit.py`: 23/23 PASS.
- `python research/risk_overlay_20260926/leverage_audit.py`: exit 0, replay uloženého capture bez siete.
- `git diff --cached --check`: kontrola whitespace pred commitom; výsledok sa uvádza v záverečnej odpovedi.
- Prvý implementačný beh lokálneho audit skriptu opravil názvy nákladových stĺpcov; prvý test harness doplnil scripts import path. Išlo o research kód, nie zmeny produkcie.

Presné logy a návratové kódy sú vo validation.json. Parametre prostredia: Python 3.12.10, pandas 3.0.2, numpy 2.4.1. Za obsah nemenných vstupov ručia SHA-256 v manifestoch.

## Exact git add list

git add -- research/risk_overlay_20260926/.gitattributes
git add -- research/risk_overlay_20260926/.gitignore
git add -- research/risk_overlay_20260926/AUDIT.md
git add -- research/risk_overlay_20260926/LEVERAGE_AND_ARCHITECTURE.md
git add -- research/risk_overlay_20260926/README.md
git add -- research/risk_overlay_20260926/contract.json
git add -- research/risk_overlay_20260926/exchange_readonly_capture.json
git add -- research/risk_overlay_20260926/frozen_inputs.zip
git add -- research/risk_overlay_20260926/input_manifest.json
git add -- research/risk_overlay_20260926/leverage_audit.py
git add -- research/risk_overlay_20260926/leverage_results.json
git add -- research/risk_overlay_20260926/local_asset_return_diagnostics.csv
git add -- research/risk_overlay_20260926/local_baseline_reproduced.csv
git add -- research/risk_overlay_20260926/local_frozen_inputs.zip
git add -- research/risk_overlay_20260926/local_input_manifest.json
git add -- research/risk_overlay_20260926/local_results.json
git add -- research/risk_overlay_20260926/local_run_manifest.json
git add -- research/risk_overlay_20260926/results.json
git add -- research/risk_overlay_20260926/run_audit.py
git add -- research/risk_overlay_20260926/run_manifest.json
git add -- research/risk_overlay_20260926/test_audit.py
git add -- research/risk_overlay_20260926/validate_research.py
git add -- research/risk_overlay_20260926/validation.json

## Commit message

`research: audit risk-overlay baseline prerequisites and leverage without production changes`

## Commit hash

Presný vytvorený commit hash a stav push sú v záverečnej odpovedi úlohy. Tento audit je súčasťou toho istého commitu; hash sa neukladá sám do seba. Vetva: codex/risk-overlay-research-20260926-current. Bez merge do main, bez deployu.
