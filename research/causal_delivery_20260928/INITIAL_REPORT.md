# TrendAtlas continuous causal evolution — first live research cycle

**Framework validation: PASS. Real experiment: RUNNING, no financial acceptance decision yet.**

The first bounded real cycle was started on Pi through the existing research dispatcher on 2026-09-27 at approximately 12:03 UTC. It is doing actual own-asset backtests, not replaying stored paper performance. The production strategy, checkout, account, orders, dashboard, reconciliation and production timer were not changed. This release is research only.

## Exact source and release

- New branch: `codex/causal-continuous-evolution-20260927`.
- Base: origin/main `730b57c1e8815e50def473ad641a1c9db3477bc4`; no blind merge.
- Contract preregistration: `b476a8edf6bfdd68936a109a631e44cd85f152ef`.
- **Frozen engine and deployed research release: `53b6a5336ca1f7ce35b481a017f7e82396f3613c`.**
- Research code: `/opt/trendatlas-research/releases/53b6a5336ca1f7ce35b481a017f7e82396f3613c/research/causal_evolution`.
- Private state/results: `/var/lib/trendatlas-research/causal-v1/current`, resolving to `cycles/causal_nested_v1_20260927`.
- Dedicated runtime: `/opt/trendatlas-research/venvs/causal-v1`, NumPy 2.4.4 / pandas 3.0.3.
- Subsequent evidence/operations commit does not replace that frozen engine. Two research-only timeout drop-ins correct systemd oneshot bounds; evaluator, schema, raw inputs and experiment manifest remain unchanged.

The original Windows checkout was left on its pre-existing branch with its unrelated changes. All new work is in `C:/Users/benda/Desktop/ta_continuous_causal`. Detailed provenance and mandatory read order: [FILES_READ.md](FILES_READ.md), [source_lineage.json](source_lineage.json).

## Verified real progress checkpoint

Snapshot: **2026-09-27 12:23:59 UTC**. Later live status can be ahead of these immutable evidence files.

|Item|Observed result|
|---|---|
|Experiment|`causal_nested_v1_20260927`|
|State|RUNNING / SEARCH|
|Completed real evaluations|314|
|Reserved evaluation attempts|315; one in progress|
|Distinct candidate configurations|80|
|Trial/lineage rows|156, including survivors/plateau trials|
|Opened outer data|No; 159 train and 156 inner-validation attempts only|
|Frozen finalists|0 at this checkpoint|
|DeepSeek API calls|3 actual completed calls|
|DeepSeek tokens|14,539|
|DeepSeek cost|USD 0.004963104, documented peak-rate upper estimate, not an invoice|
|Accepted / rejected AI proposals|6 / 6|
|Rejection reason|Noncanonical changes to inactive family parameters|
|Worker RSS / locked memory / swap|329,888 / 332,352 / 0 KiB|
|Aggregate research CPU quota|20% of one core, including worker/broker/maintenance|
|Worker accumulated CPU|208.31 seconds at snapshot|
|Temperature near checkpoint|47.95 °C|
|Free root disk near checkpoint|1,359.9 MiB; guard reserves 1 GiB|

Full request JSON, response, parent, hypothesis, token usage and validation reason are retained in `evidence/pi_deepseek_proposals.json` and the mailbox database. Rejected proposals do not expand the schema. Deterministic replacements fill rejected proposal slots under the same candidate budget. Comparison with the deterministic arm remains **IN_PROGRESS**; unequal stages must not be compared as completed trials. Arm/generation/source accounting is in `evidence/pi_trial_counts_by_arm.csv`.

`evidence/pi_first_checkpoint.zip` contains SQLite candidates/results and mailbox snapshots, frozen manifest, metadata, genes, mutation lineage and complete development fold tables. Each database passed SQLite integrity verification. Each backup is internally consistent; databases and status were sampled separately while the worker continued. This evidence archive is not an atomic cross-database replacement for the live state.

Archive SHA256: `7619be9cdf5f53810e5a4e34b9ba35573179b647f5c3ec6b81b0c9f685fcd5bf`.

## Financial decision at handoff

|Requested outcome|Current result|
|---|---|
|A — qualified high-return candidate, CAGR 150–200%|PENDING; outer is not open|
|B — best qualified robust candidate, MDD ≤25%|PENDING|
|C — best valid Pareto compromise|PENDING|
|D — REJECT if no candidate passes|PENDING; synthetic rejection is not a real-data verdict|
|E — prospective candidates|NOT_YET_FROZEN; no forward performance claim|

|Family / reference|Experiment status|Result interpretation|
|---|---|---|
|F spot time-series trend|SEARCH active in first origin|Development only|
|G spot core/satellite|Queued under frozen island schedule|No result yet|
|H spot diversified own-trend momentum|Queued under frozen island schedule|No result yet|
|D actual-perpetual conservative proxy|Queued under frozen island schedule|Never venue-certified|
|BTC SMA200 / CASH|Mandatory fixed references|Final comparison computed by the same ledger after freeze|

No historical saved “30% BTC CAGR” is inserted as a benchmark result. The benchmark must be recomputed for the exact relevant periods, costs, venue and capital. Historical data through 2026-09-26 were previously studied and are never described as globally sealed. Prospective observation starts no earlier than 2026-09-27 and the day after actual nominee freeze.

## Frozen research design

The new [evolution contract](evolution_contract.json) and [anti-overfitting contract](anti_overfitting_contract.json) precede implementation/performance. F/G/H spot and D perpetual-proxy are separate islands. Each has 10 candidates, six Pareto survivors and four mutations, at most five generations and three independent search seeds (1701, 2903, 4517). DeepSeek and deterministic arms share the same ceilings. Earlier stopping is permitted only by the frozen diversity/stagnation rules. Budget: at most 1,248 new candidate slots, 20,000 evaluation attempts, 96 API calls, USD 1 API allowance and 24 active hours. Identical-evaluation caching never erases trial accounting.

Two anchored chronological origins nominate rules for 2024 and 2025. Inner train/validation alone drive the search. All origins finish search and freeze nominees before **any** outer evaluation opens. The outer transition is irreversible: no additional historical mutations after opening. There is no weighted scalar fitness. Pareto selection considers risk/return, fold failures, costs/turnover, concentration, neighbors, search-seed consistency, complexity and the benchmark.

Purge/embargo is 459 excluded days: 365 maximum lookback + one publication day + 90 maximum holding days + three exit-TTL days. The fixed 90-day holding horizon is a disclosed new methodological constraint, not a discovered alpha overlay. An uncapped ablation is mandatory; actual exits still require executable bars and participation capacity. Literal BTC SMA200 retains its unbounded holding rule.

Primary OOS is one continuous cash/quantity ledger across annual frozen rule changes, with no fictitious year-end liquidation. Independently initialized annual diagnostic books are explicitly separate. Regime attribution currently uses those annual diagnostic books and must not be mistaken for a second primary equity curve. In development CSV, raw score rows precede the across-seed consistency assignment; exact selection vectors are retained in SQLite `selection:*` metadata and frozen finalist records.

## Accounting, stresses and statistical gates

The causal ledger uses the held asset's own executable prices, signed quantities, own marks, cash and timestamped funding. No BASE/synthetic returns, transferred coin returns, same-day PnL filtering, missing-coin zero ranking or production paper equity are inputs. One PIT eligibility contract is shared. Spot and actual-perp proxy remain separate.

Primary capital is USD 100; finalists also receive 1k/10k/100k capacity runs. Partial fills consume lagged participation capacity, carry through a fixed TTL and cancel only the unfilled order quantity. Holdings and dust remain marked; a fictitious exit is forbidden. Fees and slippage are each 10 bps in the disclosed adverse research model. Historical Hyperliquid execution certification is not claimed, and Binance spot minimum-notional rules are not advertised as Hyperliquid rules.

Finalists receive 2× fees/slippage/funding debits; one executable-bar delay; adverse mark/fill; no-best-day and no-top-three whole-episode attribution; parameter neighbors; three search seeds; yearly and regime diagnostics; concentration, capacity, dollar costs, exposure drift, asset lineage and actual prefix/future-mutation audits. D receives maintenance-margin uncertainty and signed funding scenarios and stays CONSERVATIVE_PROXY.

Statistical outputs include DSR with attempted-hypothesis penalty, retrospective CSCV/PBO, paired stationary block bootstrap (499 replicates, mean 30-day blocks), Holm correction across the frozen finalist family, plateau and seed stability. Low test power is INCONCLUSIVE. No exact Hansen SPA claim. Major concentration, fragile neighbors, causal/accounting failure, MDD >35%, or clearly negative cost/episode stresses prevent acceptance.

## Validation actually completed

|Check|Result|
|---|---|
|45 focused regression tests|PASS before release; PASS again after operations/report changes (9.253 s)|
|Immutable two-generation synthetic integration|SEALED, 325 evaluations, three seeds, both arms, 18 frozen finalist slots, full stress/report path|
|Synthetic replay resume|Idempotent; no new evaluations after sealing|
|Predetermined real-data smoke|PASS; one inner-train book, own-asset audit passed; not OOS evidence|
|Seven raw-input SHA256 values|All match preregistration|
|Forbidden legacy/production PnL imports and arbitrary code calls|None in audited frozen engine|
|Actual Pi resource probe|Raw 30-asset panel loaded under locked-memory/address-space limits|
|Production preemption semantics|PASS using isolated fake-authority units; real production never triggered|
|Broker filesystem boundary|PASS: development mailbox readable; production repo, result DB and market inputs unreadable|
|Worker network boundary|Private namespace differs from host, AF_UNIX only|
|Live database evidence integrity|Both SQLite backups report `ok`|

Synthetic tables, folds and equity curve are explicitly named `evidence/synthetic_*`; they verify plumbing, not alpha. Engineering prototypes that changed code mid-run are excluded from accepted evidence. Only the immutable verified replay is used. Real outer tables/curves will be generated at terminal sealing; they are not substituted with synthetic or development curves.

## Pi isolation, continuity and completion

Production HEAD remains `5ee031cef7de9c385056cec22f6511391d3e4f4f`; production service and timer hashes match the pre-install values. `mrv1-production.timer` is active. Existing research dispatcher timer contents/cadence are unchanged. Previous research units/drop-ins are backed up under `/var/lib/trendatlas-research/causal-v1/deployment-backup/20260927T120312Z`.

This Pi lacks a memory cgroup controller. The effective fallback is RLIMIT_AS 768 MiB and locked current/future memory; observed VmSwap is zero. Unsupported cgroup memory settings are not presented as enforcement. Disk and thermal guards pause/checkpoint research. Regeneratable pip/APT caches were reclaimed; the APT index cache was backed up locally before hash-checked deletion. Production data, installed packages and historical research results were retained.

The worker has no IP networking or production/account filesystem access. A separate broker sees only sanitized development JSON and its dedicated encrypted DeepSeek credential. Its code has a fixed API endpoint and refuses redirects; responses are never executed. The public archive collector has no exchange account credentials. Pi access credentials are kept outside git with current-user Windows encryption; no plaintext password/API key is included in artifacts.

A worker activation lasts at most 30 minutes with SQLite checkpoints, then the research dispatcher admits a continuation only when production is idle. Production has conflict/admission priority. Broker and maintenance oneshot timeouts were verified as one minute and ten minutes respectively. The fixed first next-cycle eligibility date is 2027-01-01, conditional on at least 30 new closed UTC days, a new data fingerprint, append-only coverage and a newly complete annual outer window. Timer ticks and rejection alone cannot start same-history searches.

An hourly task follow-up monitors completion quietly while progress is normal. On terminal sealing it will export the complete actual results, final decision, stresses, curves and audit, and commit/push that evidence to this same research branch. Failure or a persistent resource block is reported, not hidden. This follow-up never authorizes production promotion or a repeated same-data experiment.

## Reproduction and inspection

Use immutable engine commit `53b6a5336ca1f7ce35b481a017f7e82396f3613c` to reproduce the accepted replay. The evidence/operations commit contains extra operational files, so its code fingerprint intentionally differs; do not use it to resume the frozen state.

```powershell
git worktree add --detach ../ta_causal_engine_repro 53b6a5336ca1f7ce35b481a017f7e82396f3613c
Set-Location ../ta_causal_engine_repro
python -m venv research/causal_evolution/local_state/runtime
research/causal_evolution/local_state/runtime/Scripts/python.exe -m pip install -r research/causal_evolution/requirements.txt
research/causal_evolution/local_state/runtime/Scripts/python.exe -m unittest research.causal_evolution.tests research.causal_evolution.vendor.test_research -v
research/causal_evolution/local_state/runtime/Scripts/python.exe -m research.causal_evolution.cli run --state research/causal_evolution/local_state/synthetic_verified --synthetic --inline-broker
research/causal_evolution/local_state/runtime/Scripts/python.exe -m research.causal_evolution.cli smoke --state research/causal_evolution/local_state/real_smoke
```

Read-only live inspection from this Windows account:

```powershell
python C:/Users/benda/.codex/local_tools/trendatlas_pi.py --exec 'sudo -n cat /var/lib/trendatlas-research/causal-v1/current/status.json'
```

`ops/checkpoint_export.py` creates read-only SQLite backup evidence; it does not run a new search. Do not copy open SQLite files without their WAL or without the backup API. [AUDIT.md](AUDIT.md) covers limitations and source boundaries. [GIT_ADD.txt](GIT_ADD.txt) records exact staging commands for implementation and delivery commits.
