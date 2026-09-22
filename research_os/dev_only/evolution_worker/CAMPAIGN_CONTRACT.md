# Bounded walk-forward campaign v3 — preregistered 2026-09-22

Classes B/C/D. Explicit user authorization replaces the prior empty-queue-only
installation boundary, not any old SEALED result. No production writes/promotion,
orders, live imports, API calls, generated code or data refresh. Existing frozen
mean-reversion/evolution implementations and sealed artifacts remain unchanged.

## Scientific protocol

campaign_v3.json fixes ten chronological rolling experiments, seeds, domains,
input SHA256, costs (10 bps fees + 5 bps slippage each way), budgets and criteria.
Each selects over four consecutive six-month folds, with a continuous diagnostic
and turnover gate, then evaluates ONE frozen leader on the following six months.
Five generations, ten candidates, six eligible survivors, four unseen adjacent
one-gene mutations. Rank worst/median/mean net CAGR-2*abs(drawdown), SHA tie-break.
Fewer than six eligible survivors immediately seals HISTORICAL_REJECT. Otherwise
complete five generations. No extra generation or alternative finalist after reject.
Use unchanged pure mean-reversion math: close-D decisions, next-open fills,
long only <=0.75 target cap, no additions, next-open boundary exit, costs on all legs.
Cash and BTC use the same accounting. Assessment is never read by selection.
All history is seen exploratory retrospective, not blind validation. Windows
and selected candidates overlap; ten trials are multiple comparisons, not ten
independent confirmations. Report every experiment, including losses and cash ties.
Qualification requires strictly positive return AND fitness vs cash in all selection
folds, continuous diagnostic and later assessment, with turnover <=24x throughout.
Only HISTORICAL_REJECT or HISTORICAL_QUALIFIED_AWAITING_FORWARD. A qualified result
freezes candidate/hash and writes a proposal, never installs anything. Forward paper
observation is >=180 calendar days beginning after freeze and separate review;
2026-09-23 is only the earliest possible start, never permission to backfill.

## Admission, persistence, budgets and isolation

Preregister this contract/JSON in Git BEFORE implementation/search. Build a new
small allowlisted release. An operator bootstrap activates exactly the committed
campaign, pins its complete release SHA256 and preregistration commit, snapshots
the hash-checked input read-only under research state, and enqueues its first job
through the official enqueue command. No moving release or mutable job specification.
Root-owned campaign authorization and input are read-only in the worker namespace.
Subsequent campaign_queue records may only equal the next exact job from that
pinned authorization. They never use arbitrary queue-provided code/parameters.
The operator queue remains read-only. One worker lock and durable unique SQLite
job/study identities prevent duplicates. Any BLOCKED job blocks campaign advancement.
After each SEALED experiment, enqueue the next preregistered job irrespective of
its result. This is the explicitly approved finite campaign, not extension of the
rejected experiment. Stop after ten; no auto-generated replacement or retry seed.

Keep original three-unit asymmetric production arbitration, RefuseManualStart,
Conflicts/After production and independent gate. Never stop/start production.
One worker, Nice19, idle IO, CPUQuota20%, MemoryMax384M, MemorySwapMax0; no network,
credentials, execution imports or production access. Only research state is writable.
Temperature >75 C pauses before the next period (or immediately on signal); resume
only <68 C. Missing/unreadable sensor pauses fail-safe. Persist hysteresis across
reboot. Dispatcher retries unchanged work every 15 minutes, never busy-spins.
Check disk and temperature between actual period simulations; checkpoint evaluations
transactionally before generation selection. Kill during simulation rolls back only
that evaluation; deterministic resume reuses committed results and population.
Per-experiment elapsed deadline 7200 seconds from first admission INCLUDING pauses,
64 MiB/job; campaign 7 days from activation, 512 MiB state, >=1 GiB+64 MiB free.
Expired budget is BLOCKED for review, not a fabricated strategy rejection. Preemption
must not reset deadlines, identifiers, seed or progress. No deletion to make space.
Atomic status.json holds campaign/job, lifecycle, generation, committed evaluated
candidate count, leader, last completed experiment, pause reason, temperature,
CPU time and next step. Read-only bootstrap status reconciles persisted evidence
with real PID/service admission and SQLite progress; it does not mutate artifacts.
Research states are separate from Research OS v2 runs/ lifecycle and account truth.

## Required regression evidence

Empty queue advances only an authorized finite campaign; exhausted or blocked
campaign does not create work; immutable/SEALED/duplicate rejection; production
admission/preemption; SQLite resume; thermal hysteresis/resume; missing API harmless;
no execution/network/promotion path; next-open and no assessment lookahead; exact
10/6/4 adjacent transitions and cash/BTC reports. Local and Pi tests plus isolated
dummy arbitration precede actual enqueue. Verify production controls/checkout and
protected runtime hashes before/after, and prove a real committed evaluation on Pi.
