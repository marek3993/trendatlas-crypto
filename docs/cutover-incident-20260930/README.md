# Operator cutover incident — 2026-09-30

**NO_LIVE_CHANGE_CONFIRMED=true. READY_FOR_OPERATOR_CUTOVER at verification time.**
No assistant invocation used `--execute-live`. No Pi fence, production timer change,
VPS activation, exchange mutation, authority publish or journal/nonce write was performed.
Pi remains the sole live executor. The VPS code/input update below is staged under
its unchanged no-submit override and disabled/inactive production timer.

The new receipt was sealed at **2026-09-30 14:27:59 UTC**, for closed day
**2026-09-29**. It expires at **15:27:59 UTC / 17:27:59 Europe/Berlin**, or earlier
on any bound-state change. This document and yesterday's readiness are not an
evergreen authorization. The operator command revalidates before fencing.

## SOURCE OF TRUTH

Class **C + B**: host admission/readiness and sanitized operator diagnostics.
Normative contract: `source_of_truth/production_host_contract.json`, supplemented
by `production_execution_contract.json`, `export_contract.json` and
`pi_codex_runtime_workflow.md`. No strategy or frontend code changed.

Runtime evidence: fresh exchange Info/database readbacks, installed systemd
properties, Pi canonical current strategy/run, paired frozen-input replay, and
root-owned `/etc/trendatlas-production/ready.json`. Historical reports are not
current authority. Source checkout: `C:/Users/benda/Desktop/ta_vps_prod`, branch
`codex/vps-production-execution-20260929`. The original `market_regime_v1` checkout
and its pre-existing modifications were not edited.

## Exact root cause and incident attribution

Stable reason code: **CURRENT_CLOSED_DAY_REQUIRED**. The old helper's exact
exception was reproduced read-only: `production target needs the current closed day`.

The VPS readback retained from the operator attempt was timestamped
**2026-09-30T13:38:10.590Z** and still loaded the staged **2026-09-28** target.
The current UTC closed day was **2026-09-29**. `fresh_readback()` rejected that
date before returning from VPS `preflight`; cross-host comparison and every
fencing/activation operation were still unreachable.

Protected system journal entries for the attempt were inspected on-host, with
only allowlisted reason/event summaries transported. There was no persistent
migration exception log: the original SSH wrapper captured and discarded remote
stderr and did not store it. Therefore the original traceback text was not
recovered from a protected log. Attribution rests on the attempt's timestamped
readback, unchanged readiness/capability files, exact call ordering and fresh
deterministic reproduction. No raw protected log or credential was displayed.

The following evidence corroborates failure before any live change:

- Local cutover state file absent: even `PREPARED` had not been saved.
- Pi fence absent; production timer enabled/active and service inactive.
- VPS activation and final-handoff files absent; timer disabled/inactive.
- VPS service had no recorded start/exit timestamp. Its effective ExecStart still
  points to `run_production_rehearsal.py`; the no-submit override remains present.
- Fresh account: 7.65 AVAX, no open orders, 18 recent fills with unchanged latest
  fill timestamp 1790640668472 (2026-09-29T00:11:08.472Z), nonce 1790640666333.
- Both fresh readbacks used identical journal SHA256
  `c41fe05c53965e3510cb2c13d1c8539339b137ac24ed5a7da5ab85bea2bdf0b3`,
  no execution leases, and reported `journalUnchanged=true`.
- All 7,939 original Pi runtime/config file fingerprints matched after the audit.

## What changed since yesterday

| Dimension | Finding |
| --- | --- |
| Readiness receipt | Old boolean/capability receipt had no date, account or journal binding. It was not an expiry gate. |
| Closed day | Pi advanced to 2026-09-29; VPS remained on 2026-09-28. This was the actual rejecting gate. |
| Signal | Date component advanced; authorized target remained AVAX 1.00x with permission true. |
| Account | Quantity, orders and fills unchanged. Equity/mark prices moved with the market; those are not trades. |
| Journal | Changed since the September 29 report (`44c811...` to `c41fe0...`); both current hosts agree exactly. Pi's September 30 canonical run recorded SUCCESS / NO_ACTION / real_order_sent=false. Nonce unchanged. |
| Host state | Pi remained live, VPS remained disabled/no-submit, runtime pins and old source manifest admitted during reproduction. |

The old day guard correctly failed closed. It did **not** prove that the old
receipt was adequately bound. That separate implementation weakness is fixed.

## Exact contract impact and repair

The source contract was patched and JSON-validated before consumer implementation.
Readiness v2 binds the current UTC closed day, complete target/signal, account
identity, exact positions, detailed open orders, recent fills, journal (including
nonce tables), planner, current runtime input fingerprint, capabilities and paired
current-input replay. It expires after one hour and fails at a UTC day rollover.
Fresh prices/equity are deliberately replanned; they do not masquerade as changes
in held quantity. A changed plan still invalidates the receipt.

VPS preflight and activation both check this binding. Preflight additionally
requires the production timer disabled **and** inactive and its effective service
command still using the rehearsal wrapper. Old unbound receipts fail closed.

The SSH/operator error channel now accepts only a closed reason-code vocabulary.
Arbitrary remote stdout/stderr and exception messages are not echoed. Failures
write a safe local JSON report with reason, phase, Pi-fence status, possible-live-
activation status and report path. Uncertain states use null, never an invented
false. The pre-fence and post-possible-activation recovery boundaries are retained.
`sanitized-failure-example.json` records an actual safe SSH failure while the new
staged source intentionally had not yet been resealed.

Only the six code/contract/test files below were staged to the VPS. Its canonical
inputs were loaded from an unchanged, hashed Pi runtime archive; no snapshot date,
authority content or strategy decision was hand-edited. Capabilities and readiness
were resealed only after evidence checks. No systemd production unit or timer was
changed. Pi live source remained untouched.

## Current evidence and validation

- Frozen input archive SHA256:
  `c254ea01101ac1baac3cc66bfce9a39f43674c31f62d02fc9414ed57f704e17b`.
- ARM and x86 used the same frozen current inputs, account, journal and markets.
  Exact replay: **3,070 rows through 2026-09-29**, snapshot/history/serialization/
  planner PASS, no tolerance added. Both core hashes:
  `3834b2a18567cb78c1cc50bca1065a8dcc4f22dd86c253758f97ed317b08fb6f`.
  Both planner hashes:
  `098606b92149a550cb05e7d888fe3890cfc7b99cb75f718a7ca2d2ac9cc45baf`.
- Pi isolated canonical no-submit: `prod_20260930T142206Z_229371`.
- VPS isolated canonical no-submit: `prod_20260930T141131Z_404500`.
- Both: PREFLIGHT_READY, AVAX 1x, PREFLIGHT_ONLY, real_order_sent=false,
  live_order_chain=NOT_INVOKED, authority_status=SKIPPED_NO_SUBMIT.
- VPS separate `publish-existing --dry-run`: exit 0; no real publish/push.
- Current readbacks around 14:26 UTC: 7.65 AVAX, zero orders, unchanged fills and
  nonce, NO_ACTION and empty actions. Wallet equity was approximately $83.75–83.76
  as prices moved. Model exposure and real wallet exposure remain distinct.
- Actual operator CLI invoked **without** its live flag: exit 0 after sealing;
  Pi only_live_host=true, VPS no_submit=true, exact target/identity/journal match.
- Python full regression set: **175 passed**. Expected injected failure output
  in authority tests is not a failed suite.
- TypeScript execution/no-submit suites: **116 passed**.
- New/related migration suites on real ARM and x86: **34 passed each**.
- Source JSON parse, Python imports and `git diff --check`: PASS.

Commands:

```text
python -m unittest tests.test_production_execution tests.test_single_production_orchestrator tests.test_hyperliquid_systemd_credentials tests.test_production_asset_universe_contract tests.test_execution_authority_publish tests.test_production_host_migration tests.test_operator_cutover tests.test_migration_retirement_priority tests.test_diagnostic_portability tests.test_migration_readiness -q
node node_modules/vitest/vitest.mjs run tests/canonical-execution-contract.test.ts tests/multi-account-executor.test.ts tests/production-boundary.test.ts tests/production-asset-support.test.ts tests/no-submit-transport.test.ts
python scripts/execution/production_golden_replay.py --output <protected-host-core.json>
node --conditions=react-server --import tsx scripts/production-golden-replay.ts <same-frozen-readback.json> <protected-host-planner.json>
python scripts/execution/compare_production_replay.py <pi-core> <vps-core> <pi-planner> <vps-planner> --output <comparison.json>
python scripts/execution/cutover_pi_to_vps.py --pi-host 172.16.20.107
```

The first Pi rehearsal could not write because audit copies exhausted available
disk space; an over-pruned temporary copy then lacked its shortlist dependency.
Both were staging failures before any exchange invocation. Required copied inputs
were restored and the isolated preflight passed. All expendable copies created by
this audit on Pi were then removed, preserving evidence and the original runtime.
Final Pi free space: **1.4 GiB**, timer still enabled/active. Input archives remain
protected locally and on VPS. No unrelated files were deleted.

## Regression tests added/updated

`tests/test_migration_readiness.py` adds 14 tests covering a valid receipt; old
unbound receipt; midnight rollover; expired/future/invalid timestamp; signal;
position/order/fill/signer changes; market valuation without a trade; journal;
planner; stale replay; changed runtime inputs; hostile remote error payloads;
failure before fence for binding failures; conservative uncertain-state flags;
and safe CLI JSON without traceback. Existing cutover interruption/reconcile and
single-host tests remain passing.

## FILES READ

Ordered mandatory truth layer in the supplied workspace, then differences/current
equivalents in the actual operator checkout:
`source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`,
`export_contract.json`, `paths_registry.json`, `current_issues.md`;
`canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`;
then `source_of_truth/pi_codex_runtime_workflow.md`.

Also AGENTS.md; `source_of_truth/production_host_contract.json`,
`production_execution_contract.json`, `migration_state.json`;
September 29 migration CONTINUATION/REPORT/readiness/deployment/no-submit evidence;
`cutover_pi_to_vps.py`, `migration_host_control.py`, `pi_migration_host_control.py`,
`production_host.py`, `production_golden_replay.py`, `compare_production_replay.py`,
`run_production_rehearsal.py`, `rehearsal_workspace.py`,
`run_trendatlas_production.py`, `run_pi_fast_daily_authority_refresh.py`,
`refresh_phase67_top100_shortlist_ohlcv.py`; migration/cutover tests;
`web/scripts/production-migration-readback.ts`, `production-golden-replay.ts`;
installed effective units, protected readiness/capability files, readbacks and
sanitized journal inspection; Supabase SKILL.md (read-only transport discipline).

## Forbidden old path checked

No full-refresh, live cutover, submit/cancel adapter, manual authority edit,
stale receipt READY, old journal restore, nonce reset, dual live host, Pi fence,
timer mutation, strategy math change, tolerance relaxation, frontend internal
labels, real publish, or generated `outputs/*` / `data/*` commit. No raw protected
log or secret entered Git or operator diagnostics. No LeadPilot/research restart.

## Exact files changed / exact git add list

Code commit:

```text
git add source_of_truth/production_host_contract.json scripts/execution/migration_diagnostics.py scripts/execution/migration_readiness.py scripts/execution/migration_host_control.py scripts/execution/cutover_pi_to_vps.py tests/test_migration_readiness.py
```

Evidence commit:

```text
git add docs/cutover-incident-20260930/README.md docs/cutover-incident-20260930/cross-architecture.json docs/cutover-incident-20260930/pi-evidence.json docs/cutover-incident-20260930/vps-evidence.json docs/cutover-incident-20260930/readiness-receipt.json docs/cutover-incident-20260930/sanitized-failure-example.json
```

## Commit message / commit hash

`Bind cutover readiness to current state and report safe failure reasons` —
**d6bbcf5fc520a2e6e061b159df646a796e625325**.

Evidence commit message: `Record current-day cutover incident audit and readiness`.
Its final hash and push result are supplied in the task response rather than
self-embedded in this document.

## Operator command — not executed by the assistant

Run only while the new receipt is valid; every admission check will be repeated:

```powershell
python C:\Users\benda\Desktop\ta_vps_prod\scripts\execution\cutover_pi_to_vps.py --pi-host 172.16.20.107 --execute-live
```

The command syntax remains compatible. Its implementation and current receipt
are new. On safe failure the default diagnostic report is
`C:\Users\benda\.codex\trendatlas-cutover-diagnostic.json`.
If the receipt expires or bound state changes, regenerate current no-submit/replay
evidence; do not bypass the gate or reuse this document as READY.
