# BTC short-horizon long-only mean reversion — preregistered contract

Classes D/B. This is a separate, user-authorized research family. It neither
changes the old evolution engine nor resumes old sealed runs. Commit this
contract and study.json before writing implementation or running simulations.

Hypothesis: an excessive short-term BTC decline may revert toward its mean when
the longer regime is not strongly declining. No assertion of an existing edge.
All available history, including 2025-01-01..2026-08-19, is development/retrospective.
There is no historical production PASS or unseen historical holdout claim.

## Frozen signal and fill semantics

- At close D, use trailing windows ending at D, inclusive. Short mean is the
  arithmetic mean; standard deviation is population standard deviation (ddof=0).
  Require 200 prior observations at the first execution open for every candidate.
- Entry while flat: sd > 0 and close_D <= short_mean_D - entry_z * sd_D.
- Range filter: abs(short_mean_D / regime_mean_D - 1) <= range_band.
- Downtrend veto: close_D < regime_mean_D * (1 - downtrend_floor) forbids entry.
  Both filters must independently allow entry. Equality at the floor is allowed.
- Entry signal at close D fills only at open D+1. No same-day fill or use of
  D+1 close/high/low to decide the D signal. Open price is used for fill accounting
  and sizing only. There are no shorts or borrowed cash.
- Entry targets exposure_cap of equity after costs (0.50 or 0.75). Hold units;
  never add to an existing position. A predeclared risk-only sizing check at each
  following open may reduce excess weight back to the cap, never increase it.
  This is an execution-size guard, not an open-price entry/exit signal. Opening
  exposure must stay <= exposure_cap <= 0.75. Mark-to-market exposure can drift
  between executable opens and must be reported honestly, not silently clipped.
- At each close while held, queue a full exit when close_D >= current short_mean_D
  or max_hold holding closes have elapsed. Entry day's close counts as one.
  Exit is at next open; trims do not reset holding age. No regime-forced exits.
- After an exit at open X, block close decisions on X through X+cooldown-1.
  First possible new signal is close X+cooldown, filling at open X+cooldown+1.
  Never sell and rebuy at the same open.
- Fold start is fresh cash and zero cooldown, with features warmed only by earlier
  data. First-open entry may use the preceding close. Boundary liquidation is
  predeclared at the last open of the fold, queued on the previous close; no entry
  at the last open. No end-of-fold close fill. Use the same convention for BTC.
- Costs are 15 bps per side on traded notional, including risk trims and boundary
  exits. No daily top-up, loss averaging or hidden free liquidation.

## Budget, turnover, ranking and historical verdict

- Domains, data hash, folds, seed and budget are exactly those in study.json.
  Use five generations of ten distinct candidates, retain six eligible candidates,
  create four globally unseen adjacent one-step, one-gene mutations. No IML.
- Annualized turnover = sum(abs(traded_notional) / equity_before_that_trade)
  * 365.25 / calendar_days_in_period. Both buy and sell legs count; a full 1x
  round trip is approximately 2x turnover. Include all costs and risk reductions.
- Turnover >24x in any fold OR the continuous development period permanently
  disqualifies that candidate. It cannot be a survivor, parent or champion.
  Exactly 24x remains eligible. Do not fix excess turnover by omitting trades.
- Rank eligible candidates by the minimum fold fitness, then median, then mean,
  descending, and full candidate SHA256 ascending as deterministic final tie-break.
  Fitness is CAGR - 2*abs(maximum drawdown), measured net of all simulated costs.
- Every fold also reports cash (nominal 0%, no interest) and BTC buy-and-hold.
  The continuous development period is an overlapping diagnostic/risk gate, not
  another independent fold. It must not enter fold median or mean ranking.
- Finish exactly five generations unless fewer than six eligible survivors make
  the required 10/6/4 transition impossible. That fail-closed condition immediately
  yields HISTORICAL_REJECT; never resurrect a disqualified parent or add budget.
- After generation five, use the already-ranked leader, without trying alternative
  finalists against the outcome gate. HISTORICAL_QUALIFIED_AWAITING_FORWARD requires
  strictly positive net return AND fitness versus cash in every fold AND the
  continuous period, and no turnover disqualification. Otherwise HISTORICAL_REJECT.
- No sixth generation, domain expansion, retry with a new seed, or extra strategy
  probe follows rejection. Reporting, artifact verification and commit are allowed.
- On qualification only: freeze full candidate SHA256 and exact parameters; prepare
  a separate read-only paper monitor for review. It must contain no execution or
  exchange imports, order calls or production/authority writes. Any Pi plan runs
  after successful production at low CPU/IO priority in a separate output root.
  Stop with concrete code/config/test review before any Pi installation.

## Isolation and persistence

Use a separate package and output root from existing evolution. Read historical
OHLCV without rewriting it. Preserve every earlier SEALED database/report byte for
byte. SQLite transactions retain frozen input, study/code hashes, all candidate
genes/lineage, generation populations and full per-period metrics, curves and trades.
Interrupted generations roll back; resume is deterministic and code-hash guarded.
Allowed result labels are exactly the two HISTORICAL_* labels above; lifecycle
states are internal and do not claim production qualification. This isolated output
root is not research_os/runs and does not change Research OS v2 lifecycle enums.
Reject path traversal, output symlink/junction escapes and existing-run overwrite.
No production imports, exchange clients, subprocesses, credential access or scheduler
attachment. Reuse of pure historical parsing/math utilities is allowed and hashed.

Required tests: lookahead, next-open entry and exit, regime veto, range gate,
max_hold, cooldown, no averaging, cap sizing, both-side costs, annualized turnover
disqualification, adjacent mutations, chronological fold isolation, worst/median/mean
ranking, deterministic interrupted resume, old sealed preservation and production
path protection. No data-dependent tuning after this preregistration commit.
