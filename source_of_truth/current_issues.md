# Current Issues

## Accepted current state
- Production Core v1 is active as the primary production strategy truth interface.
- Primary strategy truth artifacts:
  - `outputs/production/current_strategy_snapshot.json`
  - `outputs/production/current_strategy_timeseries.csv`
  - `outputs/production/current_strategy_diagnostics.json`
- Pi-only runtime authority model is active.
- Runtime authority source remains:
  - `outputs/execution/authority/latest_successful_snapshot.json`
  - `outputs/execution/authority/latest_attempt_status.json`
- Legacy snapshot/runtime/refresh paths are non-authoritative for app reasoning.

## Production Core semantic guardrails
- `candidate_asset` is a model candidate only.
- `selected_asset` is the selected model candidate.
- `actual_held_asset` / `authorized_tradable_asset` are the current authorized asset.
- `effective_market_exposure` is the authorized market exposure.
- `model_candidate_exposure` is only the candidate exposure if permission allows.
- `trend_permission_active` gates market exposure.
- Candidate `BTC` does not automatically mean live market exposure.

## Active operational focus
- Recurring scheduler is ready.
- Live runtime is armed.
- Remaining proof gap is the first non-CASH end-to-end dynamic leverage evidence run.
- Confirm Production Core remains the app homepage and execution primary strategy truth interface.

## Data health guard current state
- Data Health / Source Availability Guard is active and remains separate from Production Core strategy truth and Pi runtime authority.
- Guard artifacts:
  - `outputs/production/data_health_report.json`
  - `outputs/production/data_health_report.quality.json`
  - `outputs/production/data_health_report.manifest.json`
- Current real state is `warning`, while production remains allowed.
- Current status split: `app_status=ok`, `execution_status=ok`, `research_status=warning`.
- Current block flags: `block_app=false`, `block_execution=false`.
- Production-critical failures block app and execution fail-closed.
- App-critical failures block app fail-closed.
- Execution-critical failures block execution fail-closed.
- Research-only failures do not block production, but block the relevant research probe.
- Missing optional env/API keys are surfaced as `unavailable` / `warn_only`.
- No silent fallback is allowed around guarded source availability.
- Stale or missing `BTC` daily OHLCV is production-critical and would block production/execution.
- Current stale research-only BTC derivatives panel blocks only the relevant research probe.

## Explicitly non-authoritative legacy paths
- `outputs/execution/app_snapshot/*`
- `outputs/app_refresh_pipeline/*`
- `outputs/execution/full_auto_scheduler/*`
- `outputs/execution/runtime_health/*`
- `outputs/execution/live_status/*`

## AI LAB governance
- `phase69` remains paused.
- Official strategy advancement remains paused.
- Widened dev-only anomaly operating mode remains approved.
- `response_shape_bot_v1`, bot-vs-bot compare, and `supportive_vs_caution_subset_layer_v1` remain dev-only and non-authoritative.

## Legacy phase chain
- Legacy phase-chain outputs remain research/archive/input lineage only.
- They are not the primary runtime production truth interface.
