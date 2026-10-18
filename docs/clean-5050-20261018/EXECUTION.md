# Clean 50/50 portfolio execution and VPS handoff — 2026-10-18

**IMPLEMENTED AND TESTED; OPERATOR DEPLOYMENT PENDING.** The old phase68g shutdown is confirmed by Marek's supplied receipt, not by a new SSH session here. No live order or remote service change was performed while writing this feature.

## Single deployment command

Run from an updated checkout of branch `codex/trendatlas-clean-5050-20261018` (PR #1). This is the user-authorized live activation command; it does not impose a seven-day wait:

```powershell
Get-Content -Raw .\deploy\clean_5050\install_vps.py | ssh -i "$env:USERPROFILE\.ssh\trendatlas_research_admin_20260928" ubuntu@57.129.127.49 "sudo python3 - --source-commit $(git rev-parse HEAD) --activate-live"
```

The payload contains the exact minimal source bundle published on this branch, including its per-file SHA256 manifest. It does not need a GitHub token on the server and does not overwrite the old production checkout. `--source-commit` records the operator's checked-out commit; the independent bundle hash binds the actual installed bytes. This is a source bundle deployment, not a clone of unrelated runtime/data files.

The initial SSH command schedules `trendatlas-clean-install.service` on the VPS and returns `INSTALL_SCHEDULED_ON_VPS`. **That message means installation started, not that trading is already active.** The server continues without the laptop. Progress and the final result are available with:

```powershell
ssh -i "$env:USERPROFILE\.ssh\trendatlas_research_admin_20260928" ubuntu@57.129.127.49 "sudo journalctl -u trendatlas-clean-install.service -n 80 --no-pager; sudo cat /var/lib/trendatlas-clean-install/status.json"
```

The successful terminal status is `CLEAN_LIVE_AND_ALIGNED`. A failure before activation keeps Clean's kill switch on. A failure after possible activation is recorded as reconciliation required; the installer never restarts phase68g as a rollback. Do not rerun the entire installer over an active Clean timer: inspect its receipt/journal first. A second attempt before activation can reuse the staged release. If the transient installer unit remains after a failed attempt, inspect its protected log and stop/reset only `trendatlas-clean-install.service` before retrying.

## What the installer does

1. Verifies the old phase68g config still has `kill_switch=true`, `trading_enabled=false`, and its service/timer are inactive. It reads the existing encrypted credential declaration, never the private key bytes.
2. Extracts the source-only bundle under `/opt/trendatlas-clean/releases/<commit>`, verifies hashes and uses an isolated Python environment. If Ubuntu's default Python is too new for pinned pandas, it provisions isolated CPython 3.12 using pinned uv; it does not replace the OS interpreter or old production environment.
3. Installs pinned dependencies, runs all `test_clean_5050*.py` tests natively on the VPS, downloads the original frozen 59-symbol data, then checks all 18 checkpoints, all historical reference signals, 25 truncation dates, future-mutation invariance and return identity. Any failed check stops before activation.
4. Builds a current last-closed-day signal using the requested all-USDT universe. This first download can take time; it runs on the VPS. The 59-coin reference universe is never silently substituted for live selection.
5. Runs an order-free signer/account preflight in a transient systemd unit with exactly the existing `hyperliquid-agent-private-key` encrypted credential. It verifies the named `TrendAtlasProd` agent against the master account. No key is passed in an environment variable, command line or repository file.
6. Installs the sole new `trendatlas-clean-production.service/timer`, retires the obsolete signal-only timer if present, and leaves the old phase68g kill switch on. Only after the tests and signer preflight pass does `--activate-live` clear **Clean's** kill switch and enable its timer.
7. Starts the canonical new service once and checks its actual exchange readback. Further daily runs occur at **00:10 UTC**, with persistent catch-up after reboot and 15-minute retries on failure. No Codex or laptop is needed for scheduled execution.

## Execution behavior

`signal.json` contains the decision made at close D for holdings during D+1. The service runs the producer first and the portfolio executor second. There is no extra day shift.

- Target notional is weight × post-cost account NAV; total target weights cannot exceed 1. Quantities are rounded down. A configurable conservative fee/slippage reserve avoids financing a nominal 1x portfolio with extra borrowing.
- BTC and ETH route only to dynamically resolved **UBTC/USDC and UETH/USDC spot markets**. Existing BTC/ETH perp holdings are separate positions to EXIT, not silently counted as spot. Other exact-identity main-DEX coins route to perps at leverage setting **1x**. No `BASE`, static altcoin permission list, LUNA/LUNC substitution, automatic transfer, borrow action or account-mode change exists.
- Close/reduce every independent unwanted position first, then read actual balances and recompute ENTRY quantities. A missing ENTRY market is reported for that leg and does not suppress EXITs. Available other target legs can still enter after needed EXITs finish.
- Place post-only **Alo** limits; default timeout **300 seconds**, configurable in `/etc/trendatlas-clean/policy.json`. After a confirmed fill/cancellation, recompute the remaining quantity and use a price-bounded **IOC** taker fallback (default cap 50 bp). Never place fallback while cancellation/submission is uncertain.
- Respect market size/price precision and the default $10 minimum; perp reduce-only closes can be smaller. Untradeable spot/entry dust is exposed explicitly, never advertised as zero. Small portfolio discrepancies within the configured 1% NAV tolerance do not generate endless resizing.
- SQLite WAL/FULL stores immutable daily semantic targets, CLOIDs **before** submission and a durable monotonic signing nonce. Restart recovers existing CLOIDs, including orders from a preceding day. A lost HTTP response is queried by CLOID, not blindly resent. Genuine uncertainty returns `RECONCILE_REQUIRED` with the affected CLOID and blocks further ENTRY while independent EXITs remain possible.
- A completed same-day invocation only refreshes account readback and sends no new orders. Different weights for an already frozen execution day are rejected explicitly. Merely changing code/input provenance with the same decision does not block producer resume: the original signal and new verification observations are retained.
- The new config is reread before every signed mutation. The signal producer never submits orders.

## Readback and limits

At **2026-10-18 14:52:00 UTC**, the new adapter directly queried only Hyperliquid `/info`: `unifiedAccount`, equity/free USDC **86.869106**, **0 positions**, **0 open orders**, no unresolved entry dependencies. The adapter discovered 11 perp DEXs and the actual UBTC/UETH USDC spot markets. Details: `execution_public_preflight.json`. No signer was loaded and no `/exchange` request was sent.

For unified accounts, spot clearinghouse balances/holds are the balance source; individual perp account values are not added again. Position and order readback covers all reported perp DEXs. Standard accounts are represented separately; missing spendable collateral is reported rather than silently transferred. Portfolio-margin borrowing mode is unsupported for ENTRY; known position EXITs remain possible.

After operator deployment, inspect:

- `/var/lib/trendatlas-clean-install/status.json`: install/activation phase.
- `/var/lib/trendatlas-clean/state/signal.json`: **model decision**, not holdings.
- `/var/lib/trendatlas-clean/state/execution_receipt.json`: actual account reconciliation, fills, dust, pending orders.
- `/var/lib/trendatlas-clean/state/execution.sqlite3` and its online backup: durable execution recovery.
- `/var/lib/trendatlas-clean/state/execution_preflight.json`: read-only plan, never the live receipt.

The old dashboard/publisher is **not switched by this executor task**. It must not infer Clean account exposure or PnL from model weights. Historical funding/cash-yield assumptions remain research assumptions. Exact close-to-close return identity does not prove that 00:10 orders fill at the preceding close. No claim of guaranteed future profitability or native Windows verification is made.

## Primary API references

- Official account abstraction and balance semantics: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes
- Official exchange API (Alo, IOC, spot asset IDs, leverage): https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
- Official info API (master account queries, order status and spot remapping): https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Official SDK signing primitives, pinned package 0.24.0: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
