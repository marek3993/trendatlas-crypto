# VPS production preparation continuation — 2026-09-29

**Verdict: BLOCKED. READY_FOR_OPERATOR_CUTOVER was not issued. PI_SAFE_TO_POWER_OFF=false.**

The VPS now has an isolated production runtime and successfully executed the canonical **no-submit** orchestrator. The blocker is an actual exact-replay mismatch, not an ARM-only policy. No live cutover, financial order, Pi fencing, production-timer activation on VPS, retirement or reboot was executed.

## SOURCE OF TRUTH

- Live execution host: Pi `/opt/market_regime_v1`, commit `5ee031cef7de9c385056cec22f6511391d3e4f4f`; its production timer remains enabled/active.
- Staging branch: `codex/vps-production-execution-20260929`, continuing `8db32e600b79e751bb90d34de1f098b3ee49823a`.
- VPS: `/opt/trendatlas-production/current`, user/group `trendatlas-production`; separate pinned Python 3.13.5 and Node 22.23.2, Python packages matched to Pi, npm package-lock installation.
- Strategy truth: validated Production Core and canonical intent/gate, closed day **2026-09-28**, **AVAX 1.00x**, trend permission true.
- Real account truth: fresh Hyperliquid Info reads, **7.65 AVAX**, open orders `[]`. Equity changes with market prices; it is not model equity. One read at 18:24 UTC reported equity 85.98228 USD. Frozen account/metadata inputs were used for exact architecture comparison, rather than pretending independently timed prices must match.
- Active journal: existing Supabase multi-account run/action/CLOID records and per-agent nonce. There is **no global journal sequence**. Last observed agent nonce remains `1790640666333`. No database restoration/import or journal migration write was performed.

## Exact root cause and contract impact (B/C)

The inherited no-submit batch failure bug was fixed in the preceding commit. This continuation adds a GET/HEAD-only database transport, rejects RPCs and mutations before network access, and requires a separately copied rehearsal workspace even when the Python orchestrator is constructed directly. Account snapshots, local journals and failed run evidence are isolated from the canonical runtime. Runtime files cannot be shared through symlinks/hardlinks. Before/after fingerprints prove the copied source did not change during rehearsal.

The old publisher admitted only Pi/ARM identity. `production_host_contract.json` now defines Linux/aarch64 and Linux/x86_64 capability admission: dependency pins, host binding, SHA256 source and systemd manifests, exact replay and operator-established single authority. Canonical-host admission measures the actual platform. The still-live Pi's historical identity remains compatible; x86 cannot spoof that legacy path using environment architecture overrides. Existing production Pi code is deliberately unchanged until operator migration.

The full golden replay is **not exactly equal**. Current snapshot values (excluding file/build provenance), all strategy decision columns and the real-input TypeScript planner match exactly, including NO_ACTION and empty action lists. The historical timeseries differs in:

| Field | Differing rows | Maximum absolute difference |
|---|---:|---:|
| rolling_vol_30d | 976 | 6.586000000000001e-9 |
| rolling_sharpe_90d | 97 | 3.5000002895912985e-11 |

These are derived rolling statistics. The precise native floating-point/build cause has not been isolated. File line endings were normalized to Git LF; the numerical differences remained. No tolerance was invented, widened or borrowed from an unrelated check. No strategy calculation was changed to make the replay pass. `cross-architecture.json` preserves the failed full comparison, and the root-owned VPS readiness/capability receipts remain BLOCKED. Fixing/proving this numerical portability is required before READY can be issued.

## Deployed and observed

- Canonical run `prod_20260929T184645Z_371710`: **PREFLIGHT_READY**, backend multi_account, `live_order_chain=NOT_INVOKED`, `real_order_sent=false`, dashboard materialization PASSED, authority publication SKIPPED_NO_SUBMIT. Source runtime fingerprints unchanged. See `no-submit-evidence.json`.
- Separate `publish-existing --dry-run`: exit 0, zero pushes. No real authority publication occurred. Publisher Git read access and `git push --dry-run` were verified without modifying a remote ref.
- VPS production service's persistent override invokes `run_production_rehearsal.py`. Production timer: **disabled/inactive**, `Persistent=yes`. No automatic live trading is enabled.
- Watchdog installed and manually verified: Result=success, no production writes, no strategy change, no order chain. Its timer remains disabled/inactive pending operator activation.
- Active multi-account server configuration and the existing publisher SSH credential were transferred over authenticated encrypted SSH channels without printing values. Legacy Pi agent credential was not substituted for the active backend. Files are protected from both research identities.
- `trendatlas-research` and an actual DynamicUser `trendatlas-phase2` probe received **Permission denied** for the trading environment, publisher key, production journal and protected runtime script.
- LeadPilot API/frontend/DB healthy, proxy running. All four start timestamps remain 2026-09-27T20:42:03Z: no LeadPilot restart or configuration change.
- Original research remains SEALED with 7,203 evaluations, 7,211 attempts, zero running work. Its existing checkpoint inspection passed. Phase 2 collector timer remains active. Production priority uses the existing checkpoint stop/resume protocol and a dispatcher admission condition. Active-worker stop/resume and checkpoint-failure behavior were fault-tested with synthetic adapters; no new scientific evaluation was started merely to test preemption. The real SEALED/inactive worker was not resumed by production rehearsal.
- Pi Production Core and latest production-run SHA256 still equal the original audit. Temporary copied replay data on Pi was removed after results were retained, returning disk headroom to about 1.3 GiB. No Pi production data/repository was removed.
- SHA256 deployment evidence: `deployment-SHA256.json`. Private frozen exchange/journal captures remain in protected host storage, not Git.

## Operator commands and their effect

**These commands are prepared, but live cutover must not be attempted while this report is BLOCKED.** The first command currently fails its admission gate before fencing Pi. A successful read-only planner is not a substitute for the failed full golden gate.

One future operator cutover invocation from PowerShell:

```powershell
python C:\Users\benda\Desktop\ta_vps_prod\scripts\execution\cutover_pi_to_vps.py --pi-host 172.16.20.107 --execute-live
```

The IP was observed on Pi during this task; `HostKeyAlias=trendatlas.local` preserves the known SSH host identity. If DHCP changes it, supply the current Pi address. Without `--execute-live`, the command only runs read-only preflight.

The coordinator verifies account/signer/target/journal continuity, waits for Pi to become idle, disables its timer and installs a persistent execution fence, rechecks the final shared database checkpoint, then permits VPS activation. It never restores a stale database snapshot. The VPS helper records possible activation before removing no-submit and enabling the canonical production/watchdog timers. It recognizes a Persistent timer-started run rather than blindly starting a second one. The canonical executor alone handles trading. Final checks include fresh account, open orders, recent fills, journal recovery and sole-host state.

With the currently aligned AVAX position, the expected execution is **NO_ACTION**, retaining 7.65 AVAX without a sell/buy round trip. A later invocation must follow the then-current validated strategy and account; a legitimate resize/exit/entry may differ from today's expectation.

Rollback: before any possible VPS activation, a proven non-activated VPS permits restoration of Pi. After possible submission/activation, Pi stays fenced; the tool reconciles journal/CLOIDs and exchange readback first. Repeating a successful cutover performs readback only. Ambiguous or unverified results fail closed and are not blindly replayed.

Second operator command, **only after successful cutover/readback**:

```powershell
python C:\Users\benda\Desktop\ta_vps_prod\scripts\execution\retire_pi_after_cutover.py --pi-host 172.16.20.107 --execute-cleanup
```

The cleanup tool requires SUCCESS, inventories system/user/cron paths, creates and decrypt-verifies an encrypted rollback archive with SHA256, retires/masks owned units, removes the known active plaintext trading configuration, requests reboot, verifies a different boot ID and retired units, and checks VPS again before setting PI_SAFE_TO_POWER_OFF=true. Production repository/data remain. The independently owned AI Hologram voice service is excluded; shared username alone does not establish TrendAtlas ownership. Actual Pi retirement, encrypted final archive and reboot were deliberately not executed. Cleanup ordering/credential removal/reboot proof were tested on a synthetic filesystem and systemd adapter; this is not a claim of a real reboot test.

## Regression tests and validation commands/results

- Original Python suite: **100 passed**.
- Existing authority publication suite: **17 passed**; fixtures now explicitly emulate actual ARM hardware instead of environment spoofing.
- Host/rehearsal/replay, cutover, retirement and research priority suites: **25 passed**.
- Original four TypeScript suites plus no-submit transport: **116 passed** (original 109 plus 7). Total **258** tests.
- TypeScript `tsc --noEmit`: PASS. Python compile and JSON UTF-8/parse checks: PASS. `git diff --check`: PASS.
- `systemd-analyze verify` on deployed production, timer, watchdog and readback units: exit 0. Unrelated host XFS CPUAccounting deprecation warnings were observed earlier.
- Actual VPS canonical no-submit, actual Info-only account/signer readback, stable journal/account-status checkpoint, fresh fills readback, protected filesystem permission probes, watchdog and publication dry-run: PASS.
- Exact current decision/planner replay: PASS. Full numerical golden replay: **BLOCKED**, as documented above.
- Read-only operator preflight: correctly rejected by the protected failed golden gate before any Pi fence/live action.

```text
python -m unittest tests.test_production_execution tests.test_single_production_orchestrator tests.test_hyperliquid_systemd_credentials tests.test_production_asset_universe_contract tests.test_execution_authority_publish tests.test_production_host_migration tests.test_operator_cutover tests.test_migration_retirement_priority -q
cd web
node node_modules/vitest/vitest.mjs run tests/canonical-execution-contract.test.ts tests/multi-account-executor.test.ts tests/production-boundary.test.ts tests/production-asset-support.test.ts tests/no-submit-transport.test.ts
node node_modules/typescript/bin/tsc --noEmit
```

EXIT-before-ENTRY, reduce-only exits, duplicate/CLOID prevention and unknown-submission recovery remain covered by the unchanged core execution suites. Cutover tests inject failures before activation and after possible submission, check journal/nonce handoff and prevent a second execution on repeat. No synthetic test is presented as a real financial trade.

## Forbidden old paths checked

No full-refresh, manual BUY/SELL, manual authority-snapshot edit, stale JSON journal restoration, legacy environment signer recovery, architecture spoof, second enabled trading timer or generated `outputs/*`/`data/*` commit. No frontend edits or internal labels added to frontend. Pi service/timer and trading configuration were not changed. VPS live override was never removed.

## FILES READ

Required ordered truth reads: AGENTS.md; source_of_truth/README.md; master_state.md; chat_roles.md; project_truth.json; export_contract.json; paths_registry.json; current_issues.md; canonical/script_registry.json; canonical/output_registry.json; canonical/registry_workflow.md; source_of_truth/pi_codex_runtime_workflow.md.

Additional source reads: production_execution_contract.json; watchdog_maintenance_contract.md; original migration REPORT and audit manifests; run_trendatlas_production.py; production_execution.py; authority_contract.py; authority_publish_helpers.py; run_pi_authoritative_producer.py; validate_execution_source_contract.py; Production Core builder/validator and active strategy adapter; web multi-account runner, authority, guard, repository, preflight, planner, types, dry-run gateway and Supabase admin; active database schema migration; existing execution and authority test suites; installed Pi/VPS production/watchdog/research units; pinned research orchestration checkpoint code. Supabase skill and official API security/changelog references were consulted for the read-only transport boundary. No messages were sent using a connector.

## Exact files changed / exact git add list

`GIT_ADD.txt` contains the exact explicit add command for this continuation, including code, source contracts, tests, units and reports. No credential, private account dump, raw journal, generated runtime data or virtual environment is included.

## Commit message

`Stage isolated VPS production and gate cutover on exact replay`

## Commit hash

The final task response supplies the created commit hash and push result. This document does not embed its own commit hash. No merge or production activation is implied by pushing this branch.
