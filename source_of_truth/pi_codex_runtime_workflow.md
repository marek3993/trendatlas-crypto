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

## Default Safety Posture
- do NOT run long/full refresh by default
- do NOT run `--mode full-refresh` unless explicitly approved
- allowed fast nightly authority path:
  - `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_fast_daily_authority_refresh.py`
- the fast nightly authority wrapper must refresh the read-only Hyperliquid wallet snapshot before publish-existing dry-run
- if the fast nightly wrapper detects that the canonical durable BTC-persistence dependency source day is behind the refreshed BTC closed day and the gap reaches or crosses `next_rebalance_date`, it must first refresh only the minimal Production Core dependency inputs and rebuild `current_strategy` before `publish-existing --dry-run`
- allowed publish-existing primitive:
  - `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_authoritative_producer.py --mode publish-existing`
- always dry-run before real publish
- no live order
- no manual authority snapshot edits
- no manual generated outputs/data commits outside official authority producer
- if `git pull` makes runtime stale, restore approved fresh runtime stash before dry-run
- verify:
  - `heavy_refresh_steps=skipped`
  - `live_order_chain=not_invoked`

## Required Pi Nightly Service Workflow
The installed Pi daily service (`mrv1-daily-live.service`, or the repo-provided nightly service alias) must call:

`/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_fast_daily_authority_refresh.py`

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
10. conditional rebalance-boundary dependency refresh only when the canonical durable BTC-persistence dependency source day would otherwise carry forward across `next_rebalance_date`:
    - `scripts/execution/materialize_execution_app_exports.py --production-core-dependencies-only`
    - `scripts/production/build_current_strategy_snapshot.py`
11. `scripts/execution/run_pi_authoritative_producer.py --mode publish-existing --dry-run`
12. `scripts/execution/run_pi_authoritative_producer.py --mode publish-existing` only when `MRV1_ENABLE_AUTHORITY_PUBLISH=1` and `MRV1_AUTHORITY_MODE=authoritative`

The nightly wrapper must not invoke `--mode full-refresh`, the old full Phase63 grid, a live-order submitter, or any manual authority snapshot edit.

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
- `gate would_place_real_order=false`
- `heavy_refresh_steps=skipped`
- `live_order_chain=not_invoked`

## Parallel Task Rule
- Keep an explicit open-task list with `task name / owner / status / next action / blocker`.

## Hard Runtime Boundaries
- No live order.
- No manual authority snapshot edits.
- No manual generated `outputs/*` or `data/*` commits outside the official authority producer path.
- No default escalation from `publish-existing` to `full-refresh`.
- No dashboard or tablet task may redefine repo authority away from the Pi authority files.
