# Produkčný incident — stav 4. októbra 2026

**INCIDENT_RESOLVED=false.** Oprava auditu je nasadená, čerstvý kanonický run aj publikovanie uspeli a účet je zosúladený. Záverečné potvrdenie nasledujúceho automatického runu **po oprave** zostáva otvorené: timer ho plánuje na **2026-10-05 00:10 UTC**. Plánovanie nie je dôkaz vykonania. V tomto chate je aktívny následný read-only follow-up `overi-al-automatick-run-trendatlas`, denne o 02:20 miestneho času Europe/Paris, teda teraz 00:20 UTC. Po úspešnom záverečnom overení sa má pozastaviť.

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
