from __future__ import annotations

import csv
import io
import time
import zipfile
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

BASE = "https://data.binance.vision/data/spot"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT"]
INTERVAL = "1d"
OUT_DIR = Path("data/ohlcv")


def month_iter(start_year: int, start_month: int, end_year: int, end_month: int):
    y, m = start_year, start_month
    while (y < end_year) or (y == end_year and m <= end_month):
        yield y, m
        m += 1
        if m == 13:
            m = 1
            y += 1


def current_ym():
    today = date.today()
    return today.year, today.month


def build_monthly_url(symbol: str, year: int, month: int) -> str:
    return f"{BASE}/monthly/klines/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{year}-{month:02d}.zip"


def build_daily_url(symbol: str, year: int, month: int, day: int) -> str:
    return f"{BASE}/daily/klines/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{year}-{month:02d}-{day:02d}.zip"


def fetch_zip_rows(url: str) -> list[list[str]]:
    try:
        with urlopen(url, timeout=60) as resp:
            data = resp.read()
    except HTTPError as e:
        if e.code == 404:
            return []
        raise

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        if not names:
            return []
        with zf.open(names[0]) as f:
            text = f.read().decode("utf-8", errors="replace")

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []

    if rows and rows[0] and rows[0][0].lower() in {"open time", "open_time", "date"}:
        rows = rows[1:]

    return rows


def ts_to_date_str(ts_raw: str) -> str:
    ts = int(float(ts_raw))
    if ts > 10**15:  # microseconds
        ts = ts // 1000
    elif ts > 10**12:  # milliseconds
        ts = ts
    else:
        ts = ts * 1000
    return time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))


def normalize_rows(rows: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    for r in rows:
        if len(r) < 6:
            continue
        out.append([
            ts_to_date_str(r[0]),
            r[1],
            r[2],
            r[3],
            r[4],
            r[5],
        ])
    return out


def download_symbol(symbol: str) -> int:
    year_now, month_now = current_ym()
    all_rows: dict[str, list[str]] = {}

    for y, m in month_iter(2017, 1, year_now, month_now):
        url = build_monthly_url(symbol, y, m)
        rows = normalize_rows(fetch_zip_rows(url))
        if rows:
            for r in rows:
                all_rows[r[0]] = r
            print(f"{symbol}: monthly {y}-{m:02d} -> {len(rows)}", flush=True)

    for day in range(1, 32):
        url = build_daily_url(symbol, year_now, month_now, day)
        rows = normalize_rows(fetch_zip_rows(url))
        if rows:
            for r in rows:
                all_rows[r[0]] = r
            print(f"{symbol}: daily {year_now}-{month_now:02d}-{day:02d} -> {len(rows)}", flush=True)

    final_rows = [all_rows[k] for k in sorted(all_rows.keys())]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{symbol}_1d.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        w.writerows(final_rows)

    print(f"{symbol}: final rows = {len(final_rows)} | saved -> {out_path}", flush=True)
    return len(final_rows)


def main() -> None:
    for symbol in SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        download_symbol(symbol)


if __name__ == "__main__":
    main()