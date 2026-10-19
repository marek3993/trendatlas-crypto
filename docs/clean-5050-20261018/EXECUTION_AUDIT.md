# Clean portfolio executor audit — 2026-10-18

**IMPLEMENTED_TESTED_OPERATOR_DEPLOYMENT_PENDING.** This continuation is based on PR #1 / branch `codex/trendatlas-clean-5050-20261018`, remote parent `093083e46837c3cebd3530bde139cf5b38efa214`. No remote SSH mutation, live order or actual VPS activation was performed here.

## FILES READ / SOURCE OF TRUTH

The required order was read before implementation: `AGENTS.md`; `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`, `project_truth.json`, `export_contract.json`, `paths_registry.json`, `current_issues.md`; `canonical/script_registry.json`, `output_registry.json`, `registry_workflow.md`; then `source_of_truth/pi_codex_runtime_workflow.md`.

Also read: the prior Clean package, reference fixture and checkpoint fixture; the signal validation and shutdown scripts/tests; the first-delivery audit; existing single-target production execution, credential and venue evidence described in that audit; official Hyperliquid API account-abstraction/info/exchange documentation and SDK `exchange.py`, `info.py`, `signing.py`, `pyproject.toml`. Pinned runtime SDK is `hyperliquid-python-sdk==0.24.0`, `eth-account==0.13.7`; numerical dependencies remain numpy 2.3.5 / pandas 2.2.3.

User directions are authoritative for this continuation: no mandatory seven-day wait; implement multi-asset execution in the same branch; BTC/ETH spot UBTC/UETH, others perp 1x; EXIT before ENTRY; limit then taker fallback; missing entry market must not prevent EXIT; prepare a single stdin-over-SSH installation. The user supplies a successful old shutdown receipt with `applied=true`, `verified_disabled=true`, old kill switch on and trading off, timer disabled/inactive, service inactive, no shutdown orders. This session does not convert that supplied receipt into a claimed independent SSH verification.

Classification **B/C**, retaining the already-validated **D** math. `clean_5050_contract.json` was extended before implementation. Current source/export/path/workflow contracts explicitly name the new sole Clean execution owner **after operator activation**; they do not claim it is already deployed. No new research policy, approval layer, seven-day gate or static coin permission list was introduced.

## Exact causes and fixes

1. The first delivery implemented signals only. The old runtime accepted a single asset and could not execute 50% BTC spot plus 50% another coin. Added pure portfolio planning, dynamic venue metadata, an exchange adapter and a durable execution state machine instead of relabelling the old single-asset path.
2. Retrying a trading HTTP request after loss of its response can duplicate a trade. CLOID and SUBMITTING state are persisted first; restart queries the same CLOID and never blindly resends. Proven pre-request failures and explicit exchange rejections are recorded as terminal rejections, not as permanent ambiguous orders. Actual ambiguous submissions/cancellations remain visible with reconciliation required.
3. The old signal binding included code/input hashes; adding executor code or rechecking identical weights could block same-day continuation unnecessarily. Binding now freezes semantic strategy/day/weights/parameters, preserving the original signal and recording new provenance observations. A changed daily target is still rejected.
4. The Windows shutdown failure came from Unix-only permission calls before ownership of the temporary file descriptor and a directory fsync unsupported on Windows. File ownership is now acquired by `fdopen` first, platform-specific operations are guarded, and parent-directory fsync is POSIX-only. The regression tests verify failure cleanup; native Windows was not run here.
5. A 10x exchange margin setting must not be mistaken for target notional. New perp ENTRY explicitly sets 1x; existing target perp positions also have their setting reconciled even when no quantity trade is needed. BTC/ETH perp holdings do not satisfy spot targets.

## Implemented boundaries

- The signal producer uses only price/volume history and no exchange mutation. The execution CLI is plan-only by default; the operator-installed systemd service passes `--execute-live`.
- Source policy is disabled by default. Only the explicit operator installer with `--activate-live`, after native tests/reference replay/signer-only preflight, arms the new Clean config. The old kill switch is never cleared.
- No production key is put in source, command arguments, environment provisioning or a checkout file. Systemd reuses the existing encrypted named credential; the adapter checks the named agent against the master account and expiration. The existing forbidden environment-secret path is not revived.
- Metadata discovers actual market IDs. BTC/ETH require UBTC/UETH **USDC** spot pairs, not USDH or fallback perps. No `BASE`, LUNA remapping or guessed scaled-token identity exists.
- All independent EXITs are attempted before ENTRY. An unavailable target is a per-leg error. An unresolved necessary EXIT or ambiguous prior order prevents more ENTRY, while other known EXITs can proceed.
- Defaults: Alo maker limit, 300-second timeout, confirmed cancellation before an actual-residual IOC fallback, 50 bp IOC price cap, $10 minimum, quantity/price precision, 1% NAV reconciliation tolerance. Untradeable dust remains in the actual-position receipt.
- No automatic transfer, borrow or account-abstraction change occurs. Fresh free collateral is checked before ENTRY. Unified spot balance/holds are used once; perp accountValue is not double-counted. All reported perp DEX positions/orders are queried.
- State uses SQLite WAL/FULL, per-day frozen targets, pre-submit CLOIDs, durable monotonic nonces, post-trade receipts and online SQLite backups. Default completed same-day re-entry is a readback with zero new orders.

## Actual validation

**86 focused tests PASS on the local Linux runtime.** They cover the prior signal/accounting tests plus:

- CASH → BTC spot + SOL perp; SOL → ZEC while preserving BTC; all positions → CASH; old BTC perp → BTC spot.
- Missing target market with old EXIT still executed and independent available BTC ENTRY allowed.
- No BASE/negative/NaN/infinite/>1x weights; precision/minimum dust; small reduce-only perp exits.
- Maker fill, partial maker/cancel/IOC residual, unconfirmed cancellation without fallback.
- Lost submit response with confirmed fill; unknown submission with no duplicate retry; unsubmitted reservation cleanup; simulated process death after an exchange fill but before its journal update; prior-day open-order recovery.
- Independent EXIT under an uncertain previous ENTRY; no spurious uncertainty after a proven pre-submit failure or explicit provider rejection.
- Same-day idempotency, changed frozen target rejection, monotonic nonce after clock regression/reopen, existing 10x margin setting → 1x.
- UBTC USDC selection over USDH, spot-only BTC routing, unified-account equity without double-counting, actual SDK wire asset/CLOID encoding, kill-switch reread, no borrowing on insufficient spot cash.
- Deterministic source bundle; no runtime data/key files; path escape rejection; unit/reference/signer failure cannot clear the kill switch; activation after tests; post-activation error does not restart old production; default non-activation; exact timer order.

Command:

```bash
PYTHONPATH=/path/to/installed/dependencies:src python -m unittest discover -s tests -p 'test_clean_5050*.py' -v
```

Independent rerun of actual frozen 59-coin data through **2026-10-17** again passed: **18/18 checkpoints; 2,116 daily reference decisions; zero full-history differences; 25/25 truncation dates; zero future-mutation changes; zero return-identity residual**. Details in `execution_validation.json`. Core strategy math was not changed.

```bash
python scripts/research/validate_clean_5050.py --data-dir /path/to/frozen59 --end 2026-10-17 --output-dir /path/to/validation --prefix-tests 25
python scripts/production/build_clean_installer.py
python -m compileall -q src/trendatlas_clean scripts/production scripts/research deploy/clean_5050 tests
git diff --check
```

JSON parse checks passed. Embedded archive SHA and per-file manifest passed, and two independent bundle builds matched. Systemd syntax validation passed against a temporary copy substituting the available local interpreter. Checking the exact production unit here reports the expected missing `/opt/trendatlas-clean/current/.venv/bin/python`; the installer checks the **unmodified exact unit** after that release/interpreter exists on VPS. No local placeholder production installation was created to disguise that distinction.

The installer tests are mocked VPS scenarios, not proof it has already run on VPS. The installer repeats the entire native test suite and real reference replay **on VPS** before clearing Clean's kill switch. `INSTALL_SCHEDULED_ON_VPS` is a start acknowledgment; only the terminal receipt can confirm `CLEAN_LIVE_AND_ALIGNED`.

## Read-only live evidence

At **2026-10-18 14:52:00.819894 UTC**, the new adapter directly queried Hyperliquid `/info` with no signer: `unifiedAccount`, **86.869106 USDC**, **0 positions**, **0 open orders**, no entry dependency errors. It resolved UBTC/USDC `@142` / asset 10142 and UETH/USDC `@151` / asset 10151, plus SOL/ZEC perps, using actual metadata rather than those numbers as a static map. Account observations and routing details are in `execution_public_preflight.json`. This is not SSH service-state proof and not a deployment claim.

## Forbidden old path checked / limitations

- No original generated `outputs/` or `data/`, authority snapshots, old execution journal/nonce, trading secret, old strategy math, research experiment, LeadPilot or Pi was edited or contacted through SSH. No legacy full-refresh or production run was invoked.
- This authoring session sent **zero** `/exchange` requests. Unit tests use a fake broker/fake VPS; the only real broker usage was `/info` readback.
- No new simultaneous old/new scheduler was activated. The operator installer checks old shutdown and leaves the old kill switch on.
- The old publisher/dashboard is not migrated in this task; it must not infer Clean holdings or PnL from weights. Historical funding proxies, close-price fill assumptions and model cash yield are not account income or venue-certified performance.
- No merge or VPS deployment was performed here. The feature branch/PR is updated for review and the one operator command in `EXECUTION.md` prepares the requested live transition.

## Open task list

| Task | Owner | Status | Next action | Blocker |
|---|---|---|---|---|
| Signal + portfolio execution | This implementation | Tested | Review PR #1 | None in focused tests |
| VPS installation/activation | Marek/operator command | Prepared | Run `install_vps.py` pipe | SSH route unavailable in this authoring environment |
| Native VPS proof | Installer | Not yet run | Tests/replay/signer readback before activation | Requires operator command |
| Legacy dashboard migration | Separate follow-up | Not changed | Wire Clean metrics and actual receipt explicitly | Outside this executor continuation |

## Exact files / commit

Exact file list and staging command: `GIT_ADD_EXECUTION.txt` in this directory. Commit message: `feat: add Clean 50/50 portfolio executor and tested VPS stdin installer`.

The local workspace is a partial mirror, not a claim to contain full upstream Git history. Delivery uses GitHub's tree API with actual remote parent `093083e46837c3cebd3530bde139cf5b38efa214`, preserving other files and updating the existing branch with an expected-head lease. The resulting remote commit hash is supplied in the final handoff; no merge/deploy is implied by that commit.
