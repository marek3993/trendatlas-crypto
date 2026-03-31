from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "ohlcv_4h"

TARGET_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
]

BASE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL = "4h"
LIMIT = 1000

# začne dosť skoro; Binance aj tak vráti až od reálneho zalistovania symbolu
START_DATE = "2017-01-01 00:00:00"


def fetch_klines(symbol: str, start_time: int | None = None, end_time: int | None = None) -> list:
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": LIMIT,
    }
    if start_time is not None:
        params["startTime"] = int(start_time)
    if end_time is not None:
        params["endTime"] = int(end_time)

    url = f"{BASE_URL}?{urlencode(params)}"
    with urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def klines_to_df(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    data = []
    for r in rows:
        data.append(
            {
                "date": pd.to_datetime(r[0], unit="ms"),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
        )

    df = pd.DataFrame(data)
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return df


def download_full_symbol(symbol: str) -> pd.DataFrame:
    all_rows = []
    start_time = int(pd.Timestamp(START_DATE).timestamp() * 1000)
    chunk_no = 0
    prev_last_open_time = None

    while True:
        rows = fetch_klines(symbol, start_time=start_time)
        if not rows:
            break

        chunk_no += 1
        all_rows.extend(rows)

        last_open_time = int(rows[-1][0])
        print(
            f"{symbol}: chunk {chunk_no}, rows v chunke = {len(rows)}, total rows ~ {len(all_rows)}",
            flush=True,
        )

        # ak prišlo menej než LIMIT, sme na konci histórie
        if len(rows) < LIMIT:
            break

        # ochrana proti zaseknutiu
        if prev_last_open_time is not None and last_open_time <= prev_last_open_time:
            break

        prev_last_open_time = last_open_time
        start_time = last_open_time + 1
        time.sleep(0.15)

    return klines_to_df(all_rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for symbol in TARGET_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        df = download_full_symbol(symbol)

        out_path = OUT_DIR / f"{symbol}_4h.csv"
        df.to_csv(out_path, index=False)

        print(f"{symbol}: final rows = {len(df)}", flush=True)
        if len(df) > 0:
            print(f"{symbol}: od {df['date'].iloc[0]} do {df['date'].iloc[-1]}", flush=True)
        print(f"{symbol}: uložené -> {out_path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()