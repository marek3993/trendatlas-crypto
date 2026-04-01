from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "ohlcv"
API_URL = "https://api.binance.com/api/v3/klines"
INTERVAL = "1d"
ONE_DAY_MS = 24 * 60 * 60 * 1000
FIELDNAMES = ["date", "open", "high", "low", "close", "volume"]

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
    "TRXUSDT",
    "DOTUSDT",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def today_start_utc() -> datetime:
    now = utc_now()
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def target_last_closed_date() -> str:
    return (today_start_utc() - timedelta(days=1)).date().isoformat()


def target_end_ms() -> int:
    return int(today_start_utc().timestamp() * 1000) - 1


def date_to_open_ms(date_text: str) -> int:
    dt = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def open_ms_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def read_existing_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    out: list[dict[str, str]] = []
    for row in rows:
        date_text = str(row.get("date", "")).strip()
        if not date_text:
            continue
        out.append(
            {
                "date": date_text,
                "open": str(row.get("open", "")).strip(),
                "high": str(row.get("high", "")).strip(),
                "low": str(row.get("low", "")).strip(),
                "close": str(row.get("close", "")).strip(),
                "volume": str(row.get("volume", "")).strip(),
            }
        )
    return out


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def merge_rows(existing: list[dict[str, str]], fresh: list[dict[str, str]]) -> list[dict[str, str]]:
    by_date: dict[str, dict[str, str]] = {}
    for row in existing + fresh:
        by_date[str(row["date"])] = row
    return [by_date[d] for d in sorted(by_date.keys())]


def fetch_klines(symbol: str, start_ms: int, end_ms: int, session: requests.Session) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    cursor = start_ms

    while cursor <= end_ms:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }

        payload = None
        last_error: Exception | None = None

        for _ in range(3):
            try:
                resp = session.get(API_URL, params=params, timeout=30)
                resp.raise_for_status()
                payload = resp.json()
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                time.sleep(1.0)

        if last_error is not None:
            raise RuntimeError(f"{symbol}: Binance fetch failed: {last_error}") from last_error

        if not payload:
            break

        batch: list[dict[str, str]] = []
        for item in payload:
            batch.append(
                {
                    "date": open_ms_to_date(int(item[0])),
                    "open": str(item[1]),
                    "high": str(item[2]),
                    "low": str(item[3]),
                    "close": str(item[4]),
                    "volume": str(item[5]),
                }
            )
        rows.extend(batch)

        last_open_ms = int(payload[-1][0])
        next_cursor = last_open_ms + ONE_DAY_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor

        if len(payload) < 1000:
            break

        time.sleep(0.15)

    return rows


def refresh_symbol(symbol: str, session: requests.Session, target_date: str, end_ms: int) -> tuple[int, str]:
    path = OUT_DIR / f"{symbol}_1d.csv"

    existing = read_existing_rows(path)
    existing_last = existing[-1]["date"] if existing else ""

    if existing_last and existing_last >= target_date:
        print(f"[LEGACY] {symbol} unchanged last_date={existing_last}", flush=True)
        return 0, existing_last

    start_ms = date_to_open_ms(existing_last) + ONE_DAY_MS if existing_last else date_to_open_ms("2019-01-01")
    fresh = fetch_klines(symbol=symbol, start_ms=start_ms, end_ms=end_ms, session=session)

    merged = merge_rows(existing, fresh)
    merged = [row for row in merged if row["date"] <= target_date]

    if not merged:
        raise RuntimeError(f"{symbol}: no rows after refresh")

    added = max(len(merged) - len(existing), 0)
    write_rows(path, merged)

    last_date = merged[-1]["date"]
    print(f"[LEGACY] {symbol} rows_added={added} last_date={last_date} path={path}", flush=True)
    return added, last_date


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    target_date = target_last_closed_date()
    end_ms = target_end_ms()

    print(f"[LEGACY] target_last_closed_date={target_date}", flush=True)

    session = requests.Session()
    results: list[tuple[str, int, str]] = []

    for symbol in SYMBOLS:
        added, last_date = refresh_symbol(symbol, session, target_date, end_ms)
        results.append((symbol, added, last_date))

    stale = [symbol for symbol, _, last_date in results if last_date < target_date]
    if stale:
        raise RuntimeError(
            f"Legacy refresh incomplete. target_last_closed_date={target_date} stale_symbols={','.join(stale)}"
        )

    total_added = sum(added for _, added, _ in results)
    print(f"[LEGACY] total_symbols={len(results)}", flush=True)
    print(f"[LEGACY] total_rows_added={total_added}", flush=True)
    print(f"[LEGACY] out_dir={OUT_DIR}", flush=True)
    print("[LEGACY] DONE", flush=True)


if __name__ == "__main__":
    main()