# TrendAtlas: source reconstruction, not archived performance

This directory is non-authoritative research. No strategy, runtime, account,
frontend, scheduler or producer file is changed. Model results are simulated
research account returns and are never real-account PnL.

## Source lineage and exact rules

`source_of_truth/project_truth.json` names ETF/cooldown as current, BTC
persistence as first fallback and 1.25x as second fallback. It is authoritative
for those names, not evidence that its embedded historical metrics are valid.

| Family | Source | Reconstructed rule |
|---|---|---|
| Phase61 core | `phase61_final_compare.py:MODEL_FILES`, `phase60_selective_restore_robustness.py:build_daily_tables`, `select_daily_top1_variant` | Phase61 is a comparison label; use its pinned restore-TRX/SOL core. 12 original symbols. Daily top-one score = base_rank + .35 xs20 + .20 xs90 + .10 persistence + .20 positive acceleration + .15 positive five-day thrust. base_rank = .55 LT + .30 ST + .15 confidence. Entry ST/LT >=35, confidence >=35, no chaos, MR >=-90. Hold LT >-35, confidence >=30 and positive directional bias. Candidate Yang-Zhang volatility <=.70, market mean general score >=0. BNB override: LT>=55, ST>=40, xs20>=30, otherwise preserve BNB only when runner-up is TRX/SOL. Source ATR percentile is a fraction while threshold is 70; this effectively nonbinding rule is preserved, not tuned. |
| Phase62 BTC overlay | `scripts/phase62_btc_overlay.py:build_variant_grid`, `compute_regime_columns` | Source-named default, not a best historical return: SMA30>SMA200, close>SMA30, 30-day BTC return >=8%; risk-off below SMA200 or 20-day daily volatility >6%; otherwise BTC when trend passes, core when it does not, CASH on risk-off. This is one explicit representative, not every member of the historical grid. |
| Phase63 BTC participation | `scripts/phase63_btc_participation_overlay.py:parse_variant_key`, `compute_regime_columns` | Pinned f20/s100/r30/m12/rm150/rb-03/v30/.045/wb30/wt+.02/cd3: BTC preference only when core 30-day completed return <=2%, BTC momentum >=12%, close>SMA20>SMA100, close >=.97 SMA150 and daily vol30<=.045. Risk-off goes CASH. Source cd3 is a persistence/hold latch, not the ETF 15-day reentry cooldown. |
| Phase66g soft filters | `scripts/phase66g_production_candidate_live.py:build_winner_config`, `scripts/phase66e_probation_governance.py:compute_asset_signal`, `simulate_governance_strategy_probation` | Challenger trigger requires executed BASE and weak core, same 20/100/150, 30-day +12%, .045 volatility, three-day latch. Weekly governor trains trailing 365 days, recent60, >=4 trigger days, total edge>=.5 percentage points, recent edge>=.25pp, DD deterioration<=3pp. Score 4 recent +1.5 train -1.25 DD deterioration +.15 triggers. Switch margin3, min hold3 reviews, probation45 days with negative edge banned for6 reviews. Core LTC/SOL exclusions are tested separately. |
| Phase67j no-NEO | `scripts/phase67j_final_narrow_validation_pack.py:build_profiles`, `compute_candidate_signal`, `simulate_weekly_challenger_governance` | Same 20/100/150/30/.12/.045 trend; 30-day challenger edge>=3pp over core and nonnegative recent relative edge. Governor: 365-day train/recent42, >=3 triggers, nonnegative train/recent edge, DD deterioration<=6pp, switch margin2, hold2 reviews, probation45/-0.5pp/4 reviews, promotion2pp, persistence2 weeks, reentry7 days, downside42 with deterioration<=2.5pp, extra BNB shield1pp. Remove NEO. |
| Phase68g static | `scripts/phase68g_portfolio_exposure_leverage_validation.py:build_portfolio_exposure_frame`, `add_daily_position_flags`, `add_baseline_stress_state`, `build_validation_wrapper`; `scripts/production/strategy_adapters/phase68g_66g_1p25x_candidate_adapter.py` | Candidate policy takes nonblank phase66 weekly chosen asset, otherwise phase67 reference. Explicit BASE resolves through source lineage. Trend score = clipped (core 30-day return -.02)/.12. Permission >=.10 and not stress-block day. Stress hysteresis: 20-day DD activates at -8%, clears at -4%. First and second policy-position rows force1x; subsequent eligible rows use1.25 or1.5. Adapter trend permission is applied even on initial rows. Stress-block day preserves the source switch/buffer exception. |
| BTC persistence fallback | `scripts/dev_only_production_core_btc_candidate_persistence_early_risk_compare.py:compute_btc_candidate_persistence_rows`, `build_override_states`; persistence adapter | Preserve non-CASH base. Otherwise BTC candidate for >=10 consecutive rows, -.20<trend<.10, no permission, no stress/hard invalidation => BTC .75x. Maintain until candidate ceases to be BTC, trend<=-.20 or stress/hard invalidation; baseline reentry takes priority. No hard-invalidation source exists in this route, so its source default false is preserved explicitly. |
| ETF entry/current | `scripts/dev_only_phase68g_etf_flow_impulse_probe.py:build_full_history_frame`, `scripts/dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity.py:build_cooldown_state_machine`; ETF adapter | On fallback CASH: ready explicit ETF availability row, sum of last3 sessions >=USD500m, at least2 positive sessions, BTC close>EMA10, no stress => BTC .50x. Hold uses the carried last available 2-of-3 flag; new entries require an explicit available row. Exit on flag failure, price filter failure or stress. Baseline non-CASH handoff clears early state/cooldown. Failed early exit starts15 calendar days next day. F uses the same state machine with zero cooldown; G uses15. |
| Phase68h dynamic | `scripts/phase68h_dynamic_leverage_ladder_candidate.py:build_effective_leverage` | Same wrapper; first two rows1x, eligible trend .10 to .50 ->1.25x, >=.50 ->1.50x. Its original payoff column is discarded. |
| Phase68j guards | `scripts/phase68j_tail_risk_guardrail_check.py:apply_g1_adverse_cooldown`, `apply_g2_dd5_brake` | All six source combinations: 1.25x/static1.5x/dynamic parent × G1 daily parent return<=-5% => next2 actions cap1x; G2 parent five-day rolling DD<=-7.5% => next3 cap1x. Trigger inputs are freshly reconstructed completed parent net returns. Original next-action labels are converted back to their known-at-close decision time, then the common execution lag is applied once. |
| Phase2 volatility-adjusted | captured `source_reference/phase2_signals.py.txt:Controller` | Positive 90-day momentum divided by max(.10, annualized vol60); highest eligible asset, monthly rotation, immediate own absolute-momentum exit. |
| Phase2 regime allocation | same | BTC>SMA200 or CASH. If breadth above own SMA200 >=60% and best alt 90-day momentum beats BTC by10pp, hold that alt; otherwise BTC. Monthly allocation, immediate BTC regime risk exit. |
| Phase2 slow/hysteresis | same | Positive90-day momentum, monthly reviews, minimum30 days and challenger absolute momentum advantage>=10pp to switch, while an invalid held asset can exit immediately. |
| Phase2 ensemble | same | Rank ensemble of 30/90/180-day momentum; require >=3 votes from those three positive momenta and close>SMA200; add .10 for 55-day breakout state, exited below prior20-day low; monthly rotation. |

Phase2 uses its source .40 annual volatility target divided by max(.10, vol20),
cap1.25. BTC trend weakness or vol20/vol60>1.8 caps at.5; >1.3 caps at.75; >1.2
caps at1. The four fixed representatives do not reselect prior Phase2 search
winners. The source snapshot is from commit
`ce5bcd2b1b06f87161154a71f7764cf6577b6d33`; its SHA256 is
`77a93543744081ecc8d426404d5e48d895c83983e89db4e2992d47a80e4f25ec`.

All daily targets are priced by the SAME research ledger, including daily
drift resizing. This deliberately replaces historical inconsistent return,
cost, sizing/headroom and fill implementations. It is a harmonized replay of
source decisions, not claimed byte parity to the old paper-account path.

## Identity and universe conflicts

The source runtime shortlist file contains NEO, DOGE, STX, APT, HBAR, LINK;
dropping NEO leaves five names. SSOT names APT, BCH, DOGE, ICP, STX, XTZ. The
runtime-input route is the main source reconstruction; the six-name SSOT route
is an explicit sensitivity. Neither is silently substituted for the other.

The historical wrapper copies `phase66g` returns while it can label positions
using `phase67j` or an inactive phase66 weekly candidate. A strategy with such
a label/return combination is not executable. This study executes the explicit
named policy coin, resolves BASE through the core target and NEVER matches
returns to infer a ticker. A separate economic-route sensitivity executes the
underlying phase66 target. The discrepancy is structural, not an alternative
measurement of real wallet exposure.

The same 19-asset OHLC panel and 260-observation admission mask govern every
model. Original family masks are explicit treatments; forcing every model to
select identical names would make the pruning ablation meaningless. C uses
unpruned soft and reference governance. C1 isolates soft governance, the
NEO-only sensitivity separates the two pruning operations. H replaces only
the base selector with DAILY volatility-adjusted momentum over the SAME 12
original core symbols (not the monthly 19-symbol Phase2 representative), then
rebuilds every dependent shadow and gate. I uses
the ORIGINAL score, monthly selection, minimum30 days and10 score-point
hysteresis, with immediate source candidate and market-wide CASH exits.

The source cross-section filled missing/unlisted coin returns with zero before
ranking, letting future/unavailable coins affect existing coins' ranks. The
repair masks those columns BEFORE ranking; regression tests add a future-only
coin and require exact past-score equality.

## What causal does and does not establish

Features at completed D produce targets, assumed available after D+1 open;
the earliest captured permissible daily fill is D+2 open. All nested shadow
portfolios obey the same rule, fees, slippage and funding. There is no use of
stored paper returns, summary metrics, future forward returns or full-file
history admission. The source functions' unused forward-return diagnostics
are removed before selection. Common calendar year fold exits are charged.

The fixed parameters were researched historically. Thus the six folds are
chronological computational OOS, not a fresh scientific holdout. Weekly
governance may use already completed observations inside a test year because
that online learning rule was fixed beforehand; it never sees future fold
returns and there is no outer-fold parameter fitting.

The archival cohort lacks complete delisted exchange membership, macro
publication vintages and ETF first-publication/revision vintages. Therefore
certified historical point-in-time universe/input availability remains
UNVERIFIED, even if prefix/future-perturbation tests pass. Daily spot OHLC,
adverse10bp fills,4.5bp fees and12% annual funding debit are explicit common
proxies, not actual historical Hyperliquid fills or funding. No valid exchange
backtest or deployable winner is claimed from missing evidence.

Macro coverage is particularly sparse: the captured source begins 2024-01-07;
after the source lags and rolling warmup, BTC has only 51/37/0 nonmissing daily
observations for liquidity lag8/lag10/lag12 through the common end. The source
neutral treatment of missing features is preserved. `macro_coverage.json`
records exact first/last valid dates. This reconstruction cannot certify that
the historical production system saw this same macro feature history.

No new parameters are optimized. The latest user request authorizes historical
static1.25/1.5 archeology even though the earlier objectives disallow permanent
leverage for a new production candidate. Historical rows do not promote those
exposures or amend the production objectives.
