# Continuous isolated evolution v1 — 2026-09-22

Class B/C/D research contract. This authorization supersedes the bounded-campaign
**stop rule for a new release only**. `campaign_v3.json`, its ten SEALED jobs,
their code/input hashes, and the installed pinned release remain immutable.
The research user has no production, account, authority, order, secret or network
access. Research results are retrospective only and cannot promote a strategy.

## Frozen policy and cycle boundaries

`continuous_policy.json` is bundled in a SHA256-verified, commit-pinned release.
Only its named hypothesis templates may be searched. It fixes family, domains,
seed, four chronological selection folds plus a subsequent assessment, 15 bps
one-way costs, maximum 24x annualized turnover, long-only exposure <=0.75x,
five generations, ten candidates, six survivors and four distinct adjacent
single-gene mutations. Signal inputs end at close D and a change fills no earlier
than open D+1. An eligible candidate is ranked by worst, median and mean
selection-fold net fitness, then candidate hash. The assessment never informs
selection. Cash is the mandatory qualification benchmark; BTC is reported.
History remains seen, development/retrospective, including every later input
observed by this worker. Qualification is never a production PASS.

A cycle is immutable once created: policy/release SHA, input SHA and last closed
date, family/template, domains, seed, folds, cost, population and criteria are
in `accepted.json`. A SHA256 fingerprint covers them without the cosmetic cycle
ID. SQLite checkpoints each candidate/fold and each generation transactionally.
Each cycle has a 7200-second accumulated active-service-time budget, 64 MiB
local disk budget and at most the five generations. Active time is checkpointed
in SQLite; time while the process is preempted by production, thermally paused
or waiting for the next dispatch does not consume it. Immediately before each
backtest, the ledger reserves 300 seconds of active time; a per-bar monotonic
guard bounds that one backtest to 300 seconds. Successful period commits replace
the reservation with measured active time. An interruption during the evaluation
keeps the conservative reservation, so repeated kills cannot reset the budget.
The final charged time is included in the SHA-sealed report and audit. Resource
expiry is ERROR/blocked for review, not a strategy rejection. `SEALED.json`
hashes all final files and is never edited.

## Automatic succession and scientific limits

After a SEALED cycle, the controller persists its outcome and structured reject
reasons, then chooses the next **unused** template for the same frozen input.
Turnover rejection prefers a lower-churn trend variant; failure to beat cash
prefers a regime/ensemble hypothesis; no-entry/cash-tie failures prefer a
mean-reversion entry hypothesis. Other cases use the fixed template order.
This changes the family or search space, not merely the job ID or seed.
The policy includes trend/momentum, mean-reversion as an entry or protective
component, and regime/ensemble combinations. It never generates Python or
accepts arbitrary queue code/parameters. All hypothesis attempts, fingerprints,
rejection categories and next-change explanations stay in the research ledger.

Once every distinct template for one input is used, status becomes
`WAITING_FOR_NEW_DATA`. The dispatcher remains active but admits no worker until
the read-only bound OHLCV input has at least 30 additional **closed UTC daily**
bars and a different SHA256. A new hash alone is insufficient; rewrites or
truncation cannot recycle the same search. The new input is validated and frozen
atomically before another cycle. This is an honest idle state, not a failure or
an infinite repeat of the same historical tests. Later inputs remain seen
retrospective data and each new input gets its own finite template budget.

Each activation may continue a checkpointed cycle and create the next distinct
cycle under the same worker lock. Production priority, thermal hysteresis
75/68 C, >=1 GiB + 64 MiB disk reserve, 512 MiB research-state ceiling,
Nice 19, idle IO, CPUQuota 20%, address-space/memory guards and zero swap
remain mandatory. Production starts preempt the research cgroup; resume uses
the same accepted spec and committed SQLite results. No other automatic unit
may start or stop production. An unexpected integrity, provenance, input or
resource error stops automatic succession for review.

## State and reporting

New state is isolated under `/var/lib/trendatlas-research/continuous/`:
`authorization.json` (root-owned), `ledger.sqlite3`, `status.json`, immutable
`inputs/<sha>.csv`, and `cycles/<id>/` with accepted input/spec, SQLite results,
report, audit and SEALED manifest. Old campaign state remains untouched.
`status.json` and the read-only status command expose current cycle/family,
generation, evaluated candidates, last reject reason, next change, CPU seconds,
RAM KiB, temperature, and one of RUNNING, WAITING_FOR_NEW_DATA, PREEMPTED,
PAUSED_RESOURCE or ERROR. SEALED describes a cycle, never the lifetime worker.
The process exits between bounded systemd timer activations; “24/7” means the
dispatcher continues automatic admission/recovery, not busy spinning.

No account PnL/exposure, order, production path, source_of_truth, IML or API
import is allowed in this release. Any historical qualification only creates
an inert read-only paper-monitor proposal requiring separate review.
