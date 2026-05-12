# Pi Codex Runtime Workflow

This file is the approved Pi authority runtime runbook for Codex, segmented chats, and operators.

## Scope
- Use this workflow for Pi authority, publish, scheduler, recovery, and tablet/dashboard coordination tasks.
- Do not treat this file as permission to run anything automatically. Runtime actions still require explicit approval.

## Roots
- Pi repo root = `/opt/market_regime_v1`
- Home dashboard root for tablet/dashboard tasks only = `/opt/home_automation`
- Do not treat `/opt/home_automation` as the Market Regime repo root.

## Default Safety Posture
- do NOT run long/full refresh by default
- do NOT run `--mode full-refresh` unless explicitly approved
- allowed fast authority path:
  - `/opt/market_regime_v1/.venv/bin/python scripts/execution/run_pi_authoritative_producer.py --mode publish-existing`
- always dry-run before real publish
- no live order
- no manual authority snapshot edits
- no manual generated outputs/data commits outside official authority producer
- if `git pull` makes runtime stale, restore approved fresh runtime stash before dry-run
- verify:
  - `heavy_refresh_steps=skipped`
  - `live_order_chain=not_invoked`

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
