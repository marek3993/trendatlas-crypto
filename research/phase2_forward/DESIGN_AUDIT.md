# Phase 2 pre-execution contract/design audit

Verdict for historical search and forward tournament: **BLOCKED_WITHOUT_STATE_CHANGE**.
This document precedes any Phase 2 strategy result. No strategy search, nomination,
historical replay or DeepSeek call is authorized by passing a calendar check alone.
Public-data collection and the separately requested SEALED status fix are permitted
preparatory operations. They do not change the sealed experiment or production.

## Binding sources and admission

User request dated 2026-09-29; predecessor commit
`7d8eead2377887f9f03791598ef5c3af7881d561`; the two unchanged contracts under
`research/causal_evolution/`; especially `continuation.first_refit=2027-01-01`,
`new_days_min=30`, `new_days_anchor=2026-09-26`, `same-data-successor` prohibition,
and `continuation.py` requiring a newly completed annual outer window.
The frozen engine's `configure_cycle` only permits mechanical yearly rolls within
the OLD schema. J–N must use an entirely separate engine; never monkeypatch it.

Today neither the date nor a closed 2026 annual window exists. Calling a new
historical search “architecture discovery” does not waive this rule. A valid
future launch also requires verified append-only/PIT coverage, a separate tested
engine, event-overlap purge tests and a pre-result manifest binding actual code,
input bytes, rules, costs, budget and timestamps. The strategy design is frozen in
`research_contract.json`; the separately deployed `contract.json` continues to bind
the immutable collector. It is **not** a claim that the missing engine was implemented.
`implementation_ready=false` is deliberate. No automatic launch on 2027-01-01.

## Economic hypotheses and exact finite search space

Exact enums, fixed rules and transitions are in `research_contract.json`, with no shared
inactive genes. Different families may share the causal ledger, never an old PnL
stream. All are long/CASH initially. Long/short is **NOT_RUN** until historical
mark/funding/margin/liquidation evidence supports it.

|Family|Economic hypothesis|Free parameters (allowed values)|
|---|---|---|
|J|Trend persists, but volatility-dependent exposure reduces damage when risk rises|SMA 120/180/240; vol 20/60; target 10/15/20%; exit confirmation 1/3 days|
|K|Independent asset trends can diversify risk if correlated positions cannot dominate|SMA 120/180; vol 30/60; target 10/15%; correlation cap .6/.8; weight cap .2/.25; rebalance 7/14 days|
|L|Market trend, breadth and realized volatility distinguish favorable momentum regimes|market SMA 150/200; momentum 60/120; breadth on .6/.7; target10/15%; adverse exposure0/.25|
|M|Fixed complementary horizons reduce reliance on a single timing rule|slow180/240; breakout55/120; momentum60/120; target10/15%; sleeve weights fixed1/3 each|
|N|Breakout losses can be bounded while winners remain open, subject to actual fills|breakout55/120; ATR20/40; initial stop2/3ATR; trailing4/6ATR; entry risk.25/.5%|

J has no 90-day cap. K uses 90-day lagged correlations, at most five positions,
inverse volatility, ranking hysteresis and cash for unused weights. L excludes
funding/basis/OI inputs until their PIT lineage exists. M never picks a sleeve by
future return. N's initial/trailing protection is intrinsic, with no-stop,
no-initial and no-trailing ablations; adverse OHLC ordering, gap fills and residual
positions are mandatory. New assets never inherit high-water marks or cooldowns.

All portfolios derive exposure from simulated cash/quantity account MTM, never
production fields. Target gross <=.95; actual gross >1 invalidates nomination and
triggers causal reduction at an available fill. It is impossible to guarantee a
continuous hard cap across price gaps: the ledger must disclose every breach,
retain its PnL and fail the gate rather than clip exposure or erase losses.

## Frozen budget, windows and statistical rules

5 families × 2 matched arms × 3 seeds × 2 chronological origins ×
(8 initial + 4 + 4 mutations) = **960 candidate slots maximum**. Three generations
including the initial population. At most10,000 reserved evaluation attempts,
4 neighbors per preselected nominee, 60 API calls, 1m tokens and USD1 ceiling.
Duplicate normalized hypotheses do not increase the hypothesis count or budget.
Rejected/uncertain API calls consume their reservation; replacements consume the
same slot. Actual attempts, unique hypotheses, cache hits and duplicate slots are
reported separately. No weighted fitness: validity, risk gates, Pareto.

Raw development lineage starts2019-01-01. A full365-day PIT admission warmup
precedes scored training starting2020-01-01. The two nonoverlapping exploratory
outer windows are **2023 and2026**. Origin2023 has two120-day inner windows ending
2022-04-10. Origin2026 has two120-day inner windows ending2023-12-31, deliberately
capped before the forbidden old OOS period. Each train ends266 days before its
inner-validation start. Every exact date is in `research_contract.json`.
**2024–2025 are forensic only**, excluded from new-strategy evaluation, proposals,
ranking and nomination. Closed2026 is required for refit admission and a frozen
exploratory rejection gate, never a freshly independent holdout. This means the
scientific design cannot be executed today. These are separate annual books;
there is no invented continuous equity across the omitted2024–2025 gap, and
bootstrap blocks must stay within actual observed folds.

The265 omitted days comprise244 feature/publication/exit days plus21 embargo days.
Because J/N can hold indefinitely, this fixed gap alone is insufficient. Whole
episodes intersecting label boundaries must additionally be purged, unresolved
training episodes censored and scored fold books initialized flat after unscored
warmup. These requirements need executable tests before launch. Lack of effective
observations must be INCONCLUSIVE, never a relaxed gate. Historical statistical
power cannot be promised in advance. The first design draft's2022 origin was
removed before any strategy evaluation because its first train preceded365-day
PIT admission. The collector's already frozen contract is preserved; the corrected
strategy-only contract is a new file, with unchanged budget and risk thresholds.

Within each origin, preselect at most2/family from inner results before opening
exploratory outer. The latter can only reject these; it cannot nominate alternates
or feed mutation. Separately initialized annual books and any aggregate disjoint-
fold statistics must be labeled. All history remains development evidence.

MDD preferred20%, acceptable25%, absolute35%; Sharpe>=1.5; Calmar>=4.
150–200%CAGR is a stretch, not an obligation to declare success. Require positive
no-best-day/no-top-three-whole-episode growth; max asset profit share60%, episode35%;
three seeds, >=75% passing four neighbors; 999 stationary bootstrap draws with
mean30-day blocks, DSR>=.95, CSCV/PBO<=.1 with8 blocks, Holm<=.05 across the complete
frozen comparison family. Minimum365 scored days/20 closed episodes; insufficient
effective blocks or distinct configurations is INCONCLUSIVE. Trials include all
attempted slots, neighbors and ablations; earlier uncountable research is disclosed.
Also require2×fees/slippage/funding debits, one later executable fill, adverse
mark/funding/margin/liquidation, four capitals and actual MTM exposure checks.

## Venue and execution evidence

Production venue is Hyperliquid. Official docs checked2026-09-29:

- [Public info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Perp metadata/context/funding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [Historical archive](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
- [Tick/lot constraints](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size)
- [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)

The candle API retains only the latest5000 bars. S3 offers asset contexts and L2
snapshots with incomplete/asynchronous coverage and requester-paid transfer.
No paid S3 job or AWS credential is introduced. Public current metadata is not
historical fee/lot or listing proof. Spot venue history and independent historical
index prices remain missing; oracle and mark are separate observed fields.

The collector captures all native-perp metadata/context (mark, oracle, funding,
OI, liquidity/volume, size precision, margin and delisting flags when supplied),
and1h bars/L2/funding for10 fixed assets. This fixed collection basket is NOT a
PIT strategy universe. Initial4999-hour bars/funding are explicitly historical
retrieval. Fundings paginate in400-hour pages; gaps remain unknown. Subsequent
bar fetches overlap prior two hours and preserve all response versions. Public
fee/tick/history documentation is timestamped daily. Listings are first-observed,
not asserted true listing dates. All missing values remain absent/null.

15-minute books cannot establish every intrabar fill or historical stop path.
The collector is evidence acquisition, **not a certified venue backtest or paper
trading engine**. Certified strategy fills, fee tier, historical margins and full
universe availability remain gating gaps; Binance is an explicit separate proxy.

## Prospective and operations

At most10 new nominees, max2/family; every nominee binds candidate/rules/code/data/
parameter hashes, timestamp and first eligible UTC day strictly after freeze.
No backfill, no PASS while observation is INCOMPLETE. Include the two BTC SMA200
track-specific benchmarks and the user-designated rejected F/D diagnostic
references without reselecting old OOS candidates. No nominees exist today and
no forward tracker is installed under a misleading “started” label.

Public collector has independent state/database/manifest and its own systemd
service/timer. Strictly public request allowlist; no account address, secrets,
order SDK, redirect or environment proxy. DynamicUser,256MiB RAM,20%CPU, low I/O
priority, no swap,2GiB state ceiling and2GiB disk reserve. SQLite FULL transactions,
append-only triggers and SHA256 row chain; successful per-request checkpoints
survive a later failed request. No access to old research, production or LeadPilot.

SEALED fix is outside the immutable engine: after existing manifest/DB binding
verification, `ready` returns1, systemd's successful ExecCondition skip. Failed,
corrupt or unknown states remain errors. No worker or Store is opened for SEALED.
Existing dispatcher cadence and all production timers remain unchanged.

## Resource estimate before results

VPS observed:4vCPU,7746MiB RAM,~6618MiB available,~64GiB free, no swap.
Old cycle used33432 active seconds for7203 evaluations (~4.64s/evaluation).
Using that only as a rough bound,10k new evaluations could take13–48h elapsed
depending on the more complex ledger, resource throttling and preemption.
This is NOT a measured Phase2 benchmark;24 active CPU-hour hard budget may stop
before completion. Proposed search RAM ceiling2GiB, disk2GiB state + bounded
archive; the immutable input archive must be separately capacity-audited.

Search worker benchmarks1/2 are **NOT_RUN**, because launching the research engine
is blocked and it does not yet exist. Never reuse the old exclusive WorkerLock as
a two-worker lease. Two workers require disjoint durable leases, expiry fencing,
crash tests and identical hashes against one worker, plus resource health. Until
then one worker only. Public collection is lightweight single-process I/O and
must not be advertised as this benchmark.

Collector estimate: initial~34 public requests; <=61/activation; a few MiB initial
compressed history and estimated5–50MiB/day; measure after installation. API
costUSD0 for public endpoints; research DeepSeek capUSD1 and actualUSD0 because
NOT_RUN. Current pricing must be re-frozen before any future paid API call.

The permitted work now is forensics, this design/admission scaffold, collector
deployment and the regression-tested status correction. Architecture engine,
large search, two-worker benchmark and forward nominations remain blocked.
