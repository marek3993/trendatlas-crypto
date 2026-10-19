# Clean 50/50 — TypeScript multi-account continuation

This supersedes the single-key Python deployment in the earlier PR commits. The runtime base is the existing production `web/` tree at `e85712b614db9d9faeae59cf6216aaba0470f539`, imported because PR parent `350fbbcf` did not contain it.

## Signing and execution

The existing backend joins `hyperliquid_agent_authorizations`, `hyperliquid_accounts` and `hyperliquid_agent_secrets`. It decrypts each consenting user's agent key in memory with the existing AES-256-GCM protector and `TRENDATLAS_AGENT_KEK_B64` from `/etc/trendatlas-production/multi-account.env`. No key is printed, copied into Git, exported to a systemd signing credential or shared across users.

Read-only metadata confirmed that the connected owner account ending E856 has an authorized **TA-f56c7bf7** agent and an encrypted secret. The separate exchange agent named **TrendAtlasProd** is not the selected authorization row. This change uses the selected per-user authorization, validates the derived agent address, master binding, exact approved agent name and expiry, and preserves each user's trading preference.

`signal.json.ciel_vahy` is the common portfolio. Close D applies to D+1, without another lag. BTC/ETH route only to the unique UBTC/UETH-USDC spot market identified from current metadata; other signals require the original exact perpetual identity. Existing BTC/ETH perps are reductions, not replacement spot exposure. There is no alias substitution, automatic transfer or borrowing.

The TS planner ports the Python cost-reserved NAV, size flooring, exchange dust and independent EXIT behavior. It sizes to each account's own fresh equity. All reductions precede entries; retained/entered perps must use 1x. Each order intent, price, time-in-force, maker deadline, CLOID and signed expiry is persisted before submit. Maker orders wait up to the configured timeout (default 300 seconds); cancellation must have terminal CLOID and account readback before the residual IOC. The IOC price is bounded to 50 bps from the original attempt's reference. Ambiguous submissions cannot be blindly resent. Completed same-day portfolios receive readback only.

The additive Supabase migration `20261018172656_clean_portfolio_execution` has been applied and validated. It preserves existing RLS, secrets, consent and journals, adds frozen portfolio/order evidence and enforces one Clean target per account/day. Zero Clean execution rows were created in this authoring session. Future installations validate against this prepared schema; they do not require a database password or copy secrets.

## Operator deployment

The pinned PowerShell command in the PR handoff enters `$HOME\Downloads\ta-clean`, fetches the exact commit with Git, checks it out detached, and sends `deploy/clean_5050/install_multi_account.py` through SSH stdin to `ubuntu@57.129.127.49`, using the existing `trendatlas_research_admin_20260928` key and a 15-second connection timeout. Failed fetch/checkout stops the command before installation. It does not use `raw.githubusercontent.com`, whose DNS resolution failed on the operator laptop.

The installer runs independently on VPS after scheduling. `INSTALL_SCHEDULED_ON_VPS` only acknowledges the start. Its private report is `/var/lib/trendatlas-clean-install/status.json`.

Before activation it verifies the old phase68g is disabled, builds an isolated release, runs Python and TS tests plus typecheck/build, checks all 18 historical checkpoints, builds the current all-USDT signal and public metrics, then performs read-only checks for every enrolled account. The new unit reads the existing EnvironmentFile through systemd. Only this operator invocation clears the Clean kill switch and starts the Clean unit. It never clears the old kill switch or starts `mrv1-production`.

`CLEAN_MULTI_ACCOUNT_LIVE_AND_ALIGNED` requires actual per-account receipts. Any possible-submission failure is reported as `INSTALL_FAILED_RECONCILE_REQUIRED`; there is no old-strategy rollback. Repeating the installer while Clean is active does not replace the release or submit another run.

`install_vps.py`, its old bootstrap and `execute_clean_5050.py` now fail explicitly. The Python portfolio/execution modules remain as simulation and reference code only.

## Public website

- `app.py` now presents only Clean 50/50; old phase67j/68g metrics, charts and barometer are removed.
- The Next.js public home page has SK/EN copy, four performance cards, an accessible logarithmic Clean/BTC chart, calendar-year returns, cash days and assumptions. The signed-in dashboard has a separate model target from `signal.json` and real account data from Hyperliquid.
- All full-period cards and cash days use 2021-01-01 through the same end date. CAGR compounds daily net returns using 365.25 days/year. The last-12-month card and BTC comparison use one matching trailing window.
- Daily runner artifacts are `clean5050_metrics.json` and `clean5050_timeseries.csv`; the CSV checksum is bound in the JSON. Partial or mismatched publications show unavailable. Old files are never a fallback.
- After an operator-run cycle, the server publishes only these model artifacts and the signal to versioned public Supabase Storage objects, then advances one manifest. Account receipts and keys are never published. Web rendering reads these objects (or an explicit local artifact directory).
- Real balances include spot BTC/ETH valuation and remain separate from model returns. Performance only uses exchange history; unavailable history remains unavailable.
- Funding gaps are disclosed. The 4% cash interest and close-price fill are model assumptions. A scheduled 00:10 execution is not claimed to fill at the prior close.
- The supplied wording asserting that parameters were not selected from historical results was changed to verifiable wording: fixed supplied parameters, history already inspected, no untouched out-of-sample claim.

Pushing the PR is not deployment of the external public website. The VPS command installs the producer/executor and publishes data; the frontend hosting must deploy this PR's `web/` or `app.py`. The repository homepage points to https://trendatlas-accounts.vercel.app. The connected Vercel tool returned no available teams, so its deployment configuration and production cutover were not verified. No public URL cutover is claimed.

## Validation and remaining limits

See `MULTI_ACCOUNT_AUDIT.json` for exact test counts, source commits, metric comparison and known limits. No VPS SSH session, real order, cancellation, leverage change or actual frontend cutover was performed here. Native VPS validation remains part of the operator command. Full-universe historical metrics can differ from the frozen 59-coin reference; their universe is recorded in the artifact.

The security advisor reported no new issue with the changed execution tables. Its existing server-only tables intentionally have no browser RLS policy; the unrelated existing [Auth leaked-password setting](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection) was not changed.

## Reference metric comparison (2021-01-01 through 2026-10-17)

The requested numerical acceptance target is **not fully reproduced**. Do not promote 83.5% as a measured result of this replay. With the frozen 59-coin reference prices and available observed Binance funding, the existing daily-drift/cost-reserved replay gives:

| Metric | Requested | Computed public accounting |
| --- | ---: | ---: |
| CAGR | 83.5% | 82.99245% |
| Sharpe | 1.37 | 1.36134 |
| Max drawdown | -35.9% | -36.05525% |
| Last 12 months | +39.3% | +38.92533% |
| Last 12 months drawdown | -14.0% | -13.97427% |
| BTC, matching last 12 months | -23.4% | -23.43347% |

A diagnostic that charges fees/slippage only on changes of target weights reproduces the supplied **2021–2025** yearly results to their stated precision: +476.6%, +5.9%, +83.8%, +144.4%, -11.3%. This is evidence of a cost-method difference, not proof of the author's exact implementation. That diagnostic gives 83.41514% CAGR, 1.36536 Sharpe, -35.93033% drawdown, +39.14667% trailing return and +38.00853% for 2026, so it still does not reproduce every requested number. Its formula is `gross_return - abs(held.diff()) * blended_fee - turnover * 5bps - funding + cash_interest`, with `held = decisions.shift(1)`. It omits the existing replay's price-drift rebalancing and post-cost NAV adjustment and is **not substituted for the public ledger**.

The funding REST endpoint returned HTTP 451 in this environment. Public monthly archives supplied observed history through September 2026. Missing October observations and absent original PEPEUSDT/SHIBUSDT funding remain explicit BTC/default proxies: 69 affected invested days in the full period, 17 in the trailing year. No rate was fabricated and no renamed contract was silently substituted. The remaining 2026 discrepancy cannot be certified without the reference funding inputs/cost implementation. The production runner retries the official funding REST source on VPS and discloses any remaining proxies.

All values on the page come from the generated ledger, not these acceptance numbers. The production all-USDT universe can produce different historical results from the frozen 59-coin reference; the exact universe and input hashes travel with the artifact.

## Installer manifest repair — 2026-10-19

The operator reported that 1f46a946 stopped before activation: 248/250 TS tests passed, while two source-bundle boundary tests fell back to Git because the release lacked `BUNDLE_MANIFEST.json`. `unpack()` now preserves that file after validating the source entries. The two TS tests remain unchanged. The new regression checks the release-root manifest and its exact archive bytes, and the rebuilt installer is verified by calling its embedded `unpack()` before running the suites in a Git-free directory. See `INSTALLER_MANIFEST_FIX_20261019.md` for the audit. Phase68g remains disabled; no VPS activation was performed during this repair.
