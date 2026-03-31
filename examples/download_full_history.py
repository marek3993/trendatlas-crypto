from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://api.binance.com/api/v3/klines"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "1d"
LIMIT = 1000
OUT_DIR = Path("data/ohlcv")


def fetch_all_klines(symbol: str) -> list[list]:
    start_time = 0
    rows: list[list] = []

    while True:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": LIMIT,
        }
        if start_time > 0:
            params["startTime"] = start_time

        url = BASE_URL + "?" + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not isinstance(data, list):
            raise RuntimeError(f"{symbol}: zlá API odpoveď: {data}")

        if not data:
            break

        rows.extend(data)

        if len(data) < LIMIT:
            break

        start_time = int(data[-1][0]) + 1
        print(f"{symbol}: {len(rows)} riadkov", flush=True)
        time.sleep(0.25)

    dedup = {}
    for row in rows:
        dedup[int(row[0])] = row

    out = [dedup[k] for k in sorted(dedup)]
    return out


def save_csv(symbol: str, rows: list[list]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{symbol}_1d.csv"

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])

        for r in rows:
            open_time_ms = int(r[0])
            date_str = time.strftime("%Y-%m-%d", time.gmtime(open_time_ms / 1000))
            writer.writerow([date_str, r[1], r[2], r[3], r[4], r[5]])

    print(f"{symbol}: uložené do {path}", flush=True)


def main() -> None:
    for symbol in SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        rows = fetch_all_klines(symbol)
        save_csv(symbol, rows)
        print(f"{symbol}: final rows = {len(rows)}", flush=True)


if __name__ == "__main__":
    main()