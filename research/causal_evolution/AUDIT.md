# Research audit

Classification: B (data/runtime), C (research execution/scheduling), D (strategy math). Source contracts were committed before implementation and before any real performance.

Root cause and contract impact are recorded in FILES_READ.md. No production strategy, dashboard, execution planner, Hyperliquid integration, wallet, reconciliation, production checkout or production timer is edited. Existing research-only units are the deployment target. No merge or promotion exists in the worker.

## Source and old-path control

Raw inputs match all seven preregistered SHA256 values. `evidence/forbidden_paths.json` records the import/data-source audit. Vendored common/data/signals/ledger are direct source descendants pinned by `source_lineage.json`; the old panel, acquisition runner, return-stream evaluator, weighted selection and rejection-driven same-history succession are not imported. No stored paper CAGR/equity is a data input. Underlying daily returns are computed from each own price only for risk estimation; ledger PnL is cash plus signed own quantities, own marks and timestamped funding.

The original production checkout and prior branch results are retained. This package is a new branch from current origin/main, not a merge of old branches. The legacy vendor contract is technical provenance: execution constants and canonical enum validation only. New experiment budgets, splits, authority and qualification come from the new contracts.

## Regression coverage

45 focused tests cover actual asset identity, prior-bar publication, missing-bar delayed fills, partial execution/TTL, retained dust, signed funding and debit-only stress, gross-policy causality, margin safety, full-episode attribution, 90-day real-exit horizon, true chronological gaps, JSON duplicates/nonfinite/code/island escapes, OOS date relabeling, irreversible outer barrier, crash reservation, 10/6/4 populations and independent seeds, Pareto tradeoffs, DSR trial penalty, insufficient-power status, Holm, CSCV, public archive schemas/URL allowlist, research service isolation and production-priority admission. Continuous annual rule changes preserve pre-switch account history and do not reset cash/quantities.

Synthetic integration evidence is recorded separately under evidence. Preliminary engineering runs used changing development code and are NOT research results or validation evidence. Their retained local directories explain any preliminary failure; only the immutable verified run is accepted. The final synthetic profile executes two complete generations, three independent seeds, both equal-budget arms, outer sealing, stresses, reporting and lineage export. It does not claim economic alpha.

## Statistical boundaries

Both annual origins finish all training/inner-validation search before ANY outer evaluation. A committed terminal barrier then rejects further hypothesis creation. Global historical independence is explicitly unproven because earlier work inspected this history. Prospective observations cannot enter mutation payloads before a fixed refit. DSR, CSCV, block bootstrap and Holm each preserve numeric diagnostics and insufficient-power flags. No PASS from a small-sample statistic. Outer rules, neighbors and stresses are fixed before opening outer.

Every finalist receives own-asset fill lineage checks, future-mutation signal checks and an actual truncated-prefix ledger comparison. Primary OOS is one continuous account across frozen annual strategy switches. Separate annually initialized books are diagnostic only. Regime slices attribute an unchanged account using a previously public BTC signal; they never filter already-earned PnL. No-best-day/top-three sensitivity is labeled an attribution stress, not an executable alternate trading strategy.

## Runtime boundaries

Worker: no IP network, no production/account filesystem, research-only writable state, aggregate20% research CPU slice, SQLite FULL synchronous recovery. API broker: separate mailbox containing sanitized development JSON only; historical/OOS database and market datasets are not mounted; key via a dedicated encrypted credential; no redirects/tools/code execution. Public collector: public checksum-verified archives only, no exchange keys or account API. API reservations precede requests; uncertain calls count and are not retried.

The Pi has no memory cgroup controller. MemoryMax/SwapMax alone are NOT represented as effective. Required fallback is an actual768MiB address-space cap plus locked current/future memory and verified zero VmSwap. Thermal and disk guards are fail-closed. Production preemption is both systemd conflict/order plus gate rechecks. No production execution is manually triggered to test this.

## Honest limitations

D remains conservative proxy: historical maintenance brackets, historical fee/lot certification and some mark intervals are missing. Same PERP trade marks are explicitly flagged when used as proxy, with adverse funding/mark/margin scenarios. No spot short/perp substitution and no venue-certified claim. Minimum order/precision assumptions are disclosed proxies, not transplanted Binance rules advertised as Hyperliquid rules. No leverage/stop/TP search was added.

The fixed90-day horizon is a disclosed new research constraint with an uncapped baseline ablation. It never forces a fictitious close. Residuals remain MTM. Fee/slippage rates are deliberately adverse10bps each. Universe is one shared point-in-time admission routine; missing membership stays CASH and missing prices never become tradable zero returns.

A new historical cycle requires a genuinely appended dataset and a new completed annual outer window as well as30 new UTC days and refit eligibility. This is stricter than a hash/timer gate and intentionally skips quarter checks over the same usable history. Archive or disk unavailability yields a visible waiting/paused state.

## Evidence and exact files

See `GIT_ADD.txt` for the exact implementation staging list. Deployment/test/result evidence and final report are committed separately after verification. FILES_READ.md contains the mandatory source-of-truth inventory. Runtime reports are generated from SQLite; historical numerical outcomes are not invented while the first live research cycle is RUNNING.

## Verified Pi handoff evidence

The immutable engine actually running on Pi is commit `53b6a5336ca1f7ce35b481a017f7e82396f3613c`. The live progress snapshot at 2026-09-27 12:23:59 UTC contains 314 completed evaluations, 315 reserved attempts, 80 configurations and no outer evaluations. Three actual DeepSeek calls consumed 14,539 tokens (USD 0.004963104 peak-rate upper estimate): six accepted and six rejected proposals. All six rejected proposals changed inactive family fields and were excluded. Full prompts, responses, usage and lineage are included; no key is included.

`evidence/pi_first_checkpoint.zip` was produced with SQLite's backup API, with integrity `ok` for each database. Its exact SHA256 and extraction inventory are recorded in REPORT.md. This is a live progress artifact, not final performance; the two databases and status file are independently sampled. The final A/B/C/D decision, continuous OOS curves and prospective nominations remain pending. Raw score CSV seed-consistency fields precede the across-seed selection update; selection metadata is authoritative for the actual Pareto vectors. Regime attribution is from separate annual diagnostic books, explicitly not primary continuous-book aggregation.

The actual worker reports RSS 329,888 KiB, locked memory 332,352 KiB and VmSwap 0. Its network namespace differs from PID1 and its configured address families are AF_UNIX only. A separate service with the broker's actual sandbox settings verified that the development mailbox is readable while production HEAD, candidate/results database and raw market archive are unreadable. A fake-authority unit test demonstrated both preemption and admission without ever starting real production. Scripts are retained under ops; temporary probe units were removed after checks.

Production HEAD remained `5ee031cef7de9c385056cec22f6511391d3e4f4f`. Production service/timer hashes and the existing research dispatcher timer hash are unchanged. Production timer is active. `evidence/pi_snapshot_audit.json` records systemd properties, hashes, namespaces and memory. `pi_deployment_audit.json` records the research-only release, old-unit backup and resource cleanup. Only regeneratable package caches were reclaimed; APT index bytes were backed up outside git and verified before exact-file removal. Installed packages and production/research datasets were retained.

Systemd reported that RuntimeMaxSec did not bound Type=oneshot. Research-only broker/maintenance drop-ins now set TimeoutStartSec to 60 seconds / 10 minutes; effective properties were verified. Future deployment templates and their regression assertions are corrected. This operations patch, operational probe scripts and evidence do not modify or replace the already frozen running release. Reproduction of its manifest must use the exact engine commit, not the later evidence commit's expanded file fingerprint.

The 45 focused tests were rerun successfully after the operations change. The immutable synthetic integration completed 325 evaluations and full reporting, with idempotent sealed resume. Synthetic curves/results are explicitly plumbing evidence. No economic result from a changing-code prototype, saved paper equity, old stored CAGR or the real-data smoke is used as an OOS acceptance result.

## Terminal delivery audit — 2026-09-28

**Scientific decision REJECT; evidence verification PASS.** This append supersedes
only the pending status of earlier handoff paragraphs. Initial report bytes and all
old evidence remain preserved. Classification: B/C research evidence and read-only
runtime inspection; no new D strategy-math change.

FILES READ / SOURCE OF TRUTH: see FILES_READ.md and the terminal delivery README.
The exact scientific sources remain the two frozen contracts, manifest, seven raw
input hashes and engine 53b6a5336ca1f7ce35b481a017f7e82396f3613c. Terminal SQLite is
the result authority; reports derive from it. Production authority is unchanged.

Exact root cause of financial rejection: every schedule fails inner qualification,
whole-top-three-episode removal, seed stability, DSR and bootstrap/Holm/PBO gates.
69/72 exceed 35% MDD; maximum CAGR 44.78% is below 150%; no Sharpe 1.5/Calmar 4. The
absence of a qualified strategy is not a missing API or capacity-blocked B result.
No new strategy is created from these OOS failures.

Exact contract impact: none to scientific or production contracts. Frozen targets,
parameters, costs, evaluator, data and budgets remain unchanged. Delivery tooling
is outside the frozen package. Added reports explicitly disclose actual gross
exposure drift up to 1.70055, unknown billing on 3 API failures, missing benchmark
stress books, and the true earliest prospective closed day 2026-09-29. No hidden
repair or reassignment of these outcomes was made.

### Verification actually completed

- Locked consistent snapshot at 20:16:14 UTC, after SEALED at 20:02:42 UTC. Both worker
  and broker locks were acquired by the existing snapshot helper; neither service
  was stopped/restarted. Existing 18:47 export/checkpoint 5112 was rejected as stale.
- All 132 file sizes/SHA256 values verified, both SQLite integrity/FK checks pass;
  7203 COMPLETE attempts map bijectively to 7203 results, 8 INTERRUPTED preserved,
  zero open attempts. Candidate count 1126; trial count 3415; scores 2400; populations 240.
- All 38 code/input manifest hashes match the pinned source export. Archive parts
  were reassembled to a fresh ignored directory and passed the same verification.
- All 144 final nominations equal SQLite, selected only from inner folds. All
  recorded trial creation, development completions and API payload creation precede
  first outer 19:20:21 UTC. The mailbox seal timestamp is refreshed on outer resume;
  it must not be interpreted as the initial freeze timestamp.
- All 96 saved API payloads validated against pinned allowed fields and actual
  train/validation date windows. All 93 returned responses reproduce accepted/rejected
  classifications exactly. 3 unknown network failures were counted, never retried.
  No network call or evaluator is invoked by verify.py.
- All 72 continuous results, stored stress/neighbor/capacity books, 2 benchmarks and
  54,094 equity rows reconcile with immutable SQLite. NAV-derived CAGR/Sharpe,
  recorded cumulative intrabar MDD, costs, closed episodes and concentration-removal
  calculations match within 1e-9. This independently verifies saved accounting,
  not a new raw-bar replay.
- All 7203 stored own-asset fill audits and 144 actual prefix/future-mutation audits
  are PASS. Original raw-price references were checked during the frozen run;
  delivery did not claim to independently rerun those 7203 books.
- Plain return labels do not convert data to globally sealed history. The raw
  report/status prospective date 2026-09-27 is retained as evidence but corrected
  in the final interpretation: first wholly post-freeze UTC day is September 29.
- Initial non-sudo VPS readlink exited 1 on export permissions; sudo read-only retry
  confirmed the old export. No credential or authority failure was hidden.

Full machine-readable checks: ../causal_delivery_20260928/derived/verification.json.
Exact commands: ../causal_delivery_20260928/README.md. This delivery introduces no
runtime regression fix, so no new strategy test is added. Existing frozen regression
coverage remains authoritative; the snapshot verifier adds data-integrity assertions.

### Important limits

The largest reliable tested capital is 100k for all schedules, but 4 books are
unreliable at the primary 100 account; capacity reliability is not monotonic under
minimum-order/dust assumptions. All residuals stay MTM. Maximum target gross 1.25
is not a hard cap on marked exposure: nominal D reaches 1.70055. Historical margin
brackets and Hyperliquid execution certification remain absent. D is PROXY only.
Double-cost/delayed-fill benchmark rows and 1m capacity are not in the frozen run;
they remain explicitly uncomputed. Statistical trial penalties exclude unknown
previous research choices and cannot establish global historical independence.
The Pareto output contains 29 labeled, possibly duplicate, cross-track rows and
zero accepted rows. Annual-reset diagnostics are not primary continuous NAV.

### Runtime and forbidden paths

VPS worker stopped successfully at 20:02:44 UTC; immutable terminal status has no
failure. Pi remains CHECKPOINTED at 5087 with research inactive; production timer
active/enabled at 20:27 UTC. Dispatcher 255/failed journal lines are the existing
`ready` routine refusing SEALED (non-resumable), not lost results or renewed search.
That operational log noise is documented, not repaired under this heartbeat.
The broker returns without requests once its sealed mailbox is present.

No scientific evaluator, genes, raw inputs, frozen manifest, production source,
outputs/*, data/*, authority snapshot, dashboard, account, signer, live order,
Pi timer, LeadPilot or deployment file was edited. No merge, full-refresh,
publish-existing, live-order command or same-history evolution rerun occurred.
This is a research-only commit on codex/causal-continuous-evolution-20260927.
The completion heartbeat will be paused after successful push; no Pi/VPS unit is
changed by that action. Future cycles require the existing frozen refit contract.

Exact files changed and git add list: ../causal_delivery_20260928/GIT_ADD.txt.
Commit message: research: archive sealed causal cycle and audit rejected finalists.
Commit hash: supplied in final handoff; resolve with git log -1 --format=%H --
research/causal_delivery_20260928. A report cannot contain its own resulting hash.

Terminal validation reran the pinned 45 focused tests: PASS in 15.713 seconds.
All 5,087 pre-migration evaluations and every prior science-table/proposal row
were compared directly with the final snapshot and remain byte-identical by cell.
The independently restored archive and matplotlib overview were verified; the
plot was visually inspected. No new strategy tests or scientific runs were added.
