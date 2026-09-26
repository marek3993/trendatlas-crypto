# TrendAtlas — oprava route identity a overenie bez obchodovania

Čerstvý výsledok pre uzavretý UTC deň **2026-09-25 je LTC 1,25×**. Kanonický service skončil **PREFLIGHT_READY**; nebola odoslaná, zrušená ani upravená objednávka a nemenila sa páka. Živá reconciliácia ani merge do main neprebehli.

| Pole | Čerstvý výsledok |
|---|---|
| route_type | BASE |
| base_economic_asset | LTC |
| candidate_asset | AVAX |
| candidate_trigger_active | false |
| resolved_execution_asset | LTC |
| target exposure | 1.25 |
| signal_available_at | 2026-09-26T14:59:40.296799+00:00 |
| resolution_reason | same_interval_base_holding |

LTC vyplynulo z nového výpočtu po fast refreshi. Nebolo vložené ako výnimka ani odvodené z aktuálnej pozície účtu. Production Core, normalizovaný execution intent a dashboardový modelový signál majú zhodné aktívum aj expozíciu. Reálny účet zostal samostatne zobrazený ako AVAX.

## Presná príčina a pôvod AVAX

Áno, evidencia podporuje záver, že aktuálna AVAX pozícia bola otvorená z chybného labelu. Pôvodný kanonický beh `prod_20260926T101542Z_354970` pre deň 2026-09-25 vykonal ROTATE na AVAX 1,25×, skončil FILLED_AND_ALIGNED a uvádza real_order_sent=true. Kauzálny audit a čerstvá opravená derivácia identifikujú pre tento deň BASE LTC a neaktívneho kandidáta AVAX. Ide o chybu vstupného modelového cieľa, ktorú executor nasledoval.

`load_governance_paper` uprednostnil weekly `chosen_asset`; `build_portfolio_exposure_frame` potom každým neprázdnym kandidátom prepísal `portfolio_held_asset`, hoci `executed_regime=BASE` a return zostal z BASE vetvy. Phase63 navyše pri BASE posúval názov aktíva druhýkrát, zatiaľ čo BASE return už patril aktuálnemu ekonomickému intervalu.

Staré vrstvy zároveň aplikovali informácie z uzavretia dňa na return toho istého dňa a BASE net return označovali ako gross. Nová produkčná cesta používa pôvodné parametre a rozhodovacie pravidlá, ale ekonomické aktívum odvodzuje explicitne a výnos počíta z cien až po dostupnosti signálu. Kandidátske vylúčenie LTC/SOL zostáva pravidlom výberu kandidáta; neprepisuje BASE.

## Presný náhľad EXIT / ENTRY

Posledný overovací beh: `prod_20260926T145857Z_593402`, 2026-09-26T14:58:57Z až 2026-09-26T15:00:33Z.

1. **Reduce-only SELL 9,58 AVAX**. Preflight pozoroval mark 11,039 USD a približný notional 105,75362 USD. Bez plánovaného rušenia objednávok: `cancelOrderIds=[]`.
2. Po prípadnom skutočnom exite potvrdiť výsledok z burzy, znovu načítať účet a otvorené objednávky a overiť nulovú starú pozíciu. V tomto overení k exitu nedošlo.
3. Z nového equity, disponibilnej marže, cien a metadát prepočítať cieľový notional `equity × 1,25` a množstvo LTC podľa aktuálnej presnosti trhu.
4. **ENTRY LTC** iba podľa takto prepočítaného plánu. Číselný náhľad pred exitom bol **1,45 LTC**, cieľový notional **106,3985175 USD**, pri pozorovanom equity **85,118814 USD**. Toto množstvo je podmienený náhľad, nie fixné množstvo na neskoršie odoslanie. Výsledné post-exit equity ani fill sa nepredstierajú. Ak nový vstup nebude možný, potvrdený EXIT zostáva platný a účet sa nevracia do AVAX.

Následné read-only načítanie účtu v 2026-09-26T15:00:31Z potvrdilo **9,58 AVAX**, 0 otvorených objednávok a equity **85,166714 USD**. Rozdiel equity medzi čítaniami je zmena ocenenia existujúcej pozície; nie výnos vykonaného obchodu počas overenia.

## SOURCE OF TRUTH a contract impact

Klasifikácia **B/C/D**. Najskôr bol zmenený a validovaný zdrojový kontrakt, potom selector/adaptér, Production Core, intent, exekučné hranice a dashboard/performance.

- `production_route_identity_contract.json` vyžaduje sedem route/availability polí, identitu konkrétneho aktíva a izoláciu problémov nového vstupu.
- `causal_model_performance_contract.json` viaže produkčný modelový index na kauzálny intervalový ledger. Výnos historického intervalu patrí jeho vlastnému dostupnému signálu; novší aktuálny cieľ spätne nemení tento interval.
- `production_asset_universe_contract.json` odvodzuje podporu z ekonomických BASE/governance výstupov, zodpovedajúcich cien a aktuálnych Hyperliquid metadát. Neexistuje nový ručný zoznam kryptomien.
- `production_execution_contract.json` a relevantný runtime boli prevzaté z už nasadeného Pi commitu `5ee031cef7de9c385056cec22f6511391d3e4f4f`, aby oprava na staršom main/audit základe nevrátila staré allowlisty alebo správanie pred EXIT/read-back/ENTRY. Presný pôvod súborov a hashe obsahuje [runtime_baseline_files.json](runtime_baseline_files.json).
- SSOT JSON, master state, current issues, Pi workflow a canonical registry odkazujú na tento kontrakt. Status opravy je kód na review/no-submit, bez aktivácie živých obchodov.
- No-submit nevolá ani databázové mutačné callbacky pri zlyhanom preflight-e. Existujúca schéma databázy, používateľské prihlásenie a frontend sa nemenili.

Parametre stratégie sa neoptimalizovali. Nepribudol stop-loss, trailing stop, AI/evolution beh, ďalší automatický scheduler ani schvaľovacia brána.

Nový modelový CAGR je **31,4471 %**, MDD **−40,6292 %** a celkový modelový výnos **892,7171 %** v rekonštruovanom okne. Ide o denné spot-price a funding proxy s explicitným odhadom historickej dostupnosti tam, kde chýbajú runtime logy. Reálne account PnL pochádza z burzového účtovníctva.

## Pi overenie a zachovanie produkcie

Kód bol pripravený v `/opt/trendatlas_route_review_20260926`. Jednorazová `/run/systemd/system/mrv1-route-review-20260926.service` používa konfiguráciu kanonickej služby, existujúci runtime a serverové nastavenia; mení pracovný koreň a vynucuje `run_trendatlas_production.py --no-submit`. Nemá timer. Pôvodný `/opt/market_regime_v1` bol pre overovaciu službu read-only.

Overovacia kópia obsahuje kód opravy na zachovanom nasadenom runtime 5ee031c. Jej Git HEAD a snapshot provenance sú `ed157cc0dfcc2031dbea91c690b1b15d25fcabd1`. Presné bajty 79 prenesených source súborov zachytáva [code_manifest.json](code_manifest.json); [commit_verification.json](commit_verification.json) dokladá 75 priamych zhôd a štyri rozdiely iba v normalizácii CRLF/LF Gitom (dva JSON kontrakty a dva textové súbory).

Prešli fast refresh, precheck, nový build/validácia, čerstvý account read, signer/authorization preflight, intent, gate, data health, reconciliation, read-back a dashboard. EXECUTE bol vynechaný, authority publish bol SKIPPED_NO_SUBMIT, `heavy_refresh_steps=skipped`, `live_order_chain=NOT_INVOKED`, `real_order_sent=false`.

Prvý overovací pokus odhalil starý synthetic BASE dependency rebuild a skončil ešte v REFRESH_DATA. Táto závislosť bola odstránená z novej cesty a dostala regresiu. Nasledujúci úplný beh aj finálny beh viazaný na uvedený commit prešli. Žiadny pokus nemal povolené odosielanie objednávok.

Aktuálne Hyperliquid `metaAndAssetCtxs` potvrdili všetkých 11 odvodených obchodovateľných kryptomien vrátane LTC a SOL; spolu s CASH ide o 12 cieľov; **312 rotačných plánov prešlo**, `unsupportedAssets=[]`. Testy navyše dokazujú, že chýbajúca podpora nového symbolu nebráni podporovanému reduce-only exitu starej pozície.

Desať kontrolovaných pôvodných runtime/journal/authority súborov má nezmenené hashe. Nastavenia produkčnej služby a timeru sa nezmenili. Pôvodný checkout zostal na 5ee031c; aktuálna pozícia zostala AVAX. Produkčný service je inactive/dead po úspešnom behu, timer je **enabled, active/waiting, Persistent=yes**, nasledujúci termín **2026-09-27 02:10 CEST**. Timer stále používa pôvodný produkčný kód; oprava je pripravená oddelene a nebola aktivovaná.

## Regresie, validačné príkazy a forbidden old path

Kompletné príkazy a výsledky sú v [validation_results.json](validation_results.json): hlavná Python sada **165 PASS**, finálna route sada **15 PASS**, zmrazený kauzálny replay **19 PASS**, ďalšia SSOT/registry/fast-workflow sada **33 PASS**, TypeScript **126 PASS**, typecheck a git diff check PASS. Počty jednotlivých príkazov sa čiastočne prekrývajú.

Dve staré kontroly `tests.test_output_registry_allowed_values` zlyhávajú aj na nezmenenom základe e3b0ea4: ich enumy nepoznajú dávno existujúce hodnoty registrov. Tieto dve kontroly nie sú označené ako úspešné a nesúvisia s novou route zmenou. Ostatné spustené kontroly po správnej príprave offline replay fixtures prešli.

Regresie pokrývajú BASE LTC/AVAX, TRX/DOGE, SOL a ľubovoľný nový symbol, aktívny CANDIDATE, BTC, CASH/0, rovnosť intentu/Core/dashboardu, vlastnú signal lineage každého výnosového intervalu, odmietnutie same-day performance, rotácie, EXIT pri nepodporovanom ENTRY, starý Phase63 double shift a úplnú absenciu mutačných callbackov v no-submit. Starý neprázdny `chosen_asset` override a native same-day Phase68 dependency už nie sú autoritou novej produkčnej cesty.

## FILES READ, presné zmeny a Git

- [FILES_READ.json](FILES_READ.json): povinné SSOT poradie, Pi runbook, audit a prečítané zdroje.
- [FILES_CHANGED.txt](FILES_CHANGED.txt): presný zoznam všetkých zmenených/pridaných súborov voči e3b0ea4.
- [CODE_GIT_ADD.txt](CODE_GIT_ADD.txt): presný `git add` zoznam 95 súborov implementačného commitu.
- [EVIDENCE_GIT_ADD.txt](EVIDENCE_GIT_ADD.txt): presný zoznam následného dokumentačného commitu.
- Príkaz pre implementačné stage: `git add --pathspec-from-file=validation/route_identity_20260926/CODE_GIT_ADD.txt`.
- Commit message: `Fix production route identity and causal performance accounting`.
- **commit hash:** `ed157cc0dfcc2031dbea91c690b1b15d25fcabd1` — presne tento kód uvádza úspešný Pi snapshot.
- Pushnutá vetva: `codex/production-route-identity-20260926`. Následný commit dopĺňa iba tieto dôkazy; nemení testovaný runtime.
- Bez merge do main, bez zmeny pôvodného používateľského pracovného checkoutu, bez manuálnych editácií alebo commitov `outputs/*`/`data/*`.

Podrobný strojovo čitateľný dôkaz: [pi_no_submit_evidence.json](pi_no_submit_evidence.json). Dynamická burzová kontrola viazaná hashom na ten istý snapshot: [venue_support.json](venue_support.json).

Živá reconciliácia je pripravená na posledné používateľské potvrdenie; zatiaľ nebola vykonaná.
