# Offline evolution

Run from the repository root with Python 3.10 or newer; only the standard library
is required. No IML, network, account keys or production service are used.
See [CONTRACT.md](CONTRACT.md) for timing, costs, isolation and selection rules.

The starting strategy family is BTC long/cash trend plus momentum, with trailing
volatility sizing. The adapter runs genuine historical OHLCV simulations; it is
not a backtest of the current production strategy.

Example (set the CSV path and final date to your actual historical input):

```powershell
python -m research_os.dev_only.evolution init btc_pilot_20260920 --input C:/Users/benda/Desktop/market_regime_v1/data/ohlcv/BTCUSDT_1d.csv --train-start 2018-08-01 --train-end 2022-12-31 --validation-end 2024-12-31 --holdout-end 2026-08-19 --generations 3 --cost-bps 15
python -m research_os.dev_only.evolution step btc_pilot_20260920
python -m research_os.dev_only.evolution step btc_pilot_20260920
python -m research_os.dev_only.evolution step btc_pilot_20260920
python -m research_os.dev_only.evolution finalize btc_pilot_20260920
python -m research_os.dev_only.evolution report btc_pilot_20260920
python -m research_os.dev_only.evolution status btc_pilot_20260920
```

Each `step` evaluates ten candidates, retains six, and produces four unique
one-gene mutations. Unchanged survivors reuse the same immutable-period results.
After the final planned generation the champion is frozen. The next population
is retained for audit but its four new mutations are unevaluated and cannot be
searched after final testing. Resume an interrupted search with `step` until the
predeclared budget is complete; a failed generation rolls back atomically.

`finalize` evaluates the frozen champion and BTC buy-and-hold on the final period
and seals the run. It refuses an early or repeated final test. All subsequent
evolution is refused. A new study requires a new run ID and must disclose that
prior test results have been viewed. No final test is used to choose a winner.

The run database is
`outputs/research_os/dev_only/evolution/<run_id>/research.sqlite3`.
Tables include `bars`, `candidates`, `populations`, `generations`, `evaluations`,
`curves`, `trades`, `meta`, and `final_test`. `report` exports a readable JSON
snapshot beside the database. Generated results are ignored by Git.

The default experiment uses three generations, seed 20260920, a 300-second
per-operation limit, sequential execution and 15 bps total one-way transaction
cost (fees plus assumed slippage). No external API or future data is fetched.
Training metrics are diagnostics; validation fitness is CAGR minus twice the
absolute maximum drawdown. Returns and exposure here are simulated research
values, never real account PnL or positions. There is no automatic promotion.

Validation:

```powershell
python -m unittest discover -s tests -p test_evolution_research.py -v
```
