# Evolution cash stability v2 — REJECT

## Verdict

**REJECT.** The frozen candidate passes only two of three chronological annual
cash gates. It loses 12.31% in 2022. Its continuous 2022–2024 fitness is -13.63
percentage points versus cash at zero. The already-seen exploratory interval also
fails the risk-adjusted cash gate. No sixth generation, expanded search, IML or
production promotion was performed.

This is a rejection under the preregistered research criterion, not a claim that
every possible parameterization of the family must fail. Five generations did
improve the selection score, but that did not establish stable forward performance.

## Protocol and chronology

- Requested base commit: `16bcc2b45522a1e8d38d65a85cfa3a5196476ab7`.
- Local repair branch fast-forwarded from `0591e2db` to that exact commit.
- Preregistration/code commit, created before the experiment:
  `e128359a30af8eab20547b81ac571683bf788937`.
- New experiment: `btc_cash_stability_v2_20260920`, created 2026-09-20 07:40:44 UTC.
- Train diagnostics: 2018-08-01..2019-12-31.
- Selection folds: 2020-01-01..2020-12-30 and 2020-12-31..2021-12-31.
- Frozen-candidate chronological controls: calendar years 2022, 2023 and 2024.
- Additional continuous control: 2022-01-01..2024-12-31, without annual resets.
  It overlaps the annual checks and is not counted as independent extra evidence.
- **2025-01-01..2026-08-19 was already seen and is exploratory only.** It is
  never described as untouched out-of-sample evidence. It was not used for this
  run's selection; failure may veto PASS but success cannot establish evidence.
- Exactly five generations, ten evaluated slots per generation, six retained,
  four unseen adjacent one-gene mutations each time. Seed 20260920.
- Same reviewed daily OHLCV engine and parameter domains; prior-close signals,
  next-open fills, long/cash exposure, transaction costs of 15 bps one way.
- Cash is a nominal non-interest-bearing 0% benchmark; BTC includes the same
  one-way entry/exit cost assumption. These are simulated returns, not account PnL.
- PASS requires net return > 0 and fitness > 0 in all annual control windows and
  the continuous control. Exploratory failure also vetoes PASS. BTC outperformance
  cannot compensate for failure against cash. No post-result threshold changes.

The control dates, costs, budget, input hash, and rule are in the versioned JSON
specified by [the preregistration](evolution-v2-preregistration-20260920.md).

## Results after costs

Fitness is `CAGR - 2 * abs(max_drawdown)`; the table multiplies it by 100.
Cash return, drawdown and fitness are zero in every row.

| Period | Candidate return | Candidate CAGR | Candidate max DD | Candidate fitness | BTC return | BTC fitness | Cash gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2022 | -12.31% | -12.32% | -17.06% | -46.44 | -64.31% | -198.20 | REJECT |
| 2023 | +46.85% | +46.89% | -17.58% | +11.73 | +154.85% | +115.01 | PASS |
| 2024 | +60.78% | +60.62% | -20.59% | +19.45 | +120.64% | +67.98 | PASS |
| 2022–2024 continuous | +107.50% | +27.54% | -20.59% | -13.63 | +101.86% | -107.49 | REJECT |
| 2025-01-01..2026-08-19, already seen/exploratory | +0.86% | +0.52% | -17.61% | -34.69 | -26.13% | -122.88 | REJECT |

The 2022 loss matters even though it is smaller than BTC's loss. The candidate
had only 19 exposed days that year and still lost money; nominal transaction
costs totaled about 0.43% of initial simulated equity. That does not support
attributing the whole failure to fees. The favorable continuous cumulative
return also does not meet the declared CAGR/drawdown criterion.

Frozen champion: `c79254d9f9765c5672ff`, fast/slow windows 10/90 days, momentum
60 days, threshold 2%, annualized volatility target 0.75, exposure cap 0.75.
No candidate was reselected after reading the controls.

| Generation | Population | Survivors | New mutations | Leader's weakest fold fitness ×100 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 10 | 6 | 4 | 28.19 |
| 2 | 10 | 6 | 4 | 28.19 |
| 3 | 10 | 6 | 4 | 49.41 |
| 4 | 10 | 6 | 4 | 49.41 |
| 5 | 10 | 6 | 4 | 49.41 |

There are 26 distinct evaluated strategy candidates across 50 generation slots.
Four mutations produced at generation five remain unevaluated audit records.
The database contains 32 candidate rows including two benchmarks, five generation
records, 96 period evaluations, 45,914 daily curve rows and 16,703 simulated trades.
The new run is `SEALED`; the generation budget remains exactly five.

## Different family proposed, not executed

Do not keep widening this moving-average/momentum search. A distinct next research
hypothesis is **short-horizon mean reversion in range-bound markets**, with an
explicit veto during strong downtrends, a time-limited exit and a turnover budget.
This tests reversal after short-term dislocations rather than persistence of a
medium-term trend. Any next experiment should preregister a small parameter space,
cost assumptions, cash/BTC comparisons and future observation rules before running.
This is an untested hypothesis, not a claim of superiority or a deployment request.
No alternative-family backtest or additional generation was run in this task.

## Persistence and immutability

Local output root:
`C:/Users/benda/Desktop/trendatlas_recovery_20260920/outputs/research_os/dev_only/evolution/btc_cash_stability_v2_20260920/`.
The controller generated `research.sqlite3` and `report.json`; both are ignored by Git.
Metrics, curves, trades, frozen protocol and lineage are persisted in SQLite.
Finalization is one transaction and late failure rolls back all comparative outputs.

- Input CSV SHA256 before/after:
  `52a54850a11110a5f4cf00c0668645ab80e210f577a97427396b8721704b6b26`.
- New run implementation SHA256:
  `973ce8e2f77afda0b89f21da5544221864f837c2c6a3bcae6f04f4bfdfc23d51`.
- Frozen protocol SHA256:
  `65ae9877fa04c300a3893920a45c64c61d657e74befa8370cce1b3da2d6f5a78`.
- Old `btc_pilot_20260920/research.sqlite3` unchanged:
  `e4b62b383bc2a6195574351902d48b54c25a93838ad281b7972f3e86f0bf94ce`.
- Old `btc_pilot_20260920/report.json` unchanged:
  `af16457216e9ef3f505aa00c2553ba643af3ea07b58aa7255c5e4b83436843cb`.

The old sealed run was never opened for writing or re-exported. Final verification
of the new database used SQLite `mode=ro`; integrity check returned `ok`.

## FILES READ

First read: `docs/evolution-independent-review-20260920.md` at the requested commit.
Then `source_of_truth/README.md`, `source_of_truth/master_state.md`,
`source_of_truth/chat_roles.md`, relevant research/governance/authority sections of
`source_of_truth/project_truth.json`, public/runtime guardrail sections of
`source_of_truth/export_contract.json`, the evolution artifact entry in
`source_of_truth/paths_registry.json`, `source_of_truth/current_issues.md`, evolution
entries in `canonical/script_registry.json` and `canonical/output_registry.json`,
`canonical/registry_workflow.md`, and `AGENTS.md`.

Implementation reads: evolution `CONTRACT.md`, `README.md`, `__main__.py`,
`controller.py`, `backtest.py`, `tests/test_evolution_research.py`, new `protocol.py`
and study JSON; historical local BTC CSV; old sealed artifacts for hashing only;
new generated SQLite/JSON. No Pi credentials, account data, service or deployment
files were accessed during this continuation.

## SOURCE OF TRUTH

SSOT defines research isolation and production boundaries. The independent review
defines the stronger mutation/ranking/cash rules. The preregistered study JSON and
frozen SQLite metadata define this experiment. Its generated measurements are
non-authoritative research and do not replace strategy or account truth.

## Exact root cause and contract impact

Class D/B: the prior pilot's BTC-relative comparison was insufficient to establish
risk-adjusted value versus cash. Even the revised two selection folds needed
explicit post-selection chronological controls and disclosure of the already-seen
2025–2026 interval. Added an optional versioned protocol, binding checks, persisted
comparisons and a stricter final stability verdict. Selection and backtest math
from the review commit were retained. Production contracts and frontend are unchanged.

## Regression tests / validation commands and results

`python -m unittest discover -s tests -p test_evolution_research.py -v`:

- At `16bcc2b4`: all 16 tests passed.
- With this protocol: all 21 tests passed, none skipped.
- Five added tests cover: date/input/budget/disclosure binding; no selection leakage
  and three-benchmark persistence; cash/fold decision gates; preservation of earlier
  sealed files; rollback after late chronological/exploratory failure.

Exact initialization is in the evolution README. Then `step` ran exactly five
times for `btc_cash_stability_v2_20260920`, followed by `finalize` and `report`.
Read-only SQL verified five 10/6/4 generation records, SEALED state, frozen code
hash, declared budget, comparisons, and database integrity. Source CSV and both old
artifact hashes matched their initial values. `git diff --check` passed.

## Forbidden old path checked

No SSH/Pi commands, production commit changes, deployments, service/timer changes,
exchange requests, production refreshes, full-refresh, snapshot date edits,
frontend changes, IML, old-run rewrites or manual generated-output edits.
No `outputs/*` or `data/*` artifacts were staged or committed. The original Windows
working tree was not switched, stashed or cleaned. All research execution stayed
in the separate local research worktree.

## Exact files changed / exact git add list

Preregistration/implementation commit:

```text
git add source_of_truth/project_truth.json canonical/script_registry.json research_os/dev_only/evolution/CONTRACT.md research_os/dev_only/evolution/README.md research_os/dev_only/evolution/__main__.py research_os/dev_only/evolution/controller.py research_os/dev_only/evolution/protocol.py research_os/dev_only/evolution/studies/btc_cash_stability_v2_20260920.json tests/test_evolution_research.py docs/evolution-v2-preregistration-20260920.md
```

Results/audit commit:

```text
git add docs/evolution-v2-results-20260920.md
```

## Commit message / commit hash

- `Preregister five-generation chronological cash-stability research`:
  `e128359a30af8eab20547b81ac571683bf788937`.
- `Record REJECT verdict for five-generation evolution study`: the commit
  containing this report; its exact hash is reported in the completion message.
