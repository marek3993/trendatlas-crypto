# Multi-asset rotation v1 — preregistered retrospective research

Classes B/C/D. User authorizes exactly one historical study on the isolated Pi
worker, five generations, then SEALED and stop. No trading or production promotion.
The immutable numerical preregistration is study.json. Commit this contract and
study before implementation or any candidate evaluation. Data inventory inspects
only availability, dates, hashes and OHLCV validity, never strategy performance.

## Data and evidence

Take all twelve regular *_1d.csv files in the Pi's data/ohlcv directory passing
complete consecutive daily coverage 2021-01-01..2026-08-20, valid finite positive
OHLC, positive volume, no duplicate dates or links. No performance exclusion.
The exact universe, raw file hashes, windows, domains and initial ten candidates
are frozen in study.json; the committed quality inventory records every asset.
All history is development/retrospective. 2025-01-01..2026-08-19 was already seen
in prior research. The final is isolated from this selection process, not globally
unseen evidence. A research PASS cannot be interpreted as a production PASS.
Survivorship bias of the locally available fixed universe remains a limitation.

Loader reads only the preregistered date slice, rejects missing/stale/invalid bars
or unequal asset calendars, and never fills, backfills or silently drops assets.
Worker verifies full raw SHA256, then uses immutable job copies. Operator copies
source files read-only into the one atomic queue directory's inputs/ subdirectory.
Root-owned queue input files are also covered by the existing service's read-only
queue mount. No new production path mount or production permission change is needed.
All new Pi research data/results/fixtures live under /var/lib/trendatlas-research.

## Strategy and execution math

At each scheduled rebalance, using closes through D only, require BTC close above
its regime SMA. Eligible assets have close above their own regime SMA and
close/close[-momentum_days]-1 strictly above min_momentum for confirmation_days
consecutive closes. Rank eligible assets by latest momentum descending, symbol
ascending for ties; select at most top_k, equal weights, CASH if none.
Portfolio volatility is population standard deviation of the last 30 daily
equal-weight close returns of that selected basket times sqrt(365.25), using only
data through D. Total target weight is min(exposure_cap, vol_target/volatility),
with a 1e-12 volatility floor. No shorts or borrowing; residual stays in CASH.

Rebalances are anchored at each split's first open, then every rebalance_days.
A daily BTC regime failure exits the basket next open; re-entry waits for a
scheduled rebalance and confirmation. Between rebalances retain units, except
for that veto and a standing exposure cap. At every execution open reduce, never
increase, an overweight basket pro rata to the preregistered cap. Open prices
are used only for execution/sizing, never signals. Cap is enforced after each open
fill; subsequent intraday price drift is reported, not retroactively traded.

Fresh equity 1.0 and no positions at each fold start. Decisions from D close fill
at D+1 open. Terminal liquidation is at end+1 open, never the signal-day close.
The one-day gaps between selection folds prevent overlapping liquidation periods.
Costs: fee 10 bps + slippage 5 bps on every one-way executed notional, including
entries, rotations, cap trims and final exit. Solve post-cost target equity before
allocating weights; no negative cash/implicit leverage. Report fees and slippage
separately in units of initial equity, order-fill count, turnover, equity and fills.
CASH is constant equity 1, return/fitness/costs zero. BTC buy-and-hold buys first
open and liquidates end+1 open with the same costs; no daily benchmark rebalancing.
CAGR uses exact elapsed calendar days. Drawdown uses daily closes and final open
including costs. Fitness = CAGR - 2*abs(max_drawdown).

## Evolution and one-time final

Exactly five populations of ten: initial ten fixed genes; each generation ranks
by weaker validation fitness, then mean validation fitness, then full candidate
SHA256 ascending. Train is diagnostic only. Six survive, four distinct unseen
children mutate exactly one gene one neighboring domain step. No domain extension,
new seed, adaptive fitness, budget change or duplicate candidate re-evaluation.
Deterministic RNG is seeded by seed+completed_generation for each child batch;
enumerate all valid unseen neighbor edges in sorted parent-ID/gene/domain order,
sample without replacement and enforce distinct child IDs.

Both validation folds and final must each have net return > 0, fitness > 0 and
abs(drawdown) <= 25% for PASS. CASH is the mandatory economic gate. BTC comparison
is descriptive. Five generations run even if interim scores are poor; no sixth.
After generation five, freeze its top-ranked candidate/genes/hash in a committed
SQLite transaction. Only then claim the final evaluation in a separate committed
transaction, evaluate that candidate and the two benchmarks once, and atomically
store final results + SEALED. If power is lost after the final claim but before
final commit, block with FINAL_INTERRUPTED; never automatically re-evaluate final.
This fail-closed exception to ordinary resume avoids pretending exactly-once
computation is possible across an uncommitted crash. It is a technical failure,
not a manufactured statistical verdict. Generation transactions can safely roll
back/recompute unchanged after reboot; committed generations cannot be repeated.

## Persistence and isolation

Extend the existing finite queue with one explicitly registered engine; preserve
the legacy engine and its seals. Research admission must match the bundled study
exactly, with matching preregistration commit, input manifest hash and release hash.
No arbitrary imports/scripts/commands from study JSON. Fixture admission is a
separate explicit mode and cannot be queued in production worker mode.
Reuse the worker lock, duplicate-ID/spec ledger, path/link guards, disk checks,
atomic immutable publication and read-only sealed results. Store all candidate
metrics, fills/curves, generations, lineage and final evidence in SQLite with FULL
synchronous transactions. Hash accepted spec, input copies, DB, report and audit
into SEALED.json; repeated reads never mutate sealed artifacts.

Install a new immutable small allowlisted release. Existing three systemd units
may change only their pinned release path. Keep all hardening, empty environment,
network prohibition, production priority and resource limits. Enable only the
existing dispatch timer; admit one atomic directory, wait for its automatic tick,
never start the worker directly. Verify >=1 GiB+64 MiB reserve before activation
and every generation; production must be inactive/success and timer enabled/active.
No production checkout, secrets, authority, strategy, executor or order API access.
Local and Pi synthetic tests must pass before admitting the historical job.
No IML, network/API clients or AI calls in the research process.

This module has its own dev-only lifecycle under the isolated state directory;
it does not redefine Research OS v2's research_os/runs lifecycle enum.
