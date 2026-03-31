# market_regime_v1

Prvá kostra interného research agregátora.

## Čo je hotové
- výpočet základných ST / LT / MR feature
- robustná normalizácia na spoločnú škálu
- agregácia do Directional Bias + Confidence + Regime
- ranking assetov
- odporúčaná páka
- jednoduchý paper trading loop
- abstraktné rozhranie pre neskoršie exchange adaptéry

## Čo ešte nie je hotové
- reálne data ingestory
- plný set 20+20+20 indikátorov
- backtest s fee/slippage modelom
- Streamlit / web dashboard
- reálne Binance / Hyperliquid / Gate adaptéry

## Spustenie
```bash
cd market_regime_v1
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python examples/run_demo.py
```

## Ďalší sprint
1. doplniť ingest z CSV / API
2. doplniť plný indicator pool
3. urobiť walk-forward backtester
4. pridať coin screener
5. až potom paper/live adapter
