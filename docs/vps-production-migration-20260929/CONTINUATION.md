# Production migration continuation — 2026-09-29

**READY_FOR_OPERATOR_CUTOVER.** Exact canonical replay and the actual read-only operator preflight passed. Root-owned readiness receipts are sealed. **No live cutover, financial order, Pi fence, VPS timer activation, cleanup or reboot was executed. PI_SAFE_TO_POWER_OFF=false.**

## SOURCE OF TRUTH

Branch: codex/vps-production-execution-20260929. Identical corrected source replayed on ARM and x86: **a6413782e4814d820fb6a0ed9e135878dc275ade**. Initial numerical implementation: 07dea5ca62c3a1436535634f8dd5f888db983294.

Live Pi remains /opt/market_regime_v1 at 5ee031cef7de9c385056cec22f6511391d3e4f4f, unchanged. ARM verification ran in /var/lib/trendatlas-migration/replay; VPS staging is /opt/trendatlas-production/current. Identical commit archives and SHA256 verification established source identity.

Normative contracts under source_of_truth: diagnostic_numeric_contract.json, export_contract.json, production_host_contract.json, production_execution_contract.json and pi_codex_runtime_workflow.md.

Current target: closed UTC day **2026-09-28, AVAX 1.00x**, permission true. Real account: **7.65 AVAX**, no open orders, no new fills. Planner: **NO_ACTION**, empty actions.

## Exact root cause — class B, diagnostic export contract

Raw source SHA256, row ordering, dates/index/dtypes/null masks and daily return bits match. Both hosts use Python 3.13.5, numpy 2.4.4 and pandas 3.0.3, with architecture-specific cp313 manylinux wheels. Both pandas ELF compiler comments identify GCC 14.2.1 20250110. NumPy links scipy-openblas 0.3.31.188.0, neoversev2/Haswell builds. CPUs are Cortex-A76 and virtualized Intel Haswell. Complete wheel tags, build/BLAS configuration, CPU flags and binary hashes are in numeric-portability-evidence.json.

First differing intermediate: **population variance at row 331 (zero-based), 2019-04-01**. For the 30-day window ARM gives 0x1.36d0b85607c70p-16, x86 0x1.36d0b85607c6fp-16. Means and annualization constant are bit-identical. Divergence occurs before square root, annualization and serialization.

The precise cause is **FMA contraction of the Welford second-moment multiply/add in the ARM pandas wheel**, versus separately rounded multiplication and addition on x86. A fixed-order scalar experiment with FMA reproduces every ARM 30/90-day variance bit. Disabling only FMA reproduces every x86 variance bit. ARM disassembly contains fused operations; x86 hardware supports FMA but its wheel produces the unfused recurrence result. This identifies compiler-generated contraction in pandas rolling. [Upstream recurrence](https://github.com/pandas-dev/pandas/blob/v3.0.3/pandas/_libs/window/aggregations.pyx).

Unrestricted process thread counts were 4/5 (ARM/x86). OpenBLAS/OMP/MKL/NumExpr one-thread limits produced 1/2 process threads and no changed metric bits. The scalar controlled recurrence explains the entire variance output without BLAS. Thread scheduling, BLAS, input ordering and serialization are not the cause.

## Exact lineage and contract impact

| Stage / consumer | Role |
|---|---|
| ETF-flow adapter build_candidate_timeseries | Diagnostic assignments after decisions/returns; recomputed after historical stitching. |
| staged_candidate_promotion_support.transform_candidate_timeseries_to_active | Final native diagnostics from authorized return_net, after decisions. |
| Active adapter build_timeseries | Returns the transformed frame; universe guard reads target asset. |
| Production Core builder | Builds/validates snapshot using unchanged native frame; canonicalizes only an export copy. |
| Production Core validator | Requires column names; values do not select, authorize or size trades. Canonical export also validates. |
| app.py CSV reader | Numeric coercion/presentation history. |
| TypeScript planner / web frontend | No reads of either field. Planner reads target/account/exchange metadata. |

Neither field feeds **selected asset, target exposure, trend permission, risk scaling or execution planning**. Other staged/fallback adapters emit diagnostics, but no decision reader of these names was found. No frontend or strategy adapter was edited.

The source export contract was patched and validated first. Native computation and its existing precision remain unchanged. A deep export copy changes exactly two columns. All **67 other columns, every historical row and current snapshot remain exactly unchanged** against original per-platform replay. The comparator now fails closed on any non-diagnostic history/snapshot change.

## Deterministic representation and oracle

Precision remains the **existing 12 fractional places**, not a coarser precision chosen from observed differences. Volatility is an annualized return fraction; its exported quantum is 10^-12 (10^-10 percentage points). Sharpe is dimensionless. Published returns already occupy the 12-place decimal lattice; off-lattice/infinite values fail closed. Missing values preserve active zero-fill behavior. Unique increasing ISO dates are required; no silent sort/deduplication.

Let scaled integer returns be x_i, S=10^12, n the window, A=sum(x_i), Q=sum(x_i²), D=nQ−A². Unbounded integers compute D exactly. Population variance is D/(nS)² and annualization is exactly 1461/4.

- Scaled volatility: round_half_even(sqrt(1461 D / (4 n²))).
- Scaled Sharpe: sign(A) round_half_even(sqrt(1461 A² S² / (4 D))).
- Integer isqrt and exact squared-midpoint comparisons implement rounding. No platform float reduction/sqrt or production Decimal context.
- Full windows: 30/90; earlier rows null. Zero variance: volatility 0, Sharpe null. Negative exact variance fails, never clamps.
- CSV uses fixed decimal text; JSON stays numeric. Audit also compares scaled integer arrays and complete CSV SHA256.

Independent oracle: fresh **centered two-pass Decimal mean/variance/sqrt at 80 digits**, checked at 120 digits over full history. It shares no production integer-moment algorithm and never feeds signals. Exact binary inputs and public decimal inputs were both examined.

| Original metric error vs decimal oracle | ARM / old Pi absolute | x86 absolute | Maximum relative, nonzero reference |
|---|---:|---:|---:|
| rolling_vol_30d | 2.1004e-8 | 2.2986e-8 | ~7.84341e-10 |
| rolling_sharpe_90d | 1.97274e-11 | 5.47274e-11 | ~4.35320e-11 |

Relative error at zero is undefined. Native residual variance caused 942 ARM / 976 x86 nonzero exports in truly zero-volatility windows. In 416 constant-return windows, old Sharpe was finite because of the residual; canonical Sharpe is now correctly null. These are diagnostic corrections only.

Canonical maximum absolute errors: **4.995904e-13 volatility**, **4.998774e-13 Sharpe**, bounded by exact decimal half-quantum 0.5e-12. This proves rounding, **not an acceptance tolerance**. No allclose, threshold relaxation or price/quantity/order/journal approximation was introduced.

## Decision threshold evidence

Diagnostic influence on every decision threshold is exactly zero, including exact boundaries. Tests place values below/on/above exposed boundaries and prove every non-diagnostic column unchanged.

| Historical surface | Minimum absolute distance | Maximum ARM/x86 difference |
|---|---:|---:|
| trend score − buy threshold | 0.000233 | 0 |
| trend score − activation threshold | 0.000032 | 0 |
| BTC close − EMA10 | 0.387911435689 USD | 4e-11 USD |
| three-day ETF flow − 500 million USD | 900,000 USD | 0 |
| exposure − cash tolerance 1e-9 | 1e-9 | 0 |
| exposure − leverage boundary 1.000000001 | 1e-9 | 0 |

Intentional exposure=0/1 boundaries remain exact. Cooldown/date/count boundaries and permission/filter booleans are untouched and equal in enriched decision surfaces. Baseline selector/trend decisions are frozen upstream inputs, not rerun research searches.

Native EMA is another existing differing intermediate, unchanged here. Independent 80-digit EMA oracle (alpha=2/11, adjust=false): maximum absolute errors 7.044e-11 ARM and 6.377e-11 x86 USD; closest oracle price boundary 0.387911435691 USD away. Every price-filter boolean matches. We do not claim every native intermediate is bit-identical.

## Replay / regression tests / validation commands and results

- Identical corrected commit a6413782e4814d820fb6a0ed9e135878dc275ade, identical frozen raw inputs.
- **3,069 days, 2018-05-05 through 2026-09-28: complete canonical history exact.** Snapshot exact, all 67 other columns unchanged against original history, exact NO_ACTION planner.
- Both core replay SHA256: bdee4e0cc94f3385e9c78d505fe1e52d891611005a7d90d5281642216cf2557c.
- Canonical CSV SHA256: 1c32e957ef281722b7f35712105f4330d2bef6a7150f9615e9c4ded1288619f3.
- Both planner SHA256: 740a3cbf6e709f740863d66eed95b8fb5e061f097b2df1e3dde26a2adb328416.
- **258 existing + 19 new = 277 passed:** Python 161, TypeScript 116. New 19 also passed on each actual ARM/x86 Python 3.13 runtime. TypeScript tsc, JSON parsing, git diff checks passed.
- New tests: ARM/x86 FMA fixtures for both metrics; independent 80/120-digit oracle; windows; NaN/zero/constant returns; cancellation/departing outlier; scaling/sign metamorphisms; midpoint rounding; invalid lattice/infinity; row ordering; stable serialization/unchanged native frame; boundaries; AVAX 1x; full frozen history; rejection of changed decisions/snapshot.
- Existing suites retain NO_ACTION/dust, EXIT-before-ENTRY, unknown submission/CLOID recovery, no-submit transport, journal/account isolation and operator faults. Actual readback below supplies real no-submit/account evidence; synthetic tests are not trades.

~~~text
python -m unittest tests.test_production_execution tests.test_single_production_orchestrator tests.test_hyperliquid_systemd_credentials tests.test_production_asset_universe_contract tests.test_execution_authority_publish tests.test_production_host_migration tests.test_operator_cutover tests.test_migration_retirement_priority tests.test_diagnostic_portability -q
node node_modules/vitest/vitest.mjs run tests/canonical-execution-contract.test.ts tests/multi-account-executor.test.ts tests/production-boundary.test.ts tests/production-asset-support.test.ts tests/no-submit-transport.test.ts
node node_modules/typescript/bin/tsc --noEmit
python scripts/execution/numeric_portability_audit.py --root <isolated-root> --output <private-audit.json>
python scripts/execution/production_golden_replay.py --output <core.json>
node --conditions=react-server --import tsx scripts/production-golden-replay.ts <frozen-readback.json> <planner.json>
python scripts/execution/compare_production_replay.py <pi-core> <vps-core> <pi-planner> <vps-planner> --previous-pi-core <original-pi-core> --previous-vps-core <original-vps-core> --output <report.json>
~~~

## Runtime, account, timers, LeadPilot and research

Canonical no-submit **prod_20260929T193125Z_903971** completed PREFLIGHT_READY: real_order_sent=false, live_order_chain=NOT_INVOKED, execution_outcome=PREFLIGHT_ONLY, dashboard PASSED, authority SKIPPED_NO_SUBMIT. Canonical runtime fingerprints unchanged. Separate publish-existing dry-run exited 0, zero pushes.

Fresh reads around **19:34 UTC** prove unchanged 7.65 AVAX, no open orders and no new fills. Market price moved; final read equity was 86.838001 USD. Valuation movement is not a trade or a claim of unchanged equity.

Supabase journal checkpoint remains 44c811ba01523f0461d1c21b855a96a7a3d438b244adea5975e68e75d45a9d11; nonce 1790640666333. No DB write/restore or stale handoff. Journal uses UUID/CLOID/per-agent nonce, not a global sequence. Supabase skill applied to read-only verification; no schema/permission changes.

- Pi timer **enabled/active**, sole live executor. Live source, Production Core and latest run hashes equal initial audit.
- VPS production/watchdog timers **disabled/inactive**. No-submit override remains; activated_by_operator=false, single_execution_host=null.
- Root-owned receipts updated only after successful evidence. Actual read-only operator preflight passed readiness, identity, target and journal gates.
- LeadPilot API/frontend/DB healthy, proxy running without healthcheck. All retain original 2026-09-27T20:42:03Z starts.
- Research sealed/terminal, 7,203 evaluations, 7,211 attempts, zero running; checkpoint f628fb34a0f69961d594686622bc6290331f7be1bc5b4281ca50201ff058181b unchanged. No search resumed; preemption marker cleared.
- Phase 2 timer enabled/active, latest checked collector run successful at 19:30:25 UTC. No LeadPilot/research configuration change.

Earlier protected-permission, publisher-access, systemd and synthetic preemption/cleanup proofs remain intact. No real cleanup/reboot test is claimed.

## Operator commands / stop point

This command **now passes the readiness gate**, verified without its live flag. The live form was not run:

~~~powershell
python C:\Users\benda\Desktop\ta_vps_prod\scripts\execution\cutover_pi_to_vps.py --pi-host 172.16.20.107 --execute-live
~~~

It rechecks state, quiesces/fences Pi, captures the final shared journal checkpoint and activates the sole VPS executor. Current expectation: NO_ACTION. Fresh-state checks still apply if date, target, account, source or IP changes.

Cleanup is prepared for **after successful operator cutover and verified VPS readback**:

~~~powershell
python C:\Users\benda\Desktop\ta_vps_prod\scripts\execution\retire_pi_after_cutover.py --pi-host 172.16.20.107 --execute-cleanup
~~~

The SUCCESS gate intentionally cannot pass before cutover. Cleanup encrypts/verifies rollback archives, retires owned autostart/trading configuration, reboots/verifies Pi, then rechecks VPS before PI_SAFE_TO_POWER_OFF=true. These actions remain unexecuted.

## FILES READ

AGENTS.md; ordered source_of_truth README.md, master_state.md, chat_roles.md, project_truth.json, export_contract.json, paths_registry.json, current_issues.md; canonical/script_registry.json, output_registry.json, registry_workflow.md; then source_of_truth/pi_codex_runtime_workflow.md and production_host_contract.json.

Also original report/manifests; active ETF-flow and BTC-persistence/fallback lineage; staged_candidate_promotion_support; Core builder/validator; current_emittable_universe; ETF-flow probe/cooldown; app.py; repo-wide metric searches; Python/TypeScript replay/comparator; production_host; rehearsal/cutover/host-control/retirement; package/ELF/build evidence; frozen archives; regression suites; installed units; protected Info/Supabase readbacks; Supabase SKILL.md.

## Forbidden old path checked

No tolerance widening/allclose, strategy adapter change, manual authority edit, full-refresh, generated outputs/data commit, live order/submit adapter invocation, DB mutation, architecture spoof, legacy signer revival, second active executor, Pi fence/retirement/reboot/power-off, frontend internal labels or LeadPilot/research restart.

## Exact files changed / exact git add / commit message / commit hash

GIT_ADD_NUMERIC.txt records explicit add commands and complete changed-file list versus 95452304dc0aac4b5ce5d1e48a9b390e5b3fe76b.

- 07dea5ca62c3a1436535634f8dd5f888db983294 — Canonicalize diagnostic exports with exact decimal arithmetic.
- a6413782e4814d820fb6a0ed9e135878dc275ade — Require unchanged decision history before operator cutover.

Both pushed to the same branch. The final evidence-only commit records this report and replay/no-submit/runtime/readiness manifests; its hash is supplied in the final task response, not self-embedded. It changes no replayed production source and activates no trading.

Evidence: numeric-portability-evidence.json; cross-architecture.json; no-submit-evidence.json; numeric-final-runtime-evidence.json; operator-readiness.json; deployment-SHA256.json.
