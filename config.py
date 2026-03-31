from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")

    data_dir: Path = Path("data")
    raw_dir: Path = Path("data/raw/binance")

    binance_rest_base: str = "https://fapi.binance.com"
    request_timeout_sec: int = 20
    rest_sleep_sec: float = 0.12

    kline_limit: int = 1500
    funding_limit: int = 1000
    stats_limit: int = 500

    parquet_engine: str = "pyarrow"
    derived_periods: tuple[str, ...] = ("5m", "1h")
    basis_contract_type: str = "PERPETUAL"

    datasets: tuple[str, ...] = field(
        default=(
            "klines_5m",
            "index_klines_5m",
            "premium_klines_5m",
            "funding_history",
            "funding_info_snapshots",
            "basis_5m",
            "basis_1h",
            "open_interest_hist_5m",
            "open_interest_hist_1h",
            "taker_buy_sell_5m",
            "taker_buy_sell_1h",
            "global_long_short_5m",
            "global_long_short_1h",
            "top_trader_position_ratio_5m",
            "top_trader_position_ratio_1h",
            "top_trader_account_ratio_5m",
            "top_trader_account_ratio_1h",
        )
    )


SETTINGS = Settings()