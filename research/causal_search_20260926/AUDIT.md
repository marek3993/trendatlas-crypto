# Research execution audit

Classification: **D/B** (strategy mathematics and offline data contract).
This audit follows the earlier eight-file objectives change; its old statement
that no experiment or commit existed describes that earlier stage only.

## FILES READ

The required truth/navigation order was followed before implementation:

1. `source_of_truth/README.md`
2. `source_of_truth/master_state.md`
3. `source_of_truth/chat_roles.md`
4. `source_of_truth/project_truth.json`
5. `source_of_truth/export_contract.json`
6. `source_of_truth/paths_registry.json`
7. `source_of_truth/current_issues.md`
8. `canonical/script_registry.json`
9. `canonical/output_registry.json`
10. `canonical/registry_workflow.md`

Additional reads included `AGENTS.md`, `.gitignore`, the research objectives
contract/evaluator/tests, `research/objectives_20260926/`, the previously frozen
`research/risk_overlay_20260926/` contract and audit, selected canonical registry
tests and source JSON tests, and the new code/evidence files listed in GIT_ADD.txt.
The sibling causal-baseline worktree supplied its input manifest and input ZIP;
the source bundle and all twelve extracted price members were SHA256-verified.
Historical baseline reports were context, never treated as this run's result.
The trigger block in `.github/workflows/app_refresh.yml` was read before push:
it contains only manual dispatch and schedule triggers, not a push trigger.
No Pi/runtime/scheduler/publish work was planned or executed.

## SOURCE OF TRUTH

`source_of_truth/research_objectives_contract.json` remains the explicit source
of research objectives. `engine.load_spec()` loads it and refuses a mismatch
against the hash in `pre_registration.json`; the Pareto evaluator also loads
that contract directly. Research results are reports, not official production
truth. Canonical registries only make the new runner and evidence discoverable.

## Exact root cause

The previous change provided objectives and a evidence-gated Pareto evaluator,
but no causal event engine or completed search implementing those objectives.
Old headline performance could not substitute for an independently reconciled
concrete-asset replay. An untouched historical sealed interval was unavailable.

During implementation, the first entry-delay stress shifted the entire signal
stream, which also delayed exits. This violated the requested entry-only stress.
Before completed grid results, nominations or OOS metrics were inspected, that
startup was stopped. The corrected engine queues only the frozen entry asset,
target exposure and ATR source, expires superseded targets, and keeps exits and
protection timely. The entire accepted search uses a new cache. Three delay
regressions and the preserved startup fingerprint document this correction.

The following full grid exposed an additional numerical interface failure:
Calmar was an in-memory NumPy scalar while the objectives evaluator requires
JSON-native finite numbers. Every fresh candidate was rejected, but the exact
same numbers loaded from JSON were accepted. All-CASH OOS artifacts from that
run are invalid, explicitly preserved by hash and excluded. Calmar now returns
a native float, and fresh/cached grid records both cross the same JSON boundary.
Regressions require identical non-CASH choices and native summary types. The
whole grid and all stresses were restarted with an empty cache; no mathematical
rules or parameters changed after the diagnostic development-metric inspection.

Further state-machine review found that a zero-cooldown exposure-guard exit
could reuse a rebound signal from before the exit. The next grid startup was
interrupted before OOS results. Same-asset risk reentry now requires two rising
completed closes after the recorded exit bar, including the zero-cooldown
control; the registered confirmation rule and all parameter values are retained.
Regression covers cooldown 0, 3 and 7 and existing rotation-priority tests still
pass. The accepted run starts another complete search in a new empty cache.

## Exact contract impact

The committed source objectives are implemented without lowering the 150–200%
target. The new experiment pre-registers 324 variants in each of six separate
budgets, costs, fills, risk state transitions and chronological folds. It uses
feasibility before 15-objective Pareto ranking. OOS descriptive winners cannot
replace the pre-OOS forward nominations. Missing sealed, historical universe and
venue evidence remain failed gates; no model is promoted.

## Exact files changed / exact git add list

`GIT_ADD.txt` enumerates every branch-change path relative to the clean starting
commit `ae83345fb218826ca9c5afde6f67d64e809328da`. `COMMITS.json` records the earlier
commit hashes, messages and exact per-commit paths. The research worktree was
created separately so the original checkout's unrelated dirty files were not
included. No broad staging in the original checkout was used.

Main implementation files are `engine.py`, `run.py`, `prepare.py`, `paper.py`,
`finalize.py`, `reproduce.py`, `render.py` and `summarize_results.py`. Supporting
files are pinned requirements, synthetic tests, the frozen input ZIP/design,
execution fingerprints, the measured CSV/JSON ledgers, charts and reports.
The only navigation changes after the initial eight files are the two canonical
registries. `.gitattributes` preserves fingerprinted LF source/data files and
binary ZIP/PNG bytes across Windows checkouts.

## Regression tests added/updated

39 research tests exercise causal prefixes/future mutations, same-day rejection,
listing admission, identity/account PnL reconciliation, gap and intrabar stops,
partial TP, monotonic trailing, rotation priority, cooldown/reentry, no averaging
down, delayed entries, exposure limits, bankruptcy, calendar annualization,
fold/cash accounting, parameter budgets, selection isolation, and immutable
future paper observations. Tests use synthetic fixtures; they are not evidence
of profitable market performance.

The earlier 23 objectives tests also pass. Navigation/source checks add another
14 passes: five script-registry tests, six source JSON tests and three output
registry field tests. Exact commands and tool outputs are in `test_results.json`
and the superseding research-suite record `final_research_test_results.json`:
**76 tests passed**. The unrelated legacy output-registry enum suite is not
claimed as passing or repaired by this work.

## Forbidden old path checked

- No old Research OS scalar score, model-held-asset wallet shortcut, exchange
  leverage setting or precomputed strategy return series is used by this engine.
- A search of the new Python files for old score/model exposure fields, order
  clients, full-refresh and publish-existing paths returned no matches.
- A branch diff of `app.py`, `data/`, `outputs/`, `scripts/execution/`,
  `automation/`, production truth/export/path contracts and master state is empty.
- No refresh, Pi command, authority snapshot edit, merge, deploy or live order.

## Validation commands/results

The executable reproduction commands are in README.md. The accepted market run
uses `python research/causal_search_20260926/run.py --cache scratch/causal_search_post_exit_cache`.
The final evidence is recorded separately to prevent unit tests from being
misrepresented as completed market replays:

- `results/implementation_freeze.json`: pre-run hashes and exact implementation
  commit; checked by the post-run verifier.
- `results/verification.json`: full budget counts, fold chronology, quantity /
  price / fee / funding accounting, daily equity and log-growth reconciliation,
  asset-per-episode identity, top-three-trade omission and fail-closed gates.
- `results/reproducibility_verification.json`: core-file comparison of a
  second OOS/stress/neighbor/audit replay and 54 fresh grid-scenario spot checks.
  All files except the order-normalized validation grid require identical bytes;
  that table requires exactly equal values. This does not claim that the full
  grid was computed from scratch twice.
- `results/expanded_audits.json`: actual prefix/future-mutation runs and concrete
  fill lineage checks for all 18 policies, including any result above 150%.
- `results/development_high_return_audits.json`: separate 2020 replay, accounting,
  prefix and future-perturbation audits for each selected development result
  above 150%, without selecting or tuning new parameters.
- `results/evaluation/objectives_screening.json`: all objectives gate outcomes
  bound to code, inputs, parameters, metrics and evidence.
- `paper/forward_seal.json`: prospective nominees and immutable source hashes;
  no fabricated future observations.

The initial serial startup was also stopped solely to parallelize six independent
partitions. The three interrupted starts, the entry-delay and post-exit reentry
corrections, and the completed but invalid scalar-interface run are retained
under `attempts/`; none changed parameter budgets after seeing results.

## Commit message / commit hash

The requested initial eight files were committed as
`bed0f0fe6c4266839ed1e1af5cd2a247e9e7004d` with message
`research: replace objectives with gated robust and aggressive Pareto evaluation`.
Subsequent implementation commits and their paths are in `COMMITS.json`.
The final evidence commit hash and verified remote branch are provided in the
task handoff, since a commit cannot contain its own hash without changing it.

Research branch: `codex/causal-pareto-research-20260926`.
Remote: `https://github.com/marek3993/trendatlas-crypto.git`.
