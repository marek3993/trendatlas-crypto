V1 implementácia je rozdelená takto:

1. `features.py`
   - počíta indikátory z OHLCV
2. `scoring.py`
   - normalizácia a agregácia do ST/LT/MR
3. `ranking.py`
   - ranking coinov / assetov
4. `leverage.py`
   - odporúčaná páka
5. `paper.py`
   - prvý paper-trading loop
6. `exchange_base.py`
   - rozhranie pre neskoršie napojenie na Binance / Hyperliquid / Gate

Najprv ladíme len research + paper.
Až potom sa spravia konkrétne adaptéry na burzy.
