# Causal Pareto research — 2026-09-26

The measured outcome is in [RESULTS.md](RESULTS.md), with the handoff and
validation evidence in [AUDIT.md](AUDIT.md). The prior eight-file objectives
change was committed first as `bed0f0fe`; this directory implements and executes
that task. This is offline research, with no production authorization.

## Reproduce from the committed inputs

Run from the repository root with Python 3.12 and the pinned requirements:

```powershell
python -m pip install -r research/causal_search_20260926/requirements.txt
python -m unittest discover -s research/causal_search_20260926 -p "test_*.py" -v
python -m unittest discover -s tests -p test_research_objectives.py -v
python research/causal_search_20260926/run.py --out scratch/full_reproduction --cache scratch/fresh_grid_cache
python research/causal_search_20260926/finalize.py --out scratch/full_reproduction
python research/causal_search_20260926/render.py --out scratch/full_reproduction --report scratch/full_reproduction/RESULTS.md
```

Use new empty output/cache directories for a fresh run. A populated cache is
accepted only for the exact frozen implementation fingerprint. `reproduce.py`
also verifies a second complete OOS/stress/neighbor/audit replay using a verified
grid cache and independently recomputes grid indices 0, 162 and 323 in every
partition under all three scenarios. That check is explicitly distinguished
from a second fresh full-grid search.

## Evidence map

- `pre_registration.json`, `inputs.zip`: universe, concrete symbol identities,
  member hashes, all parameters, folds, costs and six separate budgets, frozen
  in Git before the first market replay.
- `results/implementation_freeze.json`: implementation/input/contract hashes
  and creation time before the accepted full run.
- `results/validation_scores.csv`: all 1,944 candidates and seven historical
  metric windows. The six validation years overlap the overall development
  summary by design; their rows are not independent trials.
- `results/walk_forward_choices.json`: all 108 choices made from earlier
  validation data. No OOS outcome chooses the parameters of its own fold.
- `results/nominees_before_oos.json`: A/B/C policy nominations based on 2020
  validation, written before calculation of OOS policy metrics. The forward
  fixed parameters use the already frozen 2026 choice from 2025 validation.
- `results/pareto_table.csv`, `results/oos_folds.csv`: 18 predeclared adaptive
  policies, their observed descriptive Pareto frontier, and six OOS folds each.
- `results/*_equity.csv`, `*_events.csv`, `*_signals.csv`: daily equity,
  concrete-asset accounting events and decision availability. Exported episode
  IDs are local to each annual fold; use `(year, episode)` as the global key.
- `results/*_double_cost.csv`, `*_delayed.csv`, `parameter_neighbors.csv`:
  actual replays with frozen nominal choices, not rescaled nominal curves.
- `results/expanded_audits.json`, `verification.json`, `evaluation/`:
  prefix/future-perturbation replays, fill/asset checks, independently rebuilt
  quantity/price/cost PnL and fail-closed assessment against the objectives.
- `results/reproduction_manifest.json`: deterministic core artifact hashes.
- `results/reproducibility_verification.json`: second replay and fresh grid
  spot-check results. Implementation timestamps and chart metadata are excluded
  from deterministic core comparison. The validation grid alone may have a
  different row/column order after loading a sorted JSON cache; its values must
  match exactly after canonical ordering. All other core files must match bytes.
- `attempts/`: fingerprints and explanations for two interrupted starts and the
  completed grid with a rejected scalar-type interface and invalid CASH output.
  Their work is not hidden or counted as new unique parameter trials.

## Interpretation

Historical OOS is chronological computational OOS, not research history that
nobody has previously inspected. The fixed universe contains twelve surviving
coins. Listing admission uses 252 completed daily observations but does not
reconstruct delisted assets. Daily spot OHLC, a 12% annual full-notional funding
debit, 4.5 bp fees and 10 bp slippage per side are explicit proxies; they do not
certify historical derivative listings, liquidity, funding or fills.

Decisions from close D become available at D+1 00:00:01 UTC and first execute at
the next captured daily open, D+2. The delay stress queues the frozen entry for
one extra bar and retains timely exits/protection. Superseded queued entries
expire. Stops simulate both OHLC path orders and take the worse terminal equity;
intraday drawdown is retained. Annual boundaries close positions and charge
costs for all alternatives. OOS folds start with unit equity and their net
returns are then compounded chronologically.

The best-day/top-three-trade removals subtract net log contributions, preserving
the period length. They are omission diagnostics, not alternate capital-allocation
backtests. Neighbor perturbations never feed back into selection. Selection
requires prior-validation risk feasibility; observed OOS violations remain
visible and disqualify that policy instead of being hidden through reselection.

## Prospective sealed paper evaluation

```powershell
python research/causal_search_20260926/paper.py --init
python research/causal_search_20260926/paper.py --prices-dir path/to/new_daily_bars
```

The committed `paper/forward_seal.json` binds the nominees and code before the
prospective interval. Supply all twelve identically named CSVs with complete
new daily bars starting 2026-09-26, columns `date,open,high,low,close` (additional
columns are ignored). Evaluation starts 2026-09-27 and ends 2027-09-26.
Incomplete/future bars, missing days, different asset cutoffs, modified accepted
bars and changed frozen code are rejected. Every as-of record is immutable.

Interim numbers are hypothetical liquidation-value replays including a terminal
exit. They are not an append-only ledger of observed broker fills. The final
interval is the final fixed-policy evaluation. No collector, scheduler or order
API is installed; this command consumes supplied new data offline. No parameter
refit or automatic winner/promotion is allowed. Missing venue/universe evidence
continues to block certification even after the future interval completes.
