# Offline strategy archaeology — 2026-09-26

Start with [REPORT.md](REPORT.md), containing the single common40-row table,
the A-I contrasts, ETF-only-period evidence, fold returns and research verdict.
[ARCHAEOLOGY.md](ARCHAEOLOGY.md) maps every family to source functions and rules.
[AUDIT.md](AUDIT.md) describes tests, corrections, limitations and change scope.

This is a research branch, not a production fix or promotion. Nothing here is
real-account PnL. Historical membership/publication vintages and venue-specific
fill/funding evidence remain unverified. Fixed historical parameters and masks
were already researched; the annual folds are computational chronological OOS.

Reproduce from repository root using Python3.12 and the versions in the freeze:

Use `core.autocrlf=true` when checking out the repository's original source
files: the source hashes were frozen from this Windows CRLF checkout. The
research subtree preserves its exact committed bytes with `.gitattributes`.
A different source-file encoding/line-ending convention must fail the hash
check; do not overwrite the contract to make that failure disappear.

```powershell
python -W ignore research/archeology_20260926/test_replay.py
python -W ignore research/archeology_20260926/run.py
python -W ignore research/archeology_20260926/run.py --double-feedback
python -W ignore research/archeology_20260926/audit.py
python -W ignore research/archeology_20260926/render.py
```

Do not rerun `prepare.py` against changed local inputs when reproducing. The
committed `inputs.zip` is the immutable public market-data bundle; it contains
only19 raw OHLCV members, the macro series and ETF source panel, not any paper
returns, account, wallet, credential or runtime artifact. Each input member is
hashed in `contract.json`. `prepare.py` intentionally refuses to replace a
freeze. Raw source paths and coverage are preserved.

`run.py` imports pure source functions and never calls legacy script mains,
refreshes, exchange clients or output writers. Its only writes are inside this
research directory. A protected-tree inventory checks data, outputs, SSOT and
canonical before/after. The source hash manifest is checked before execution.

Outputs:

- `results/comparison.csv`: required metrics and frozen-signal2× costs/+1-bar
  timing sensitivity; `results/folds.csv`: every annual fold including CASH.
- `results/etf_window.csv`: same models, freshly simulated from12 January2024.
- `results/ledgers.zip`: explicit targets, each actual fill, daily ledger and
  complete trade episodes for all40 comparison rows (including named aliases).
- `feedback/*`: independent full rule reconstruction at2× costs, not a favorable
  replacement for the frozen-signal stress.
- `causality_audit.json`: prefix/future perturbation evidence and missing-data
  certification limits. `ablation_deltas.csv`: paired non-additive contrasts.
- `attempts/preaudit_artifacts.zip`: superseded fresh run, retained only for
  audit of the holding-duration/rank-denominator correction. It is NOT an old
  paper series and is not a source of the final replay. At that intermediate
  stage numerical performance agreed exactly; median holding was corrected by
  one day for ordinary open-to-open exits.
- `attempts/selector_scope_before_fix.zip`: superseded code/hash/metrics before
  final H/I isolation fixes. H now uses the same 12-symbol core pool; I preserves
  the original market-wide CASH gate as well as held-candidate invalidation.

Research dependencies: numpy2.4.1, pandas3.0.2. Plotting additionally uses
matplotlib3.11.2; plotting dependencies were installed into a task-specific
temporary directory, without changing project or global environments.

No new parameter search, live orders, Pi connection, deployment, timer change,
full refresh, authority snapshot edit, or generated `data/*`/`outputs/*` commit
is part of this work.
