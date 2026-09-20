# Isolated evolution research

Class D (backtest math) and B (persisted research results). This module implements
the user's 2026-09-20 research request only. It does not change the live strategy.

- Ten distinct candidates per generation, six survive, four unseen one-gene
  mutations fill the next population. IML is optional and is not imported.
- Initial adapter: daily BTC long/cash trend and momentum strategies, with
  trailing volatility sizing capped at 1x. These are research candidates, not
  replicas of the production strategy. No synthetic fitness values.
- Validate chronological, consecutive UTC OHLCV bars, positive finite prices,
  OHLC consistency and closed dates. Persist the input bars and original SHA256.
- Fix seed, generation budget, date splits, costs, parameter domains, fitness,
  and source-code hash before search. Resume only with the identical code.
- Signals use only closes strictly before the execution day's open. Rebalance
  at that open with fees plus slippage on actual traded notional; carry positions
  overnight, mark at each close, liquidate at the final close with costs.
- Train, validation and final test are consecutive, disjoint periods. Earlier
  observations may warm up trailing features. Every period starts with cash.
  Search reads no bars after validation end. Rank by validation CAGR minus twice
  absolute maximum drawdown; break ties by candidate ID. Training metrics are
  diagnostics, never reported as an independent test.
- Freeze the champion from the last evaluated generation before final testing.
  Evaluate only that champion and buy-and-hold on the final period, once after
  the fixed generation budget. Persist the result and seal the run; no subsequent
  mutation, selection, or resumed search can use this final test.
- SQLite transactions store inputs, candidates, lineage, populations, survivors,
  per-period metrics, daily curves and trades. Interrupted generations roll back.
  All runs remain visible: rejected candidates and poor final results are retained.
- Writes are confined to the resolved repository research output root; reject
  symlink escapes. No production imports, credentials, exchange calls, authority
  writes, publish calls, scheduler hooks, or automatic promotion.
- Run sequentially with a fixed generation budget and wall-time limit. This
  implementation runs locally; it is not deployed into the Pi production service.

This is a reproducible experiment, not proof of an investable edge. Multiple
generations optimize validation, and previously viewed market history cannot be
claimed to be a globally untouched holdout. The final period is isolated from
this run's programmatic selection. Costs are a fixed simulation assumption.
