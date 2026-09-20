# Isolated evolution research

Class D (backtest math) and B (persisted research results). This module implements
the user's 2026-09-20 research request only. It does not change the live strategy.

- Ten distinct candidates per generation, six survive, four unseen one-gene
  mutations fill the next population. Each mutation moves exactly one adjacent
  step in that gene's frozen domain. IML is optional and is not imported.
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
  Search reads no bars after validation end. Split validation into two
  chronological folds and rank first by the weaker fold's CAGR minus twice
  absolute maximum drawdown, then by mean fold score and candidate ID. Training
  metrics are diagnostics, never reported as an independent test.
- Freeze the champion from the last evaluated generation before final testing.
  Evaluate only that champion, cash and buy-and-hold on the final period, once
  after the fixed generation budget. A research PASS requires beating cash in
  both net return and the declared risk-adjusted fitness. Persist the result and
  seal the run; no subsequent mutation, selection, or resumed search can use
  this final test.
- SQLite transactions store inputs, candidates, lineage, populations, survivors,
  per-period metrics, daily curves and trades. Interrupted generations roll back.
  All runs remain visible: rejected candidates and poor final results are retained.
- Optional versioned chronological-control protocol is bound to the input hash,
  seed, costs, splits and generation budget before search. All control windows
  follow the selection cutoff, are consecutive and disjoint, and precede the
  explicitly already-seen exploratory interval. A single frozen champion is
  tested on each window, their continuous union, and the exploratory interval.
  Each comparison persists candidate, cash (0% nominal, no yield) and BTC metrics,
  curves and trades. The continuous union is not counted as another independent
  window. PASS requires positive net return and positive declared fitness versus
  cash in every control window and their continuous union. Exploratory failure
  can veto PASS; exploratory success never supplies independent evidence.
  Failure means REJECT and no further generations. No re-selection on controls.
  Historical controls remain retrospective checks, not prospective proof.
- Writes are confined to the resolved repository research output root; reject
  symlink escapes. No production imports, credentials, exchange calls, authority
  writes, publish calls, scheduler hooks, or automatic promotion.
- Run sequentially with a fixed generation budget and wall-time limit. This
  implementation runs locally; it is not deployed into the Pi production service.

This is a reproducible experiment, not proof of an investable edge. Multiple
generations optimize validation, and previously viewed market history cannot be
claimed to be a globally untouched holdout. The final period is isolated from
this run's programmatic selection. Costs are a fixed simulation assumption.
