from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd

from binance_rest import BinanceFuturesREST
from config import SETTINGS
from storage import ensure_dirs, upsert_dedup


def utc_day_start(day_str: str) -> datetime:
    return datetime.fromisoformat(day_str).replace(tzinfo=timezone.utc)


def to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def split_and_store(
    df: pd.DataFrame,
    dataset: str,
    symbol: str,
    ts_col: str,
    dedup_keys: list[str],
) -> None:
    if df.empty:
        print(f"  -> {dataset}: empty")
        return

    tmp = df.copy()

    if "symbol" in dedup_keys and "symbol" not in tmp.columns:
        tmp["symbol"] = symbol

    if ts_col not in tmp.columns:
        raise KeyError(f"{dataset}: missing ts column '{ts_col}'")

    tmp["_day"] = pd.to_datetime(tmp[ts_col], utc=True).dt.date

    for day, part in tmp.groupby("_day"):
        part = part.drop(columns="_day").reset_index(drop=True)
        upsert_dedup(part, dataset=dataset, symbol=symbol, day=day, keys=dedup_keys)

    print(f"  -> {dataset}: {len(df)} rows")


def backfill_symbol(client: BinanceFuturesREST, symbol: str, start_dt: datetime, end_dt: datetime) -> None:
    pair = client.symbol_to_pair(symbol)
    start_ms = to_ms(start_dt)
    end_ms = to_ms(end_dt)

    print(f"\n[{symbol}]")

    df = client.get_klines(symbol, "5m", start_ms, end_ms)
    split_and_store(df, "klines_5m", symbol, "ts_open_utc", ["symbol", "ts_open_utc"])

    df = client.get_index_klines(pair, "5m", start_ms, end_ms)
    split_and_store(df, "index_klines_5m", symbol, "ts_open_utc", ["pair", "ts_open_utc"])

    df = client.get_premium_klines(symbol, "5m", start_ms, end_ms)
    split_and_store(df, "premium_klines_5m", symbol, "ts_open_utc", ["symbol", "ts_open_utc"])

    df = client.get_funding_rate(symbol, start_ms, end_ms)
    split_and_store(df, "funding_history", symbol, "funding_time_utc", ["symbol", "funding_time_utc"])

    for period in SETTINGS.derived_periods:
        df = client.get_basis(pair, period, start_ms, end_ms, SETTINGS.basis_contract_type)
        split_and_store(df, f"basis_{period}", symbol, "ts_utc", ["symbol", "ts_utc"])

        df = client.get_open_interest_hist(symbol, period, start_ms, end_ms)
        split_and_store(df, f"open_interest_hist_{period}", symbol, "ts_utc", ["symbol", "ts_utc"])

        df = client.get_taker_volume(symbol, period, start_ms, end_ms)
        split_and_store(df, f"taker_buy_sell_{period}", symbol, "ts_utc", ["symbol", "ts_utc"])

        df = client.get_global_long_short(symbol, period, start_ms, end_ms)
        split_and_store(df, f"global_long_short_{period}", symbol, "ts_utc", ["symbol", "ts_utc"])

        df = client.get_top_trader_position_ratio(symbol, period, start_ms, end_ms)
        split_and_store(df, f"top_trader_position_ratio_{period}", symbol, "ts_utc", ["symbol", "ts_utc"])

        df = client.get_top_trader_account_ratio(symbol, period, start_ms, end_ms)
        split_and_store(df, f"top_trader_account_ratio_{period}", symbol, "ts_utc", ["symbol", "ts_utc"])


def backfill_funding_info_snapshot(client: BinanceFuturesREST, snapshot_dt: datetime) -> None:
    df = client.get_funding_info()
    if df.empty:
        print("[ALL] funding_info_snapshots: empty")
        return

    df = df.copy()
    df["snapshot_utc"] = snapshot_dt
    split_and_store(df, "funding_info_snapshots", "ALL", "snapshot_utc", ["symbol", "snapshot_utc"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Binance USDⓈ-M raw datasets")
    parser.add_argument("--start", required=True, help="napr. 2026-02-22")
    parser.add_argument("--end", required=True, help="napr. 2026-03-23")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()

    start_dt = utc_day_start(args.start)
    end_dt = utc_day_start(args.end) + timedelta(days=1) - timedelta(milliseconds=1)

    client = BinanceFuturesREST()

    print("[START]")
    backfill_funding_info_snapshot(client, datetime.now(timezone.utc))

    for symbol in SETTINGS.symbols:
        backfill_symbol(client, symbol, start_dt, end_dt)

    print("\nDONE")


if __name__ == "__main__":
    main()