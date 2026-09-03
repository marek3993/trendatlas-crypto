# Pi Codex Runtime Workflow

This file is the approved Pi authority runtime runbook for Codex, segmented chats, and operators.

## Scope
- Use this workflow for Pi authority, publish, scheduler, recovery, and tablet/dashboard coordination tasks.
- Do not treat this file as permission to run anything automatically. Runtime actions still require explicit approval.

## Roots
- Pi repo root = `/opt/market_regime_v1`
- Home dashboard root for tablet/dashboard tasks only = `/opt/home_automation`
- Do not treat `/opt/home_automation` as the Market Regime repo root.

## Current Stable Runtime State Recorded 2026-05-16
- Raspberry Pi authority automation is installed and working.
- `mrv1-daily-live.timer` is enabled and active.
- Nightly authority run is scheduled for 02:10 local time, after the UTC candle close.
- `mrv1-watchdog.timer` is enabled and active.
- `home-blinds-dashboard.service` is enabled and active.
- `home-dashboard-kiosk-watchdog.timer` is enabled and active.
- Dashboard backend starts automatically after boot.
- Kiosk watchdog opens/reopens Chromium dashboard automatically.
- PC Windows scheduled MRV1 tasks are disabled; PC remains `manual_recovery_debug_only`.
- Pi fast daily wrapper refreshes `scripts/execution/hyperliquid_read_only_snapshot.py` before `publish-existing`.
- Latest confirmed execution dry-run passed in safe CASH/no-action state:
  - `AUTH target=2026-05-15`
  - `INTENT=2026-05-15 CASH 0.0 stale=False`
  - `GATE=2026-05-15 CASH blocked False`
  - `REAL_ACCOUNT=CASH / 0.00x`
  - `MODEL_SIGNAL=CASH / 0.0x`
- Live order/leverage test is intentionally not done while the current strategy says `CASH`.
- Current dashboard graph display is accepted; do not add graph legends or semantic rewrites unless explicitly requested later.

## Canonical Production Posture
- do NOT run long/full refresh by default
- do NOT run `--mode full-refresh` unless explicitly approved
- the only automatic daily production entrypoint is:
  - `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_trendatlas_production.py`
- `run_pi_fast_daily_authority_refresh.py`, `run_pi_authoritative_producer.py`, and controlled submit helpers remain internal modules/tools; no competing automatic scheduler may invoke them independently
- the fast nightly authority wrapper must refresh the read-only Hyperliquid wallet snapshot before publish-existing dry-run
- if the fast nightly wrapper detects that the canonical durable BTC-persistence dependency source day is behind the refreshed BTC closed day and the gap reaches or crosses `next_rebalance_date`, it must first refresh only the minimal Production Core dependency inputs and rebuild `current_strategy` before `publish-existing --dry-run`
- allowed publish-existing primitive:
  - `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_authoritative_producer.py --mode publish-existing`
- always dry-run before real publish
- live order submission is allowed only from the canonical orchestrator after every current-run gate passes; safe validation uses `--no-submit`
- the production signer is the distinct named Hyperliquid API/agent wallet `TrendAtlasProd` for master account `0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856`
- signer material is loaded only as the systemd encrypted credential `hyperliquid-agent-private-key` through `LoadCredentialEncrypted`; inline config, process-environment, command-line, journal, artifact, dashboard, and run-manifest secret transport are forbidden
- because this Pi has no usable TPM2 device, systemd host-key encryption is the approved strongest practical encrypted-credential backend
- `--no-submit` must validate credential presence, derive the public signer address locally, and validate master role plus named-agent authorization without instantiating the order-submission adapter or mutating exchange state
- every live transition must have a durable pre-submission journal record and deterministic Hyperliquid CLOID before the request is sent
- restart recovery must query the exchange by CLOID and refresh account/open-order state before any residual submission
- the canonical service uses `Restart=on-failure` with `RestartSec=15min`; a temporary failure retries the same orchestrator, while a successful pass is not restarted
- during a legitimate first attempt for closed day D, the prior successful authority snapshot may be D-1 only when the in-progress attempt plus canonical Production Core, intent, gate, and account fingerprints all prove the same run and D; stale underlying inputs and mismatched bindings still block
- fixed-dollar sizing is forbidden; target notional is fresh account equity multiplied by validated Production Core target exposure, with safety violations blocking rather than clipping
- no manual authority snapshot edits
- no manual generated outputs/data commits outside official authority producer
- if `git pull` makes runtime stale, restore approved fresh runtime stash before dry-run
- verify:
  - `heavy_refresh_steps=skipped`
  - `live_order_chain=not_invoked`

## Required Pi Nightly Service Workflow
The installed Pi production service must call only:

`/opt/market_regime_v1/.venv/bin/python scripts/execution/run_trendatlas_production.py`

The orchestrator owns the following ordered state machine under one lock: refresh, precheck health, Production Core build/validation, fresh account snapshot, canonical intent, canonical gate, data-health validation, reconciliation plan, optional controlled live execution, exchange/account read-back, post-trade verification, finalized production run manifest, dashboard materialization, and final authority publish. Authority success is forbidden before required execution and verification are complete. A completed run must never be materialized or published with `final_status=RUNNING`.

That wrapper must run exactly the fast dependency chain before publish-existing:

1. `scripts/refresh_legacy_ohlcv.py`
2. `scripts/refresh_phase67_top100_shortlist_ohlcv.py`
3. `phase60_selective_restore_robustness.py --dependency-only --model-key phase60_restore_trx_sol_base`
4. `scripts/phase63_btc_participation_overlay.py --winner-only --variant-key phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3`
5. `scripts/phase66g_production_candidate_live.py`
6. `scripts/phase67j_final_narrow_validation_pack.py`
7. `scripts/dev_only_build_btc_etf_flow_daily_panel.py`
8. `scripts/verify_app_freshness.py`
9. `scripts/execution/hyperliquid_read_only_snapshot.py`
10. `scripts/execution/build_hyperliquid_real_performance_ledger.py` (read-only exchange-native account accounting; never places an order)
11. conditional rebalance-boundary dependency refresh only when the canonical durable BTC-persistence dependency source day would otherwise carry forward across `next_rebalance_date`:
    - `scripts/execution/materialize_execution_app_exports.py --production-core-dependencies-only`
    - `scripts/production/build_current_strategy_snapshot.py`
12. `scripts/execution/run_pi_authoritative_producer.py --mode publish-existing --dry-run`; its required safe internal chain is:
    - validate the current Production Core snapshot
    - run `scripts/execution/build_execution_intent_from_strategy_exports.py` into the canonical intent paths
    - run `scripts/execution/prepare_real_order_gate.py` from that canonical intent and the current read-only Hyperliquid snapshot into the canonical gate paths
    - validate data health against the real canonical intent and gate; temporary execution-source path overrides are forbidden
    - rematerialize app/runtime/dashboard artifacts from the refreshed canonical execution state
    - do not invoke reconciliation or any live-order submitter
13. `scripts/execution/run_pi_authoritative_producer.py --mode publish-existing` only when `MRV1_ENABLE_AUTHORITY_PUBLISH=1` and `MRV1_AUTHORITY_MODE=authoritative`; it must repeat/verify the canonical execution chain against the written authority files before publishing

The orchestrator must not invoke `--mode full-refresh`, the old full Phase63 grid, or any manual authority snapshot edit. It may invoke the controlled live execution primitive only after its pre-submit checks and only when not running `--no-submit`. Manual Streamlit `live_execute` is intentionally disabled; only the credential-mounted canonical systemd production service may reach live submission.

If the conditional refresh is required but the dependency-only materialization or Production Core rebuild cannot complete safely, the wrapper must fail before publish with `BLOCKED_REBALANCE_BOUNDARY_NEEDS_BASELINE_REFRESH`. The adapter guard that blocks unsafe carry-forward across rebalance boundaries remains the final fail-closed protection.

## Required Pi Workflow
1. `git status`
2. `git fetch origin main`
3. `git pull --rebase origin main`
4. locate fresh stash if runtime stale
5. restore approved runtime bundle only if needed
6. run publish-existing dry-run:
   `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_authoritative_producer.py --mode publish-existing --dry-run`
7. only then run real publish:
   `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_authoritative_producer.py --mode publish-existing`
8. pull published authority commit
9. verify final state

If step 3 invalidates the approved fresh runtime bundle, restore the approved stash before step 6 and do not improvise manual output or snapshot edits.

## Required Verification Fields
- `AUTH attempt status`
- `AUTH success model/target`
- `target_closed_day_utc`
- `dashboard_public_status exists when expected`
- `real_account asset/exposure/in_market`
- `model_signal preferred_asset/exposure`
- `health block_app/block_execution`
- `canonical intent day/model/signal/target/exposure exactly match Production Core`
- `canonical gate signal/target and intent fingerprint match the canonical intent`
- `canonical gate account-snapshot fingerprint matches the current read-only account snapshot`
- `gate would_place_real_order` recorded from current policy/account/signal state; regardless of value, the fast authority workflow must stop before submission and report `live_order_chain=not_invoked`
- `heavy_refresh_steps=skipped`
- `live_order_chain=not_invoked`

## Parallel Task Rule
- Keep an explicit open-task list with `task name / owner / status / next action / blocker`.

## Hard Runtime Boundaries
- No live order outside the canonical production orchestrator.
- `--no-submit` must never invoke an exchange mutation.
- Missing, malformed, expired, wrong-account, wrong-name, or unauthorized signer credentials must block before any exchange mutation.
- The old `HYPERLIQUID_SECRET_KEY` process-environment provisioning path is forbidden for production and must not be recovered or reinstated.
- Safe publish-existing validation performs no live order and never invokes the submitter.
- No manual authority snapshot edits.
- No manual generated `outputs/*` or `data/*` commits outside the official authority producer path.
- No default escalation from `publish-existing` to `full-refresh`.
- No dashboard or tablet task may redefine repo authority away from the Pi authority files.
