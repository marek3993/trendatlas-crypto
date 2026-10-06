# Phase 2 v2

Research only. The v1 contract, evaluator, immutable results, and sealed original
manifest are preserved. V2 uses a distinct SQLite ledger and unique cycle;
completed genes/results and the event hash chain cannot be overwritten.

The user explicitly reclassified **2018-05-05 through 2026-09-25** as previously
seen development, including 2024–2025. There is **no independent historical
outer OOS**. **2026-09-27 through 2027-09-26** remains prospectively LOCKED;
2027 remains SEALED. Sep26 2026 is excluded. Timestamp guards stop before parsing
future price/target columns. Frozen inputs contain no prospective prices.

Fourteen adjacent half-year development test folds span Jan1 2020–Sep25 2026.
Before each test, the runner evaluates two inner chronological halves of the
preceding 365 days. Candidate creation, DeepSeek context, parent selection and
the frozen selection use only that origin's past training results. Survivors
remain members of successive generations and origins without duplicate same-
origin evaluations. Subsequent hypotheses are never replayed into earlier test
selections. Repeatedly seen historical development and a modern language model
cannot establish independent historical predictive validity.

The primary equity curve carries cash, quantities and whole position episodes
through fold boundaries. CAGR is compounded ending NAV relative to initial NAV
over the actual elapsed UTC calendar days. Close-equity MDD includes the initial
NAV and is computed for the entire curve and separately for each fold. Short
fold CAGR is diagnostic only. The daily execution book uses prior-close targets,
next-open fills, 10 bps fee plus 10 bps slippage, maximum 1.25x gross, and an
explicit 10% annual borrowing debit on negative cash. These are historical spot
proxies, not execution certification or wallet performance.

Every reference uses the same book, timing and costs. Production is an offline
replay of canonical authorized targets, never an imported return series.
Historical `BASE` refers to a composite sleeve, not a ticker: it is expanded only
using the same-date `phase67j_no_neo_main_paper.csv::executed_position` when its
regime is BASE and no challenger is selected. An underlying CASH position gives
zero risky exposure. Original labels/exposures and resolution lineage are kept.
Production files are read-only and are never regenerated or edited.

Asset and whole episode contributions reconcile to NAV/log growth, retain IDs,
and preserve undefined concentration as null. Top-three removal subtracts the
three best positive **closed** whole episodes, retaining calendar duration.
Open episodes are marked OPEN; fewer than three positive closed episodes makes
this diagnostic INCONCLUSIVE. Missing held-asset prices reject a trial entirely,
including its full-horizon CAGR. The legacy best is invalid at the original LUNA
halt on May13 2022; there is no fabricated sale, price, or truncated headline.

The isolated broker sends at most two parents, weak folds and a bounded novel
menu; no full ledgers or equity arrays. It batches four proposals, uses content
hash caching, native provider token usage and durable per-attempt reservations.
Ambiguous calls are not retried; only explicit 429 is retried once. The input
wire JSON is capped at 6,500 UTF-8 bytes and output at 1,500 tokens. Cost is a
documented conservative tariff estimate, separate from the provider invoice.
AI/deterministic lineage, invalid trials and paired parent deltas are audited;
performance advantage is not claimed from tiny or unequal samples.

The runner is offline and cannot access production, account credentials or the
broker credential. The broker sees only its mailbox. Systemd ExecCondition skips
empty broker mailboxes and finished walk-forward jobs without loading market
arrays or sending requests. No automatic new cycle is created merely to spend
tokens. Stagnant valid fronts stop the search within an origin; an empty valid
front chooses CASH for its frozen test instead of promoting an invalid trial.

`audit.py` opens SQLite read-only, verifies the hash chain and assembles the
continuous stitched curve from immutable fold books. `dispatch_condition.py`
uses only stdlib and never mutates the ledger. `deploy.py` installs research
units and requires references/tests before activation. Its only migration path
is the explicitly checked native-integer checkpoint fix: unchanged prices,
unchanged strategy math, exact equality of every existing completed result,
backup, append-only event, and the same cycle ID.

Validation: `python -m unittest tests.test_phase2_v2 -v`.

Recovery contract (2026-10-06): `phase2_v2_recovery_contract.json` and
`continuation.py` preserve the exact evaluator/input binding and cycle. A
terminal missing-price failure in a frozen selected test becomes an immutable
receipt. The entire continuous selected portfolio is then UNDEFINED_INVALID;
the four valid prefix books are diagnostics only, not a full-horizon CAGR.
Later origins continue unchanged past-only training and selection, while their
tests are NOT_EVALUABLE_CONTINUITY_LOST. No cash reset, liquidation or replay is
invented. `status` separates valid completed folds from processed origins.
Legacy `audit.py` only assembles valid prefix books; after a terminal receipt,
use continuation status and the recovery audit evidence before interpreting
any prefix metric. Timers continue automatically until all 14 origins are
processed, then stop without a duplicate cycle or extra API budget.

Validation: `python -m unittest tests.test_phase2_v2_continuation tests.test_phase2_v2 -q`.
