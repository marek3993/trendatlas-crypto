# TrendAtlas Clean 50/50 — implementation and handoff

**Signal implementation validated. NOT deployed. No live multi-asset executor is implemented by this change.**

Marek withdrew the seven-day dry-run requirement. There is no seven-day waiting gate in the contract or runner. This implementation does not activate trading, issue an order, or claim that phase68g is disabled.

## Implemented

- Standalone `src/trendatlas_clean/` package; no imports from phase42/63/66/67/68 or their stored model returns.
- Exact supplied features: 20/40/80/160-day trend, 20/40/80-day volatility-normalized score, sample standard deviation over 60 days with 40 observations, original 30-day quote-volume median with 20 observations, 365 observed closes.
- Reference CLEAN state machine, strict hysteresis `challenger > held + 0.25`, BTC preference +0.25, fixed 50/50 CLEAN + BTC-trend allocation, combined BTC weight up to 1.0.
- First missing original close immediately removes a coin from CLEAN eligibility, as explicitly clarified in the attachment. Three-day ffill is only used for indicators and price returns.
- Original LUNA is archive-only and cut after 2022-05-13. No original/new-LUNA price splicing.
- Signals record the decision at close D and intended holdings during D+1; the signal is not shifted. Only accounting applies yesterday's decision to today's return.
- Bounded public-data GET downloader using Binance's documented market-data-only endpoint, with archive support and source hashes. The private/account/trading API is not used.
- Frozen 59-coin replay and separate all-USDT discovery. The latter combines current exchangeInfo with historical archive prefixes and versioned stable/wrapped/leveraged exclusions. It has not been replay-certified in this session; new token classifications require periodic review.
- Atomic signal writes, SQLite WAL with FULL synchronization, idempotent same-day recovery, immutable decision bindings, online SQLite backup. Revised same-day inputs preserve the original signal and produce an explicit error.
- Geometric CAGR, price-drift rebalancing costs and explicit spot/perp fee, slippage, cash-yield and funding assumptions; model PnL is not account PnL.
- Isolated signal-only systemd service and daily 00:10 UTC persistent timer, with 15-minute failure retries. No credentials or live execution modules are mounted/imported.
- Operator-only phase68g shutdown script, with runtime-path validation and kill-switch/systemd readback. It is unit-tested, not run on the VPS.

## Actual validation

Public Binance data was fetched independently through 2026-10-17 for all 59 symbols, including delisted history. The reference module in `tests/fixtures/clean_5050_reference.py` is the exact supplied core, not a reimplementation used to validate itself.

| Check | Observed result |
|---|---:|
| Supplied historical checkpoints | 18 / 18 match |
| Compared daily signals since 2021 | 2,116 / 2,116 match |
| Full-history reference signal differences | 0 |
| Independent prefix/truncation dates | 25 / 25 match |
| Future-price/volume mutation changes to earlier decisions | 0 |
| `return[t] - sum(weights[t-1] * price_return[t])` max absolute error | 0 |
| Last reference decision, close 2026-10-17 | CASH 1.0 |

There are 178 actual allocation changes since 2021 when carrying the previous historical allocation into the interval. Counting the initial state of the 2021 interval as an observation gives 179, matching the supplied count's convention. Neither number is an exchange fill count.

The fetched funding API returned HTTP 451 in this environment. Accounting therefore uses the supplied explicitly labelled fallback policy, not observed funding: BTC rate where available, otherwise 0.0003/day. With these proxies, the diagnostic replay gave 86.7356% CAGR / -35.2018% drawdown from 2021, and +37.8383% over the last 365 days. **These are not a reproduction of the user's 83.5% result, not venue-certified, not untouched OOS, and not deployable performance evidence.** Signals do not depend on funding, so this does not explain away a failed signal checkpoint: all signal checkpoints actually passed.

Daily price replay assumes fills at the preceding close and explicit costs. It does not prove fills at 00:10 UTC. Cash yield 4% is a model assumption, not a statement about what the real account earns. No missing funding is labelled observed zero. Unpriceable held returns invalidate metrics; hypothetical exits without an observed price are flagged rather than claimed as exchange fills.

Exact source bindings and validation results are in `validation.json` in this directory. No generated `data/` or `outputs/` was committed.

## Reproduce

From this feature checkout, Python 3.12+:

```bash
python -m pip install -r requirements-clean-5050.txt
python -m unittest discover -s tests -p test_clean_5050.py -v
python scripts/research/fetch_clean_5050_data.py --data-dir /var/lib/trendatlas-clean/reference-data --end 2026-10-17
python scripts/research/validate_clean_5050.py --data-dir /var/lib/trendatlas-clean/reference-data --end 2026-10-17 --output-dir /var/lib/trendatlas-clean/reference-validation --prefix-tests 25
```

An arbitrary historical reference run is separate from the daily producer. The daily producer requires the current last closed UTC day and a fresh observed BTC close. A stale BTC input is an input error, not an invented CASH decision.

```bash
python scripts/production/run_clean_5050.py --data-dir /var/lib/trendatlas-clean/reference-data --state-dir /var/lib/trendatlas-clean/state --universe reference --refresh
```

For all-USDT signal collection only, `sudo bash deploy/clean_5050/install_signal_service.sh` installs `/opt/trendatlas-clean` and `trendatlas-clean-signal.timer`. **This is NOT a live cutover command.** It does not change the production timer, production checkout, account, or dashboard. No mandatory observation period is imposed.

## One operator action to disable phase68g

From a Windows PowerShell checkout containing this feature branch, with the existing SSH key and network access to the VPS:

```powershell
Get-Content -Raw .\scripts\production\disable_phase68g.py | ssh ubuntu@57.129.127.49 "sudo python3 - --repo-root /opt/trendatlas-production/current --apply"
```

The standalone script verifies that the installed production unit points to the supplied root, stops/disables its timer, stops its service, atomically writes `kill_switch=true`, `trading_enabled=false`, `dry_run_enabled=true`, preserves a local config backup, and reads the state back. It never calls the production run or an order endpoint. A failed or ambiguous shutdown returns exit 2; it does not declare the account flat. A read-only exchange reconciliation is still required before any later activation, especially if an old run was in flight.

This command **has not been run**. The authoring environment attempted a read-only SSH command and received `Network is unreachable` on 57.129.127.49 port 22. No password/key was requested, read, changed, or transmitted.

## Remaining live integration — explicit, not a new waiting period

1. On the VPS, inspect the actual production source commit, unit, config and exchange metadata/account state. Do not replace the production checkout with the older main branch: the published manifest declares a different production commit.
2. Extend the canonical executor/intent contract to a portfolio of weights. The existing code accepts one `target_asset`; it cannot be made into a BTC+SOL portfolio by changing a label. Preserve durable per-leg idempotency, account readback and terminal receipts across partial fills/restarts.
3. Resolve actual Hyperliquid spot market identifiers, precisions, minimum notionals and unified-account availability for UBTC/UETH; use actual 1x perp settings for other coins. `routes_metadata` in the new signal is descriptive, not a verified venue mapping or an order plan.
4. Implement and test the requested limit-first/taker fallback. The timeout X was not supplied and is not guessed by this implementation. No submitter or fake activation command is shipped.
5. Confirm the current all-USDT universe, exclusions and data coverage; report differences from the frozen 59-coin reference. Do not silently substitute the 59-coin universe for the requested live universe.
6. Publish Clean-only model metrics with geometric CAGR and a separately sourced actual account view. Existing dashboard/main model has not been switched by this change.
7. After the required tests and runtime verification, the operator may activate the fully implemented canonical path without a seven-day delay. Re-read the current closed-day decision at cutover; do not reuse an expired historical validation signal.

**No claim of LIVE_READY, CUTOVER_COMPLETE, phase68g disabled, or account alignment is made by this delivery.**

## Short access handoff for Marek

Use a Codex/terminal session with the `marek3993/trendatlas-crypto` feature checkout and existing SSH-key access to `ubuntu@57.129.127.49`, plus sudo for the TrendAtlas units. The current authoring environment has no network route to SSH. Keep credentials out of chat. Continue from the tested module and this report; do not repeat the research or add the withdrawn seven-day wait.
