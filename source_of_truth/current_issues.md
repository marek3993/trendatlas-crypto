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
- Full migration to the multi-account execution backend is approved and implemented on the rollout branch but is not active on the Pi until the final no-submit preflight and cutover. The target keeps the same `mrv1-production.timer`, canonical Python orchestrator, and single-run lock; it replaces only the execution stage, executes accounts sequentially, requires the owner account to be uniquely eligible, and stops after the first unsafe account result.
- After the approved cutover is activated, `mrv1-production.service` must not mount or pre-validate the legacy `TrendAtlasProd` signer. Per-user encrypted agent secrets are decrypted only inside the Pi worker, while Vercel exchange writes remain disabled.
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
- Production/execution dependency failures block only new_trade_transition; block_app remains false and system_available true.
- App-critical failures degrade only the dependent display capability.
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

## Watchdog deployment observed 2026-09-21
- Dependency-scoped watchdog 4c8fdbd5c54603c9c8f40bd9faaccfe7f2d10590 deployed as reviewed file overlays; Pi HEAD remains 1bb2d0d64363d111d92e4257d0a7345b484b8532.
- mrv1-watchdog.timer enabled/active at 01:25, 07:25, 13:25, 19:25 UTC + <=5min jitter. Production timer unchanged enabled/active.
- Research BTC derivatives panel/quality is stale (2026-04-19); only run_research_btc_derivatives is blocked. system_available=true, block_app=false, block_execution=false.
- Deterministic diagnostic cache repair succeeded. OpenAI key/file absent, warning only; no API request or order sent. AI waits for operator-provided OPENAI_API_KEY in /etc/default/trendatlas-watchdog.
- 55 targeted local tests and 19 Pi regressions passed. Broader account-schema test has an independently reproduced pre-existing performance={} expectation mismatch, outside this maintenance change.
- Deployment evidence and preservation exceptions (three expected latest watchdog reports) are recorded in docs/watchdog-deployment-audit-20260921.md.

## Evolution empty-queue operation resolved 2026-09-22
- The former empty-queue installation scope was superseded by explicit campaign authorization. All ten real historical studies completed on Pi (260 evaluated candidate instances; 1,430 period evaluations), all HISTORICAL_REJECT; budget exhausted with no unregistered follow-on work. Prior REJECT/SEALED studies remain unchanged. The Pi lacks a memory cgroup controller: research now additionally uses LimitAS=384M and mlockall(CURRENT|FUTURE), with observed zero worker swap. Historical results are exploratory and cannot establish a production PASS. See docs/evolution-campaign-deployment-20260922.md.

## Continuous research and AVAX status observed 2026-09-22
- AVAX / 1.00x is a model candidate, not an authorized entry. Production intent is CASH / 0 and the real wallet is CASH / 0.00x; `candidate_entry_not_authorized`, `trend_permission_active=false`, `no_market_entry_authorized`, and gate `no_action` explain the missing order. This is expected waiting, not stale production data or a watchdog trade block. The kiosk now reports the signal, wait reason, next check and absence of a blocking safety gate. No manual order or strategy change was made.
- Continuous Pi research release `826e42d9f31d92d290c5c152566cc917cda5be20` is deployed outside the production checkout. It automatically completed and SEALED five distinct retrospective cycles, all `HISTORICAL_REJECT`; the first cycle advanced automatically into a different family. The current state is `WAITING_FOR_NEW_DATA`: after exhausting the frozen same-input catalogue, the dispatcher checks every 15 minutes and will admit a new cycle only after 30 appended closed UTC daily BTC bars. Do not call this a production PASS or replay a rejected fingerprint on the same input.
- Production checkout/commit, 575 protected production files, 93 old immutable research files, production/watchdog timers and all account/authority/execution journals remained unchanged through installation and the kiosk patch. Research has no order API, network, production checkout, secret or authority access. Audit: docs/continuous-evolution-deployment-audit-20260922.md.

## Execution repair contract, 2026-09-25
- Class C+B incident: independent Python/TypeScript/database trading asset restrictions and historical approval gates can reject valid strategy targets; full-plan entry checks can strand non-target exposure.
- The new normative contract is `source_of_truth/production_execution_contract.json`: dynamic exchange metadata, verified EXIT before ENTRY, account-isolated failures, durable recovery and separate wallet/model/outcome display.
- Implementation/deployment evidence is tracked in `docs/execution-reconciliation-20260925.md`; this contract update is not a claim of live alignment or completed deployment.
