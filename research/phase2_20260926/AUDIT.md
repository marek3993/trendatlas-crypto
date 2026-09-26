# Phase 2 audit and handoff

Classification: **D (strategy math), B (research data contract)**. Source addendum
was written and validated before implementation. Production authority unchanged.

## FILES READ

The required truth read order was followed: `source_of_truth/README.md`,
`master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`,
`paths_registry.json`, `current_issues.md`, then `canonical/script_registry.json`,
`output_registry.json`, `registry_workflow.md`. Also read `AGENTS.md` and the
explicit user research instructions.

Concrete research files read: `source_of_truth/research_objectives_contract.json`,
`scripts/research_objectives.py`, phase-1 `pre_registration.json`, `engine.py`,
`run.py`, `finalize.py`, `render.py`, `test_engine.py`, `AUDIT.md`,
`results/results.json`, `results/walk_forward_choices.json`, legacy equity/event
exports and input bundle. Inspected `.gitattributes` and workflow triggers before
the authorized research-branch push. New source/runner/test/audit/report files and
their actual artifacts were inspected throughout implementation.

## SOURCE OF TRUTH

- `source_of_truth/research_objectives_contract.json`: unchanged user goals,
  feasibility-first Pareto, exposure caps, OOS/sealed and robustness gates.
- `source_of_truth/research_phase2_contract.json`: offline sequencing, same
  accounting/costs, diagnostic scope and distinct new strategy families.
- `research/phase2_20260926/diagnostic_freeze.json` and `search_freeze.json`:
  immutable experiment specifications, identities, input/code hashes and budgets.
- Research outputs are evidence, not production truth or wallet PnL.

## Exact root cause

The failed phase-1 signal frequently switched a daily momentum rank winner despite
longer lookbacks: median holding 2–3 days and roughly 33–36 flat-to-flat entries per
year in the diagnosed representatives. For robust Calmar, entries plus rotation
exits account for 35.54 of 40.10 annual turnover; resize contributes only 1.35.
Asset selection often lagged matched-period BTC, with BNB/ADA losses and TRX
concentration. Costs consumed 9.17% annual equity-normalized debits; eliminating
all costs still left 64.62% MDD. Bad regimes and repeated loss sequences persisted
across folds; protective mechanisms did not reliably offset the rotation losses.
Timing sensitivity does not establish that earlier fills would fix the strategy.
Exact additive accounting and non-additive controlled counterfactuals are kept
separate in the diagnostic files and report.

The new families reduce turnover substantially and improve some risk/return
tradeoffs, but the 150% objective remains unmet. No active robust policy passed
25% MDD. The observed aggressive compromise is 19.0149% CAGR / 31.6066% MDD with
4.3961× turnover and maximum realized exposure 1.2937×. It fails the main Sharpe,
Calmar, fold, trade-concentration, neighbor and sealed requirements. It does not
replace the failed pre-OOS nominee.

## Exact contract impact

Only a research addendum was added. No target, absolute DD gate, cost convention,
live leverage setting, execution authority, production export or account field
changed. Universe, prior price file identities and same causal availability
assumptions are retained. Daily D+1 open is unavailable under the declared
D+1 00:00:01 publication assumption; D+2 is used and D+3 entries are stress tested.
The annual passive benchmark drift is disclosed separately from actively capped
strategy exposure. Equal-weight benchmark intraday DD is a conservative bound.

## Exact files changed / exact git add list

[GIT_ADD.txt](GIT_ADD.txt) is the complete path-by-path branch change list against
`9f3bed37ad47c5b952e170aea58671c66fb0c37f`, including each result artifact. It is also
the exact path list for staging with:

```powershell
git add --pathspec-from-file=research/phase2_20260926/GIT_ADD.txt
```

Changes are restricted to `.gitattributes`, the two canonical registry additions,
the phase-2 research contract and `research/phase2_20260926/`. The input archive is
reused from phase 1; no external data refresh was performed.

## Regression tests added/updated

Ten phase-2 tests cover default-engine equality, true no-resize holding, prefix
invariance after future price mutation, CASH, accounting/exposure sanity,
SMA-versus-EMA definition, monthly cadence, minimum holding versus risk exit,
all eight families with no protective overlay, and feasibility-first rejection
of a high-growth/high-drawdown candidate. The existing 39 engine/runner/paper tests
and 23 objectives tests remain unchanged and pass.

The preflight test-fixture correction (read-only pandas arrays) is preserved in
the first unrun freeze file; no market search ran against that superseded freeze.
A UTF-8 SVG reader correction affected report rendering only. No strategy patch,
new parameter grid, selection retry or failed market run was hidden after OOS.

## Forbidden old path checked

The branch diff against phase 1 is empty for `app.py`, `data/`, `outputs/`,
`scripts/execution/`, `automation/`, production truth/master/export/path contracts
and all of `research/causal_search_20260926/`. The original dirty local checkout
was not staged, edited or reset. The new worktree is isolated on its own branch.

No full-refresh, runtime authority command, Pi command, live order, merge or deploy
was run. The repository workflow has manual/schedule triggers, not a push trigger;
no workflow dispatch was requested. Reading those triggers did not change runtime.

## Validation commands/results

- `python -m unittest discover -s research/phase2_20260926 -p test_phase2.py -v`: **10 PASS**.
- `python -m unittest discover -s research/causal_search_20260926 -p test_*.py -v`: **39 PASS**.
- `python -m unittest tests.test_research_objectives tests.test_script_registry_required_fields tests.test_script_registry_paths_exist tests.test_source_of_truth_json_valid tests.test_output_registry_required_fields -v`: **37 PASS**.
- Total: **86 tests passed**. This is the scoped relevant suite, not an assertion
  that every unrelated legacy repository test was run.
- `diagnose.py run`: six benchmarks, all 18 legacy policies reproduced; 45
  predeclared ablation replays. `diagnostic_details.py`: holding/timing attribution
  and preserved-cooldown isolation check passed.
- `search.py run --workers 6`: 396 distinct partition/variant candidates,
  1,188 nominal/2×-cost/delayed historical grid scenarios, 84 OOS policies,
  504 folds and 252 neighbor replays. All normal, stress and neighbor outcomes
  retained, including CASH and losses. No adaptive grid extension.
- `audit.py`: every OOS event ledger independently reconciled; **984 actual
  prefix/future-perturbation probes**. Missing venue/PIT/sealed evidence stays false.
- `audit_high_lineage.py`: all **198** development/validation rows at or above
  150% audited, using **166 unique complete-window event replays** after identical
  cap/variant/window deduplication. These are not 198 OOS winners.
- `reproduce.py`: **427 bitwise-identical files**, plus **54 fresh full-history
  scenario checks**. Not a second exhaustive grid search; scope recorded precisely.
- All frozen runtime dependency bytes, including legacy spec and serialization
  helper, matched the complete pre-run git commit `740f5ccd` (12 files checked).
- Equity/Pareto PNG and SVG artifacts were rendered from results and visually
  inspected. Tables use event MDD; the equity chart DD panel uses daily closes.
- `git diff --check`: the scoped attribute recognizes preserved CRLF as line
  endings while retaining trailing-space checks. An initial staged check flagged
  those CR characters; no frozen evidence bytes were rewritten. Final staged
  validation and remote HEAD verification are recorded in the task handoff.

Exact executable reproduction commands are in [README.md](README.md) and
[RESULTS.md](RESULTS.md). `execution_receipt.json` and `artifact_manifest.json`
bind completed outputs; final commit history is in `COMMITS.json`.

## Commit message / commit hash

Research branch: `codex/phase2-family-research-20260926`.
Remote: `https://github.com/marek3993/trendatlas-crypto.git`.

Pre-run commits:
- `82f1980d`: `research: freeze phase-two benchmark and failure diagnosis protocol`.
- `4113418e`: `research: record baseline diagnosis and freeze eight new strategy families`.
- `740f5ccd`: `research: preserve exact hashed artifact bytes across checkouts`.

Final evidence commit message:
`research: complete phase-two benchmarks, new-family OOS and audited results`.
The final **commit hash** is supplied in the task handoff after commit and verified
remote push; a commit cannot include its own hash without changing its identity.
