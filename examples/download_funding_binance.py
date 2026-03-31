from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT"]
LIMIT = 1000
OUT_DIR = Path("data/funding")


def ms(dt: str) -> int:
    return int(datetime.fromisoformat(dt).replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_all_funding(symbol: str, start_time: int) -> list[dict]:
    rows: list[dict] = []

    while True:
        params = {
            "symbol": symbol,
            "limit": LIMIT,
            "startTime": start_time,
        }

        url = BASE_URL + "?" + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not isinstance(data, list):
            raise RuntimeError(f"{symbol}: zlá API odpoveď: {data}")

        if not data:
            break

        rows.extend(data)
        print(f"{symbol}: {len(rows)} funding rows", flush=True)

        if len(data) < LIMIT:
            break

        start_time = int(data[-1]["fundingTime"]) + 1
        time.sleep(0.25)

    dedup = {}
    for row in rows:
        dedup[int(row["fundingTime"])] = row

    out = [dedup[k] for k in sorted(dedup)]
    return out


def save_csv(symbol: str, rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{symbol}_funding.csv"

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["funding_time", "date", "funding_rate", "mark_price"])

        for r in rows:
            ts = int(r["fundingTime"])
            date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts / 1000))
            writer.writerow([
                ts,
                date_str,
                r.get("fundingRate", ""),
                r.get("markPrice", ""),
            ])

    print(f"{symbol}: uložené -> {path}", flush=True)


def main() -> None:
    start_time = ms("2019-01-01 00:00:00")

    for symbol in SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        rows = fetch_all_funding(symbol, start_time=start_time)
        save_csv(symbol, rows)
        print(f"{symbol}: final funding rows = {len(rows)}", flush=True)


if __name__ == "__main__":
    main()