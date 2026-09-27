# Offline slow trend research

Base `58e308315d03a4561d53bbbd4019f7392f66e662`; branch `codex/slow-trend-research-20260927`.
Read REPORT.md and AUDIT.md. Only this directory is new. No production registry, runtime, dashboard, account, execution planner, Pi, scheduler, or order endpoint is changed.

Python3.12.10, numpy2.4.1, pandas3.0.2; matplotlib3.11.2 for report figures. Install dependencies in an isolated environment if needed. The optional plotting fallback uses the existing temporary plotting environment; it does not install into production.

```powershell
Set-Location C:/Users/benda/Desktop/ta_slow_trend
python -m unittest discover -s research/slow_trend_20260927 -p test_research.py -v
python research/slow_trend_20260927/audit.py
python research/slow_trend_20260927/verify_saved.py
python research/slow_trend_20260927/extra_outputs.py
python research/slow_trend_20260927/render.py
python research/slow_trend_20260927/release_checks.py
```

Full offline reproduction into a new directory, **no DeepSeek charge**:

```powershell
python research/slow_trend_20260927/run.py --replay-proposals research/slow_trend_20260927/results/designer_events.jsonl --output-dir "$env:TEMP/ta-slow-trend-reproduction"
```

Final recorded verification payloads must match the newly computed development inputs exactly. Three H events additionally preserve the original API payload: they were revalidated after enforcing the already-frozen inverse-vol/equal-risk restriction; the equal-notional proposal was rejected, and no new H call was made. The verification payload is explicitly marked as not sent to the API. Offline replay refuses to call the API if an event is absent. Do not delete or overwrite completed evidence to search for a favorable result. Technical correctness failures are preserved and explained.

Original bounded acquisition (already committed normalized bundles suffice):

```powershell
python research/slow_trend_20260927/data.py
```

Original successful research run, reusing9 development-only API calls from the preserved pre-validation technical attempt and making at most3 new D calls:

```powershell
python research/slow_trend_20260927/run.py --continue-proposals research/slow_trend_20260927/attempts/pre_delay_audit_fix/results/designer_events.jsonl
```

Do not use `--continue-proposals` for routine reproduction: it permits paid calls for missing events. Key is read only from named process or Windows current-user environment entries; no exchange account key or production dotenv is opened. Never put API keys in command arguments, evidence or chat.

Source hierarchy: frozen contract -> exact input hashes -> own-symbol raw observations -> quantity/cash ledger -> staged selection freezes -> immutable results -> report. Old equity/returns/CAGR tables are never inputs.

Spot and actual-perpetual tracks are separate. Perpetual history is Binance USD-M, explicitly CONSERVATIVE_PROXY, not Hyperliquid historical performance or venue certification. Current Hyperliquid rules are documented as evidence, not projected backwards into a fictitious market. Simulated USD assumes USDT/USD1:1; cash has zero return, no FX depeg model. Fees/lot/book depth remain model assumptions, with explicit stresses. Residual positions remain marked and cannot become fictitious year-end fills.

If ledger evidence was partitioned for Git hosting, `python research/slow_trend_20260927/package.py --restore-ledgers` reconstructs the ignored `results/ledgers.zip` before the audit/render commands. Partition and uncompressed member hashes are verified; ZIP container timestamp metadata may differ, while every evidence member remains identical. This operation only creates research evidence inside this directory.

The local `.gitattributes` preserves exact frozen bytes despite Windows `core.autocrlf`. `release_checks.json` summarizes independent replay/accounting tests and publication checks; `GIT_ADD.txt` is the exact path manifest. The full-panel low-drawdown and highest-CAGR rows in REPORT.md are descriptive and validation-rejected, not post-OOS replacements for the frozen finalists. Their unplanned full stresses are explicitly NOT_RUN.
