from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol: str, interval: str = "1d", limit: int = 1000):
    start_time = 0
    out = []

    while True:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }
        if start_time > 0:
            params["startTime"] = start_time

        url = BASE_URL + "?" + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not isinstance(data, list):
            raise RuntimeError(f"Neočakávaná odpoveď API: {data}")

        if not data:
            break

        out.extend(data)

        if len(data) < limit:
            break

        last_open_time = data[-1][0]
        start_time = last_open_time + 1
        time.sleep(0.2)

    dedup = {}
    for row in out:
        dedup[row[0]] = row

    rows = [dedup[k] for k in sorted(dedup)]
    return rows


def save_csv(rows, output_path: str):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])

        for r in rows:
            open_time_ms = int(r[0])
            date_str = time.strftime("%Y-%m-%d", time.gmtime(open_time_ms / 1000))
            writer.writerow([date_str, r[1], r[2], r[3], r[4], r[5]])


def main():
    if len(sys.argv) < 3:
        print("Použitie: python fetch_binance_klines.py BTCUSDT data\\ohlcv\\BTCUSDT_1d.csv")
        raise SystemExit(1)

    symbol = sys.argv[1]
    output_path = sys.argv[2]

    rows = fetch_klines(symbol=symbol, interval="1d", limit=1000)
    if not rows:
        raise RuntimeError("Nepodarilo sa stiahnuť žiadne kline dáta.")

    save_csv(rows, output_path)
    print(f"OK: uložené {len(rows)} riadkov do {output_path}")


if __name__ == "__main__":
    main()
