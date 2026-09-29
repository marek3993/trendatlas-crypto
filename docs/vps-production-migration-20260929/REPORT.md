# Production migration audit, 2026-09-29

**Verdict: BLOCKED_WITHOUT_LIVE_CHANGE. PI_SAFE_TO_POWER_OFF=false.**

This is an incomplete migration, with a tested preparation fix. Neither host's
production runtime, credentials, timers, data, journal, or publication was changed
by this task. No migration order was submitted. Pi was not rebooted or shut down.
The assistant cannot execute financial trades or activate automatic trading;
the live cutover requires the operator. This report does not claim that all
permitted staging and migration preparation has been completed.

Observations below were collected directly on the two hosts and through read-only
database and exchange requests on 2026-09-29, approximately 17:39–17:51 UTC.
Historical reports were used only to locate code and credentials, not to determine
the current model target or wallet position. Values are observations at those
times, not guarantees about a still-running production scheduler afterward.

## FILES READ

Required truth files were inspected in the original local checkout, followed by
the production-version changes after identifying the actual Pi commit:

- `AGENTS.md`
- `source_of_truth/README.md`
- `source_of_truth/master_state.md`
- `source_of_truth/chat_roles.md`
- `source_of_truth/project_truth.json`
- `source_of_truth/export_contract.json`
- `source_of_truth/paths_registry.json`
- `source_of_truth/current_issues.md`
- `canonical/script_registry.json` (including relevant production entries)
- `canonical/output_registry.json` (including authority/journal entries)
- `canonical/registry_workflow.md`
- `source_of_truth/pi_codex_runtime_workflow.md`
- `source_of_truth/production_execution_contract.json`
- `source_of_truth/watchdog_maintenance_contract.md`

Implementation reads included `run_trendatlas_production.py`,
`production_execution.py`, `run_pi_authoritative_producer.py`,
`authority_contract.py`, `authority_publish_helpers.py`,
`validate_hyperliquid_production_signer.py`, `hyperliquid_read_only_snapshot.py`,
production systemd templates, the multi-account production runner, batch,
repository, authority, canonical guard, live-preflight and Supabase admin modules,
the execution database schema, and the regression suites named below.
The research migration README/contract at `0f76d2f6` were read for operational
context. The Supabase skill was read for the read-only journal audit.

## SOURCE OF TRUTH

Production code: Pi `/opt/market_regime_v1`, commit
`5ee031cef7de9c385056cec22f6511391d3e4f4f`, branch
`codex/production-recovery-20260926`. Runtime data and outputs are intentionally
dirty; they were not restored, pulled over, or committed.

Strategy: live `outputs/production/current_strategy_snapshot.json` and its
validated `execution_intent`. Wallet: fresh Hyperliquid Info API responses.
Execution: current production manifest plus the **Supabase multi-account** run,
action, nonce and lock tables. Publication: the Pi authority pair. The local PC
checkout is not current production authority.

## Exact root cause and contract impact

The production host migration has not occurred: the only installed production
timer is still on Pi; the VPS has no `trendatlas-production` user or production
checkout. Current publication code also requires `raspberry_pi` and ARM. In
particular, `build_pi_authoritative_env` forces Pi identity, and
`ensure_pi_only_publish_allowed` rejects x86_64. The current source validator and
repository publisher likewise require Pi identity. Copying the runtime unchanged
would therefore not establish valid VPS publication authority. No architecture
or identity spoofing was performed.

A concrete class B/C defect was additionally found and reproduced: the
`runPreflightedBatch` failure callback ran before its `noSubmit` return. For
FAILED, BLOCKED, and ENTRY_BLOCKED preflights it could invoke `createRun`,
`finishRun`, and `setAccountStatus` on the shared production database. Because
`createRun` recovers the existing account/signal run, a rehearsal could overwrite
a previously terminal execution result and mark the live account blocked/error.

The source contract was updated and JSON-validated first. The implementation now
invokes failure persistence only for live-mode batches. Rehearsal failures remain
visible in the returned report without changing shared database state. Existing
live failure recording and independent-account continuation remain tested.
This patch is **not deployed** on Pi or VPS and is not a host-authority migration.

## Requested migration evidence

| Item | Observed result |
| --- | --- |
| 1. Pi/VPS production commit | Pi `5ee031cef7de9c385056cec22f6511391d3e4f4f`; VPS production checkout absent. |
| 2. Last closed day | `2026-09-28`. |
| 3. Current target | **AVAX, 1.00x**, `trend_permission_active=true`, `allow_live_order_candidate=true`, strategy validation passed. Neither LTC, BTC nor CASH is the current target. |
| 4. Before migration | Fresh exchange read at about `17:44:45 UTC`: long **7.65 AVAX**, open orders `[]`; observed position value `85.0527 USD`. Exchange leverage setting 10x is not portfolio exposure. |
| 5. VPS no-submit result | **NOT RUN**. No VPS orchestrator, pinned production environment or migrated credentials installed; no cross-architecture parity claim. |
| 6. Migration orders/fills | **None initiated by this task.** Cutover did not begin. |
| 7. After migration | No migration occurred. No new post-cutover account state exists. The fresh read above is an audit observation only. |
| 8. Journal continuity | Active journal is Supabase, not the historical local JSON journal. See identifiers below; no first VPS sequence exists. |
| 9. VPS production timer | Absent; not enabled or started. |
| 10. Pi units | Production/watchdog timers remain enabled/active; additional units below. Nothing was masked. |
| 11. Pi reboot test | NOT RUN: successful VPS live run/read-back prerequisite has not occurred. |
| 12. PI_SAFE_TO_POWER_OFF | **false**. |
| 13. Single execution host | Pi has the sole production service/timer observed on these two hosts; VPS has no production installation. This proves no VPS cutover, not completion of migration. |
| 14. Dashboard authority | Latest successful authority still says `automatic_producer_id=raspberry_pi`, closed day `2026-09-28`, current/success. Tablet backend still reads Pi files. External deployed web configuration was not independently audited. |
| 15. Research | VPS original experiment `SEALED`, phase `TERMINAL`, failure null, 7,203 evaluations / 7,211 attempts, D result `REJECT`. Worker inactive after successful completion. Phase 2 collector appeared during this audit and its timer is enabled/active; not modified by this task. |
| 16. LeadPilot | API, frontend and DB containers healthy; proxy running. All four container start times remain on `2026-09-27T20:42:03Z`; no restart/configuration change by this task. |
| 17. Permissions | Existing VPS research user cannot read/write Docker socket, LeadPilot directory or research API credential source. Production/research/signer/journal isolation is **NOT TESTED**, because VPS production is absent. |
| 18. SHA256 | Attached manifests fingerprint inspected Pi artifacts/units and existing VPS research units/status. These are audit manifests, **not** a complete transferred-runtime equality manifest. |
| 19. Tests | See validation matrix. |
| 20. Changed files / add list | Seven explicitly listed files in `GIT_ADD.txt`. No secrets, DB, raw journal, `data/*`, or `outputs/*` added. |
| 21. Branch / commit / push | Preparation branch `codex/vps-production-execution-20260929`, based on observed Pi production commit. Commit/push result is reported in the final task response. No merge or main update. |
| 22. Verdict | **BLOCKED_WITHOUT_LIVE_CHANGE**. |

### Last successful production execution and journal

- Run `prod_20260929T001003Z_171542`, finished `2026-09-29T00:11:57Z`;
  `SUCCESS`, `FILLED_AND_ALIGNED`, backend `multi_account`, no-submit false.
- The morning run reduced AVAX by 1.93, reduce-only; the resulting position was
  7.65 AVAX. This happened **before this task**, not during migration.
- Database run UUID `5599db8e-962a-4815-8366-19073b18fb66`;
  last action UUID `7d625144-a42a-480b-8d82-61488ae16457`, leg 0,
  `RESIZE`, `SUBMITTED`, `VERIFIED`.
- Exchange-confirmed order `559520232243`, CLOID
  `0x9d0611c0ea77e558ee8f280e3d2777c2`; fill size 1.93 at 10.693.
  The Python manifest's different planner CLOID is not a substitute for the
  actual multi-account journal/exchange order identity.
- Last agent nonce `1790640666333`; database lock table empty at read time.
  This schema has UUID run/action identifiers and per-agent nonce, **no global
  monotonic journal sequence**. Do not invent one or substitute a stale file.
- Local `latest_execution_journal.json` is from `2026-09-06`, CASH/NO_ACTION,
  execution `exec_f973fc01cb74cdd176f9eeb497fd2351`; it is not today's active journal.
- `execution_mode.kill_switch=false`. One active authorized enrollment,
  `TA-f56c7bf7`, execution status aligned. The latest production manifest reports
  per-account signer PASS; exchange named-agent authorization remains present.
  This audit did not decrypt or independently validate the active signer.
- The historical `TrendAtlasProd` encrypted credential remains on Pi at mode
  0400, but the active multi-account unit does not mount it. The active server
  environment file is root:trendatlas 0640. Migration must preserve the encrypted
  agent secret/KEK and the existing database journal/nonce continuity; simply
  moving the legacy systemd signer would migrate the wrong execution backend.

### Pi service and auto-start findings

- `mrv1-production.timer`: enabled, active/waiting, `Persistent=yes`, next
  `2026-09-30 02:10 CEST`; canonical service inactive, MainPID 0, no overrides.
  Service enabled=false is normal for timer invocation; it does not prevent trading.
- `mrv1-watchdog.timer`: enabled/active.
- `research_os_pi_cycle.timer`: **enabled/active**, service failed/exit 1.
  Thus the claim that all Pi research auto-start is already off is false.
- Newer causal broker/maintenance/evolution timers: disabled/inactive; their
  services inactive. Disabled units have not been masked.
- `mrv1-daily-live.timer`, `mrv1-daily-preview.timer`: disabled/inactive;
  legacy full-auto service disabled/inactive.
- `home-blinds-dashboard.service`, `home-dashboard-kiosk.service` and
  `home-dashboard-kiosk-watchdog.timer`: enabled/active.
- `trendatlas-wifi-setup-mode.timer`: enabled/active. `ai-hologram.service` is
  also enabled/active and references the home automation tree; inspect ownership
  before deciding whether it belongs in TrendAtlas retirement.
- Current `trendatlas` user-manager timer inventory: zero timers. The scanned
  `/etc/cron.d` and `/var/spool/cron/crontabs` contained no matching TrendAtlas
  references. This is not an exhaustive proof covering every possible user,
  periodic script, interactive session, or boot path.
- `/opt/home_automation/home_dashboard.py` uses local paths under
  `/opt/market_regime_v1/outputs/`, including `dashboard_public_status.json`.
  The public status reports AVAX/1.00x and the current production run.

### Research and concurrent deployment

Initial VPS inventory showed an old failed dispatch unit. Subsequent inspection
showed `Result=exec-condition`, inactive, with the scientific state SEALED and no
failure; this must not be mislabeled as failed research. Phase 2 units were
installed externally during this audit: `trendatlas-phase2-collector.timer`
enabled/active/Persistent, collector service inactive/success. Do not overwrite
these units or presume the original research layout is the whole live inventory.
Production preemption and checkpoint/resume were not exercised.

## Regression test added/updated

`web/tests/canonical-execution-contract.test.ts` adds three parameterized cases
for FAILED, BLOCKED, and ENTRY_BLOCKED rehearsal results. Each starts with an
existing aligned/terminal production record and proves neither persistence nor
execution is invoked, state stays unchanged, and the failure remains reported.
All three failed against the old implementation, then passed after the fix.

## Validation commands/results

| Check | Result |
| --- | --- |
| `python -m unittest tests.test_production_execution tests.test_single_production_orchestrator tests.test_hyperliquid_systemd_credentials tests.test_production_asset_universe_contract -q` | **100 passed**, synthetic/local. |
| From `web`: `node node_modules/vitest/vitest.mjs run tests/canonical-execution-contract.test.ts tests/multi-account-executor.test.ts tests/production-boundary.test.ts tests/production-asset-support.test.ts` | **109 passed**. |
| Planner, reduce-only EXIT, EXIT-before-ENTRY, quantity/precision, stale-data rejection, journal/idempotency, power loss between EXIT/ENTRY, reconciliation | Covered by the above Python/TypeScript suites with synthetic exchange adapters. These are not live-order proofs. |
| `node node_modules/typescript/bin/tsc --noEmit` | PASS. |
| `python -m py_compile scripts/execution/run_trendatlas_production.py scripts/execution/production_execution.py tests/test_single_production_orchestrator.py` | PASS. |
| Source contract JSON parse and new read-only clause assertion | PASS before consumer patch. |
| `systemd-analyze verify /etc/systemd/system/mrv1-production.service /etc/systemd/system/mrv1-production.timer` on Pi | PASS, exit 0. |
| `systemctl show mrv1-production.timer -p Persistent` on Pi | yes; actual boot recovery NOT exercised. |
| Production authority guard with Linux/x86_64 context | Rejects with `authority publish requires ARM Pi runtime`; no platform spoofing. |
| `git diff --check` | PASS. |
| Full canonical VPS no-submit, paired SHA256 runtime transfer, cross-architecture replay | **NOT RUN**. |
| VPS production/research/LeadPilot isolation, research preemption, Pi retirement/boot test | **NOT RUN**. Existing research-vs-LeadPilot/Docker checks only, as above. |

The TypeScript dependencies were reused from a local worktree with an identical
package-lock hash through an untracked directory junction. No environment or
dependencies on Pi, VPS, or LeadPilot were changed. The first local Vitest command
used the repository root and could not resolve the web alias; rerunning from
`web` produced the explicit failing-then-passing regression results above.

## Forbidden old path checked

Installed production ExecStart uses only `run_trendatlas_production.py`.
Legacy scheduler timers were inspected; no alternate trading timer was enabled
by this task. Production-boundary tests pass for the retired independent submitter,
single lock, and browser/request-route isolation. No full refresh, order submitter,
manual authority edit, arm-platform override, model-as-wallet substitution, or
generated runtime commit was used. UI files were not changed.

## Remaining completion requirements

The migration still needs a source-contract-backed VPS authority implementation,
isolated production user/runtime and pinned x86 dependencies, secret-safe transfer
of the **active multi-account** configuration, an immutable runtime/DB checkpoint
and matching manifests, canonical no-submit plus frozen-input cross-architecture
comparison, tested resource prioritization, and verified VPS publication. The
new no-submit patch must be included in the reviewed rehearsal code first.

Only after matching preflight and operator-controlled live activation with
terminal account/order read-back may the Pi timers/services be retired, credentials
removed from automatic paths, rollback archive sealed, and Pi reboot tested.
None of these prerequisites may be replaced by a successful unit test or an old
report. The production authority remains Pi until a real cutover is completed.

## Exact files changed / exact git add list

See `GIT_ADD.txt`; only the seven named files belong to this task.

## Commit message

`Protect no-submit journal state and audit blocked VPS migration`

## Commit hash

The final task response records the resulting commit hash and push result.
This document intentionally does not embed a self-referential commit hash.
