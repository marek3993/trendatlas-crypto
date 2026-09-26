# TrendAtlas replacement strategy research

Read [REPORT.md](REPORT.md), [AUDIT.md](AUDIT.md) and [contract.json](contract.json).
This is an executed research experiment based on archaeology commit
`d3be15dbd4da8be1f97cb526dc8cacf8cd7d0e75`. No production code is imported by the
new decision engine or edited by this branch.

Python 3.12.10, numpy 2.4.1, pandas 3.0.2; chart renderer matplotlib 3.11.2.
Dependencies are in `requirements.txt`. No exchange/account credential is needed.

## Reproduce

The committed run is immutable. For a fresh reproduction, copy the research
directory into a NEW named sibling directory within `research/`, retaining the
source files and frozen inputs but excluding `results/`, report-derived files
and raw `archive/` cache. The source code resolves its research root relative to
its own file; all new writes stay in that new directory. Do not overwrite the
committed freeze or delete its results to force a rerun. Alternatively review
all committed results without executing the search again.

The helper copies exactly the frozen code/inputs to a NEW sibling directory,
disables API calls by default, and runs tests, search, audit, extra stresses and
reporting. Use an environment with the pinned dependencies installed:

```powershell
python research/new_strategy_20260926/reproduce.py --destination new_strategy_reproduction --run
```

Equivalent individual commands after the helper's copy-only invocation:

```powershell
python -W ignore research/new_strategy_reproduction/test_framework.py
python -u -W ignore research/new_strategy_reproduction/run.py
python -W ignore research/new_strategy_reproduction/audit.py
python -W ignore research/new_strategy_reproduction/extra_validation.py
python -W ignore research/new_strategy_reproduction/render.py
```

The runner refuses an existing `results/freeze.json`. Use the committed input
bundle, cohort, listing evidence and notices; do not acquire newer data during
reproduction. To reproduce the deterministic proposal run exactly, ensure
`DEEPSEEK_API_KEY` and `MRV1_DEEPSEEK_API_KEY` are absent in the process environment.
If deliberately provided with `--allow-api` for a separate experiment, the bounded proposer may
call the documented DeepSeek endpoint; it never sees OOS or prospective results.

`acquire.py` and `listings.py` are the original bounded public-data preparation
commands. They are not necessary for offline replay. Official raw archive ZIPs
and matching checksum metadata are preserved in `archive_evidence.zip`; the
scored input is `market_inputs.zip`. `acquisition.json` and
`listing_acquisition.json` retain provenance and download checksums.

## Artifacts

- `results/development.jsonl` / CSV: every candidate, rules, status, costs and
  stresses, including rejected capacity checks.
- `results/generations.json`: every 10→6→10 population transition.
- `results/origin_*_frozen.json`: prior-year selection frozen before OOS.
- `results/finalists_frozen.json`: prospective A/B/C nominations and rejected
  aggressive diagnostic; no 2026 performance is read.
- `results/family_results.*`, `oos_folds.json`: full annual OOS, including zero
  CASH folds. Incomplete execution evidence is never averaged into a result.
- `results/pareto_fronts.*`: feasible/infeasible development Pareto fronts;
  `oos_pareto_descriptive.json` does not perform reselection.
- `results/ablations.json`, `neighbors.json`, `finalist_neighbors.json`: fixed
  component contrasts and adjacent parameter checks.
- `results/ledgers.zip`: concrete signals, timestamps, fills, costs and complete
  trade episodes. `baseline_stresses.json` contains reference cost/delay stress.
- `causality_audit.json`: invariance, lineage and freeze evidence.
- `decision.json`: REJECT; missing prospective/venue evidence cannot become PASS.
- `attempts/*.zip` and `attempt_summary.json`: two superseded complete runs,
  their frozen code and the explicit accounting of correctness reruns.
- `artifact_manifest.json` and `GIT_ADD.txt`: exact committed artifact hashes
  and individually reviewed staging paths.

The fixed unlevered spot hypotheses do not meet the 150–200% CAGR objective.
No ETF, TP, trailing stop, cooldown, leverage or failed-model ensemble is used
to disguise that result. Funding is venue-specific and separate; it does not
turn spot prices into a perpetual dataset.
