"""Public GET-only Binance data download; no account, signer, or order endpoints."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from .core import CUTOFF
from .data import REFERENCE_SYMBOLS

MARKET_API = "https://data-api.binance.vision"
ARCHIVE = "https://data.binance.vision/"
BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "tb_base", "tb_quote", "ignore"]
START_MS = int(pd.Timestamp("2017-08-01", tz="UTC").timestamp() * 1000)
_rate_lock = threading.Lock()
_next_request = 0.0


class DataUnavailable(RuntimeError):
    pass


def last_closed_day() -> str:
    return (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date().isoformat()


def _bytes(url: str, *, cache: Path | None = None, missing_ok: bool = False) -> bytes | None:
    """Bounded retries; 400/404 may mean absent data, 451 never means delisted."""
    global _next_request
    key = hashlib.sha256(url.encode()).hexdigest()
    cp = cache / key if cache else None
    if cp and cp.exists():
        return cp.read_bytes()
    for attempt in range(3):
        with _rate_lock:
            delay = max(0, _next_request - time.monotonic())
            if delay:
                time.sleep(delay)
            _next_request = time.monotonic() + 0.2
        try:
            request = Request(url, headers={"User-Agent": "TrendAtlas-Clean-public-data/1.0"})
            with urlopen(request, timeout=30) as response:
                body = response.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                raise DataUnavailable("Public response exceeds size bound")
            if cp:
                cp.parent.mkdir(parents=True, exist_ok=True)
                _atomic_bytes(cp, body)
            return body
        except HTTPError as exc:
            if exc.code in {400, 404} and missing_ok:
                return None
            if exc.code in {400, 401, 403, 404, 418, 451}:
                raise DataUnavailable(f"HTTP {exc.code}: {url.split('?')[0]}") from exc
            if attempt == 2:
                raise DataUnavailable(f"HTTP {exc.code}: public-data request failed") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                raise DataUnavailable(f"Public-data transport failed: {type(exc).__name__}") from exc
        time.sleep(min(2 ** attempt, 4))
    raise AssertionError("unreachable")


def _atomic_bytes(path: Path, body: bytes) -> None:
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".clean-")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if Path(temp).exists():
            Path(temp).unlink()


def _listing(prefix: str, *, delimiter: str | None = None) -> tuple[list[str], list[str]]:
    keys, prefixes, marker = [], [], ""
    while True:
        args = {"prefix": prefix, "max-keys": 1000}
        if delimiter:
            args["delimiter"] = delimiter
        if marker:
            args["marker"] = marker
        root = ET.fromstring(_bytes(BUCKET + "?" + urlencode(args)))
        ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
        batch = [x.text for x in root.findall("s:Contents/s:Key", ns)]
        ps = [x.text for x in root.findall("s:CommonPrefixes/s:Prefix", ns)]
        keys.extend(batch)
        prefixes.extend(ps)
        if root.findtext("s:IsTruncated", default="false", namespaces=ns) != "true":
            return keys, prefixes
        next_marker = root.findtext("s:NextMarker", namespaces=ns)
        marker2 = next_marker or (batch[-1] if batch else ps[-1] if ps else "")
        if not marker2 or marker2 == marker:
            raise DataUnavailable("Archive listing did not advance")
        marker = marker2


def to_daily(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "quote_volume"])
    out = frame.copy()
    t = pd.to_numeric(out["open_time"], errors="raise")
    t = t.where(t < 1e14, t // 1000)
    dates = pd.to_datetime(t, unit="ms", utc=True)
    if not dates.eq(dates.dt.normalize()).all():
        raise DataUnavailable("Non-midnight daily candle")
    out["date"] = dates.dt.tz_localize(None)
    for c in ("open", "high", "low", "close", "volume", "quote_volume"):
        out[c] = pd.to_numeric(out[c], errors="raise")
    # Identical pagination overlaps are fine; conflicting candles are not.
    duplicates = out[out["date"].duplicated(keep=False)]
    for _, d in duplicates.groupby("date"):
        if len(d[["open", "high", "low", "close", "volume", "quote_volume"]].drop_duplicates()) != 1:
            raise DataUnavailable("Conflicting duplicate daily candle")
    return out.drop_duplicates("date").sort_values("date")[["date", "open", "high", "low", "close", "volume", "quote_volume"]]


def klines_api(symbol: str, end: str, *, start_ms: int = START_MS) -> pd.DataFrame:
    rows, start = [], start_ms
    end_ms = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000) - 1
    while start <= end_ms:
        params = {"symbol": symbol + "USDT", "interval": "1d", "startTime": start, "endTime": end_ms, "limit": 1000}
        body = _bytes(MARKET_API + "/api/v3/klines?" + urlencode(params), missing_ok=True)
        if body is None:
            break
        batch = json.loads(body)
        if not isinstance(batch, list):
            raise DataUnavailable("Unexpected klines response")
        if not batch:
            break
        rows.extend(batch)
        nxt = int(batch[-1][0]) + 86_400_000
        if nxt <= start:
            raise DataUnavailable("Kline pagination did not advance")
        if len(batch) < 1000:
            break
        start = nxt
    return pd.DataFrame(rows, columns=COLS)


def klines_archive(symbol: str, end: str, cache: Path) -> pd.DataFrame:
    prefix = f"data/spot/monthly/klines/{symbol}USDT/1d/"
    keys, _ = _listing(prefix)
    last_month = end[:7]
    keys = [k for k in keys if k.endswith(".zip") and k.rsplit("-", 2)[-2] + "-" + k.rsplit("-", 1)[-1][:2] <= last_month]

    def read_key(key: str) -> pd.DataFrame:
        body = _bytes(ARCHIVE + key, cache=cache)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = archive.namelist()
            if len(names) != 1 or archive.getinfo(names[0]).file_size > 16 * 1024 * 1024:
                raise DataUnavailable("Unexpected archive layout/size")
            df = pd.read_csv(archive.open(names[0]), header=None)
        if df.shape[1] != 12:
            raise DataUnavailable("Unexpected kline archive columns")
        df.columns = COLS
        return df

    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(pool.map(read_key, sorted(keys)))
    # Current incomplete month is supplied by daily archives, not an invented bar.
    if symbol not in CUTOFF and end[:7] >= last_closed_day()[:7]:
        for day in pd.date_range(end[:7] + "-01", end):
            key = f"data/spot/daily/klines/{symbol}USDT/1d/{symbol}USDT-1d-{day.date().isoformat()}.zip"
            body = _bytes(ARCHIVE + key, cache=cache, missing_ok=True)
            if body:
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    df = pd.read_csv(archive.open(archive.namelist()[0]), header=None, names=COLS)
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS)


def fetch_symbol(symbol: str, data_dir: Path, end: str) -> dict:
    if not re.fullmatch(r"[A-Z0-9]+", symbol):
        raise ValueError("Invalid symbol")
    path = data_dir / "ohlcv" / f"{symbol}.csv"
    effective_end = min(end, CUTOFF.get(symbol, end))
    if path.exists():
        existing = pd.read_csv(path, parse_dates=["date"])
        if not existing.empty and existing["date"].max() >= pd.Timestamp(effective_end):
            return {"symbol": symbol, "status": "CACHE", "rows": len(existing), "end": str(existing['date'].max().date()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    else:
        existing = pd.DataFrame()
    if symbol in CUTOFF:
        raw, source = klines_archive(symbol, effective_end, data_dir / ".http_cache"), "ARCHIVE_ORIGINAL_LUNA"
    else:
        start = START_MS
        if not existing.empty:
            # Refresh the final seven days for revisions; retain preceding source history.
            start = int((existing["date"].max() - pd.Timedelta(days=6)).tz_localize("UTC").timestamp() * 1000)
        try:
            raw, source = klines_api(symbol, end, start_ms=start), "BINANCE_MARKET_DATA_API"
        except DataUnavailable as exc:
            # Source failure is recorded; archives remain the same Binance price source.
            raw, source = klines_archive(symbol, end, data_dir / ".http_cache"), "ARCHIVE_AFTER_API_ERROR:" + str(exc)
        if raw.empty and existing.empty:
            raw, source = klines_archive(symbol, end, data_dir / ".http_cache"), "ARCHIVE_DELISTED_OR_UNAVAILABLE"
    daily = to_daily(raw)
    if not existing.empty:
        daily = pd.concat([existing[~existing['date'].isin(daily['date'])], daily], ignore_index=True).sort_values("date")
    daily = daily[daily["date"] <= pd.Timestamp(effective_end)]
    if daily.empty:
        raise DataUnavailable(f"No Binance observations for {symbol}")
    _atomic_bytes(path, daily.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.17g").encode())
    return {"symbol": symbol, "status": "OK", "source": source, "rows": len(daily),
            "start": str(daily["date"].min().date()), "end": str(daily["date"].max().date()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fetch_funding(symbol: str, data_dir: Path, end: str) -> dict:
    """Missing history is reported; load() applies the reference's labelled proxies."""
    rows, start = [], START_MS
    end_ms = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000) - 1
    try:
        while start <= end_ms:
            args = {"symbol": symbol + "USDT", "startTime": start, "endTime": end_ms, "limit": 1000}
            body = _bytes("https://fapi.binance.com/fapi/v1/fundingRate?" + urlencode(args), missing_ok=True)
            batch = json.loads(body) if body else []
            if not batch:
                break
            if not isinstance(batch, list):
                raise DataUnavailable("Unexpected funding response")
            rows.extend(batch)
            nxt = int(batch[-1]["fundingTime"]) + 1
            if nxt <= start:
                raise DataUnavailable("Funding pagination did not advance")
            start = nxt
            if len(batch) < 1000:
                break
    except DataUnavailable as exc:
        return {"symbol": symbol, "status": "FUNDING_UNAVAILABLE", "reason": str(exc), "rows": 0}
    if not rows:
        return {"symbol": symbol, "status": "FUNDING_UNAVAILABLE", "rows": 0}
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    df["rate"] = pd.to_numeric(df["fundingRate"], errors="raise")
    daily = df.groupby("date")["rate"].sum().rename("funding_daily").reset_index()
    _atomic_bytes(data_dir / "funding" / f"{symbol}.csv", daily.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.17g").encode())
    return {"symbol": symbol, "status": "OK", "rows": len(daily)}


def discover_universe(exclusions_path: Path) -> dict:
    exclusions = json.loads(exclusions_path.read_text())
    info = json.loads(_bytes(MARKET_API + "/api/v3/exchangeInfo"))
    symbols = {x["baseAsset"] for x in info["symbols"] if x["quoteAsset"] == "USDT"}
    _, prefixes = _listing("data/spot/monthly/klines/", delimiter="/")
    symbols.update(p.rstrip("/").split("/")[-1][:-4] for p in prefixes if p.rstrip("/").endswith("USDT"))
    explicit = {x: reason for reason in ("stablecoins", "wrapped_tokens") for x in exclusions[reason]}
    accepted, rejected = [], {}
    for s in sorted(symbols):
        reason = explicit.get(s)
        for suffix in ("UP", "DOWN", "BULL", "BEAR"):
            if s.endswith(suffix) and s[:-len(suffix)] in symbols:
                reason = "leveraged_token"
        if reason:
            rejected[s] = reason
        elif re.fullmatch(r"[A-Z0-9]+", s):
            accepted.append(s)
    return {"symbols": accepted, "excluded": rejected, "source": "Binance exchangeInfo + historical archive prefixes",
            "classification_sha256": hashlib.sha256(exclusions_path.read_bytes()).hexdigest(),
            "classification_status": "VERSIONED_EXPLICIT_EXCLUSIONS_REQUIRES_PERIODIC_REVIEW"}


def fetch_all(data_dir: Path, symbols: list[str] | tuple[str, ...], end: str, *, workers: int = 6, funding: bool = False) -> dict:
    if end > last_closed_day():
        raise ValueError("Cannot download an unclosed UTC day")
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_symbol, s, data_dir, end): s for s in symbols}
        for future in as_completed(futures):
            s = futures[future]
            try:
                row = future.result()
                rows.append(row)
            except Exception as exc:
                row = {"symbol": s, "status": "FAILED", "reason": str(exc)}
                failures.append(row)
            print(json.dumps(row), flush=True)
    fund_rows = []
    if funding:
        with ThreadPoolExecutor(max_workers=min(workers, 4)) as pool:
            fund_rows = list(pool.map(lambda s: fetch_funding(s, data_dir, end), symbols))
    manifest = {"requested_closed_day": end, "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "symbols_requested": list(symbols), "ohlcv": sorted(rows, key=lambda x: x["symbol"]),
                "failures": failures, "funding": fund_rows}
    _atomic_bytes(data_dir / "fetch_manifest.json", json.dumps(manifest, indent=2).encode() + b"\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--end", default=last_closed_day())
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--funding", action="store_true")
    parser.add_argument("--workers", type=int, choices=range(1, 13), default=6)
    args = parser.parse_args()
    report = fetch_all(args.data_dir, args.symbols or REFERENCE_SYMBOLS, args.end, workers=args.workers, funding=args.funding)
    return 2 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
