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
- Pi/Codex runtime runbook: `source_of_truth/pi_codex_runtime_workflow.md`
- Runtime authority source:
  - `outputs/execution/authority/latest_successful_snapshot.json`
  - `outputs/execution/authority/latest_attempt_status.json`
- PC role: `manual_recovery_debug_only`
- GitHub Actions role: `validation_only`
- Pi authority is runtime/publish authority and remains separate from Production Core strategy truth.
- Canonical daily Pi production entrypoint is `scripts/execution/run_trendatlas_production.py`; it owns refresh through final authority publish under one single-run lock and one run manifest.
- On a first attempt or recovery after missed runs, the previous successful authority snapshot may be one or more days behind only when the in-progress attempt and canonical Production Core, intent, gate, and account fingerprints prove the same run and new day; all underlying stale inputs still block. Recovery reconciles only the current target; it never replays missed orders or edits the old successful snapshot.
- `mrv1-production.service` retries a failed canonical pass after 15 minutes and stops retrying after success; no second scheduler or execution path is introduced.
- Completed production execution must be finalized in the run manifest after post-trade verification and before dashboard/runtime materialization; authority publication consumes that finalized state and must never publish `RUNNING` as a completed run status.
- Public real exposure is fresh wallet position notional divided by real account equity, never the model target. `dashboard_public_status.execution.live_order_sent` remains a boolean compatibility field and must reflect finalized run submission evidence.
- Real account balance observability distinguishes total equity, free collateral, exchange-native withdrawable, margin used, and position notional. In Hyperliquid unified-account mode, spot stable `total` is total equity while free collateral is the coherent native spot `total - hold`; the legacy `available_balance_usd` field is only a nullable compatibility alias of free collateral and must never copy total equity. A withdrawable value is published only when exchange-native semantics are valid for the current abstraction; otherwise it is unavailable rather than fabricated.
- Manual Streamlit `live_execute` is intentionally disabled. Live reconciliation is owned only by the credential-mounted canonical systemd production service.
- `publish-existing` remains an internal authority-publish primitive and is not a production scheduler entrypoint.
- `--mode full-refresh` requires explicit approval.
- The orchestrator reuses the validated fast dependency refresh and must not escalate to `--mode full-refresh` without explicit approval.
- Live submission is permitted only after the current run has validated Production Core, canonical intent/gate provenance, current data health, fresh account state, deterministic reconciliation, and durable pre-submit idempotency recovery.
- The production Hyperliquid signer must be the named API/agent wallet `TrendAtlasProd` authorized by master account `0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856`; account queries must continue to use the master-account address, never the agent address.
- Signer material must be supplied only through the `mrv1-production.service` systemd encrypted credential `hyperliquid-agent-private-key`; inline config, environment-secret, command-line, journal, artifact, dashboard, and run-manifest secret transport are forbidden.
- Every production run, including `--no-submit`, must derive the signer address locally and validate the configured master account plus current exchange-side named-agent authorization without submitting an order.
- Execution sizing is `fresh_account_equity_usd * validated_target_exposure`; fixed-dollar policy limits must not clip a valid strategy target. Relative safety ceilings block instead of resizing.
- A same-asset residual that is within the explicit post-trade tolerance and below the exchange minimum order notional is precision-limited alignment: the recurring planner must emit `NO_ACTION`, retain the residual for observability, and must not create or submit a dust order.
- Every submitted transition uses a deterministic Hyperliquid CLOID and a durable journal record written before the exchange request. Restart recovery queries exchange state by CLOID and refreshes the account before deciding whether any residual order is safe.
- Authority success for a run requiring execution is published only after exchange outcome and post-trade account verification are known.

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
- Production/execution dependency failures block only new_trade_transition; block_app remains false and system_available true.
- App-critical failures degrade only the dependent display capability.
- Execution-critical failures block execution fail-closed.
- Research-only failures do not block production, but they block the relevant research probe.
- Missing optional env/API keys are surfaced as `unavailable` / `warn_only`.
- No silent fallback is allowed for degraded or missing guarded sources.
- Execution health must validate the canonical intent and gate paths directly against Production Core and the canonical read-only account snapshot; temporary execution-source path overrides are forbidden.
- Stale or missing `BTC` daily OHLCV blocks new_trade_transition only; unrelated capabilities remain available.
- Current real state: `overall_status=warning`, `app_status=ok`, `execution_status=ok`, `research_status=warning`.
- Current block flags: `block_app=false`, `block_execution=false`.
- Production remains allowed in the current state.
- Current stale research-only BTC derivatives panel blocks only the relevant research probe.

## Runtime/live state
- Recurring scheduler: active through the single canonical production timer
- Live runtime: armed
- Remaining proof gap: first non-CASH end-to-end dynamic leverage evidence run
- Canonical scheduler target: `scripts/execution/run_trendatlas_production.py`; legacy fast/authority/full-auto scripts are internal tools and must not be enabled as competing automatic production schedulers.
- Approved migration target (not active until cutover validation completes): the same canonical production orchestrator may delegate its execution stage to the fail-closed multi-account backend while retaining the existing single timer, single lock, refresh, validation, verification, and authority-publish ownership. Dual legacy plus multi-account order submission is forbidden.

## AI LAB dev-only governance
- `phase69` remains paused.
- Official strategy advancement remains paused.
- Widened dev-only anomaly operating mode is approved.
- `response_shape_bot_v1` is approved.
- Bot-vs-bot compare is approved.
- `supportive_vs_caution_subset_layer_v1` is approved.
- Dev-only post-run anomaly step is attached after successful daily refresh.
- All such outputs remain `dev_only=true` and `non_authoritative=true`.

- User-authorized local evolution research (2026-09-20) is dev-only: 10 candidates,
  6 survivors, 4 new mutations, real historical backtests and a sealed final test.
  IML is not required. Results cannot alter production, authority or scheduling.

## Legacy phase chain
- Legacy phase-chain outputs are research/archive/input lineage only.
- They are not the primary runtime production truth interface.

## Dependency-scoped maintenance observed 2026-09-21
- Watchdog is installed and enabled four times daily UTC; it can repair only its own diagnostic cache, never run production/refresh/publish or submit orders.
- Source failures affect declared capabilities/actions; system availability remains true. Order freshness/provenance checks remain fail-closed for new_trade_transition.
- AI diagnosis is optional; missing OPENAI_API_KEY currently leaves deterministic maintenance active with warning. Deployment audit: docs/watchdog-deployment-audit-20260921.md.

## Bounded research campaign observed 2026-09-22
- The explicitly authorized v3 campaign completed on Pi: all ten rolling walk-forward experiments finished five generations of 10/6/4 and SEALED HISTORICAL_REJECT. Its finite budget remains exhausted and its artifacts immutable. See docs/evolution-campaign-deployment-20260922.md; no production promotion or order.

## Continuous research and dashboard observed 2026-09-22
- Pi production remains at commit `1bb2d0d64363d111d92e4257d0a7345b484b8532`; `mrv1-production.timer` remains the only production trading scheduler, enabled/active. The real account is CASH / 0.00x. AVAX / 1.00x is a model candidate only: `trend_permission_active=false`, authorized target CASH / 0, gate `no_action`, no entry authorized and no order requested/sent. Next daily production check is 2026-09-23 00:10 UTC; the 2026-09-27 rebalance can first be processed on 2026-09-28 00:10 UTC if entry becomes authorized. The kiosk now says `Čaká na signál` and explains the wait instead of labelling it as a safety block.
- Isolated continuous research release `826e42d9f31d92d290c5c152566cc917cda5be20` (release SHA256 `78fb441a486d6a3e398e728f0c843d5f77acca9130e313b48e876631213c00cf`) is deployed only under `/opt/trendatlas-research`. The enabled dispatcher automatically completed five distinct, fingerprinted retrospective BTC/cash cycles; all SEALED `HISTORICAL_REJECT`. Four completed five generations of 10/6/4; regime ensemble stopped after generation one because fewer than six eligible survivors remained. The worker is now inactive and status is `WAITING_FOR_NEW_DATA` until at least 30 new append-only closed UTC BTC daily bars exist. Dispatcher checks automatically every 15 minutes; it does not replay the same rejected search.
- Research has no production/account/authority/order/network access and cannot promote a strategy. The Pi lacks a memory cgroup controller, so actual no-swap compute protection is the observed `LimitAS=384M`, `mlockall(CURRENT|FUTURE)`, nonzero locked memory and zero worker swap; CPU quota is 20% of one core. All ten old v3 SEALED studies remain untouched. Full deployment and no-order evidence: `docs/continuous-evolution-deployment-audit-20260922.md`. Historical rejection is not a production PASS.

## Execution repair contract, 2026-09-25
- Class C+B incident: independent Python/TypeScript/database trading asset restrictions and historical approval gates can reject valid strategy targets; full-plan entry checks can strand non-target exposure.
- The new normative contract is `source_of_truth/production_execution_contract.json`: dynamic exchange metadata, verified EXIT before ENTRY, account-isolated failures, durable recovery and separate wallet/model/outcome display.
- Implementation/deployment evidence is tracked in `docs/execution-reconciliation-20260925.md`; this contract update is not a claim of live alignment or completed deployment.
