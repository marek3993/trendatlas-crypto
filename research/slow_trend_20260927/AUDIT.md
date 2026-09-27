# Audit — slow trend research

Classification: **B (data/runtime contract) + D (strategy mathematics)**. Scope is offline research only. This document must be read together with the machine-verifiable `audit_results.json`, `reproduction_check.json`, `data_audit.json`, staged freezes and preserved attempts. It does not certify a live trading venue.

## SOURCE OF TRUTH

1. User instructions and source commit `58e308315d03a4561d53bbbd4019f7392f66e662` on `codex/capacity-followup-20260927`.
2. Repository SSOT and canonical registries preserve production authority; they are not changed.
3. `contract.json` + `protocol_freeze.json`: hypotheses, asset identity/PIT contract, four temporal partitions, capital, execution/cost/margin assumptions, budget, Pareto procedure and pass criteria fixed before performance computation.
4. `candidate_panel_frozen.json`:184 fixed candidates and identical10-candidate initial populations for each arm/family. No B/C mutations.
5. `data_freeze.json`: exact input hashes; own-asset observations only. Existing price bundles are reused, existing performance/equity/CAGR tables are not.
6. `engine_freeze.json`: implementation and data manifest hashes after documented correctness repairs, still before validation/OOS.
7. `results/validation_nominees_frozen.json` and `results/finalists_frozen.json`: nomination boundaries. DeepSeek cannot read validation, OOS or forward. Forward2026 is not opened. Historic2023–2025 was previously researched and is not claimed pristine.
8. Saved order/fill/quantity/cash/funding evidence and `results/complete_comparison.csv`, then REPORT.md and figures. Reports cannot feed parameter mutation.

## Exact root causes and contract impact

The predecessor's execution gate could reject the whole account when a remainder below a conservative10USD spot floor could not be flattened at an artificial annual boundary. Its D gate required complete historical margin brackets, so missing certification blocked even clearly marked low-exposure proxy computation. These are unsuitable for this new request. The predecessor remains immutable; its stored results are neither rewritten nor reused as performance inputs.

The new ledger retains actual quantities, residual orders and dollar MTM through calendar years; TTL cancels the order, not the position. Dust alone does not invalidate the book. Material inability to exit and missing held prices remain explicit reliability failures. Target lot precision is a model assumption and has a coarse-quantity sensitivity; it is not represented as historical Hyperliquid certification.

The D track now separates **venue-certified NOT_AVAILABLE** from **CONSERVATIVE_PROXY actually computed**. It uses exact-symbol Binance USD-M trade/mark/funding with signed position accounting. Mark gaps can use the same perp trade price under explicit adverse mark scenarios; no spot-price surrogate. Maintenance5/10/20% and adverse mark0/1/3% are assumptions, not fabricated historical brackets. Current Hyperliquid minimum/fees/precision and liquidation facts have primary-source citations in sources.json. No Binance spot rule is attributed to Hyperliquid; the10USD Hyperliquid minimum is independently documented.

Three implementation problems were found during development, before validation/OOS, and preserved rather than silently overwritten:

- `attempts/pre_causal_risk_fix`: automatic perp gross reduction could size from the current open and fill at that same open; a derived maximum of future target weights could influence the cap. Fixed by an explicit configuration gross limit, published i−2 bar risk observations, separately timestamped risk intents and latency-safe margin exit. No protective fill is invented inside a candle.
- `attempts/pre_delay_audit_fix`: the one-bar-later stress originally delayed strategy and margin orders but not automatic gross-risk orders. It now delays those signals too. Pure funding features were cached without changing nominal values.
- `attempts/pre_H_schema_fix`: the shared enum exposed equal-notional weights to H, contrary to the frozen H inverse-vol/equal-risk rule. The validator now rejects equal-notional H. One prior API proposal was discarded; original dev-only H hypotheses were revalidated, with deterministic replacement and no additional H API charge. Original API payload and new reproduction verification payload are both retained; the latter is explicitly not claimed to have been sent.

The first attempt made 9 real calls (F/G/H). Later interrupted attempts made no new calls. The complete run made 3 new D calls, reaching the global 12-call ceiling: 19,159 tokens, estimated $0.004544922, 43 accepted and 5 rejected proposals. F/G replay checks exact development payloads. H recovery never accesses validation/OOS and retains rejected proposals/reasons. All final offline reproduction payloads must match exactly. Technical repeats do not add candidate budget slots or permit new parameter ranges.

## FILES READ

Truth-first sequence, read before edits:

```text
AGENTS.md
source_of_truth/README.md
source_of_truth/master_state.md
source_of_truth/chat_roles.md
source_of_truth/project_truth.json
source_of_truth/export_contract.json
source_of_truth/paths_registry.json
source_of_truth/current_issues.md
canonical/script_registry.json
canonical/output_registry.json
canonical/registry_workflow.md
```

Repository implementation/evidence inspected or directly consumed as raw input:

```text
.gitignore
.github/workflows/app_refresh.yml (trigger search; no push deployment trigger)
research/capacity_followup_20260927/README.md
research/capacity_followup_20260927/contract.json
research/capacity_followup_20260927/common.py
research/capacity_followup_20260927/market.py
research/capacity_followup_20260927/identity.py
research/capacity_followup_20260927/data_prepare.py
research/capacity_followup_20260927/designer.py
research/capacity_followup_20260927/evaluate.py
research/capacity_followup_20260927/perpetual_gate.py
research/capacity_followup_20260927/spot_daily.zip
research/capacity_followup_20260927/spot_4h.zip
research/capacity_followup_20260927/perp_trade.zip
research/capacity_followup_20260927/perp_mark.zip
research/capacity_followup_20260927/funding.zip
research/capacity_followup_20260927/identity_events.json
research/capacity_followup_20260927/venue_notices.json
research/new_strategy_20260926/ledger.py (source inspection)
research/new_strategy_20260926/archive_evidence.zip (only raw archive members)
```

New source, configuration, test and result files are listed exactly in `GIT_ADD.txt`; `artifact_manifest.json` gives sizes and SHA256. External facts are primary-source links in `sources.json`; acquired Binance archives carry checksum records in `*_acquisition.json`. Production dotenv, exchange credentials and exchange account state were not read. Only the specifically authorized DeepSeek environment key is used for model calls and secret-leak checking, never stored.

## Forbidden old path control

- No BASE/synthetic return stream, carried return from another asset, stored model/paper equity, or old CAGR input.
- No current-survivor list: eligibility is derived from the full historical archived census and trailing observations; ticker epochs are separate.
- Unavailable prices remain unavailable. They do not become zero-return ranking candidates. Stale held valuation is flagged and does not authorize fills.
- MDD is a positive loss magnitude; Pareto minimizes it. Calmar=CAGR/MDD, never a sign-reversed bonus.
- Perp PnL/funding use signed quantity and the own perp instrument, not spot prices. Long/short episodes are distinct.
- Signals use completed prices and explicit availability; fills require actual own instrument open and positive actual bar volume. Primary accounting is cash plus own quantities; funding is separate signed cashflow. The source engine extends the archaeology asset-resolved invariant for multiasset partial fills and derivatives; no old strategy return generator is called.
- DeepSeek JSON is schema-validated with strict types, duplicate-key and nonfinite rejection. No arbitrary code eval/exec, tools or evaluator changes. API keys and authorization headers are absent from recorded payloads.
- No runtime registrations, production outputs/data writes, authority snapshots, account queries, order endpoint, scheduler command, Pi connection, merge or deployment.

## Regression tests and independent validation

`test_research.py` verifies own-asset attribution; missing-price no-fill; earliest signal/latency and delayed fill; partial fills/TTL; retained and marked dust; no spot shorts; signed funding and doubled debits; adverse margin and publication-safe exit; published gross-risk intents and their delayed stress; explicit cap independence from future targets; full-episode account reconciliation; coarse quantity residual; schema/evaluator protection including H restriction; missing cash slots; negative-trend CASH; breakout using prior highs; prefix causality; archived B/C exclusion.

`audit.py` independently reconstructs cash and quantities from saved fills, then matches NAV at every recorded4h row for primary finalists/stresses/benchmarks. It verifies signal availability, actual own open, observed volume, participation, entire episode log attribution, input/engine hashes, max5 PIT membership, historical warmup, no missing-price membership, strict designer development boundary, and real prefix recomputation of finalist/indicator targets.

`verify_saved.py` recomputes every primary frozen finalist and both benchmarks without API calls. It also recomputes contextual2022–2025 benchmarks from prices, never reads the old~30%/33% as an input.

Completed validation:

- 917 unique evaluations in the completed run, 194 primary OOS rows, 15 frozen diagnostic finalists. These counts exclude the preserved aborted technical attempts; they are not a claim of only 917 physical computations across all attempts.
- 18 regression tests passed. All 32 real truncated-input prefix causality checks passed.
- Independent cash/quantity/own-mark reconstruction passed for 80 detailed books and 3,266 fills. Maximum NAV difference was $5.033e-10; maximum independent funding difference was $5.000e-13. Delayed fills were checked against the second actually executable instrument bar, not just a nominal clock offset.
- All 17 independent primary replays (15 finalists and two benchmarks) matched exactly: 38 numeric metrics each, maximum difference zero, zero new API calls.
- No development/validation-qualified base exists; no stop, trailing, partial-TP or ensemble was promoted to compensate for failed alpha. All four families are REJECT for the requested target. Forward 2026 remains unopened.
- The prespecified panel contains a descriptive 46.43% CAGR / 23.35% MDD BTC momentum row and a 64.94% / 33.58% BTC breakout row. They failed development/validation qualification and were never frozen finalists. Reporting them does not promote them after OOS. Their unplanned cost/delay/capacity/neighbor stresses remain explicitly NOT_RUN; no robustness claim is made.
- Equity, annual-fold and risk/return images were visually checked. `release_checks.py` verifies freeze timing, unchanged engine/data hashes, the research-only diff, API event boundaries and absence of the authorized API key from plain and compressed evidence. It does not print the key.

Validation commands (exact outcomes are in their saved output/JSON files):

```powershell
python -m unittest discover -s research/slow_trend_20260927 -p test_research.py -v
python research/slow_trend_20260927/run.py --continue-proposals research/slow_trend_20260927/attempts/pre_delay_audit_fix/results/designer_events.jsonl
python research/slow_trend_20260927/audit.py
python research/slow_trend_20260927/verify_saved.py
python research/slow_trend_20260927/extra_outputs.py
python research/slow_trend_20260927/render.py
python research/slow_trend_20260927/release_checks.py
python research/slow_trend_20260927/package.py
git diff --check
git diff --cached --name-only
```

## Files changed, exact git add list, commit

All new files are confined to `research/slow_trend_20260927/`. Ancestor research and production files have no changes. `GIT_ADD.txt` contains each exact repository-relative path, including explicitly authorized research-generated evidence and split ZIPs; no production-generated outputs/data are staged.

The directory-local `.gitattributes` disables line-ending normalization only for this new research directory, preserving frozen SHA256 bytes across Git checkouts. The complete `results/ledgers.zip` is ignored locally; committed partitions preserve every member exactly and are restored using the documented command. This changes no production Git attribute or runtime contract.

Native CRLF evidence is preserved byte-for-byte. The first staged whitespace check treated those carriage returns as trailing whitespace; the directory-local whitespace attribute now explicitly recognizes CRLF while retaining the ordinary trailing-blank, final-blank and space-before-tab checks. Matplotlib SVG trailing layout spaces were removed without changing its paths or scientific values; the renderer includes that formatting step. Frozen inputs/engine/results were not reformatted. The repeated check and staged Git-blob SHA256 verification passed.

Exact staging command (manifest contains literal paths, not globs):

```powershell
git add -f --pathspec-from-file=research/slow_trend_20260927/GIT_ADD.txt
```

Commit message: `research: evaluate frozen slow trend families with causal residual and perp proxy accounting`

Commit hash is reported with the final handoff and can be obtained with `git rev-parse HEAD` on the research branch. The hash cannot be embedded in its own committed contents. No merge or deployment is part of this task.

## Material limits

This is a frozen historical research comparison, not an account or execution certificate. Venue history, historical maintenance/lot/fee tables and administrative listings are incomplete. OHLC-based slippage/participation cannot reproduce order-book queue priority. USDT/USD1:1 and zero cash yield are assumptions. Portfolio intrabar extremes are conservative simultaneous bounds. Open terminal positions remain open and valued. Closed-episode removal does not reallocate the cash that an alternative untraded portfolio would have had. Historical OOS was previously explored; forward2026 remains unopened. No failed strategy is promoted or blended to hide its weakness.
