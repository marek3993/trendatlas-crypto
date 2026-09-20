# BTC short-horizon mean reversion: HISTORICAL_REJECT

Study: `btc_short_mean_reversion_v1_20260920`.
Research worktree: `C:/Users/benda/Desktop/trendatlas_recovery_20260920`.
Branch: `fix/pi-authority-outage-recovery-20260920`.
Base: `e4929701ed4f3239ace1c92a7eb91c1ab113f2fb`.

The preregistered five-generation study completed and sealed **HISTORICAL_REJECT**.
The selected leader failed the cash gate in six of eight folds and in the
continuous period. No further generations, strategy probes, parameter changes,
seed retries or monitor preparation followed rejection. No Pi access, installation,
production commit change, snapshot edit, refresh or order submission occurred.

All history, including 2025-01-01 through 2026-08-19, is
**development/retrospective**. The eight chronological folds are selection data,
not independent unseen tests. The overlapping continuous diagnostic is not a
ninth independent sample. There is no claim of production qualification.

## Preregistration and implementation provenance

1. `16d15998e62778d1fce02dbf8824ddcfa5e9a6eb` —
   `Preregister separate BTC short-horizon mean-reversion family`.
   CONTRACT.md, study.json, preregistration note and SSOT isolation entries were
   committed **before any Python implementation or candidate simulation**.
2. `b042b27b315228d9fcc66726812db9f4a23bdefc` —
   `Implement preregistered isolated BTC mean-reversion study`.
   Committed after the 43-test suite passed and before initializing the study.
3. Result/audit commit message:
   `Record historical rejection of preregistered BTC mean-reversion study`.
   Its exact hash is supplied in the completion response and is recoverable with
   `git log -1 --format=%H -- docs/mean-reversion-v1-results-20260920.md`.

The preregistered CONTRACT.md and study.json did not change after commit 1.
Frozen code hash (new package Python, contract/study, shared pure OHLCV/math utility;
CRLF normalized):
`55f7d2fbafb96f6bf26bd55979f8dc8735b1d0c74deff7ffebe4ebbb10424410`.
Canonical study SHA256:
`10b11bee0a8c088eb56e101b03b5ccf8a482a5dc288dd580fdf504649b636012`.
The stored code hash still matched the implementation during the final audit.

## Frozen model and selection

Use inclusive trailing close means and population standard deviation; entry when
close <= short mean minus entry_z standard deviations. Both gates must allow
entry: abs(short mean / regime mean - 1) <= range_band and
close >= regime mean * (1 - downtrend_floor). Require 200 completed warmup bars.
Use only close-D information for signals; fill on open D+1. Exit at mean recovery
or max_hold holding closes; entry day's close counts as one. After an exit at
open X, first eligible signal is close X+cooldown, filled on the following open.

No additions while held, shorting or borrowed cash. Costs are 15 bps on every
traded leg, including risk trims and boundary liquidations. At each open the
predeclared sizing guard can trim excess exposure, never add units. Last-period
liquidation occurs at its last open, with no last-open entry; BTC uses the same
boundary convention. Cash is nominal zero-return cash without interest.

Turnover sums traded notional / pre-trade equity across both sides, annualized
by 365.25 / calendar days. More than 24x in any fold or the continuous period
disqualifies the candidate, including as survivor or mutation parent.

Rank by worst fold fitness, then median, then mean, then full candidate SHA256.
Fitness = CAGR - 2 * abs(maximum drawdown), net of costs. Qualification requires
strictly positive net return AND fitness versus cash in every fold and the
continuous period. BTC is reported as a secondary benchmark. No alternative
finalist is tried after the ranked leader fails this gate.

Five generations each evaluated a population of 10, retained 6 and generated 4
globally unseen adjacent one-gene mutations. Every generation had 10 eligible
candidates; no turnover disqualification occurred. The final four children were
recorded but not evaluated. There were 26 evaluated candidates and 30 candidate
records, not 30 evaluated candidates or a sixth evaluated generation.

The same leader remained first in all five generations. Its worst/median/mean
fold fitness was -14.294139% / 0.000000% / -2.076535% in each generation.
Evolution therefore did not improve the leading candidate during this budget.

Leader SHA256 (audit identity only; rejected, not promoted):
`cfba4aa36a3a81a5c5d0ca03d751adfc82b926f9ed0825670deec4a959729f72`.

```json
{"mean_window":30,"entry_z":1.5,"regime_window":150,"range_band":0.05,
 "downtrend_floor":0.10,"max_hold":3,"cooldown":7,"exposure_cap":0.50}
```

## Historical results after costs

Percentages below are net total returns and annualized fitness respectively.
Turnover is annualized two-way equity-normalized turnover. Each fold restarts
with fresh cash and warmup from preceding observations only.

| Period | Strategy return | Cash return | BTC return | Strategy fitness | Turnover | Entries | Cash gate |
|---|---:|---:|---:|---:|---:|---:|---|
| 2019 | 0.000% | 0% | 95.186% | 0.000% | 0.000x | 0 | fail: tie |
| 2020 | 0.000% | 0% | 300.112% | 0.000% | 0.000x | 0 | fail: tie |
| 2021 | 0.693% | 0% | 62.427% | 0.365% | 1.005x | 1 | meets |
| 2022 | 0.000% | 0% | -64.174% | 0.000% | 0.000x | 0 | fail: tie |
| 2023 | -4.689% | 0% | 153.988% | -14.294% | 1.978x | 2 | fail |
| 2024 | 0.798% | 0% | 118.794% | -0.568% | 1.002x | 1 | fail: fitness |
| 2025 | -0.848% | 0% | -5.723% | -3.590% | 1.998x | 2 | fail |
| 2026-01-01..08-19 | 1.024% | 0% | -26.374% | 1.474% | 1.590x | 1 | meets |
| Continuous 2019-01-01..2026-08-19 | -3.101% | 0% | 1643.516% | -10.850% | 0.915x | 7 | fail |

Continuous leader CAGR: -0.411883%; maximum close-to-close drawdown: -5.219294%.
Twenty trade legs include seven entries, seven full exits and six risk trims.
Costs paid: 0.010263666975872433 units of initial equity (1.026367%). This cost
sum is descriptive; it is not the difference from a separately simulated
zero-cost strategy. No zero-cost strategy probe was run after rejection.

Exact reason codes: `dev_2019:cash_gate`, `dev_2020:cash_gate`,
`dev_2022:cash_gate`, `dev_2023:cash_gate`, `dev_2024:cash_gate`,
`dev_2025:cash_gate`, `continuous:cash_gate`.

Exact root cause of rejection: the selected sparse strategy did not establish
positive return and risk-adjusted improvement over cash in every preregistered
period. Three folds had no entry, two lost money, and 2024's positive return was
insufficient after the drawdown penalty. Only seven entries across the continuous
history provide very limited evidence. Turnover did not cause rejection and its
limit was not relaxed. This rejects this frozen study, not every possible
mean-reversion strategy. No new strategy family or parameter search was started.

## Tests and stored-artifact verification

Command: `python -m unittest tests.test_mean_reversion_research tests.test_evolution_research -q`.
Result: **43 tests passed**, 22 new plus 21 existing, 6.734 seconds on the recorded
successful run. An initial pytest invocation found pytest absent; the existing
standard-library unittest runner needs no installation. One initial unittest run
exposed a test-only SQLite handle left open during Windows temporary-directory
cleanup; the fixture was fixed to close it explicitly before the successful run.
There was no historical run before the suite passed and implementation commit.

Regression coverage: actual next-open entry/exit prices; no lookahead from future
close/high/low/volume; independent range gate and regime veto; zero-variance and
warmup rejection; max_hold timing; exact cooldown; no averaging/borrowing; opening
cap and costed risk trims; both-side fees; last-open liquidation and BTC/cash
benchmarks; turnover boundary and disqualification; independent chronological
fold accounting; adjacent unseen one-gene mutations; worst/median/mean/hash
ranking; qualification including continuous-period failure; fold overlap/gap
rejection; atomic interrupted resume; deterministic five-generation results;
sealed-run and duplicate-export protection; code/input hash guards; disqualified
parent exclusion; production/old-run sentinels; path traversal, junction/symlink
and hard-link protection; forbidden imports. Existing 21 evolution tests also
passed without edits to that package or its tests.

The actual run used CLI `init --input` with the path below, exactly five calls to
controller.step, stopping when SEALED, then CLI `export`. No resume or rerun of
the actual experiment was necessary. JSON registries parsed successfully and
`git diff --check` passed. Generated artifacts are ignored, not committed.

SQLite read-only audit: `PRAGMA integrity_check` = `ok`; 3,290 bars; 30 candidate
records; 60 population slots (includes unexecuted next population); 5 generation
records; 252 evaluations = 26 candidates * 9 periods + 2 benchmarks * 9 periods.
Each evaluation retains metrics, full equity curve and trades. Generation
populations, six survivors and four mutations are retained with lineage.

All 5,585 persisted candidate trade rows across the 234 candidate-period
evaluations were checked: signal_day < fill_day, fill == open, and
cost == notional * 0.0015; **zero violations**. Counts include overlapping
continuous-period trades and must not be presented as independent observations.
Maximum annualized turnover across all evaluated candidates/periods: 14.095243x.
Maximum post-trade opening exposure: 0.75 within floating-point tolerance.
Maximum marked-to-market close exposure: **0.767621**, honestly retained;
the preregistered cap applies at executable opens, and prices can move between
opens. The leader's maximum opening/close exposure was 0.50 / 0.507213.
No claim of an intraday 0.75 cap is made.

## Artifact identities and preservation

Input, read-only:
`C:/Users/benda/Desktop/market_regime_v1/data/ohlcv/BTCUSDT_1d.csv`.
3,290 daily rows from 2017-08-17 through 2026-08-19; no refresh or date rewrite.
SHA256 before/after:
`52a54850a11110a5f4cf00c0668645ab80e210f577a97427396b8721704b6b26`.

New artifact root, relative to the research worktree:
`outputs/research_os/dev_only/mean_reversion/btc_short_mean_reversion_v1_20260920/`.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| research.sqlite3 | 20578304 | 1724fbd2fe1b5cf9b28bfa263c8a1e35ec0731adac7b8b9f912ea3d9e6a373ce |
| report.json | 59616 | 4b201b919ca86fdb42de661b2073958e68195bbd4520818974b323883be90b5c |

Old SEALED artifact hashes matched the pre-study values byte for byte:

| Path under outputs/research_os/dev_only/evolution/ | SHA256 |
|---|---|
| btc_pilot_20260920/research.sqlite3 | e4b62b383bc2a6195574351902d48b54c25a93838ad281b7972f3e86f0bf94ce |
| btc_pilot_20260920/report.json | af16457216e9ef3f505aa00c2553ba643af3ea07b58aa7255c5e4b83436843cb |
| btc_cash_stability_v2_20260920/research.sqlite3 | 1e0446bad7cf09965c7674aa9c3471f4d9db72c3e46b1f9fc2441eaa743a35fe |
| btc_cash_stability_v2_20260920/report.json | 02a8a74198aa77670eb3273e2e4c13745b56d884cceaa653ad1d290e2b4881e9 |

The new sealed database hash was unchanged after read-only reporting/audit.

## Required repository audit

**FILES READ:** AGENTS.md; docs/evolution-v2-results-20260920.md;
source_of_truth/README.md, master_state.md, chat_roles.md; relevant sections of
project_truth.json, export_contract.json, paths_registry.json; current_issues.md;
canonical/script_registry.json, output_registry.json, registry_workflow.md;
Pi runtime runbook scope/canonical posture in
source_of_truth/pi_codex_runtime_workflow.md; research_os/docs/research_os_v2_contract.md;
research_os/runs/templates/run_folder_contract.json; previous evolution
CONTRACT.md, README.md, backtest.py, controller.py and tests/test_evolution_research.py;
new mean-reversion preregistration, contract, study, implementation and tests;
.gitignore. Reads followed the required SSOT orientation before implementation.

**SOURCE OF TRUTH:** user-authorized D/B research scope plus SSOT isolation/path
contracts; the new preregistration fixes study semantics. Canonical registries
only navigate to artifacts. SQLite, JSON and this results note are research
evidence, not production authority, account PnL or a strategy promotion.

**Exact contract impact:** separate dev-only family and output path, frozen
eight-fold retrospective qualification rules and fixed budget. Production,
execution, authority, APP exposure/PnL semantics, Research OS v2 lifecycle enums
and the prior sealed studies are unchanged. IML was not added. No frontend change.

**Forbidden old path checked:** no edits to prior evolution implementation or
SEALED artifacts; no write to outputs/production, outputs/execution/authority,
account snapshots, old export/publish paths, data inputs, Pi /opt/market_regime_v1
or /opt/home_automation. The original market_regime_v1 checkout remains dirty
with its existing work and runtime data; it was not cleaned, stashed, reset or
used as an output root. Its BTC input was read and hash-checked only. Pi was not
contacted, so no claim of a newly verified Pi runtime status is made.

**Exact changed files / git add lists:**

```text
# Preregistration commit 16d15998e62778d1fce02dbf8824ddcfa5e9a6eb
git add docs/mean-reversion-preregistration-20260920.md research_os/dev_only/mean_reversion/CONTRACT.md research_os/dev_only/mean_reversion/study.json source_of_truth/project_truth.json source_of_truth/paths_registry.json

# Implementation commit b042b27b315228d9fcc66726812db9f4a23bdefc
git add .gitignore canonical/script_registry.json canonical/output_registry.json research_os/dev_only/mean_reversion/README.md research_os/dev_only/mean_reversion/__init__.py research_os/dev_only/mean_reversion/__main__.py research_os/dev_only/mean_reversion/backtest.py research_os/dev_only/mean_reversion/controller.py tests/test_mean_reversion_research.py

# Results/audit commit
git add docs/mean-reversion-v1-results-20260920.md
```

No generated outputs or data are included in these commits. The historical
research stopped at rejection; no installation approval is requested.
