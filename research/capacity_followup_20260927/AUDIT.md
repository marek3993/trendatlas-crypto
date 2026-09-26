# Audit — capacity follow-up

Class **B + D** (data/execution contract and strategy math), research only. Source commit `f5ecbfd1a35dec62a4482cd1a1aa5181e6790551`; isolated worktree `C:/Users/benda/Desktop/ta_capacity_followup`; branch `codex/capacity-followup-20260927`.

## FILES READ

Repository authority read from the original read-only checkout `C:/Users/benda/Desktop/market_regime_v1` in required order before work: `source_of_truth/README.md`, `source_of_truth/master_state.md`, `source_of_truth/chat_roles.md`, `source_of_truth/project_truth.json`, `source_of_truth/export_contract.json`, `source_of_truth/paths_registry.json`, `source_of_truth/current_issues.md`, `canonical/script_registry.json`, `canonical/output_registry.json`, `canonical/registry_workflow.md`. Also `.github/workflows/app_refresh.yml` (no push trigger; no workflow was dispatched), `AGENTS.md` and `source_of_truth/research_objectives_contract.json`. Large registries were inspected for authority/production/semantic fields; their exports are not research performance inputs.

Ancestor implementation read: `research/new_strategy_20260926/contract.json`, `common.py`, `market.py`, `signals.py`, `ledger.py`, `evaluate.py`, `designer.py`, `run.py`; public archive ZIP/checksum evidence from `archive_evidence.zip`. Only the ancestor **metric function** is imported by the new ledger; the ancestor simulator is called only by the parity regression test. No saved ancestor CAGR or paper equity is supplied to selection, proposer or evaluation. Parent source/contract hashes are in the evaluator freeze.

All new source files and generated evidence in this research directory were inspected by direct reads, tests or the independent audit. Market source records are identified individually by URL/key/checksum in `acquisition.json` and `identity_acquisition.json`; complete archive census XML is in `indexes.zip`. Identity and delisting source URLs are in `identity_events.json` and `venue_notices.json`. DeepSeek official pricing evidence is in `deepseek_pricing_source.txt`; D evidence links and exact intervals are in `perpetual_data_gate.json`.

## SOURCE OF TRUTH

Production authority remains the repository SSOT and Pi; this experiment creates no authority snapshot. The user explicitly restricted work to offline research and authorized result commit/push on a separate branch.

Research rules: `contract.json` with `protocol_freeze.json` (before acquisition and performance); engine/market identities: `engine_data_freeze.json` (before the current complete run; the failed first-row serialization attempt is separately preserved); chosen historical/forward configurations: `results/finalists_frozen.json` (before outer evaluation). Actual own-asset fills, cash and quantities: `results/replay_ledgers.part*.zip` (unchanged member hashes in `results/ledger_partitions.json`). Reported metrics: `results/aggregate.json` and per-fold `results/outer_folds.json`, computed afresh.

Data-quality comparison found144,090 complete daily/six-bar intraday observations and one close discrepancy: DOGEUSDT2021-10-28, relative0.00033356 (about3.34bp). Both published raw sources are retained; no result-driven price correction. Details: `data_quality.json`.

## Exact root cause

The previous capacity path rejected the entire replay when an intended order exceeded0.1% of one historical4h quote-volume at a fixed10,000 USD capital. It did not represent100 USD account scale or executable partial orders. Therefore a capacity rejection was not evidence that familyB had no alpha at the user's account size.

Historical archive inspection also identified ticker reuse and redenominations. A venue symbol alone is not sufficient identity across LUNA,BNX,SUN,DREP,COCOS,STRAX,QUICK,VIDT unit/token changes. Combining those histories would manufacture momentum and misinterpret quantity. This was corrected before computing any new strategy performance; thresholds, folds and parameter grids were not fitted to that check.

FamilyD additionally lacks complete versioned historical maintenance, liquidation and administrative evidence. Public mark/trade/funding archives and current authenticated margin brackets are different contracts. The latter cannot be used to fabricate historical short performance.

## Exact contract impact

All changes are additive in `research/capacity_followup_20260927/`. The ancestor and production strategies, dashboard, execution planner, Hyperliquid integration, account files, Pi timers and reconciliation are unchanged. No canonical production script/output registration is added for offline research.

One PIT universe ranks actual historical instrument epochs with365 observations, rolling30 liquidity and top10 membership. Known notices are publication-aware. Symbol reuse resets history and quantity; there are no aliases or synthetic successor returns. Observation dates are recorded distinctly from administrative dates; complete global administrative coverage is not falsely claimed. All12 ceased symbols in the preliminary eligible union have primary spot-cessation notices, plus epoch-change notices.

Five independent capitals, true partial fills and TTL, adverse next-executable4h open, fee/slippage/funding separation, no forced terminal exits, explicit dust failures. Successful annual folds compound real simulated USD NAV. After a failed chain, later years remain independently restarted diagnostics and never manufacture a complete CAGR. Spot USDT is modeled at USD par; fractional lots and10 USD minimum notional are conservative fixed assumptions, not live venue certification.

A/C remain archived, D is gated and E requires independent qualified families. DeepSeek proposes parameters only through strict JSON; it cannot change code/data/metric/evaluator. Development and outer evaluation are staged with no feedback. The main150–200%/35%/1.5/4 objective is unchanged and BTC SMA200 is a mandatory additional benchmark.

## Preserved implementation attempt

The first run calculated the first development candidate but failed serializing `numpy.bool_` before recording that row. No API call or outer replay had occurred. Its source, initial freeze and D coverage report are preserved in `attempts/before_serialization_and_funding_coverage_fix.zip`. The repeat changes only JSON scalar conversion and D coverage diagnostics for millisecond timestamps/variable funding intervals. Parameters, folds, prices, cost model and selection rules are unchanged. The completed budget is220 unique development rows; one first-candidate evaluation was technically repeated, explicitly recorded rather than hidden. Two regression tests cover these failures.

## Regression tests added

`test_followup.py`: protocol hash, partial entry/exit, TTL, target cancellation, proportional cash funding, per-fill participation, own-asset return identity, two-asset NAV and episode attribution, fee reconciliation, no missing/zero-ranked asset, new listing warmup, identity-epoch reset/prefix invariance, notice exclusion before liquidity rank, delay including initial order, D+1, dust retention, no same-day lookahead, future-ledger invariance, cost stress, no short/leverage in spot, strict JSON/enum types, OOS proposer rejection, deterministic fallback fairness, positive drawdown penalty, benchmark noninferiority, ancestor-kernel parity under nonbinding capacity.

`audit.py`: frozen hashes, real market prefix invariance across the complete permitted grid, every recorded fill's latency/participation/price, order quantity/average-price reconciliation, development quotas, API payload whitelist, forbidden paths, production/ancestor diff. `verify_saved.py`: repeat18 selected real-data replays across100 and1m USD and all cost/delay variants with exact metric tolerance, including expected safe failures.

## Forbidden old path checked

No BASE/synthetic return input, no other-asset return attribution, no paper/model equity as account PnL, no same-day filtering of an already-earned return, no unavailable-asset zero fill into rank, no current-survivor universe, no positive reward for worse drawdown. The only parent runtime dependency is pure metric aggregation over the new actual ledger; parity test use of the old simulator is separate from research results. No production order/account endpoint or exchange secret loader is imported.

## Validation commands/results

Commands are in README. Unit output: `test_results.txt`; independent evidence audit: `validation.json`; real-data reproduction: `reproduction_check.json`; calculation completion/budget: `results/run_completed.json`; D coverage gate: `perpetual_data_gate.json`; decision gates: `decision.json`. Generated results are authorized by the user's explicit request to run calculations and commit the results; nothing under root `outputs/` or `data/` is touched.

## Exact files changed / git add

The exhaustive path list is `GIT_ADD.txt`; `artifact_manifest.json` records SHA256 for the deliverable files (excluding its own hash). All paths are under the new research directory. Stage exactly:

```powershell
git add -f --pathspec-from-file=research/capacity_followup_20260927/GIT_ADD.txt
git diff --cached --check
git diff --cached --name-only
```

## Commit message

`research: replay capacity follow-up with PIT identities and bounded DeepSeek evolution`

## Commit hash

The delivering commit is reported in the final response and can be resolved with `git log -1 --format=%H -- research/capacity_followup_20260927`. Its own hash cannot be embedded into itself. Until the commit succeeds, no commit is claimed by this document. No merge/deploy is authorized.
