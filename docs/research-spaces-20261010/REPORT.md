# Automatic successor research spaces — 2026-10-10

Implemented and deployed to `/opt/trendatlas-research/continuous/releases/77ed52a9aab5bce7` on the existing VPS. Research only. The tiny-space acceptance driver automatically exhausted one new configuration, froze space 2 and actually evaluated new candidates with the unchanged cost/position accounting engine. No operator supplied a successor, reset a registry or reopened an old experiment.

## Exact root cause

Classification **B/C/D**. The previous scheduler separated batch lifetime from daily budgets, but `planner.remaining()` still described only the original 54,880-point K grid. `ensure_request()` stopped at zero and `local_proposals()` could enumerate only that grid. `freeze_next()` had no state or transition for a successor research space, so full-space exhaustion ended in `IDLE_NO_AUTHORIZED_NOVEL_WORK`.

This is distinct from today's live wait: read-only preflight found 256 completed candidates, 64 closed batches, 33,612 unused original configurations, lifetime alpha index 1,700 and a genuinely exhausted daily compute/API allowance. We did not force live exhaustion or reset that allowance to demonstrate the feature.

## SOURCE OF TRUTH and exact contract impact

`source_of_truth/research_space_successor_v1.json` was written and validated before implementation. It prospectively extends `continuous_research_contract_v1.json`; all previous contracts and frozen runtime files remain byte-identical.

- Original K space is inherited as space 1, with global legacy dedup and outstanding work intact.
- A successor is constructed locally from completed valid **training AND validation** views: descending validation log growth, ascending drawdown, deterministic candidate-id tie break. Diagnostic results, significance and sealed data cannot influence construction.
- Existing envelopes are retained. Only `vol_target` uses step 0.005 over 0.06–0.24; `correlation_cap` uses step 0.05 over 0.30–0.90; `asset_weight_cap` uses step 0.025 over 0.10–0.25. Existing lookback/rebalance enums stay unchanged. The declared full refinement envelope has 824,915 configurations, including the original grid; the eligible frontier may end earlier.
- A chosen parent's center and immediate neighboring values define a Cartesian grid of at most 27 configurations. The first ranked eligible parent with globally unseen configurations seeds the successor. This deterministic construction is `LOCAL_RESULT_REFINEMENT`, never credited as an AI invention or a market discovery.
- `research_spaces`, `space_batches`, `space_ends` are append-only. A space freezes lineage, parent evidence, complete eligible-view digest/count, grid, novelty count, windows, event-frequency policy, contamination and lifetime statistical design before acceptance/backtests. Every new batch is linked to its frozen space before evaluation.
- Pending responses, open batches, unassigned proposals and unfinished scientific attempts prevent a space transition. A pending response yields `WAIT_PENDING_SPACE_REQUEST`. Empty eligible novelty yields `IDLE_NO_ELIGIBLE_NOVEL_FRONTIER`; missing valid feedback yields `IDLE_NO_VALID_TRAIN_VALIDATION_FEEDBACK`.
- AI retains its separate provenance and raw-response checks. Subsequent requests carry a compact frozen space descriptor and enums. Every pre-existing request, including the unpaid pending request, was checked for identical wire hashes at deployment.
- Shared 24 attempts/day, 6,500 input/1,500 output tokens, USD0.25/day, USD5/month and 128 candidate starts/day are unchanged. Reservations, retries, hypotheses, genes and scientific history are never reset. Global identities exclude space IDs, prose and lineage.
- The adapter widens only research K input validation. Lookbacks, signal/accounting/exit formulas, cost stress tests, identity quarantine and candidate-specific missing-price/LUNA invalidation are unchanged. All seen history remains adaptive development; conditional p-values and unverified temporal independence never confirm a trading candidate. Sealed dates remain inaccessible.

## Runtime evidence and practical limits

[Preflight](preflight.json), [deployment freeze](deployment.json), [first native audit](runtime-first.json), [later native audit](runtime-final.json), and [isolated native acceptance evidence](native-acceptance.json) are committed.

The native acceptance run used a synthetic market and a separate temporary ledger. Its provider replies are explicitly test fixtures; it made **no live paid AI calls**. The backtest engine itself was real. Automatic activations yielded:

| Activation | Frozen space | Unique completed | Completed backtests |
|---|---:|---:|---:|
| 1 | 1 | 1 | 6 |
| 2 | 2 | 2 | 11 |
| 3 | 2 | 3 | 16 |

Space 2 froze at **2026-10-10T08:54:07.388619Z**, before its first candidate reservation. Its hash is `3d6f1b2488e64398e4d927a3fbb66f3450979e45f7988919fd1c9cbd224a0684`. It had seven globally novel configurations and inherited alpha index 1,445. The first new candidate was `5fe2d591b1cd891855f3589003f5b1963956ad12dd06dea5a6d9796fe5d94c80`. Book hashes, calendar row counts, metrics, reconciled PnL and ordered freeze/reservation/completion events are in the acceptance evidence. The three candidate alpha positions were 1,445–1,447; 16 backtest computations are not 16 scientific tests.

The installed research services completed further automatic activations using the new entrypoint. Their actual live status remains **WAIT_DAILY_COMPUTE_BUDGET**, 256 unique candidates, 64 closed batches, space 1, 33,612 unused original configurations. Last actual backtest completion was **2026-10-10T00:41:26.080525Z**. API accounting remains 48 lifetime attempts, 24 today, zero attempts left today, USD0.16 daily and USD4.82 monthly monetary headroom under conservative reservations. The next daily allowance begins 2026-10-10T22:00:00Z (midnight Europe/Paris); normal timer activations will resume prepared research then, subject to the unchanged guards. We do not claim new live computation after deployment or live whole-space exhaustion.

Both audits verified unchanged predecessor hashes. Deployment compared hashes/counts of every existing scientific/data table and the complete API reservation rows before/after. Existing records were unchanged; only prospective space tables/meta/hash-chain events were appended. Old releases remain available. The hash chain passes. Worker network isolation, broker credential separation and all production/Pi/LeadPilot denied paths remain in the units; only research release and entrypoint paths changed.

## Regression test added

`tests/test_research_spaces.py` adds ten meaningful checks:

1. Tiny-space exhaustion → automatic freeze → actual unchanged-engine evaluation across three activations.
2. Crash after successor freeze/attempt reservation → same space, candidate, attempt and alpha on resume, without new billing.
3. Outstanding old AI response blocks transition; an open batch stays in its own space.
4. Global dedup survives namespace/prose changes; out-of-space and off-grid proposals are rejected.
5. Diagnostic canaries do not change eligible parent evidence; future intervals and invalid receipts are excluded.
6. No valid training/validation evidence gives honest IDLE without scientific reset.
7. Old protocol and legacy wire bytes remain identical; old contract enums are unchanged.
8. A fixture AI proposal using successor enums is actually admitted and backtested with the same shared reservations.
9. Exhausted eligible frontier remains IDLE across repeated calls instead of relabeling genes.
10. Deployment changes only the isolated research entrypoint and retains unit restrictions.

## Validation commands/results

Exact commands and timings are in [validation.json](validation.json). The relevant local suite passed **87 tests**, then **3 additional** newly added edge-case tests passed: **90 distinct regressions**. On the VPS, `python -B -m unittest tests.test_research_spaces -v` passed all ten tests in 15.986 seconds as the actual research user. The native acceptance driver additionally retained concrete lineage/book evidence. `systemd-analyze verify` passed during deployment. JSON validation, `git diff --check`, local/deployed source hash comparison and predecessor/table/reservation comparisons passed.

## Forbidden old path checked

No modifications to original `research/continuous_research/*.py`, protocol v2, original Phase2/anomaly contracts, frozen input files, generated `data/*`/`outputs/*`, production/account/order paths or frontend. No old SEALED cycle reopened. No price/exit invention, full refresh, Pi SSH, LeadPilot change or live order. Existing production authority documents were read as boundaries; production truth fields were not changed. The unrelated dirty Desktop checkout was untouched.

## FILES READ

Truth-first sources: `AGENTS.md`; `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`; `canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`; `source_of_truth/pi_codex_runtime_workflow.md`.

Concrete sources: `source_of_truth/continuous_research_contract_v1.json`; `research/continuous_research/{planner,schema,runtime,ledger,contract,common,deploy}.py`; `research/continuous_research_protocol.py`; `research/discovery_evolution/{runtime,statistics}.py`; `research/phase2_v2/{market,engine}.py`; `scripts/deploy_continuous_research_protocol.py`; `scripts/audit_continuous_research.py`; `tests/test_continuous_research.py`; `.gitattributes`; relevant prior truth notes and current read-only native manifests/ledgers/unit state. New implementation, contract, tests and deployment files were read during validation.

## Exact files changed / exact git add list

[git-add.txt](git-add.txt) lists all 18 paths staged explicitly. No generated market/output data or unrelated work is included.

## Commit message

`research: continue exhausted spaces with frozen result-driven successors`

## Commit hash

The final response records the pushed commit hash. It can also be resolved from `git log -1 --format=%H -- docs/research-spaces-20261010/REPORT.md` on `codex/anomaly-discovery-lab-20261008`.
