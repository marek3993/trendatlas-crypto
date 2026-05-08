# Master State

## Official state snapshot
- Official core production baseline: `phase66g_production_soft_filters`
- Official universe winner: `phase67j_no_neo_main`
- Current live/app truth: `phase68g_66g_1p25x_candidate`
- Current app main strategy model: `phase68g_66g_1p25x_candidate`
- Reference strategy model: `phase67j_no_neo_main`
- Benchmark: `BTC`

## Production Core v1 strategy truth interface
- Primary production strategy truth interface:
  - `outputs/production/current_strategy_snapshot.json`
  - `outputs/production/current_strategy_timeseries.csv`
  - `outputs/production/current_strategy_diagnostics.json`
- Build script: `scripts/production/build_current_strategy_snapshot.py`
- Validation script: `scripts/production/validate_current_strategy_snapshot.py`
- Adapter model: `strategy_adapter_replacement_model`
- App homepage and execution now read Production Core v1 as the primary production strategy truth interface.

## Production Core semantics
- `candidate_asset` = model candidate, not automatic live exposure.
- `selected_asset` = selected model candidate.
- `actual_held_asset` / `authorized_tradable_asset` = current authorized asset.
- `effective_market_exposure` = current authorized market exposure.
- `model_candidate_exposure` = candidate exposure if permission allows.
- `trend_permission_active` gates market exposure.
- `execution_target` = authorized execution target.
- Candidate `BTC` does not automatically mean live market exposure.

## Phase68G promotion
- Current live truth: `phase68g_66g_1p25x_candidate`
- Best deployment candidate: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Official fallback: `phase68i_dynamic_ladder_candidate`
- App main strategy model: `phase68g_66g_1p25x_candidate`
- Live mode contract current: `phase68g_66g_1p25x_candidate`
- Fallback contract: `phase68i_dynamic_ladder_candidate`
- `ordering_remains_unchanged = false`

## Production Core vs Pi authority
- Production Core v1 is the primary strategy truth interface.
- Raspberry Pi is the only automatic production producer.
- Runtime authority source:
  - `outputs/execution/authority/latest_successful_snapshot.json`
  - `outputs/execution/authority/latest_attempt_status.json`
- PC role: `manual_recovery_debug_only`
- GitHub Actions role: `validation_only`
- Pi authority is runtime/publish authority and remains separate from Production Core strategy truth.

## Data Health / Source Availability Guard
- Guard status: active
- Authoritative guard artifacts:
  - `outputs/production/data_health_report.json`
  - `outputs/production/data_health_report.quality.json`
  - `outputs/production/data_health_report.manifest.json`
- Build script: `scripts/production/build_data_health_report.py`
- Validation script: `scripts/production/validate_data_health_report.py`
- The guard is separate from Production Core strategy truth and separate from Pi runtime authority.
- The guard governs data/source availability only.
- Production-critical failures block app and execution fail-closed.
- App-critical failures block app fail-closed.
- Execution-critical failures block execution fail-closed.
- Research-only failures do not block production, but they block the relevant research probe.
- Missing optional env/API keys are surfaced as `unavailable` / `warn_only`.
- No silent fallback is allowed for degraded or missing guarded sources.
- Stale or missing `BTC` daily OHLCV is production-critical and blocks production/execution.
- Current real state: `overall_status=warning`, `app_status=ok`, `execution_status=ok`, `research_status=warning`.
- Current block flags: `block_app=false`, `block_execution=false`.
- Production remains allowed in the current state.
- Current stale research-only BTC derivatives panel blocks only the relevant research probe.

## Runtime/live state
- Recurring scheduler: ready
- Live runtime: armed
- Remaining proof gap: first non-CASH end-to-end dynamic leverage evidence run

## AI LAB dev-only governance
- `phase69` remains paused.
- Official strategy advancement remains paused.
- Widened dev-only anomaly operating mode is approved.
- `response_shape_bot_v1` is approved.
- Bot-vs-bot compare is approved.
- `supportive_vs_caution_subset_layer_v1` is approved.
- Dev-only post-run anomaly step is attached after successful daily refresh.
- All such outputs remain `dev_only=true` and `non_authoritative=true`.

## Legacy phase chain
- Legacy phase-chain outputs are research/archive/input lineage only.
- They are not the primary runtime production truth interface.
