# Phase 2 v2 evaluator correction and VPS activation

```
OLD_CYCLE_CHECKPOINTED=true
OLD_RESULTS_PRESERVED=true
V2_EVALUATOR_VALID=true
CONTINUOUS_WF_START=2020-01-01
CONTINUOUS_WF_END=2026-09-25
PRODUCTION_TRUE_CAGR=30.9986%
BTC_SMA200_TRUE_CAGR=34.2279%
OLD_BEST_CANDIDATE_TRUE_CAGR=UNDEFINED_INVALID_LUNA_HALT
OLD_BEST_WITHOUT_TOP3_TRADES=UNDEFINED_INVALID_LUNA_HALT
ACTIVE_EVOLUTION_V2=true
OUTER_OOS_LOCKED=true
FORWARD_2027_SEALED=true
```

These headline dates and reference CAGR describe the fully replayed **2,460-day**
reference curves, not a claim that the live chronological selector already
finished all 14 folds. At checkpoint D it completed 3 test
folds, with its stitched selected portfolio ending 2021-06-30.
This is simulated, previously seen development evidence with historical spot
proxies. No independent historical sealed OOS is claimed.

## Exact root cause

Classification **B/C/D**. V1 reset the book separately for four short validation
folds and averaged their annualized CAGR. Annualization amplified brief bull
segments, so the arithmetic average was not a portfolio's actual compounded
calendar CAGR. The runner also replaced undefined concentration with zero and
discarded dominant asset/episode identities. The valid Pareto front was empty;
a diagnostic fallback was not a qualified winner.

## SOURCE OF TRUTH / exact contract impact

`source_of_truth/phase2_v2_contract.json` is a new user-authorized research
contract. Development is May5 2018–Sep25 2026, including previously seen
2024–2025, explicitly losing any independent historical OOS claim **for v2**.
There is no historical outer OOS for this new experiment. Sep26 2026 is excluded.
Prospective Sep27 2026–Sep26 2027 stays LOCKED; forward 2027 stays SEALED.
Legacy contracts and frozen manifests were not rewritten.

Fourteen adjacent half-year development test folds cover 2020–2026. Each origin
has a rolling 365-day past-only training window with two chronological inner
validation halves. Mutation context and candidate selection precede the test;
selection is durably frozen before its replay. Cash, quantity and whole position
episodes carry across test folds. Repeated retrospective development and LLM
prior knowledge do not establish independent historical predictive validity.

One causal daily equity curve supplies compounded calendar CAGR and close
peak-to-trough MDD. Each fold has its own diagnostics from the same carried book.
All references use prior-close targets and next-open fills, 10bps fee plus 10bps
slippage, 1.25x maximum target gross and explicit 10% annual borrowing debits.
2x costs, an extra open of entry delay, omitted best day and omitted three entire
positive closed episodes remain available. Open episodes remain OPEN; missing
concentration and insufficient top-three episodes remain null/inconclusive.

Production's historical BASE is a composite sleeve, not a ticker. All 400 BASE
rows had matching BASE regime and no challenger in the underlying same-date
phase67j decision export. It expands the held constituent; 69 underlying CASH
rows contribute zero risky exposure. Original target/exposure and resolution
source are preserved. No existing PnL curve supplies the recalculated returns.
Production files were not regenerated or edited.

## Reference results

| Reference | CAGR | MDD | Sharpe | Calmar | 2x costs CAGR | Delayed CAGR | Without best day | Without top3 closed episodes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_BUY_HOLD | 44.0144% | 76.6293% | 0.9126 | 0.5744 | 43.9717% | 43.9980% | 40.2488% | UNDEFINED |
| BTC_HALF | 25.2938% | 48.9932% | 0.8999 | 0.5163 | 24.7945% | 25.2867% | 23.5720% | UNDEFINED |
| BTC_SMA100 | 44.8661% | 39.1293% | 1.0923 | 1.1466 | 41.0040% | 42.3186% | 41.0783% | -2.3588% |
| BTC_SMA200 | 34.2279% | 64.7056% | 0.9003 | 0.5290 | 31.9751% | 34.7561% | 30.7182% | -6.0264% |
| CASH | 0.0000% | 0.0000% | UNDEFINED | UNDEFINED | 0.0000% | 0.0000% | 0.0000% | UNDEFINED |
| OLD_BEST | UNDEFINED | UNDEFINED | UNDEFINED | UNDEFINED | UNDEFINED | UNDEFINED | UNDEFINED | UNDEFINED |
| PRODUCTION | 30.9986% | 41.5240% | 0.8011 | 0.7465 | 20.1132% | 11.7614% | 23.7320% | 8.7741% |

Exact fold metrics, costs, turnover, concentration and episode identities live
in the isolated VPS reference JSON files. `reference-evidence.json` preserves
headline and per-fold read-back locally. CASH and buy-and-hold legitimately
have undefined top-three closed episode diagnostics; they are never filled with
zero.

The legacy best gene hash
`53e35c0943230832c56c97f57a07ff6e70caf3ae3aebe9db73d95ab8e4d6c87e`
is invalid over the full requested horizon: original LUNA is still held at
May13 2022, with no executable/mark price across its venue halt and identity
change. Its full-horizon CAGR and top-three-removal CAGR are undefined. We did
not invent a liquidation or produce a shorter flattering CAGR.

## Legacy preservation and checkpoint/resume

The drained old cycle `phase2_dev_20261005_002605` was marked
`LEGACY_METHODOLOGICALLY_INCOMPARABLE`. Both its development and broker timers
are disabled. The collector was unchanged. All **39,996 candidates and 639,936
completed evaluations** were preserved, with full SQLite backup:
`/var/lib/trendatlas-research-development/legacy-checkpoints/20261005T171413Z`.

Candidate rows SHA256:
`fef388998cd229c7fbea0242723c8a706c088dbf478d2ba9645a1f25d25c01b3`.
Evaluation rows SHA256:
`28e64c3ddae9a0f8d89f34a1ce85e57b7a738dab0e727a372f086166f683b06f`.
Both matched before/after retirement and the backup. Audit chain and SQLite
integrity passed.

A VPS-only NumPy cooldown-key serialization failure was corrected with native
integer keys. The serialization-only migration retained the same v2 cycle,
backed up SQLite, proved exact equality of **all nine** existing completed
results and unchanged decompressed inputs, then recorded the old/new bindings
in an append-only event. It changed no candidate or evaluation row.

## Real VPS verification

Cycle: `phase2_v2_20261005T175209Z_47661557`.
Deployed evaluator release:
`/opt/trendatlas-research/phase2-v2/releases/91237299dee6880e`.
State: `/var/lib/trendatlas-research-v2`.
Inputs: `/var/lib/trendatlas-research-v2-inputs/91237299dee6880e`.

| Checkpoint UTC | Completed trial records | Stage |
|---|---:|---|
| 2026-10-05T18:00:40.976347+00:00 | 18 | [0, 0, 'WAITING'] |
| 2026-10-05T18:01:42.234612+00:00 | 52 | [0, 1, 'ADVANCED'] |
| 2026-10-05T18:11:06.041332+00:00 | 291 | [2, 5, 'WAITING'] |
| 2026-10-05T18:19:00.240594+00:00 | 501 | [3, 3, 'WAITING'] |

These are continuous training trial records per candidate/origin/stress, not
v1 short-fold evaluation counts. Checkpoint D includes 497 fully priced results
and 4 terminal invalid trial records. Systemd invocation changes and successful
terminal runs prove automatic continuation. Generation 0 → 1 → 2 and later
origins ran without a manually invoked production or research worker run.
Inherited memberships retain two survivors; their completed same-origin
results are reused. Gene duplicates and evaluation-key duplicates both equal
zero; SQLite and append-only hash-chain checks pass. Invalid market/entry trials
are terminal rejected records, never automatically repeated or promoted.

The worker is offline; production roots/credentials are inaccessible. The broker
can see only the mailbox, not the frozen market bundle or account state.
Versioned standalone dispatch guards skip empty broker work and finished
walk-forward jobs. Their installation changed no evaluator binding and did not
restart a service. A versioned read-only audit helper includes arm attrition and
a coherent SQLite read snapshot; engine code remains frozen.
The committed market/compact sources trim trailing empty lines only; that
whitespace cleanup was not redeployed into the frozen evaluator release.

## DeepSeek usage and mutation quality

First successful request: 2026-10-05T18:00:24.718907+00:00.
Provider request ID: `a7647393-3919-4c1b-82ed-c01a3da77c5a`.
Wire input upper bound 5623 UTF-8 bytes; actual input
1951 tokens, output 576, total 2527; no retry, no cache hit.
The four proposed mutations were schema-valid, locally unique and registered
with parent lineage. Subsequent execution validity is audited separately.
Relative to the user-supplied dashboard average 10,011,394 / 587 ≈ 17,055
 tokens/request, this request is approximately 85.2% smaller. That dashboard
period is not newly reconciled to a Phase 2-only invoice in this task.

At the 18:11 snapshot: 8 provider calls, 20241 reported tokens. At checkpoint D:
16 provider calls, 41148 reported tokens; every
attempt keeps raw usage/request ID. Estimated tariff cost is explicitly a
conservative documented estimate, not an independently verified invoice.
Input is capped at 6,500 bytes and output at 1,500 tokens. Entire ledgers,
historical equity arrays and global seen-hash lists are absent from prompts.
Content-cache and uncertain-call no-retry behavior have regression tests.

The archived Oct3 quality report had zero qualified DeepSeek candidates before
and after compact prompting under v1. Its short-fold CAGR is methodologically
incomparable to v2; we do not claim numerical quality improvement across engines.
V2 tracks separate AI/deterministic provenance and same-origin parent deltas.
At origin2 in the archived 18:11 snapshot, DeepSeek had 19 fully priced candidates,
17 eligible, mean training CAGR 24.74%, mean parent delta −5.86pp; deterministic
had 22, 20 eligible, mean CAGR 26.12%, delta −1.78pp. These small unequal samples
provide **no proven DeepSeek advantage**. They are training evidence, not the
stitched selected portfolio or prospective OOS. Raw attrition and lineage are in
`final-snapshot.json` and `verification.json`.

Public acquisition used only authorized date bounds of the read-only
[Binance Kline endpoint](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints).
The new bundle combines historical public spot bars, exact public 2018/2026
quote volume and explicitly flagged local volume*close proxy rows. A corrupt
KLAY timestamp series from 1970 was excluded. Missing observations stay missing;
venue completeness/survivorship independence is not certified.

## Regression test added/updated

`tests/test_phase2_v2.py`: **16 tests passed on Windows and against the deployed
VPS evaluator plus its standalone dispatch guard**. Covers geometric calendar
CAGR, contiguous book/fold carry, whole closed-episode removal, named log/PnL
attribution, next-open and delayed entry, future prefix invariance, nulls,
protected date parsing, benchmark cost parity, native ATR-stop JSON checkpoint,
resume/binding rejection, immutable records, inherited survivors, duplicate
prevention, content cache, ambiguous-request no-retry and empty dispatch.

## Forbidden old path checked

Git scope excludes `app.py`, `scripts/production`, `scripts/execution`, generated
`outputs/`, existing `data/`, v1 engine/contract, and old frozen manifests.
No production systemd unit was controlled, no wallet/order/dashboard/LeadPilot
state changed, and Pi was neither contacted nor enabled. Only research units,
new research contracts, registries and audit documents changed. The prior
production incident heartbeat was not modified in this task.

## Validation commands/results

- `python -m research.phase2_v2.contract`: READY; authorized partition/folds valid.
- `python -m unittest tests.test_phase2_v2 -q`: 16/16 PASS, Windows and VPS.
- `python -m compileall -q research/phase2_v2`: PASS.
- changed JSON registries parsed successfully; `git diff --check`: PASS.
- legacy SQLite quick/foreign-key/hash-chain and row-preservation checks: PASS.
- v2 read-only audits: integrity ok, hash chain valid, zero duplicate keys/genes.
- automatic worker/broker invocation timestamps and counters: recorded in
  checkpoint A/B/C/D, the 18:11 snapshot and verification JSON.

## FILES READ

- `AGENTS.md`
- `source_of_truth/README.md`
- `source_of_truth/master_state.md`
- `source_of_truth/chat_roles.md`
- `source_of_truth/project_truth.json`
- `source_of_truth/export_contract.json`
- `source_of_truth/paths_registry.json`
- `source_of_truth/current_issues.md`
- `canonical/script_registry.json`
- `canonical/output_registry.json`
- `canonical/registry_workflow.md`
- `source_of_truth/pi_codex_runtime_workflow.md`
- `source_of_truth/phase2_development_contract.json`
- `source_of_truth/phase2_broker_policy.json`
- `research/phase2_continuous/README.md`
- `research/phase2_continuous/engine.py`
- `research/phase2_continuous/runtime.py`
- `research/phase2_continuous/run.py`
- `research/phase2_continuous/broker.py`
- `research/phase2_continuous/compact.py`
- `research/phase2_audit_20261003/phase2_deploy_optimization_20261003.py`
- `research/phase2_audit_20261003/phase2_quality_after_20261003.json`
- `tests/test_phase2_continuous.py`
- `scripts/production/strategy_adapters/phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter.py`
- `scripts/production/strategy_adapters/phase68g_btc_persistence_10d_early_risk_075_adapter.py`
- `scripts/production/strategy_adapters/phase68g_66g_1p25x_candidate_adapter.py`
- `scripts/dev_only_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate.py`
- `scripts/phase66g_production_candidate_live.py`
- `scripts/phase66e_probation_governance.py`
- `scripts/phase67j_final_narrow_validation_pack.py`
- `scripts/phase63_btc_participation_overlay.py`
- `scripts/phase68h_dynamic_leverage_ladder_candidate.py`
- `deploy/systemd/trendatlas-phase2-development.timer`
- `deploy/systemd/trendatlas-phase2-broker.timer`
- New v2 contract, source modules and tests written/read during validation.
- Development-only slices of local `data/ohlcv` and `data/ohlcv_phase67_top100`,
  canonical production target CSV, phase67j decision paper and selected legacy
  phase63/phase66g papers; target-only metadata from
  `C:/Users/benda/Desktop/ta_vps_prod/outputs/production/current_strategy_timeseries.csv`.
- VPS research service/timer definitions, SQLite/mailbox/status, original frozen
  manifest **split metadata only**, authorized historical spot input, identity
  notices, and newly acquired development public data. No outer-result file or
  prospective price was opened.

## Exact files changed / exact git add list

See `GIT_ADD.txt`, one exact repository-relative file per line. Generated input
archives, model target CSVs and SQLite databases are not committed. The audit
receipts are explicitly authorized research evidence, outside outputs/data.

## Commit message

`Fix Phase 2 v2 calendar evaluator and launch isolated nested evolution`

## Commit hash

Recorded in the final chat response after this report is committed. No push.
