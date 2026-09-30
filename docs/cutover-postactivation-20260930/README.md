# Post-activation cutover incident — 2026-09-30

**CUTOVER_COMPLETE. LIVE_ORDER_SENT=false.** Final exchange verification:
2026-09-30T15:28:23.764Z. Pi remains fenced; VPS is the sole execution and
publication host. No new cutover, production run, manual order, cancellation,
cleanup, shutdown or reboot was performed by the assistant. LeadPilot and
research were not changed.

## SOURCE OF TRUTH

Incident class **C + B**. Source contracts are
`source_of_truth/production_host_contract.json`, `production_execution_contract.json`,
`export_contract.json`, and `pi_codex_runtime_workflow.md`. Operational truth in
`project_truth.json` and `master_state.md` now records the verified operator
activation. No strategy implementation, target mathematics or frontend changed.

Live evidence is the installed host posture, exchange Info readback, Supabase
journal, original production manifest, current authority artifacts, protected
activation/handoff/success receipts, and the local operator state file. Historical
readiness does not supersede post-activation reconciliation.

## Initial read-only snapshot and classification

The original local diagnostic and cutover state were read and preserved before
repair. The state was `RUN_REQUESTED`, last updated 14:42:21.182 UTC. Independent
host snapshots at 15:00:39–40 UTC established:

| Item | Pi | VPS |
| --- | --- | --- |
| Production timer | disabled/inactive | enabled/active |
| Production service | inactive | failed, exit 2 |
| Persistent Pi fence | present | not applicable |
| No-submit override | absent, but fenced | absent after operator activation |
| Watchdog timer | enabled/active | enabled/active |
| Latest production run | prod_20260930T001011Z_854735 | prod_20260930T144223Z_081482 |
| Latest outcome | SUCCESS / NO_ACTION | EXECUTION_COMPLETE_PUBLISH_FAILED / NO_ACTION |

The VPS activation intent was written at **14:42:19.814 UTC**, with
`run_requested=true`. The final handoff existed. Therefore this was **Pi fenced +
VPS activated**, not a failed pre-activation attempt or split-brain. The
activation receipt's `ACTIVATING` field is the durable original activation intent;
completion is recorded separately in cutover-success.json and local SUCCESS.

No emergency stop of both timers was necessary: single-host ownership was
unambiguous. The VPS service's deterministic exit 2 prevented automatic retry;
NRestarts was zero. Pi was never restored.

## Exact root cause and REMOTE_FAILURE provenance

1. The operator's VPS service started at 14:42:21 UTC; canonical run started at
   14:42:23 UTC. EXECUTE passed at 14:43:34 and POST_TRADE_VERIFY passed at
   14:43:39. The target was already aligned, so the outcome was NO_ACTION with
   `real_order_sent=false`.
2. AUTHORITY_PUBLISH failed on **Permission denied reading
   `/etc/trendatlas-production/capabilities.json`**. It was root:root **0600**.
   The canonical publisher runs as `trendatlas-production`, so it could not read
   its host admission evidence. `atomic_write_json` creates a new 0600 inode;
   activation did not restore service-readable ownership/mode. The preceding
   preparation also sealed this file at 0600. This was a preparation/activation
   defect, not a strategy or exchange error.
3. An actual service-user admission probe then exposed a second permission
   defect: the five systemd files referenced by that evidence were also unreadable
   to the publisher. Root-only preflight checks and a publication dry-run did not
   exercise the real authority-write guard under the service UID.
4. The service exited **2 at 14:44:25 UTC**. `systemctl start` consequently
   returned failure to `run-once`; a nonzero service exit did not mean an unknown
   financial submission.
5. The old coordinator called `vps_provably_never_activated()` inside its exception
   handler **before saving RECONCILE_REQUIRED**. A failure of this secondary
   remote probe masked the original service failure and left RUN_REQUESTED.
   No activation-status sudo invocation appears after run-once in the protected
   14:40–14:45 journal interval. The original client did not retain stderr or the
   SSH return code, so the exact original transport error text is unrecoverable.
6. During this audit the same remote path independently reproduced **SSH exit
   255 / Connection timed out**, before command execution. A reconciliation
   attempt encountered it too. The repaired tool preserved RECONCILE_REQUIRED
   and successfully attached independent Pi/VPS state snapshots. Later read-only
   reconciliation succeeded. This proves intermittent SSH timeout as a present
   transport fault; it is not represented as recovered historical stderr.

Protected logs were read on-host and only allowlisted categories/source locations
were displayed. No secret or raw protected log was copied into this report.

## Containment and deterministic reconciliation

- Pi persistent fence and disabled/inactive production timer were preserved.
- VPS remained the only enabled production scheduler. Neither production service
  was started or restarted by the assistant.
- Exchange Info and database reads confirmed 7.65 AVAX, zero open orders, no fills
  from 14:40 UTC onward, no execution leases, and unchanged nonce 1790640666333.
- All four historical CLOIDs were queried directly through exchange `orderStatus`:
  **all filled**, matching journal verification_state VERIFIED. No new CLOID or
  action row was created by the incident or recovery.
- The same-day journal run `71be83e0-ef16-4112-886f-2c76ec497372` was terminal
  NO_ACTION, completed at 14:43:34.452 UTC. The journal hash was already
  `177f7f579aed2d811f92219b4f15b98d63a95906ff9fc751afb63d63538b8809`
  at the first fresh incident readback and remained identical after recovery.
- Non-secret capabilities and the five referenced systemd files were set to
  root ownership, production primary group, **0640**. Unit contents and scheduling
  were unchanged. Full admission then passed as the actual service user.
- A dedicated, locked **publication-only** recovery targeted the exact existing
  run `prod_20260930T144223Z_081482`. It verified terminal execution, ran
  `publish-existing --dry-run`, then `publish-existing`; both succeeded with
  `heavy_refresh_steps=skipped` and `live_order_chain=not_invoked`.
- Recovery retained original failure evidence in the manifest, did not call the
  execution orchestrator, did not touch the journal/nonce, and finalized the same
  run as SUCCESS / NO_ACTION / authority PASSED.
- Only after recovery, `systemctl reset-failed mrv1-production.service` cleared
  the historical failed flag. The service is inactive. Its historical last exit
  code remains 2 and its start timestamp remains 14:42:21, proving no second start.
- The separate `--reconcile-only` path completed with execution_verified=true,
  publication_verified=true and verified=true. Local state is SUCCESS; the VPS
  cutover-success receipt exists. The live cutover command was not repeated.

## Final state

| Field | Verified value |
| --- | --- |
| Verdict | CUTOVER_COMPLETE |
| LIVE_ORDER_SENT | false |
| Fills since 2026-09-30T14:40:00Z | none |
| Position / open orders | 7.65 AVAX / 0 |
| Model target | closed day 2026-09-29, AVAX 1.00x |
| Planner | NO_ACTION, empty actions |
| Pi timer / service / fence | disabled+inactive / inactive / present |
| VPS timer / service / no-submit | enabled+active / inactive / absent |
| Watchdog timers | enabled+active on both; neither changed by this audit |
| Sole active execution host | VPS vps-4f79db29 |
| Nonce | 1790640666333, unchanged |
| CLOIDs | four historical records, all exchange filled / journal VERIFIED; none new |
| Publisher authority | canonical_production_host, latest attempt success |
| Authority snapshot | run 20260930_151656, generated 15:17:15 UTC, closed day 2026-09-29 |
| Authority publisher commit | a9480b5ab8244ba95c16f9f9c0b458f76aa38fef |
| Cleanup eligibility | yes at final verification; cleanup was not executed |

The VPS source contract and actual service-user admission were revalidated after
the final operational patch. Current wallet equity moved with market prices;
this is not a change in held quantity and is not model PnL.

## Contract impact and implementation

- `production_host_contract.json` specifies service-user access, durable uncertainty
  before network probes, independent host snapshots, verified execution separated
  from publication failures, and publication-only recovery of an existing run.
- `write_capabilities` restores root ownership, the production group and 0640
  after atomic replacement. Preflight tests readability of the capability and
  every referenced runtime/systemd file as the actual service user.
- After a lost run response, the coordinator saves RECONCILE_REQUIRED first and
  automatically attempts read-back. It never invokes run-once or restores Pi in
  that path. Repeated calls reconcile the same activation.
- Diagnostics include a host snapshot even when readback fails. Missing host
  observations are explicit `available=false`, never fabricated. SSH timeouts,
  closed connections and auth failures now have stable sanitized reason codes
  and a numeric remote exit code, without printing stderr.
- The classifier requires the exact run/day/signal, terminal per-account journal
  records, verified actions, no leases, aligned fresh accounts, successful
  EXECUTE/POST_TRADE_VERIFY stages and successful publication before completion.
- The recovery utility holds the canonical single-run lock, uses the existing
  run identity and preserves execution evidence/file access. Interrupted
  publication can resume; a failed publish restores the prior manifest state.
  It contains no order, cancellation, timer or service-start path.

## Regression tests and validation commands/results

Windows full Python suite: **190 tests, OK, one Linux ownership test skipped**.
That test and the other migration tests ran on actual ARM and x86: **49 passed
on each host, no skips**. TypeScript execution/no-submit suites: **116 passed**.

New tests cover response loss, durable uncertainty before a failing probe,
no second run/order or Pi restore, diagnostic host snapshots, safe SSH timeout
classification, unknown CLOID rejection even with an aligned wallet, missing
journal/wrong run/day/signal/no-submit rejection, publication-only ordering,
idempotence/interruption, restoring original evidence on failure, actual service
UID checks and atomic capability permissions. Existing response-loss tests were
updated to expect immediate successful readback when terminal proof is available.

Exact ARM/x86 Production Core replay remains unchanged: **3,070 rows**,
normalized snapshot/history/diagnostic export identical, CSV SHA256
`7c23b25b3b4c395f4108d28950982daae4b192ff4d538d7f6a8b5c73255d8ada`.
Both semantic replay hashes:
`5c335cf85e8b7f4bc338a9192ac888233467a7b6c3be65be920faee419c85d84`.
Only existing provenance exclusions were used; no new numerical tolerance.

```text
python -m unittest tests.test_production_execution tests.test_single_production_orchestrator tests.test_hyperliquid_systemd_credentials tests.test_production_asset_universe_contract tests.test_execution_authority_publish tests.test_production_host_migration tests.test_operator_cutover tests.test_migration_retirement_priority tests.test_diagnostic_portability tests.test_migration_readiness tests.test_post_activation_recovery -q
node node_modules/vitest/vitest.mjs run tests/canonical-execution-contract.test.ts tests/multi-account-executor.test.ts tests/production-boundary.test.ts tests/production-asset-support.test.ts tests/no-submit-transport.test.ts
python scripts/execution/cutover_pi_to_vps.py --pi-host 172.16.20.107 --reconcile-only
git diff --check
```

## FILES READ

The ordered SSOT/canonical reads from this conversation remain the baseline:
source_of_truth README, master_state, chat_roles, project_truth, export_contract,
paths_registry, current_issues; canonical script_registry, output_registry,
registry_workflow; then pi_codex_runtime_workflow. Current host contract and
project migration fields were re-read before repair/truth updates.

Also: original diagnostic and local state; cutover_pi_to_vps,
migration_host_control, migration_diagnostics, migration_readiness,
production_host, authority_contract, authority_publish_helpers,
run_pi_authoritative_producer, run_trendatlas_production,
retire_pi_after_cutover, production_golden_replay/compare; operator/host/
orchestrator tests; installed unit metadata/permissions, protected activation,
handoff, production manifests, authority snapshots, filtered system journals,
exchange Info and Supabase readback. Existing Supabase skill read-only discipline
was retained; no schema, credential, database permission or data mutation occurred.

## Forbidden old path checked

No new cutover or production run, manual BUY/SELL, cancellation, unknown-order
resubmission, old journal restore, nonce reset, Pi reactivation, competing host,
full refresh, manual authority snapshot edit, strategy change, tolerance
relaxation, frontend internal notes, cleanup, shutdown or reboot. Generated
authority publication used only the official producer, dry-run first. No generated
outputs/data were manually committed. No raw protected log or secret was exposed.

## Exact files changed / exact git add list

```text
git add source_of_truth/production_host_contract.json source_of_truth/project_truth.json source_of_truth/master_state.md scripts/execution/cutover_pi_to_vps.py scripts/execution/migration_host_control.py scripts/execution/migration_diagnostics.py scripts/execution/migration_reconciliation.py scripts/execution/recover_production_publication.py tests/test_operator_cutover.py tests/test_post_activation_recovery.py
git add docs/cutover-postactivation-20260930/README.md docs/cutover-postactivation-20260930/pi-initial.json docs/cutover-postactivation-20260930/vps-initial.json docs/cutover-postactivation-20260930/pi-final.json docs/cutover-postactivation-20260930/vps-final.json docs/cutover-postactivation-20260930/deployment.json docs/cutover-postactivation-20260930/arm-validation.json docs/cutover-postactivation-20260930/x86-validation.json docs/cutover-postactivation-20260930/original-diagnostic.json
```

Runtime-only changes: capabilities content/hash evidence and its owner/group/mode;
group/mode of the five already installed systemd files; official generated
publication/manifest recovery and cutover-success receipts; reset of the historical
failed service flag. No production timer/unit contents changed.

## Commit message / commit hash

`Reconcile lost cutover responses and recover publication without execution` —
**348120938c8e85b4660de7e76d8223a17cf7af0e**.

Evidence commit: `Record completed cutover reconciliation and publication recovery`.
Its hash and push result are reported in the task response.
