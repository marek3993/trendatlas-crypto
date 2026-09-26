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

## Stable Pi/runtime/dashboard state recorded 2026-09-02
- Raspberry Pi authority automation is installed and working.
- `mrv1-production.timer` is enabled and active as the single canonical production scheduler.
- Nightly authority run is scheduled for 02:10 local time, after the UTC candle close.
- `mrv1-watchdog.timer` is enabled and active.
- `home-blinds-dashboard.service` is enabled and active.
- `home-dashboard-kiosk-watchdog.timer` is enabled and active.
- Dashboard backend starts automatically after boot.
- Kiosk watchdog opens/reopens Chromium dashboard automatically.
- PC Windows scheduled MRV1 tasks are disabled; PC remains manual recovery/debug only.
- Pi fast daily wrapper refreshes the read-only Hyperliquid wallet snapshot before `publish-existing`.
- Latest confirmed execution dry-run passed in safe CASH/no-action state:
  - `AUTH target=2026-05-15`
  - `INTENT=2026-05-15 CASH 0.0 stale=False`
  - `GATE=2026-05-15 CASH blocked False`
  - `REAL_ACCOUNT=CASH / 0.00x`
  - `MODEL_SIGNAL=CASH / 0.0x`
- First canonical production reconciliation completed as `FILLED_AND_ALIGNED` with order `533921077867`; no further order is authorized for compatibility hardening.
- Current public homepage graph policy is locked: the main `Modelový vývoj vs BTC` graph is the only public graph section, no extra expandable `Reálny účet` graph is allowed, and graph legends must not be added unless explicitly requested.
- Public main graph semantics are authorized-model only: the red model line uses the model strategy after trend permission, and the lower strip uses authorized model exposure after trend permission.
- Candidate/preferred asset is model preference only. It is not authorized exposure and not real wallet exposure.
- If the model prefers a crypto candidate but trend permission does not authorize entry, the public model line must stay flat for that blocked-entry period and the lower strip must show `0x`.
- Public UI must not leak internal labels such as `Základná zložka`, `Zakladna zlozka`, `BASE`, `BASELINE`, `CORE`, `BASELINE_RISK`, `EARLY_RISK`, `FULL_RISK`, or internal strategy/profile names.

## Production Core semantic guardrails
- `candidate_asset` is a model candidate only.
- `selected_asset` is the selected model candidate.
- `actual_held_asset` / `authorized_tradable_asset` are the current authorized asset.
- `effective_market_exposure` is the authorized market exposure.
- `model_candidate_exposure` is only the candidate exposure if permission allows.
- `trend_permission_active` gates market exposure.
- Candidate `BTC` does not automatically mean live market exposure.

## Active operational focus
- Keep recurring production scheduling on the single canonical orchestrator `scripts/execution/run_trendatlas_production.py`; competing production execution timers remain disabled.
- `mrv1-production.service` uses `LoadCredentialEncrypted=hyperliquid-agent-private-key`; the named `TrendAtlasProd` signer is validated against master account `0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856` before execution.
- The former process-environment signer is intentionally unrecoverable and must not be searched for. Browser-wallet extraction, credential dumping, filesystem-forensic secret recovery, and any master-private-key request are forbidden.
- Exchange authorization expiry is an operational lifecycle condition: daily signer validation must surface the public expiry and fail closed once authorization is expired.
- Live runtime activation settings remain armed, but execution must fail closed unless deterministic CLOID recovery, canonical provenance, fresh account/margin state, and post-trade verification all pass.
- Public compatibility hardening must keep verified real exposure separate from the 0.5 model target, preserve `live_order_sent=true` for the first filled run, and publish only a finalized terminal production status.
- Account observability must keep Hyperliquid total account equity separate from free collateral, withdrawable amount, margin used, and position notional. Unified-account spot collateral visibility must not make the full spot stable total appear free while native holds back a position; missing native free/withdrawable semantics must surface as unavailable.
- Manual app `live_execute` is intentionally disabled because the Streamlit process does not own the systemd signer credential; the canonical service is the only live execution entrypoint.
- Confirm Production Core remains the app homepage and execution primary strategy truth interface.
- Current live/app truth is `phase68g_etf_flow_impulse_early_risk_cooldown_15`.
- Official softer fallback is `phase68g_btc_persistence_10d_early_risk_075`.
- Secondary fallback is `phase68g_66g_1p25x_candidate`.
- `phase68i_dynamic_ladder_candidate` is legacy / historical fallback only.
- ETF-flow is promoted and is the current live truth.

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
- Canonical execution health is locked to `outputs/execution/intents/latest_execution_intent.json` and `outputs/execution/live_gate/latest_real_order_gate_decision.json`; temporary publish-existing execution artifacts may not override those sources in data health.
- Production execution state is recorded in `outputs/execution/production_runs/latest_production_run.json` and durable transition journals under `outputs/execution/execution_journal/`; these never replace Production Core, canonical intent/gate, or real account truth.
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


## Route identity repair — 2026-09-26 (review / no-submit only)
- Classes B/C/D: weekly candidate names previously replaced inactive BASE economic holdings; same-day decision returns also contaminated model performance.
- Normative contract: `source_of_truth/production_route_identity_contract.json`. BASE joins the same-interval concrete Phase60 asset. CANDIDATE requires its actual trigger. No strategy parameters or candidate-selection exclusions are changed.
- The current signal target is distinct from a historical interval holding. Both have explicit route/availability lineage; only the causal interval ledger feeds model performance. Real account equity/PnL remain exchange-native.
- Preserve the deployed `5ee031cef7de9c385056cec22f6511391d3e4f4f` exit-first executor, per-account isolation and persistent scheduler semantics when integrating this repair with the main/audit base. `production_execution_contract.json` supersedes older allowlist/duplicate approval-gate prose.
- The causal adapter consumes freshly produced Phase60/governance/trend/ETF/raw prices directly. It does not rebuild the synthetic legacy Phase68 same-day dependency.
- Stage the repair in an isolated Pi tree and run the same canonical orchestrator/service environment with `--no-submit`. No-submit skips database mutation callbacks as well as every exchange mutation. Keep the production timer, journal, authority snapshots, secrets and position unchanged.
- No merge, live activation or trade is authorized. Successful rehearsal is evidence for the operator's final decision, not a permission to trade.
