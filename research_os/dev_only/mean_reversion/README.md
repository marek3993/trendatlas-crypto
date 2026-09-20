# Isolated BTC short-horizon mean reversion

Python 3.12+, standard library only. No IML, network, execution/exchange modules,
production orders, production files or scheduler integration. All historical
data are development/retrospective; no independent historical holdout exists.

The preregistration is commit `16d15998e62778d1fce02dbf8824ddcfa5e9a6eb`.
Read CONTRACT.md and study.json before use. Do not change this version's domains,
folds, seed, input hash or budget. The CLI accepts no output-root override.

From the research worktree:

```powershell
python -m unittest tests.test_mean_reversion_research tests.test_evolution_research -v
python -m research_os.dev_only.mean_reversion init --input C:/Users/benda/Desktop/market_regime_v1/data/ohlcv/BTCUSDT_1d.csv
python -m research_os.dev_only.mean_reversion step
```

Call `step` once per generation, at most five times. If the returned state is
SEALED, stop immediately. A generation is one atomic transaction; after an
interruption, run the same step with the frozen code and study. Do not reinitialize.
Changed code/specification, duplicate initialization and writes to sealed runs
are rejected. The complete input is stored in SQLite and is not refreshed.

```powershell
python -m research_os.dev_only.mean_reversion report
python -m research_os.dev_only.mean_reversion export
```

Export creates `report.json` exactly once beside the database in
`outputs/research_os/dev_only/mean_reversion/btc_short_mean_reversion_v1_20260920/`.
Both files are ignored generated artifacts. Reports open the database read-only.
All candidate curves, trades and nine period evaluations (eight folds plus the
overlapping continuous diagnostic) remain in the database. Cash and BTC receive
the same period boundaries and costs where trades occur.

Each completed generation records ten candidates, six eligible survivors and
four globally unseen adjacent mutations. Generation five's children are saved
for lineage completeness but never evaluated: 26 evaluated candidates, 30 total
candidate records. No sixth generation is permitted. If fewer than six candidates
remain eligible, immediately seal HISTORICAL_REJECT without creating children.

Only HISTORICAL_REJECT and HISTORICAL_QUALIFIED_AWAITING_FORWARD are allowed.
Qualification requires strictly positive return and fitness versus zero-return
cash in every fold and the continuous period, with no turnover breach. BTC is a
reported secondary comparison, not an undeclared qualification threshold.
On rejection, do not add probes, generations, domains or a Pi monitor. On
qualification, freeze the candidate and prepare a separate read-only monitor for
review; stop before installing anything on Pi. Historical results never authorize
production promotion.

Opening weights are capped at 0.50 or 0.75 after costs; risk-only open trims can
reduce units. Mark-to-market close weights can drift above that target between
opens, and `max_close_exposure` reports this without clipping. No borrowing,
shorting or additions to held positions are allowed.
