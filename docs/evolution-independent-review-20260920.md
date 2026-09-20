# Independent evolution review — 2026-09-20

## Verdict

The sealed `btc_pilot_20260920` remains valid as a reproducible pilot, but its
champion is **REJECTED for further promotion evidence**.

It returned +2.21% with -24.05% maximum drawdown and 1.35% CAGR on the recorded
final period. Under the declared fitness `CAGR - 2 * abs(max_drawdown)`, its
final score is approximately -46.75%, while cash is 0%. Beating a falling BTC
buy-and-hold benchmark does not establish useful risk-adjusted value.

## Findings

1. Final evaluation omitted the cash benchmark even though candidates can stay
   in cash. This made the BTC comparison look stronger than the economic result.
2. Mutation changed one gene but could jump across multiple domain values. That
   did not match the requested gentle evolution.
3. Selection used one continuous validation interval. Repeated generations can
   overfit that interval even with a sealed final test.
4. The final interval was isolated from programmatic selection, but it was not
   globally unseen market history. It cannot support a production claim.
5. IML has no demonstrated incremental benefit here. It remains excluded. Only
   an equal-budget preregistered ablation may justify adding it later.

## Contract and implementation changes

- Mutation moves one adjacent domain step in exactly one gene.
- Validation is split chronologically into two folds.
- Ranking prioritizes the weaker fold, then the mean fold score, then candidate ID.
- Final testing includes cash and BTC buy-and-hold.
- A research PASS requires beating cash in both net return and declared fitness.
- Existing sealed runs remain immutable. The improved protocol requires a new run ID.
- Production execution, authority, accounts and scheduling are untouched.

## Validation

`python -m unittest discover -s tests -p test_evolution_research.py -v`

16 tests passed. Added coverage for adjacent mutation, robust fold ranking and
the final cash decision gate.

## Next experiment

Run a new versioned study with the same fixed budget and disclose that the
2025-01-01..2026-08-19 result has already been viewed. Treat it as exploratory.
Use rolling chronological development checks and begin accumulating a new
prospective untouched period. Do not promote any candidate from this branch.

