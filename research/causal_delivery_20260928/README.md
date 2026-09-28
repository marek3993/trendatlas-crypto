# Immutable terminal delivery

Financial decision: **REJECT**. This directory is evidence and offline verification,
not a new experiment or deployable strategy. Read the completed
[REPORT](../causal_evolution/REPORT.md) and [AUDIT](../causal_evolution/AUDIT.md).

## Source of truth and inventory

- Frozen scientific engine: `53b6a5336ca1f7ce35b481a017f7e82396f3613c`.
- `archive/terminal.tar.gz.part01` through `part03` reconstruct the exact locked
  20:16 UTC VPS snapshot. `archive/index.json` records per-part and whole hashes.
  SQLite is authoritative for requests, results, trials, nominees and API usage.
- `raw/` is a byte-preserved convenient subset of original terminal exports.
  `raw/transfer_manifest.json` describes all 132 files inside the full snapshot,
  not just this convenient subset. `raw/REPORT.md` is the original generated report;
  its prospective date is a contractual floor, corrected by the audited top report.
- `derived/` contains read-only reconciled tables. They neither replace the frozen
  results nor select/mutate candidates. Fractions are unformatted numeric values.
- `INITIAL_REPORT.md` preserves the original pre-completion report byte-for-byte.
- The two VPS text captures and Pi capture are read-only runtime evidence. The
  first VPS capture ends exit 1 because non-sudo readlink could not traverse the
  root-owned export path; the second sudo readlink succeeded and confirmed the
  export was stale. No service was changed.

## Reproduce verification, without re-running research

Run from this research worktree root in PowerShell. Python 3.12 was used for local verification; the VPS engine used 3.13;
Python 3.12+ supports the safe tar extraction filter. Choose fresh paths below:
the restore command intentionally refuses existing destinations.

```powershell
python research/causal_delivery_20260928/restore.py --destination research/causal_evolution/local_state/final_restore
git worktree add --detach ../ta_causal_pinned_verify 53b6a5336ca1f7ce35b481a017f7e82396f3613c
python -m venv research/causal_evolution/local_state/verify_runtime
research/causal_evolution/local_state/verify_runtime/Scripts/python.exe -m pip install -r ../ta_causal_pinned_verify/research/causal_evolution/requirements.txt
research/causal_evolution/local_state/verify_runtime/Scripts/python.exe research/causal_delivery_20260928/verify.py --snapshot research/causal_evolution/local_state/final_restore/snapshot --engine ../ta_causal_pinned_verify --out research/causal_evolution/local_state/verification_reproduced
```

The verifier opens both databases with `mode=ro&immutable=1`. It checks all transfer
hashes, all 38 frozen code/input hashes, SQLite integrity/FKs, completed-attempt
bijection, budgets, scope dates, no post-outer trials/development, all 96 API
payloads/responses with the pinned pure validator, saved causal audits, all 72
continuous schedule metrics/stresses/neighbors/capacities, both benchmarks and all
54,094 exported daily equity rows. CAGR, Sharpe, recorded intrabar MDD, whole-episode
removals, closed-trade counts and dollar costs are reconciled from saved NAV/books.
This is an independent extraction/calculation check, not a new replay against raw
market bars. Saved fill/prefix audits came from the original frozen run.

Both benchmark nominal books are included. Double-cost/later-fill benchmarks were
not evaluated by the frozen runner; table cells say `NOT_EVALUATED`. This verifier
does not fill gaps by executing new strategy books after sealing.

Validation actually used the existing pinned source export at
`C:/Users/benda/.codex/tmp/causal-frozen-53b6a5` and the dedicated research runtime;
all source hashes were checked. The committed archive was reassembled into a fresh
`local_state/terminal_reconstruction_test` and verified again successfully.

## Curves and tables

`derived/common_comparison.csv` is the shared 74-row table. Continuous annual folds,
all stresses/neighbors, all four capital levels, exact annual rules, full episodes,
API calls, matched arm budgets and descriptive arm medians have separate CSVs.
All original development tables and lineage are retained; all saved books, orders
and available detailed fills are in the SQLite/archive. No missing fill is invented.

The original all-line SVG is byte-preserved. The overview plots every family row,
with separate spot/perp benchmarks, and performs no selection. To reproduce:

```powershell
python -m venv research/causal_evolution/local_state/plot_runtime
research/causal_evolution/local_state/plot_runtime/Scripts/python.exe -m pip install matplotlib==3.10.6
research/causal_evolution/local_state/plot_runtime/Scripts/python.exe research/causal_delivery_20260928/plot.py
```

Package installation is local to that optional plotting environment. No Pi/VPS or
production runtime changes are involved. The pinned engine's regression suite can
be run separately in its worktree; no `cli run`, evolution restart, or refit is part
of these reproduction commands.

## Authority and commit

The scientific contracts, evaluator, input data, budgets and remote deployment are
unchanged. Historical experiments, recovery/migration audits and earlier evidence
remain intact. Only terminal reporting, offline tooling and evidence are staged.
Exact staging paths: [GIT_ADD.txt](GIT_ADD.txt). Commit message:
`research: archive sealed causal cycle and audit rejected finalists`.

Commit hash is given in the final response and can be resolved without embedding
a circular self-hash: `git log -1 --format=%H -- research/causal_delivery_20260928`.
After push, only the Codex completion heartbeat is paused; no research deployment,
Pi timer, production service or order authority is changed.

Optional preservation check: append `--prior-checkpoint <checkpoint-5087>` to the
verifier. The original candidates SQLite hash must be
`5457c1d146ae3d7825dec926cb0d13b82ea1b13c596f578c98b48715254ad720`.
All old science-table cells, 41 orchestration events and 84 API records matched
the final snapshot. Progress metadata intentionally advances and is not compared
as immutable. Raw exports keep original line endings/whitespace by attributes;
this preserves their SHA256 values rather than rewriting historical evidence.
