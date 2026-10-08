# TrendAtlas Anomaly Discovery Lab

Standalone research on the existing VPS Python/systemd stack. The worker has no
network, account credential, production or collector access. The separate
DeepSeek broker receives bounded prior-training aggregates and uses Phase2's
existing transport, durable reservations, cache, retry and usage accounting.

The existing deployed Phase2 v2 engine is copied byte-for-byte into the isolated
release. Declarative anomaly targets enter through its existing PRODUCTION
interface. Production strategies and the completed Phase2 cycle are untouched.
No generated code executes, and the research schema grants no trading allowlist.

Eleven condition families, three thresholds and two horizons give 66 normalized
rules. All numeric choices, budgets, clustering, costs, neighbors, null model
and folds are frozen before computation. A named idea with identical rule values
is the same hypothesis. SQLite reservations, completed trials, selections,
continuous books and a hash-chained audit are append-only. Counters and API budget
identity survive process restarts and later origins.

Before each of 14 development tests, candidate screening and selection use two
chronological halves of the preceding 365 days, purged by 14 days. All adjacent
threshold and horizon neighbors are measured. AI receives only these prior
aggregates. Each family carries its actual simulated cash, quantities and whole
episodes between tests, including losing and CASH periods. Failed execution data
invalidates the book; subsequent folds cannot manufacture a fresh cash account.

Daily condition triggers and globally clustered events are different counts.
Transitive horizon overlap joins simultaneous assets and sustained conditions;
missing eligible calendar days break clusters and are excluded from exposure.
Reports store yearly frequencies, gaps, durations, representative assets,
regimes, eligible denominators and block uncertainty. Forward favorable movement,
matched prior non-event controls, and costed portfolio economics are separate.

Lifetime alpha spending is alpha/[t(t+1)], including train and neighbor trials.
Block sign randomization preserves intra-block time and cross-asset dependence;
its conditional independent symmetric block-sign assumption is explicit. The
union bound requires conditionally valid p-values. Calibration under that null
is recorded separately. No general FWER guarantee is asserted for repeatedly
inspected financial history. Sparse evidence is INSUFFICIENT_EVIDENCE; rare events
are retained. A read-only reporting consumer suppresses misleading sparse/zero
bootstrap confidence bounds without rewriting the frozen source books.

All inputs are the existing immutable historical spot bundle, ending 2026-09-25.
Prospective 2026-09-27 through 2027-09-26 is LOCKED, and 2027 remains SEALED.
The Lab cannot access the collector archive. Historical universe completeness,
exact publication times and venue certification are unavailable. Unresolved
identity segments are quarantined. Some spot quote volume is an explicitly
declared volume-times-close proxy. Funding/OI/liquidations/order-book inputs are
UNAVAILABLE, never zero. A full extra daily bar precedes the existing next-open
fill as a conservative publication buffer; delayed-entry stress adds another.

Every selected nominal book also undergoes independent quantity × open-gap plus
close-move minus rebuilt fee/slippage/borrow accounting. Stresses rerun 2x costs
and delayed entries. Whole closed-trade and asset log contributions reconcile,
best-day and top-three whole-trade removals retain the full calendar, and primary
CAGR compounds continuous equity rather than averaging fold annualization.

The outbox contains exact, tested declarative hypotheses, parents and prior
validation evidence, plus bounded mechanism-inspired Phase2 gene suggestions.
The gene suggestions are explicitly not equivalent to every anomaly condition.
`handoff.ingest` validates a future training cutoff and normalized gene identity;
it cannot reopen or modify the completed frozen v2 cycle. A future Phase2
experiment can consume the exact declarative rule through the same target adapter.

VPS paths:

- `/var/lib/trendatlas-anomaly-lab/lab.sqlite` — immutable research evidence.
- `/var/lib/trendatlas-anomaly-lab/discovery_report.json` — current reporting read model.
- `/var/lib/trendatlas-anomaly-lab/handoff/` — future-origin hypothesis outbox.
- `/var/log/trendatlas-anomaly-lab/` — separate worker/broker logs.
- `trendatlas-anomaly-lab.timer` and `trendatlas-anomaly-broker.timer` — unattended continuation.

The worker is bounded to one process, 60% CPU, 3 GiB memory and 180 seconds of
planned work per tick. The observed peak was 1.3 GiB. Fourteen lifetime API calls,
112,000 tokens and a conservative tariff reservation cap are frozen. After 14
origins the finite experiment is EXHAUSTED; timers skip costly work and new API
calls. Completion never reclassifies seen history as an independent holdout and
never confirms a trading candidate.

Local validation:

`python -B -m unittest tests.test_anomaly_lab tests.test_anomaly_lab_reporting tests.test_phase2_v2 tests.test_phase2_v2_continuation -q`

Read-only VPS audit:

`python -B -m research.anomaly_lab.audit --root /var/lib/trendatlas-anomaly-lab`

Primary statistical reference: Sture Holm, *A Simple Sequentially Rejective
Multiple Test Procedure* (1979), especially the union-bound argument. The
implemented lifetime spending extension is stated above; it is not mislabeled
as Holm step-down or an independent prospective validation.

https://www.ime.usp.br/~abe/lista/pdf4R8xPVzCnX.pdf
