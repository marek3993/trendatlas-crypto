# market_regime_v1

Top-level operator guide for the current DATA refresh flow.

## Official DATA commands

Official DATA refresh entrypoint:

```powershell
python .\scripts\daily_refresh_app_pipeline.py
```

Official DATA freshness or health-check entrypoint:

```powershell
python .\scripts\validation\check_strategy_chain_freshness.py
```

Windows convenience wrapper for the refresh flow:

```powershell
.\run_data_refresh.ps1
```

The wrapper is optional. It only forwards arguments to `scripts/daily_refresh_app_pipeline.py` and does not replace the official Python entrypoint.

## Expected operator workflow

1. Run the refresh entrypoint to rebuild the app-facing data chain.
2. Run the freshness check to confirm the strategy chain is still contiguous and up to date.
3. If the health-check exits non-zero, inspect `outputs/validation/reports/strategy_chain_freshness_report.json` for the first broken stage and missing date.

## What each command does

`scripts/daily_refresh_app_pipeline.py`:
- runs the existing multi-step refresh chain
- preserves the underlying legacy scripts
- writes a timestamped run manifest under `outputs/app_refresh_pipeline/`
- refreshes canonical downstream app export artifacts through the existing materialization step

`scripts/validation/check_strategy_chain_freshness.py`:
- reads the strategy lineage from raw BTC through the canonical app export and live status outputs
- writes `outputs/validation/reports/strategy_chain_freshness_report.json`
- exits with code `1` when it finds the first freshness break

## Common commands

Full refresh:

```powershell
python .\scripts\daily_refresh_app_pipeline.py
```

Full refresh through the wrapper:

```powershell
.\run_data_refresh.ps1
```

Refresh with optional skips:

```powershell
.\run_data_refresh.ps1 --skip-legacy-refresh --skip-macro-refresh
```

Freshness or health-check:

```powershell
python .\scripts\validation\check_strategy_chain_freshness.py
```

## Operational notes

- No `source_of_truth/*` files are part of this flow.
- The app behavior does not change here; this is an operator workflow cleanup only.
- The official refresh script remains `scripts/daily_refresh_app_pipeline.py`.
- The official health-check script remains `scripts/validation/check_strategy_chain_freshness.py`.
