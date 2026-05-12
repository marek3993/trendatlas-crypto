# Master State

## Official state snapshot
- Official core production baseline: `phase66g_production_soft_filters`
- Official universe winner: `phase67j_no_neo_main`
- Current live/app truth: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Current app main strategy model: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Reference strategy model: `phase67j_no_neo_main`
- Benchmark: `BTC`
- Official repo workflow discipline: `contract_first_regression_locked`

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
- `actual_held_asset` / `authorized_tradable_asset` = current authorized asset, not real wallet/account balance truth.
- `current_asset` = legacy/model-side asset label, not real wallet exposure truth.
- `effective_market_exposure` = current authorized market exposure, not wallet-confirmed exposure.
- `model_candidate_exposure` = candidate exposure if permission allows.
- `trend_permission_active` gates market exposure.
- `execution_target` = authorized execution target.
- Candidate `BTC` does not automatically mean live market exposure.
- Real wallet/account exposure must come from `real_account_state`, not from Production Core fields.
- Model strategy performance must stay in `model_performance_state`, not in real account PnL.

## Repo-wide contract-first workflow
- Bug classes: `A=wording/UI-only`, `B=runtime/data contract`, `C=execution/authority/scheduler`, `D=strategy math`.
- Classes `B`, `C`, and `D` must not start with a UI patch.
- For classes `B`, `C`, and `D`, patch and validate the source contract first, then patch consumers.
- Required normalized public/runtime contracts:
  - `real_account_state`
  - `model_signal_state`
  - `model_performance_state`
  - `authority_state`
  - `data_health_state`
- Forbidden shortcuts: do not use `actual_held_asset`, `current_asset`, or `effective_market_exposure` as real wallet exposure.
- Forbidden shortcuts: do not use model equity or paper equity as real account PnL.
- Forbidden shortcuts: do not show model exposure as real account exposure.
- Forbidden shortcuts: dashboards must not infer account state from model fields.
- Recurring bugs require a regression test.
- A wording-only fix is allowed only for class `A`.
- Non-trivial Codex output must include `FILES READ`, `SOURCE OF TRUTH`, exact root cause, exact contract impact, exact files changed, regression test added/updated, forbidden old path checked, validation commands/results, exact git add list, and commit message.

## Phase68G promotion
- Current live truth: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Best deployment candidate: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Official softer fallback: `phase68g_btc_persistence_10d_early_risk_075`
- Secondary fallback: `phase68g_66g_1p25x_candidate`
- Current app main strategy model: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Live mode contract current: `phase68g_etf_flow_impulse_early_risk_cooldown_15`
- Fallback contract: `phase68g_btc_persistence_10d_early_risk_075`
- `phase68i_dynamic_ladder_candidate` is legacy / historical fallback only.
- ETF-flow is promoted and is the current live truth.
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
