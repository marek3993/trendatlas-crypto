# Research audit

## FILES READ

Required order was followed: `source_of_truth/README.md`, `master_state.md`,
`chat_roles.md`, `project_truth.json`, `export_contract.json`,
`paths_registry.json`, `current_issues.md`, then `canonical/script_registry.json`,
`output_registry.json`, `registry_workflow.md`. The user-amended
`source_of_truth/research_objectives_contract.json` was read from the original
checkout and captured as `objectives_reference.json`.

Concrete source functions and their files are listed in `ARCHAEOLOGY.md` and
hashed in `contract.json:source_hashes`. Additional read-only references were
the prior original replay's `legacy_base.py`, `legacy_selection.py`,
`legacy_reference.py`, `legacy_overlays.py`, `replay_support.py`, `run_replay.py`,
the earlier `study_engine.py`, the causal-baseline `rebuild_signals.py`, and
Phase2 `common.py`, `signals.py`, `replay.py`, source contract and protocol.
Those previous results were not accepted as performance evidence or consumed
as strategy returns. The new engine independently reconstructs PnL.

## SOURCE OF TRUTH

SSOT defines the current model/fallback identities and production boundaries.
Source Python functions define the strategy rules. `contract.json` defines this
non-authoritative research experiment. Raw frozen OHLC, macro and ETF source
observations supply input values. `results/*` are fresh research findings, not
new official truth. Production SSOT/export/runtime contracts were not amended.

The task is class D+B. The research contract was written, hashed and loaded
before signal/replay implementation and validated by regression tests. No UI
or downstream production patch was made.

## Exact root causes and corrections

1. `phase68g_portfolio_exposure_leverage_validation.load_governance_paper`
   imports `strategy_return` as `base_ret`, while
   `build_portfolio_exposure_frame` can choose another weekly/reference asset
   label. `build_validation_wrapper` then multiplies that inherited stream.
   A named asset can inherit another asset's payoff and inherited costs. The
   new ledger receives ONLY explicit target symbols/weights and prices its own
   asset, so payoff transfer and inherited-cost double counting are impossible.
2. Phase63/66/67 wrappers mix source decision/executed labels and synthetic
   BASE return streams. Close-D conditions and stress information cannot be
   used as a filter on already earned same-day returns. Every reconstructed
   decision and every inner shadow in this study executes at D+2; metrics
   already completed by D may inform its next decision, not its prior fill.
3. Governance computes signed `candidate_dd - baseline_dd`, rewarding worse
   negative drawdowns. Research uses `max(0, baseline_dd - candidate_dd)` and
   prepends initial equity/includes first return in window metrics. Thresholds
   and score coefficients stay fixed.
4. Phase60 fills unavailable cross-sectional return columns with zero before
   ranking. Future/not-yet-admitted coins affect existing ranks. The new
   cross-section masks unavailable columns before ranking. Phase2 ensemble
   uses only eligible names in its rank denominator for the same reason.
5. Original governance terminal scheduling uses the last observed row as a
   boundary, so appending future data can alter the prior terminal period.
   Anchored seven-day review dates and explicit six-day authorization windows
   preserve source review gaps independently of dataset length.
6. Source runtime shortlist and SSOT shortlist disagree. Both are disclosed;
   a separate SSOT sensitivity prevents an undocumented choice from being
   mistaken for a canonical universal result.

Source metric defects are corrected only inside this research implementation.
Nothing asserts that production is now fixed.

## Exact contract impact

New research-only contract, engine, rule reconstruction, tests, reproducible
inputs, ledgers and report under `research/archeology_20260926/`. No production
contract, strategy promotion, authority change, runtime interface or frontend
change. Historical leverage rows are permitted by the latest explicit user
request, not approval of a new static-leverage production design.

The signal-publication assumption, daily sizing, funding proxy, margin
assumption, conservative intraday DD and fold resets are shared adjustments;
they are documented, not claimed as the old source's original fills. A policy
requiring historical executable venue quotes cannot be certified from these
daily proxy data. Full delisted-universe and release-vintage audits remain
UNVERIFIED rather than silently passing.

## Regression test added/updated

`test_replay.py`: 21 passing tests cover contract/input hash lock, cash/zero
folds, concrete-asset payoff isolation, D+2 timing and first-fill cost,
same-day/unknown-label rejection, missing EXIT quote rejection, prelisting
admission, adverse fill prices and both rotation legs, complete episode PnL
reconciliation under resizing, doubled costs, initial/intraday drawdown,
maintenance liquidation, future price perturbation, signed-DD/first-return
correction, future-only symbol rank invariance, CASH permission, exact holding
duration, tail-trigger timing, the source BTC persistence threshold, the
unchanged core universe in H and immediate market-wide risk exit in I.

`audit.py` independently reruns all40 comparison rows on a prefix ending
2024-09-19 and with all later OHLC/ETF/macro data perturbed. Each prior target
symbol/exposure must match the full fresh run. All fills must follow their
signal's availability and use a concrete symbol/adverse fill; trade episode
log contributions reconcile to full net log growth. Machine results are in
`causality_audit.json`; limitations stay explicit even when calculations pass.

The cached NumPy governance evaluator was compared against the preceding fresh
run: all published numerical performance metrics agree exactly (max absolute
difference0), except the intentionally corrected median holding duration.
The ensemble rank repair did not change this observed run's metrics.

## Forbidden old path checked

No strategy decision or payoff reads `*_paper.csv`, saved summaries,
production timeseries, app snapshots or authority state. The only input from
`outputs/` is the explicitly identified ETF SOURCE panel, copied read-only into
the research freeze. `BASE`/`CORE`/`CANDIDATE` cannot reach the trading ledger;
unknown symbols and missing actual held/exit quotes fail. No runtime full
refresh, publish-existing, live-order or scheduler command was run.

Each replay inventories3,028 protected worktree files under `data`, `outputs`,
`source_of_truth`, `canonical`, with no changes. Final Git staging is restricted
to the exact research-only paths in `GIT_ADD.txt`. Existing uncommitted changes
in the user's original checkout were neither staged nor modified.

## Validation commands/results

From `C:/Users/benda/Desktop/ta_archeology`:

```powershell
python -W ignore research/archeology_20260926/test_replay.py
python -W ignore research/archeology_20260926/run.py
python -W ignore research/archeology_20260926/run.py --double-feedback
python -W ignore research/archeology_20260926/audit.py
python -W ignore research/archeology_20260926/render.py
git diff --cached --check
```

The engine/rule replays completed for40 rows each at nominal and fully
reconstructed2× costs. The main run also independently executes40 frozen-signal
2× accounting stresses and40 extra-bar fill stresses, plus the ETF-window
replays. See both `receipt.json` files for protected-state checks and run
hashes. The 21-test output is captured in `test_results.txt`. Final causal
audit PASS: 40 prefix checks and 40 future-perturbation checks, each covering
2,591 signal rows through 2024-09-19, plus 24,340 fills and 40 complete PnL
reconciliations. The exact result and evidence gaps are in
`causality_audit.json`.

Plot rendering required matplotlib unavailable in either initial runtime;
it was installed only in `C:/Users/benda/AppData/Local/Temp/ta-archeology-plot-deps`.
The successful rendering command prepends no project environment changes:

```powershell
python -W ignore -c "import sys,runpy,numpy,pandas; sys.path.append('C:/Users/benda/AppData/Local/Temp/ta-archeology-plot-deps'); runpy.run_path('research/archeology_20260926/render.py',run_name='__main__')"
```

## Attempts and corrections

Two startup attempts failed before any final comparison: a pandas `.empty`
property called as a function, and a positive exposure on a resolved CASH
target. Both were fixed; the latter received a regression test. The original
freezes are retained as `initial_failed_freeze.json` and
`second_failed_freeze.json`. No strategy parameters changed.

The first complete run was superseded to correct inclusive exit-day holding
counts, repair ensemble unavailable-rank normalization and accelerate the
identical governance arithmetic. Its artifacts/freeze remain under `attempts/`.
At that intermediate stage all strategy metrics agreed exactly except
corrected holding duration.
No retry or choice was made to improve performance. Render-only dependency
failures did not execute or alter strategy accounting.

Final code review found H accidentally allowed reference-only symbols into the
core selector, and I preserved its held-candidate gate but not the original
market-wide CASH gate. H now retains the original 12-symbol core mask and I
preserves both source risk exits. These isolate the requested selector-only
interventions; thresholds and schedules were not changed. The preceding code,
hashes, metrics and audit remain in `attempts/selector_scope_before_fix.zip`.
Nominal and cost-feedback replays, 21 regressions and the full prefix/future
audit were rerun. `selector_scope_validation.json` verifies every non-H/I
metric is identical in both nominal and cost-feedback runs (max difference 0).
The corrected H raises CAGR to 20.66% but has 62.03% MDD; corrected I has
-3.35% CAGR and 57.14% MDD. Neither passes the unchanged decision gates.

## Exact files changed / exact git add list

Every changed file is new and is listed individually in `GIT_ADD.txt`. The
reviewed staging command is:

```powershell
git add -f --pathspec-from-file=research/archeology_20260926/GIT_ADD.txt
```

The repository ignores ZIPs. `-f` adds only the exact reviewed research paths,
including the frozen public inputs and complete ledgers; it does not stage any
production `data/*` or `outputs/*`. Research `.gitattributes` preserves frozen
bytes and recognizes CRLF as line endings for whitespace checks.

## Commit message

`research: reconstruct TrendAtlas families with common causal replay and ablations`

## Commit hash

The committed hash and successful remote push are reported in the final task
response. A commit cannot contain its own hash; verify with `git rev-parse HEAD`
on `codex/strategy-archeology-20260926`. No merge or production deployment is
authorized by this research commit.
