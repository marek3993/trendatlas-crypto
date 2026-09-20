# Cash stability v2 — preregistration

This protocol is committed before initializing the new run or calculating any
new candidate results. Base review: `16bcc2b45522a1e8d38d65a85cfa3a5196476ab7`.
Scope: local research only, classes D/B. No Pi connection or deployment.

- Run ID: `btc_cash_stability_v2_20260920`; exactly five generations of 10/6/4.
- Same BTC trend/momentum family, domains and seed 20260920 as the prior pilot.
  Adjacent one-gene mutation and weakest-then-mean two-fold ranking from the review.
- Train diagnostics: 2018-08-01..2019-12-31.
- Selection: 2020-01-01..2021-12-31, split by the existing equal-day fold function.
- Freeze the generation-five champion once. No re-selection or tuning thereafter.
- Independent-of-this-search chronological control windows: 2022, 2023, 2024,
  evaluated separately from fresh cash with the same frozen genes and costs.
- Also evaluate the continuous 2022-01-01..2024-12-31 interval to expose the
  difference between yearly resets and carrying positions across year boundaries.
  This overlaps the annual controls and is not an extra independent observation.
- 2025-01-01..2026-08-19 is already seen, explicitly exploratory only. It cannot
  establish untouched out-of-sample evidence. Older market data are also historical;
  the annual controls are chronological with respect to this algorithm's selection,
  not globally unseen or prospective data.
- Each period compares net return, CAGR, drawdown and `CAGR - 2*abs(drawdown)`
  against nominal non-interest-bearing cash (0%) and BTC buy-and-hold.
- Costs: 15 bps one way, fees plus assumed slippage; no funding because exposure
  is long/cash and capped at 1x. Same next-open accounting as the reviewed engine.
- PASS requires strictly positive net return AND fitness versus cash in all three
  annual controls AND the continuous control interval. An exploratory failure also
  vetoes PASS; exploratory success supplies no independent confirmation.
- BTC outperformance is reported, but cannot rescue a failed cash gate.
- REJECT means no sixth generation, no wider search or IML. Propose a different
  strategy family as a future research hypothesis without running it here.
- No candidate can be promoted from this experiment, even if it receives PASS.

Machine-readable binding:
`research_os/dev_only/evolution/studies/btc_cash_stability_v2_20260920.json`.
Input SHA256: `52a54850a11110a5f4cf00c0668645ab80e210f577a97427396b8721704b6b26`.

The selection cutoff was moved earlier so that older controls genuinely follow
selection. Testing a champion selected on 2023–2024 against 2022 and calling that
a forward check would reverse the chronology.

The prior `btc_pilot_20260920` is immutable. Before fast-forward:

- SQLite SHA256: `e4b62b383bc2a6195574351902d48b54c25a93838ad281b7972f3e86f0bf94ce`.
- Report SHA256: `af16457216e9ef3f505aa00c2553ba643af3ea07b58aa7255c5e4b83436843cb`.

Validation before execution: all 16 tests at the review commit passed; all 21
tests after the chronological protocol addition passed. The five new regressions
cover protocol/date/budget binding, comparative persistence and selection cutoff,
cash decision gates, old sealed artifact immutability, and late-finalization rollback.
