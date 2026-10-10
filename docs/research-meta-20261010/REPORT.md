# Resource-paced autonomous research and post-K meta-policy

Implemented and deployed on the existing VPS at `/opt/trendatlas-research/continuous/releases/b7ea9e89cfd1caef`. This changes only research. Production, account, orders, LeadPilot, Pi and frontend were not changed.

## Exact root cause

Classification **B/C/D**. The active v1 worker stopped candidate admission twice at 128 starts/day: the scheduler gate in `runtime.tick` and the candidate reservation gate in `runtime.evaluate_candidate`. The earlier space adapter still searched only K's three refined risk axes. Its transition also waited for an unresolved paid request, which could make full-space continuation depend on the API day rolling over.

Read-only preflight found 256 completed candidates, 128 completed that day, 64 closed batches, 24/24 paid API attempts for the day and abundant host capacity: four CPUs, load about 0.22, about 44.9 GB free disk. The wait was a fixed-count policy, not evidence of unavailable compute capacity.

## SOURCE OF TRUTH / exact contract impact

`source_of_truth/research_meta_policy_v1.json` was written and validated before consumers. It records the user's explicit prospective authorization; earlier contracts, source files, batches, counters and results remain immutable.

**Resource admission replaces the daily count.** There is no daily candidate-count limit in the active meta-policy. One candidate is resumed per activation. Before market preparation and each uncached backtest phase, the worker checks host CPU busy percentage/load/pressure, available RAM, memory and I/O pressure, free disk and ledger/WAL size. Missing/invalid observations fail closed to a resource WAIT. Completed phases remain checkpointed, and a resource pause resumes the same scientific reservation and backtest key.

Admission thresholds: CPU busy below 75%, load below 0.8 per CPU, CPU PSI some avg10 below 70%, at least 1.5 GiB available RAM, memory PSI full below 2%, I/O PSI full below 10%, free disk at least 2 GiB plus 250 MiB incoming-book reserve, ledger/WAL below 3 GiB. Kernel bounds remain 60% of one CPU and 3 GiB RAM, with 2 GiB MemoryHigh, no swap, Nice19, CPUWeight1, IOWeight1 and idle I/O. These controls yield research capacity to other workloads without modifying any production unit. Long individual phases remain preemptible by the kernel limits; cooperative checks occur between phases.

**API accounting is unchanged.** The same broker and append-only reservation ledger retain 24 attempts/day including retries, 6,500 input/1,500 output per request, USD0.25/day and USD5/month. No new billing account or reset. A quota-limited pending request does not block local work or successor construction. Old request wire hashes were compared before deployment; late old proposals are retained as receipts and must satisfy the current frozen scope.

**The automatic meta-policy extends beyond K.** It rotates J/K/L/M/N primitive strategies and six distinct two-mechanism combinations: J+K, J+L, J+M, K+L, K+M, L+M. J/L/M/N use their already supported parameter enums and features; K retains the authorized refined envelope. This changes lookback/risk/confirmation/breadth/momentum/breakout combinations, not only the three K risk parameters.

A `BLEND` compiles two primitive target vectors, calculated from the prior close, with weights 0.25/0.5/0.75 into **one original quantity/cash/cost book** at the next open. Each component maintains independent prior signal memory, including through checkpoints. Returns/equity curves are never averaged. Canonical family order plus complemented swapped weights deduplicate reversed descriptions. Nested and same-family blends are rejected. N remains supported standalone with its original intraday stop execution; it cannot enter target-only blends because that would silently change its stop semantics.

**Space selection and freezing.** Only valid, exact-window train/validation views enter ranking or AI context. The local planner rotates categories and builds bounded neighborhoods from ranked eligible evidence and supported shared parameter projections. If those neighborhoods are exhausted, a deterministic canonical search finds unused configurations, scanning at most 4,096 positions per activation and checkpointing the cursor in append-only `meta_scans`. It freezes the entire next space grammar, lineage, evidence hashes/counts, frequency policy, statistical design and contamination before admission/evaluation. Existing `research_spaces`, `space_batches` and `space_ends` are reused without rewriting them.

Deterministic plans use `LOCAL_META_POLICY`; they are never mislabeled AI-authored or new market discoveries. The existing metered AI loop can propose configurations in each frozen grammar with at most two compact parents; original parser limits apply. Global canonical genes and rule+gene hypothesis identities exclude space IDs and wording. Every historical registry and selection record persists.

**Scientific constraints remain binding.** Development ends 2026-09-25, feedback ends 2021-12-17 and 2026-09-27 through 2027-09-26 stays locked. Original train/validation windows, 30-day blocks, 14-day gaps, minimum 30 nonzero blocks, lifetime alpha `0.05/[t*(t+1)]` with inherited 1,444 and all invalid scientific reservations persist. Repeated historical selection remains contaminated development; conditional p-values and unverified independence never confirm a trading candidate. No price, LUNA exit or lossless CASH transition is invented. Invalid candidates remain individually terminal; independent prepared candidates continue.

The supported grammar is finite, although much broader than K. Its exact per-category cardinalities are in [validation.json](validation.json). Complete exhaustion of all supported categories reports `IDLE_META_GRAMMAR_EXHAUSTED`; there is no artificial progress by recycling genes or claiming arbitrary new executable mechanisms. `WAIT_META_SCAN` is a checkpointed search, not a completed backtest.

## Native runtime proof

[Preflight](preflight.json), [deployment freeze](deployment.json), [first automatic-progress snapshot](runtime-first.json), [second snapshot](runtime-second.json) and the [read-only collector](audit_runtime.py) are committed.

| Snapshot (UTC) | Total completed | Completed today | Paid API attempts today |
|---|---:|---:|---:|
| Before deployment | 256 | 128 | 24 |
| 2026-10-10 10:09:40 | 257 | 129 | 24 |
| 2026-10-10 10:11:44 | 258 | 130 | 24 |

The existing VPS timer performed these activations; no manual worker invocation, day rollover, notebook loop or counter reset was used. Ten new actual backtests completed across the two candidates while paid proposals remained at their daily cap. Last actual completion in the second snapshot is **2026-10-10T10:11:42.295474Z**. Detailed candidate IDs, attempt IDs, alpha positions and verified book hashes are in the snapshots. Computing flags can legitimately be false between phases; growth in committed books/candidates and separate automatic activation timestamps establish progress.

API reservations remain 48 lifetime attempts and USD0.18 conservatively reserved for the month: zero new paid calls during this work, zero attempts left today, USD0.16 daily monetary headroom and USD4.82 monthly headroom. Financial headroom does not override the exhausted attempt quota. Resource admission was `ADMITTED` in the recorded run.

Deployment and audits verified unchanged old scientific table prefixes, old API reservations and predecessor hashes; the hash chain validates. Original source bindings remain valid, with an additional frozen meta-policy manifest. Only the research worker priority/resource settings and the two research entrypoint paths changed. Credential isolation, worker private networking and production/Pi/LeadPilot denied paths remain in place.

The live K space was not artificially exhausted. It continues normally with new globally unique candidates. Post-envelope behavior is established by the following explicit test fixtures, rather than falsely claiming that 824,915 live backtests were performed.

## Regression test added / meaningful post-envelope proof

`tests/test_meta_research.py` adds eleven tests:

1. Admission after 128 existing scientific reservations while the shared API ledger has 24 paid reservations; the next scientific position is 1,573, without resetting debt or billing.
2. The complete **824,915-configuration K envelope** is seeded as used history in a temporary test ledger. These are exhausted-registry fixtures, not claimed historical backtests. With an outstanding paid request and API cap, the planner automatically freezes J and performs its five real unchanged-engine backtests. No operator supplies the successor.
3. Automatic rotation in a small supported grammar reaches J+K and executes five actual blend backtests, without manually creating that space.
4. The blend's per-day targets equal the declared weighted component targets with separate memories; the continuous costed book reconciles, chronological prefixes agree, and JSON checkpoint/resume gives the same final equity.
5. Canonical reversed-composition dedup and rejection of nested/same-family/N-in-blend/invalid-weight configurations.
6. Frozen-blend AI wire/admission, global dedup, diagnostic-canary exclusion and the 6,500-token bound.
7. Bounded scan cursors advance durably and report honest terminal grammar exhaustion.
8. A pending old AI request does not block local successor work; old wire bytes remain identical.
9. CPU, load, RAM, pressure, storage and unknown observations pause admission without a scientific reservation.
10. Mid-candidate resource wait preserves an already written phase and resumes the same attempt/alpha without duplicates.
11. Deployment retains research sandbox/credential boundaries and applies lower research priorities only.

On the VPS, all eleven passed as `trendatlas-continuous` with low CPU/I/O priority, in **48.899 seconds**. Their output is retained in the runtime snapshots. The complete-K fixture froze its automatic J successor at **2026-10-10T10:08:19.001393Z**, with candidate `a68c19c05ccb158fcf5edf6d669dbb6ed479a89efcd0beb4a4828ba93545057a`; all five books were valid and API reservations stayed 24. The automatic composition fixture reached space 6/J+K with candidate `2fe24c80b7412eec84209e30a0eb203d794f85b88364a2246af582297e8b6ab9` and five actual books. Test prices are synthetic; no paid API call was used for these fixtures.

## Validation commands/results

- `python -B -m unittest tests.test_meta_research tests.test_research_spaces tests.test_continuous_research tests.test_continuous_research_protocol tests.test_discovery_evolution tests.test_anomaly_lab tests.test_anomaly_lab_reporting tests.test_phase2_v2 tests.test_phase2_v2_continuation -q`: **101 tests PASS**, 218.553 seconds.
- Native `python -B -m unittest tests.test_meta_research -v`: **11 PASS**, 48.899 seconds.
- `systemd-analyze verify`: PASS for the isolated research units during deployment.
- Source/meta contract validation, JSON registry validation, `git diff --check`, local/deployed SHA-256 equality and old request-wire/prefix/reservation checks: PASS.
- Two subsequent read-only native snapshots prove growing completed counts at the unchanged paid cap; all new valid book hashes and PnL reconciliation audits were checked.

## FILES READ

`AGENTS.md`; truth-first `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`; `canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`; `source_of_truth/pi_codex_runtime_workflow.md`.

Concrete sources: `source_of_truth/phase2_development_contract.json`, existing continuous/space contracts and prior report; `research/phase2_v2/{engine,market}.py`; `research/research_spaces.py`; existing continuous planner/runtime/schema/ledger/broker/common/contract code; `scripts/deploy_research_spaces.py`; prior audit helper; continuous/space tests; `.gitattributes`; new contract/modules/tests/installer and native manifests, read-only resource observations, units and ledgers.

## Forbidden old path checked

No original runtime/protocol/space source bytes or frozen contracts were edited. No `data/*`, `outputs/*`, authority snapshots, production scripts, frontend, account/order API, Pi deployment or LeadPilot changes. No full refresh, sealed reads, abandoned experiment reopening, scientific reset, invented exit or retesting an old gene under a new namespace. The dirty Desktop checkout remains untouched; all edits are in the existing research worktree.

## Exact files changed / exact git add list

[git-add.txt](git-add.txt) contains the exact 19 explicitly staged paths. The five frozen deployment files match the native manifest byte-for-byte; old modules remain unchanged.

## Commit message

`research: pace by resources and continue through mechanism meta-spaces`

## Commit hash

The final response records the pushed commit hash. Resolve it with `git log -1 --format=%H -- docs/research-meta-20261010/REPORT.md` on `codex/anomaly-discovery-lab-20261008`.
