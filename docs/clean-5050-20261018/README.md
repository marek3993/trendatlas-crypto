> Superseded execution direction: use [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md). The single-key Python executor is not the deployment route. Verified signal math remains unchanged.

# TrendAtlas Clean 50/50 — implementation and handoff

**Signal and portfolio execution implemented and tested. Operator VPS deployment is pending.** See [EXECUTION.md](EXECUTION.md) for the current one-command activation and exact runtime behavior.

Marek withdrew the seven-day dry-run requirement. There is no seven-day waiting gate in the contract or runner. No live activation or order was performed by this authoring session. Marek subsequently supplied a successful phase68g shutdown receipt; the new installer rechecks it before deployment.

## Implemented

- Standalone `src/trendatlas_clean/` package; no imports from phase42/63/66/67/68 or their stored model returns.
- Exact supplied features: 20/40/80/160-day trend, 20/40/80-day volatility-normalized score, sample standard deviation over 60 days with 40 observations, original 30-day quote-volume median with 20 observations, 365 observed closes.
- Reference CLEAN state machine, strict hysteresis `challenger > held + 0.25`, BTC preference +0.25, fixed 50/50 CLEAN + BTC-trend allocation, combined BTC weight up to 1.0.
- First missing original close immediately removes a coin from CLEAN eligibility, as explicitly clarified in the attachment. Three-day ffill is only used for indicators and price returns.
- Original LUNA is archive-only and cut after 2022-05-13. No original/new-LUNA price splicing.
- Signals record the decision at close D and intended holdings during D+1; the signal is not shifted. Only accounting applies yesterday's decision to today's return.
- Bounded public-data GET downloader using Binance's documented market-data-only endpoint, with archive support and source hashes. The private/account/trading API is not used.
- Frozen 59-coin replay and separate all-USDT discovery. The latter combines current exchangeInfo with historical archive prefixes and versioned stable/wrapped/leveraged exclusions. It has not been replay-certified in this session; new token classifications require periodic review.
- Atomic signal writes, SQLite WAL with FULL synchronization, idempotent same-day recovery, immutable decision bindings, online SQLite backup. Different same-day weights preserve the original signal and produce an explicit error; identical weights with newer input/code hashes preserve the original signal and append provenance verification.
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

## Current execution continuation

Marek ran the old-model shutdown helper successfully: applied/verified, old kill switch on, old trading disabled, old timer disabled/inactive and service inactive, zero shutdown orders. This is user-supplied host evidence. A new read-only exchange observation confirmed CASH 86.869106 USDC and no positions/open orders at 14:52 UTC on 18 October.

The portfolio executor, recovery journal, live systemd chain and source-bundle VPS installer are now implemented. See [EXECUTION.md](EXECUTION.md) and [EXECUTION_AUDIT.md](EXECUTION_AUDIT.md). Default maker timeout is 5 minutes, configurable; after confirmed cancellation only the actual remaining quantity falls back to a bounded IOC order. The operator's single installation command runs tests on VPS before activating only Clean. No SSH access or live activation was performed from this environment.

The legacy dashboard is not migrated in this task. It must be switched separately to Clean model metrics and actual account readback; do not interpret old dashboard output as a receipt from the new executor.
