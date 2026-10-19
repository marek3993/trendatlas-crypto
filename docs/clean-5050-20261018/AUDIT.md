# Clean 50/50 signal implementation audit — first delivery

**Historical first-delivery record. Current executor implementation and validation supersede its integration-pending statements: see [EXECUTION_AUDIT.md](EXECUTION_AUDIT.md).**

## FILES READ

Pinned repository `aab0a4777e2afba829ed90bd7f0b508e256d214c`:

- AGENTS.md.
- The required ordered read: source_of_truth/README.md; master_state.md; chat_roles.md; project_truth.json; export_contract.json; paths_registry.json; current_issues.md; canonical/script_registry.json; canonical/output_registry.json; canonical/registry_workflow.md.
- source_of_truth/pi_codex_runtime_workflow.md.
- execution/config/execution_mode.json; scripts/execution/trading_operation_mode.py; requirements.txt; .gitignore; .github/workflows/app_refresh.yml.
- Production manifest and single-target executor/orchestrator paths inspected in the preceding audit; manifest declares source commit e85712b614db9d9faeae59cf6216aaba0470f539. This is not proof of the complete installed VPS source tree.
- User attachment Pasted text (3).txt: clarified first-missing-close eligibility, reference data download, exact core implementation and frozen params.
- Latest user override: no seven-day waiting requirement; requested live transition after checkpoint/truncation/return-identity tests.
- Binance official market-data-only API documentation and public-data archive documentation, including the microsecond spot timestamps introduced in 2025.

## SOURCE OF TRUTH / contract impact

Class B/C/D. Added and JSON-validated source_of_truth/clean_5050_contract.json before the downstream module. The user reference is the mathematical source; no old model return, BASE token, same-day permission filter, or saved equity feeds the new module. source_of_truth/project_truth.json records a requested replacement and validated signal module, not an already accomplished live switch. Export and path contracts register an isolated signal artifact. The old live/app truth is not silently changed.

The seven-day requirement was explicitly removed from the contract and runner. Added a regression against its reintroduction. Existing forward/sealed research experiments are not read or changed.

## Root cause addressed

The previous chain combined position/return date conventions, abstract BASE labels and same-row permission-to-return filtering. The new model constructs indicators from the price prefix, writes the decision on D and uses that decision only for D+1 price returns. Same-day return information cannot erase a previously held loss. This task does not retroactively rewrite or certify old performance results.

## Validation

See validation.json for 59-symbol input hashes, 18/18 checkpoint matches, 2,116/2,116 daily reference matches, 25/25 truncation checks, zero future-mutation changes and zero gross-return identity residual.

38 unit/regression tests PASS, plus a real reference-data signal CLI smoke run (CASH 1.0, orders_sent=0, mandatory_wait_days=0).

Unit command: `python -m unittest discover -s tests -p test_clean_5050.py -v`.

Additional commands: `python -m compileall -q src/trendatlas_clean scripts/production scripts/research tests`; `systemd-analyze verify deploy/systemd/trendatlas-clean-signal.service deploy/systemd/trendatlas-clean-signal.timer`; `bash -n deploy/clean_5050/install_signal_service.sh`; JSON parse checks; `git diff --check`.

Tests cover exact feature/reference equivalence, full-history prefix consistency, future mutations, strict hysteresis, immediate eligibility exit, regime reset, deterministic ties, observed history counts, return identity and non-erasure of same-day losses, both rotation cost sides, price-drift rebalancing and post-cost 1x sizing, spot funding exclusion, geometric CAGR, missing-return invalidation, original LUNA cutoff, missing-funding labels, UTC timestamp units, restart and crash recovery, immutable daily signals, current-day data requirements, and operator shutdown behavior without real systemd mutation.

## Forbidden old path checked

No imports of legacy phase engines or order/signing SDKs in the signal package. No generated production outputs, production data, authority snapshots, journals, nonce, credentials, account state, dashboard, Pi, LeadPilot or research experiment changed. No service was remotely started/stopped and no SSH credential was read. The only SSH attempt was read-only and failed before authentication because there was no route to port 22.

The shutdown helper is standalone, operator-only and uses --apply for its documented local runtime mutation; unit tests replace systemctl and use temporary config files. It sends no order and never claims that stopping a process proves an exchange position is closed.

## Deployment status and limitations

NOT_DEPLOYED. Required signal tests pass. VPS access is unavailable. The live portfolio executor for BTC/ETH spot plus a potential perp leg is not implemented by this change, and the limit-first timeout X remains unspecified. All-USDT production discovery exists but full-universe replay/venue mapping is not certified. These are implementation/access limitations, not a seven-day approval or waiting gate.

Funding API access returned HTTP 451, so only labelled funding proxies were used. No claim of reproducing 83.5% CAGR or generating new untouched OOS evidence is made. Daily closing-price accounting does not prove realizable 00:10 fills. Cash yield is hypothetical.

## Exact files changed / git add

See GIT_ADD.txt. Commit message: `feat: implement reference-verified Clean 50/50 signals and operator handoff`.

The local initial context commit is not a repository-history claim. Delivery is built through GitHub's tree API with the actual main commit as parent and only the listed files changed. The final pushed commit hash is supplied in the delivery response.
