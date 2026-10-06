# Produkčný incident — stav 6. októbra 2026

**INCIDENT_RESOLVED=false — zostáva čerstvý browser read-back.** Dnešný automatický
run `prod_20261006T001001Z_915393` pre uzavretý deň 2026-10-05 úspešne vykonal
kanonický AVAX ENTRY a skončil SUCCESS/FILLED_AND_ALIGNED. Priama burza o
16:42:28 UTC potvrdila 7.47 AVAX long, equity 85.467664 USD, expozíciu
1.000746902x a žiadne open orders. Cieľ je AVAX/1x, účet je v existujúcej
kanonickej tolerancii. Follow-up neposlal žiadnu objednávku ani nespustil run.
Chrome naďalej blokuje dashboard otvoreným UI iného rozšírenia, takže zhoda
aktuálneho prihláseného dashboardu zostáva UNKNOWN a follow-up ACTIVE.
Dôkazy: `followup-20261006.json`. Nasledujúci odsek a pôvodný audit sú zachované
ako historické pozorovania z 5. a 4. októbra; ich CASH stav už nie je aktuálny.

**INCIDENT_RESOLVED=false — zostáva iba browser read-back.** Nasledujúci automatický run po oprave bol read-only potvrdený 5. októbra 2026: `prod_20261005T001018Z_547978`, SUCCESS/NO_ACTION, bez objednávky. Systemd invocation `bdfd5bcff4bc4f2cb605479c7085fbd8` skončil exit 0 o 00:12:39 UTC; timer zostáva enabled/active. Čerstvé priame Hyperliquid overenie o 05:22:42 UTC potvrdilo 83.348433 USDC, nulové pozície a open orders. Uzavretý deň je 2026-10-04, autorizovaný cieľ CASH/0x; journal, nonce a publikovaný účet sú v zhode. Chrome však znovu blokuje automatizáciu otvoreným rozhraním iného rozšírenia. Verejný autentifikovaný dashboard preto dnes nebol potvrdený a follow-up zostáva ACTIVE. Dôkazy: `followup-20261005.json`. Zvyšok pôvodného auditu nižšie zachováva historické dôkazy zo 4. októbra.
## Živý účet a kanonický cieľ

Posledné priame burzové overenie: **2026-10-04T07:34:10.335250Z**. Master je `0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856`, nie agent. Účet používa `unifiedAccount`.

- Spot: **83.348433 USDC**, native hold 0; USDE, USDT0 a USDH majú nulový zostatok. Žiadny spot AVAX ani iné nenulové krypto aktívum.
- Equity: **83.348433 USD**, free collateral **83.348433 USD**. Natívny perp accountValue 0 nie je celkové equity unified účtu. [Oficiálny Hyperliquid kontrakt](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals) vyžaduje pri unified účte spot balances pre celkový obchodný zostatok.
- Perp pozície: **žiadne** na native ani všetkých desiatich aktuálne registrovaných HIP-3 dexoch: xyz, flx, vntl, hyna, km, abcd, cash, para, mkts, io. Súčet position notional a margin used je 0.
- Otvorené objednávky: **0** na všetkých jedenástich perp dexoch aj native spot/perp účte.
- Real exposure: **0.00x**. Reálny účet: **CASH / USDC**. Quantity: **83.348433 USDC**, AVAX quantity 0.
- Najnovší úplne uzavretý UTC deň: **2026-10-03**. Čerstvo prepočítaný a validovaný autorizovaný modelový cieľ je **CASH / 0.00x**. Kandidát zostáva **AVAX / 1.00x**, `trend_permission_active=false`, `allow_live_order_candidate=false`, `reason_code=candidate_asset_not_btc`.
- ACCOUNT_ALIGNED=true. Počas opravy nebola odoslaná objednávka ani cancellation; nonce zostal **1790813499788**, action journal má stále **5** historických akcií, leases 0.

Úplné odpovede spot/perp, fills, orders, funding, non-funding ledger, sale/journal väzba, kanonický výsledok a publikačný kontrakt sú v `audit-evidence.json`. Časový začiatok auditu je 2026-09-30 14:40 UTC, konzervatívne pred aktiváciou. Časové odpovede sú menšie než stránkovací limit; history obsahuje menej než limit 2 000 udalostí. Žiadny odhad zo stratégie nebol použitý ako wallet stav.

## Predaj 7.65 AVAX a história od cutoveru

**AVAX_SELL_FOUND=true.** Jediný fill od cutoveru:

| Položka | Overený údaj |
|---|---|
| Čas fillu UTC | 2026-10-01T00:11:41.250Z |
| Asset / side / size | AVAX / sell, Close Long / 7.65 |
| Fill price / notional | 10.918 / 83.5227 USD |
| Reduce-only | true, IOC |
| Exchange order | 561784971605 |
| Skutočný CLOID | 0xd91d0679bb48242964e7922e7b861ac7 |
| Production run | prod_20261001T001018Z_507340 |
| Durable per-account journal run | c74ae2b4-4e9a-4ff0-81f3-88323a3b1864 |
| Action row | bba2bdc0-aecf-4186-9119-b99af54b1f94 |
| Action / verification | EXIT / VERIFIED |
| Canonical closed day / target | 2026-09-30 / CASH 0x |
| Closed PnL / fee | +1.56825 / 0.037585 USDC |

`orderStatus` priamo podľa CLOID je **filled**. Dve historické order udalosti `open` a `filled` majú rovnaký order/CLOID; ide o životný cyklus jednej objednávky, nie dve odoslania. Od predaja nepribudol ďalší fill. Non-funding ledger od cutoveru je prázdny; funding má 10 udalostí, súčet **-0.010463 USDC**. Žiadny vklad ani výber v tomto intervale.

**Presný dôvod predaja:** cieľ Production Core sa pre uzavretý deň 30. septembra zmenil z autorizovaného AVAX 1x na CASH 0x. Baseline FULL_RISK ani ETF EARLY_RISK vstup nepovolili. AVAX zostal kandidátom, pre ktorý ETF early-entry podmienka neplatila (`candidate_asset_not_btc`). Executor preto správne vykonal reduce-only EXIT a overil plochý účet. Nešlo o broker chybu, stratený ENTRY ani ručný predaj. Historická canonical timeseries aktuálne potvrdzuje pre 29. september AVAX 1x/permission=true, pre 30. september aj 3. október CASH 0x/permission=false.

## Produkčné služby, runy a publisher

VPS `vps-4f79db29` je jediný aktívny execution/publish host. Jediný produkčný scheduler je `mrv1-production.timer`: enabled/active, `Persistent=yes`, `OnCalendar=*-*-* 00:10:00 UTC`, bez zmeny rozvrhu. `mrv1-production.service` volá iba kanonický Python orchestrátor s backendom `multi_account`, oddeleným service userom a existujúcim chráneným EnvironmentFile. Legacy signer credential sa nemontuje. Existujúce priority hooks služby zostali nezmenené. Iný produkčný execution/publish timer nie je nainštalovaný; watchdog nie je obchodný scheduler.

| Production run | Výsledok / cieľ | Order |
|---|---|---|
| prod_20260930T144223Z_081482 | NO_ACTION / AVAX 1x; publikovanie dodatočne opravené | žiadny |
| prod_20261001T001018Z_507340 | SUCCESS, FILLED_AND_ALIGNED / CASH 0x | AVAX EXIT vyššie |
| prod_20261002T001018Z_553850 | SUCCESS, NO_ACTION / CASH 0x | žiadny |
| prod_20261003T001001Z_821721 | SUCCESS, NO_ACTION / CASH 0x | žiadny |
| prod_20261004T001018Z_485129 | SUCCESS, NO_ACTION / CASH 0x | žiadny |
| prod_20261004T073000Z_449133 | SUCCESS, NO_ACTION / CASH 0x; čerstvý run po oprave | žiadny |

Read-only systemd journal od cutoveru potvrdzuje pôvodný exit 2 pri publikačnej permission chybe 30. septembra a potom úspešné automatické invocation 1., 2., 3. a 4. októbra. Pôvodná chyba už bola odstránená pred týmto auditom, jej execution bol NO_ACTION a nebola znovu opravovaná ani prehrávaná.

Run po dnešnej oprave bol spustený autorizovanou existujúcou systemd službou, začal 07:29:58 UTC, canonical manifest začal 07:30:00 a skončil **07:32:08 UTC**. Service exit 0, Result success, NRestarts 0. EXECUTE, POST_TRADE_VERIFY, DASHBOARD_RUNTIME a AUTHORITY_PUBLISH PASSED. Ťažký refresh bol skipped. Publisher najprv vykonal `publish-existing --dry-run`, potom skutočný `publish-existing`. Najnovšia autorita má run `20261004_073143`, generated 07:32:02 UTC, current/success, closed day 2026-10-03.

Nový manifest má `execution_evidence.available=true`, journal UUID `9395a298-f83a-4359-a7e0-edc51cd2eaac`, actions/cloid/order_id prázdne. Opakovaný same-day run znovu použil existujúci canonical-signal journal UUID; nevytvoril action ani neposunul nonce. Toto je reálne overenie resume/no-duplicate v aktuálnom NO_ACTION stave. EXIT/ENTRY a nejednoznačná odpoveď sú pokryté regresiami; nový reálny EXIT/ENTRY sa nevynucoval, pretože čerstvý cieľ je CASH.

## Presná príčina a dopad kontraktu

Incident je triedy **B + C**. Rozdiel CASH/0x vs AVAX/1x nevznikol exekučným zlyhaním: zamieňal sa kandidát s autorizovaným cieľom. Dashboard CASH bol v zhode s burzou aj autorizovanou stratégiou. Žiadna stratégia ani obchodný target sa nemenili.

Skutočná nájdená chyba bola v **order identity audite**: Python orchestrátor pri RECONCILE zapísal CLOID svojho pomocného plánu. Aktívny TypeScript executor používa vlastný account/signal/action CLOID a per-account durable journal. Jeho child report obsahoval len výsledný status, takže Python preview CLOID zostal v terminalnom manifeste a exchange order ID zostal null. Predajový manifest preto nesprávne uvádza `0x8c1297e3ef5f1f8f59d440d9383d09d1`; burza a journal jednoznačne dokazujú `0xd91d0679bb48242964e7922e7b861ac7`.

Najprv bol rozšírený a validovaný `production_execution_contract.json::execution_evidence`. Potom executor dostal sanitizovaný read-only receipt z vlastného journalu: run UUID, CLOID, exchange order ID, submission a verification state. Orchestrátor teraz preberá výhradne owner receipt, nikdy preview. Neodoslané návrhy a cancellation identifikátory nevydáva za nové order identity. Neprístupný receipt je explicitne unknown; zachová terminalný execution outcome a nič znovu neodosiela. No-submit nevydáva preview za live journal receipt.

**Historický manifest ani autoritatívne snapshoty sa ručne neprepisovali.** Správnu historickú väzbu zachováva tento audit a burza/journal. Nové manifesty už používajú opravenú cestu.

## Dashboard a otvorené záverečné overenie

V Chrome profile používateľa bola 07:28 UTC otvorená https://trendatlas-accounts.vercel.app/dashboard, účet Marek Benda/master končiaci e856. Viditeľné: CASH, Out of market, OPEN POSITIONS 0, OPEN ORDERS 0, REAL EXPOSURE None, TOTAL ACCOUNT VALUE $83.35, DATA SOURCE Live Hyperliquid read-only API. To sa zhoduje s presným burzovým stavom 83.348433 USDC.

Po tejto kontrole Chrome zablokoval ďalšiu automatizáciu otvoreným UI iného rozšírenia. Používateľ dostal konkrétnu požiadavku zavrieť ho. Verejne hostovaná stránka nebola po oprave znovu načítaná; burza však po oprave potvrdila rovnaký účet, bez akéhokoľvek nového order/fillu. Čerstvý publikovaný `dashboard_public_status` má správny real_account CASH/0 a model_target_state CASH/0, oddelene od model_signal AVAX/1. Žiadny frontend bol zmenený.

Task zostáva otvorený do potvrdenia automatického invocation po nasadení a finálneho browser read-backu. Follow-up nesmie začať ďalší ručný run ani objednávku, meniť harmonogram len kvôli dôkazu alebo označiť čakajúci timer za vykonaný run.

## Regresné testy a validation commands/results

Pridané regresie: durable identity vs pomocný preview; zachovanie order ID a verified CLOID pri opakovaní bez druhého orderu; null identita pri nedostupnom observation receipt bez zmeny verified outcome; filtre pre neodoslaný plán/cancellation; contract identity invariant. Predtým existujúce testy stále preverujú EXIT → fresh read-back → nové ENTRY sizing, CLOID recovery, nejednoznačné submission, account isolation a no-submit GET/HEAD-only transport.

```text
python -m unittest tests.test_dynamic_execution_source_contract tests.test_single_production_orchestrator tests.test_production_execution tests.test_post_activation_recovery -q
  Windows: 106 OK, 1 Linux-only test skipped; VPS x86: 106 OK, no skip.
node node_modules/vitest/vitest.mjs run tests/multi-account-executor.test.ts tests/canonical-execution-contract.test.ts tests/no-submit-transport.test.ts tests/production-boundary.test.ts
  Clean local checkout: 110 passed.
  Installed live VPS: 109 passed; generated-data clean-Git assertion failed.
node node_modules/typescript/bin/tsc --noEmit
  exit 0.
git diff --check / git diff --cached --check
  passed.
production_golden_replay.py --output <isolated-audit>/replayed-core.json
  3070 rows; exact frozen snapshot/history/diagnostic serialization,
  no new tolerance; unchanged planner/signer/submission/CLOID source hashes.
run_production_rehearsal.py -> canonical orchestrator --no-submit
  prod_20261004T072728Z_619563, PREFLIGHT_READY, CASH/0,
  real_order_sent=false, authority SKIPPED_NO_SUBMIT,
  canonical_files_unchanged=true, returncode 0.
systemctl start --no-block mrv1-production.service
  Authorized fresh live reconciliation: SUCCESS/NO_ACTION, no order,
  verified exchange read-back, dry-run-before-real-publish PASSED.
```

The installed VPS generated-data test executes `git diff -- data outputs` against a live runtime with existing generated changes and is not a clean-source test environment. It was not disabled or weakened. Production immutable source/deployment hashes and isolated rehearsal `canonical_files_unchanged=true` were independently verified. Tests do not claim that a real new market-entry trade occurred.

Deployment was under the existing production flock with the service inactive; only the seven reviewed source/test files were overlaid. Backups: `/var/lib/trendatlas-production/production-audit-20261004/before`. SHA256 admission evidence was updated through `write_capabilities`, preserving root:production-group 0640 and actual-service-user readability. Exact x86 replay was compared against the retained, measured ARM/x86 frozen production reference; ARM baseline date and proof remain recorded. No fresh ARM run or Pi contact is claimed. Evidence is in `deployment-evidence.txt`.

## FILES READ

Ordered: `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`; `canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`; then `source_of_truth/pi_codex_runtime_workflow.md`, `production_execution_contract.json`, `production_host_contract.json`, `AGENTS.md`.

Also read: cutover-postactivation README/final replay evidence; execution/config/execution_mode; run_trendatlas_production, migration_host_control, migration_readiness, migration_reconciliation, rehearsal_workspace, run_production_rehearsal, production_host, production_golden_replay, compare_production_replay; production-migration-readback, run-multi-account-production-cycle, production-golden-replay; executor engine/repository/types/batch and relevant tests; package/vitest configuration; production units/timer and allowlisted systemd messages; canonical manifests, account/authority/public contracts, current canonical timeseries, Supabase journal/nonce/lease evidence and live Hyperliquid Info.

Skills read: Supabase SKILL.md and computer-use SKILL.md. Supabase changelog was checked; no schema, permissions, auth or dependency changes were made. Browser was read-only. A historical migration chat was retrieved for production context; no message was sent to another chat.

## SOURCE OF TRUTH

Strategy: validated Production Core current_strategy and exact canonical intent/gate provenance. Account: fresh Hyperliquid master-account Info. Order identity/recovery: active Supabase per-account action journal and exchange orderStatus/fills. Runtime: installed canonical VPS service/timer and finalized production manifests. Publication: canonical two-file authority; app_snapshot is downstream materialization, never independent account authority. Normative contracts: production_execution_contract, production_host_contract, export_contract and current runtime workflow.

## Forbidden old path checked

No manual order or hardcoded AVAX target; no retry of the filled sale; no nonce reset/journal restore; no authority snapshot edit; no competing scheduler; no full-refresh. No use of model equity/exposure as wallet facts. Legacy app_snapshot/full_auto_scheduler/live_status/old refresh runtime fields were not used as authoritative current account evidence. No strategy math, asset allowlist, tolerances, frontend labels or consent changed. Pi was not contacted or enabled. No research or LeadPilot code/config was inspected or changed.

## Exact files changed / exact git add list

```text
git add -- source_of_truth/production_execution_contract.json scripts/execution/run_trendatlas_production.py web/src/server/multi-account-executor/engine.ts web/src/server/multi-account-executor/repository.ts tests/test_dynamic_execution_source_contract.py tests/test_single_production_orchestrator.py web/tests/multi-account-executor.test.ts
git add -- docs/production-incident-20261004/REPORT.md docs/production-incident-20261004/audit-evidence.json docs/production-incident-20261004/deployment-evidence.txt
```

Runtime-only: the same seven file overlays, capability hashes/access restoration, isolated rehearsal and private audit artifacts, and official producer-generated fresh runtime/authority/publication. Production unit/timer contents and historical execution evidence stayed unchanged. No outputs/data were manually staged or committed.

## Commit message / commit hash

Code: `Bind production order audit to active executor journal receipts` — **bcd54a85c2273b82ee47fafa51738d3fb457e164**.

Evidence: `Record production account reconciliation and pending automatic verification`. Its commit hash is provided in the response. Branch: `codex/production-incident-audit-20261004`; no push or merge performed. Task completion is deliberately pending, not claimed by committing this report.

## Read-only follow-up — 2026-10-05

- Automatic timer trigger: 00:10:16 UTC. Service started 00:10:17, terminal manifest finished 00:12:38, systemd exit 0 at 00:12:39. Invocation `bdfd5bcff4bc4f2cb605479c7085fbd8`; NRestarts 0. Next automatic timer event: 2026-10-06 00:10 UTC, Persistent=yes.
- Run `prod_20261005T001018Z_547978`: SUCCESS/NO_ACTION; EXECUTE, POST_TRADE_VERIFY, DASHBOARD_RUNTIME and AUTHORITY_PUBLISH PASSED. No manual run, order, cancellation or runtime snapshot was initiated by the follow-up.
- Current UTC closed day 2026-10-04. Canonical target CASH/0, candidate AVAX/1, trend permission false. Core, intent, gate and account-snapshot SHA256 bindings match exactly. Authority `20261005_001214`: success/current, generated 00:12:32 UTC; account read-back 00:11:43 UTC.
- Fresh direct exchange Info at 05:22:42 UTC: unifiedAccount, USDC 83.348433, hold 0, stable free funds 83.348433; other reported spot balances zero. No positions or orders on native and all ten currently registered HIP-3 dexes. Real notional/exposure and margin used 0. Exchange-native individual-perp accountValue=0 is not unified total equity.
- Supabase was queried with GET only, with exact response counts and matching journal hashes before/after. Current durable run UUID `aaca7558-c73d-4161-a1f0-f80eab367c6b`, NO_ACTION, completed 00:11:39.181 UTC, no action rows. Total historical actions remain 5; nonce remains 1790813499788; leases 0. Latest manifest receipt correctly binds to this UUID, with empty order/CLOID arrays.
- Only one fill since cutover: the previously verified 7.65 AVAX EXIT on 2026-10-01 00:11:41.250 UTC, order 561784971605, CLOID `0xd91d0679bb48242964e7922e7b861ac7`. Fresh orderStatus remains filled. No duplicate submission or new fill after the repair.
- Producer-generated public contract contains real_account CASH/0, equity/free collateral 83.348433, authorized target CASH/0, SUCCESS/NO_ACTION and live_order_sent=false. It preserves AVAX/1 as a separate model candidate. Compatibility `would_place_real_order=true` represents canonical gate readiness, as assigned by prepare_real_order_gate.py; actual planner, receipt, journal and exchange all prove no order was requested or sent. This compatibility flag was not used as submission evidence.
- Authenticated Chrome read-back remains UNVERIFIED: opening dashboard tab 703928341 was followed by Chrome blocking automation because another extension UI is open. No session/token extraction or alternate unauthenticated evidence was substituted. User was asked to complete or dismiss that UI. Published VPS contract agreement does not establish current browser agreement. INCIDENT_RESOLVED remains false; follow-up was not paused.

### FILES READ / SOURCE OF TRUTH / validation

Read AGENTS.md, the ordered ten truth/navigation documents, pi_codex_runtime_workflow.md (local only), production_execution_contract.json, production_host_contract.json, the original incident report/evidence, production-migration-readback.ts, Supabase admin/repository code, and relevant gate/export assignments. Remote evidence: terminal manifest, core/intent/gate/account files, both authority files, public contract, systemd show/journal, live Hyperliquid Info and Supabase execution tables. Supabase and computer-use skill instructions were followed. No Pi, research or LeadPilot connection or inspection occurred.

Original root cause and deployed contract repair remain unchanged. This follow-up's remaining blocker is browser observation, not account misalignment or a failed automatic run. Contract impact: none. No runtime code, services, timers, generated outputs/data or journals changed. No new regression test; existing repair regressions are recorded above. Read-only validation: automatic invocation/exit, current closed day/target, SHA256 provenance, journal receipt, unchanged action/nonce, all venue position/order lists, and publication agreement passed. Browser verification blocked. Local JSON parse and git diff --check validate the evidence only.

Exact files changed / git add list:
`git add -- docs/production-incident-20261004/REPORT.md docs/production-incident-20261004/followup-20261005.json`

Commit message: `Record automatic production verification and pending Chrome readback`.
Commit hash: recorded in the final response after committing this audit; no push or merge.

## Read-only follow-up — 2026-10-06

- Timer reálne spustil produkciu o 00:10:00 UTC. Manifest
  `prod_20261006T001001Z_915393` skončil 00:12:29 UTC; systemd invocation
  `4d7203dd04534d3f921f6a8143585a78` exit 0 o 00:12:30 UTC, Result success,
  NRestarts 0. Timer enabled/active/waiting, nasledujúci termín 7. októbra
  00:10 UTC. Nejde len o naplánovaný run.
- Najnovší úplne uzavretý UTC deň 2026-10-05 má kanonický autorizovaný cieľ
  AVAX/1x, trend_permission_active=true. Core → intent → gate → account
  fingerprinty aj signal ID sú v zhode. EXECUTE, POST_TRADE_VERIFY,
  DASHBOARD_RUNTIME a AUTHORITY_PUBLISH PASSED. Authority `20261006_001204`
  je success/current pre ten istý deň, generated 00:12:23 UTC.
- Automatický ENTRY fill 00:11:27.744 UTC: 7.47 AVAX, cena 11.159 USD,
  order `566271255984`, CLOID `0x69b7680580acc75446fb6e497545bfa2`, fee
  0.03751 USDC. Priamy orderStatus podľa CLOID je filled. Supabase run
  `f98ab533-7006-413e-8804-0327594cf6e4` má FILLED_AND_ALIGNED;
  action `7cb38327-581b-47c9-9973-14ba00a86501` má SUBMITTED/VERIFIED a rovnakú
  order identitu ako nový manifest aj burza. Opravený owner receipt teda
  funguje aj pre skutočne odoslanú objednávku, nie iba NO_ACTION.
- Priama Hyperliquid Info kontrola 16:42:28.074521 UTC: unifiedAccount;
  spot stable total 85.467664 USDC, hold 8.55315, free collateral
  76.914514 USD. Ostatné spot balances sú nulové. Native perp AVAX long
  7.47, position notional 85.5315 USD, unrealized PnL 2.17377 USD. Na všetkých
  aktuálne registrovaných HIP-3 dexoch žiadna ďalšia pozícia; open orders
  spolu 0. Real exposure = position notional / unified equity = 1.000746902x.
  Rozdiel voči cieľu je 0.063836 USD, pod existujúcou planner toleranciou 1 USD:
  ACCOUNT_ALIGNED=true. Exchange leverage parameter 10 nie je market exposure.
- Od cutoveru sú presne dva filly: pôvodný 7.65 AVAX EXIT 1. októbra a dnešný
  7.47 AVAX ENTRY. Historický predaj, jeho dôvod a identita zostávajú potvrdené.
  Journal má 17 runov, 6 action rows, 0 leases; nonce 1791245486492 zodpovedá
  novému automatickému ENTRY. Hashy kompletných read-only GET journal odpovedí
  pred/po kontrole sú rovnaké. Follow-up neurobil write/RPC ani nonce reset.
- Producentom publikovaný kontrakt má správny deň, AVAX/1x cieľ, reálnu pozíciu
  7.47 AVAX a FILLED_AND_ALIGNED. Jeho equity 83.288513 USD je stav pri
  produkčnom read-backu 00:11:33 UTC, nie čerstvé equity o 16:42. Cenový pohyb
  nie je dokladom nesúladu. Publikovaný súbor však nenahrádza pozorovanie
  aktuálneho dashboardu v prihlásenom browseri.
- Chrome/Marek: prvý inventár timeout sa zotavil. Navigácia vytvorila tab
  `703928546`; následný read-back vrátil: "Google Chrome is blocking automation
  because another extension UI is open on this page. Complete or dismiss that
  extension UI in Google Chrome, then ask me to continue." UI nebolo obchádzané,
  session ani auth tokeny neboli extrahované. DASHBOARD_MATCHES_EXCHANGE=UNKNOWN.
  Follow-up sa nepozastavil, pretože podmienka úplného potvrdenia nie je splnená.

### FILES READ / SOURCE OF TRUTH / kontrakt / validácia

Prečítané: pôvodný report a followup-20261005; AGENTS.md; desať truth/registry
dokumentov v požadovanom poradí; lokálny pi_codex_runtime_workflow.md a
production_host_contract.json; web/scripts/production-migration-readback.ts,
web/src/lib/supabase/admin.ts, kanonický orchestrátor a
web/src/server/multi-account-executor/planner.ts. Normatívne produkčné
kontrakty a význam wallet/model polí sú uvedené vo vyššom SOURCE OF TRUTH.
VPS: iba existujúce produkčné manifest/core/intent/gate/account/authority/public
súbory, systemd show/journal a EnvironmentFiles cesta. Account = čerstvá
Hyperliquid master Info odpoveď; order identita = burza + Supabase journal.
Použité read-only pokyny Supabase a computer-use; changelog overený, žiadna
implementácia Supabase feature, migrácia ani zmena auth/dependencies.

Root cause opraveného incidentu B+C zostáva preview CLOID namiesto owner
receipt. Nový reálny ENTRY teraz potvrdzuje správne napojenie. Zostávajúci
blokátor je Chrome observation, nie vykonanie runu alebo nesúlad účtu.
Contract impact: žiadny. Žiadny nový regresný test ani nasadenie; source/runtime
sa nemenili. Existujúce regresie opravy sú zaznamenané vyššie.

Validácia: current closed day, SHA256 provenance, úspešný automatický systemd
invocation/terminal manifest, verified receipt/CLOID/fill/journal, stabilný
GET-only journal hash, všetky aktuálne venue pozície/open orders, aktuálna
alignment tolerancia a publikovaná position quantity PASS. Browser BLOCKED.
Lokálny JSON parse a git diff --check overujú iba auditné artefakty.
Prvý pokus použil chýbajúcu starú EnvironmentFile cestu; opravené podľa
systemd EnvironmentFiles bez akejkoľvek zmeny configu. Dôkaz zaznamenaný v JSON.

Forbidden old path checked: žiadny Pi kontakt, research/LeadPilot kontrola,
run/start/restart/publish/refresh, live order/cancellation, ručný runtime
snapshot, generated outputs/data edit, DB write alebo dashboard zmena.
Jediná nová objednávka patrí už prebehnutému automatickému runu, nie follow-upu.

Exact files changed / git add list:
`git add -- docs/production-incident-20261004/REPORT.md docs/production-incident-20261004/followup-20261006.json`

Commit message: `Record automatic AVAX entry and blocked dashboard verification`.
Commit hash: recorded in final response after audit commit; no push/merge.

## Read-only closure check — 2026-10-06 17:09 UTC

The original production execution repair is confirmed. The incident cannot be
declared fully resolved because a real dashboard balance discrepancy was found,
independently of the later Chrome extension interruption.

SOURCE OF TRUTH: direct master-account Hyperliquid Info, all registered perp
venues, current GET-only Supabase journal, terminal canonical manifest, and the
successfully loaded hosted dashboard. Evidence: closure-readback-20261006.json.

Exchange read-back at 17:09:12.905607 UTC: unifiedAccount, USDC total/equity
85.735517 USD, AVAX long 7.47, position value 85.800420 USD, real exposure
1.000757014x, no other positions and zero open orders. The 0.064903 USD residual
is below the unchanged 1 USD tolerance: ACCOUNT_ALIGNED=true.

Original run prod_20261006T001001Z_915393 is SUCCESS/FILLED_AND_ALIGNED.
The active journal run f98ab533-7006-413e-8804-0327594cf6e4, action
7cb38327-581b-47c9-9973-14ba00a86501, manifest and direct filled orderStatus
all agree on order 566271255984 and CLOID
0x69b7680580acc75446fb6e497545bfa2. Journal GET hashes before/after match;
17 runs, six action rows, one nonce record, zero leases. The only two fills
since cutover remain the historical 7.65 AVAX exit and automatic 7.47 entry.

Dashboard https://trendatlas-accounts.vercel.app/dashboard loaded successfully
in Chrome tab 703928572. Visible master identity 0xae8d…e856, synchronization
6 Oct 2026 19:06 local (17:06 UTC), In market, AVAX 7.47, one position,
zero open orders, and Live Hyperliquid read-only API all confirm the position.
However, its TOTAL ACCOUNT VALUE was 96.23 USD and EXCHANGE WITHDRAWABLE
87.66 USD. The exchange's unified equity remains approximately 85.74 USD;
the native single-perp margin accountValue is 10.780536 USD and withdrawable
2.200494 USD at the fresh read-back. The discrepancy is consistent with the
old additive spot-plus-perp dashboard formula. The inspected current repo
info.ts already contains the correct unified-account guard; the live page
therefore does not demonstrate that corrected balance behavior. Exact deployed
source/version was not independently retrieved, so additive double-counting
is a supported inference, not a newly proved deployment diagnosis.

DASHBOARD_MATCHES_EXCHANGE=false (position matches, balance does not).
INCIDENT_RESOLVED=false. This blocker is a measured balance disagreement,
not a request to close Chrome. A subsequent reload was blocked by extension UI;
the prior successful observation and independent exchange read remain evidence.
The existing follow-up was not paused because its completion condition remains
false. Production, account, frontend and deployments were not changed.

FILES READ: ordered ten truth/navigation documents, local runtime workflow,
production_host_contract.json, production_execution_contract.json, original
incident report/followup, dashboard/page.tsx, hyperliquid/info.ts,
hyperliquid/performance.ts, planner.ts, supabase/admin.ts and
production-migration-readback.ts; live manifest/core/public contract/systemd
posture, GET-only journal and native exchange Info. Supabase skill/changelog
and computer-use guidance were read. No credentials or signing material were
printed, stored in audit evidence or sent to the browser.

Root cause of original execution incident remains the repaired preview-CLOID
mapping. New class B observability finding: hosted balance disagrees with native
unified account equity. Contract impact: no change; no patch/test/deployment is
authorized for production in this request. Existing repair regressions remain
documented above. Validation: native account/order/fill/venue queries, preserved
GET journal hash, matching receipt/manifest identity, successful dashboard
observation, evidence JSON parse and git diff --check. The account/order checks
pass; complete dashboard balance agreement fails.

Forbidden old path checked: no production run/start/restart, order/cancel,
publish/refresh, DB write/RPC, manual snapshot, generated outputs/data edit,
Pi contact, LeadPilot control or production strategy/account modification.

Exact files changed / git add list:
`git add -- docs/production-incident-20261004/REPORT.md docs/production-incident-20261004/closure-readback-20261006.json`

Commit message: `Record verified AVAX position and dashboard equity mismatch`.
Commit hash: reported after committing in the final chat response. Requested
commit aebc0b2cbd6a7159432ac8994845baaed6c1f902 was pushed to its existing
production audit branch and its remote hash verified. No merge into main.
