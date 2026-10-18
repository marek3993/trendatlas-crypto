"""Isolated CSV input loading. Funding proxies are labelled, never observed zeros."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from .core import CUTOFF, validate_panel

REFERENCE_SYMBOLS = tuple("BTC ETH BNB XRP ADA SOL DOGE TRX LTC LINK DOT AVAX BCH ETC XLM EOS XMR NEO IOTA ATOM VET FIL THETA MATIC UNI AAVE ICP FTM ALGO NEAR LUNA FTT SHIB APT ARB OP SUI PEPE TON HBAR XTZ ZEC DASH WAVES SAND MANA AXS CRV EGLD INJ ONT QTUM ZIL ICX OMG KSM CHZ GALA WIF".split())


@dataclass
class Panel:
    close: pd.DataFrame
    quote_volume: pd.DataFrame
    funding: pd.DataFrame
    funding_source: pd.DataFrame
    input_sha256: str
    files: dict[str, str]


def _daily_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df:
        raise ValueError(f"Missing date: {path.name}")
    dates = pd.to_datetime(df.pop("date"), utc=True, errors="raise")
    if not dates.eq(dates.dt.normalize()).all():
        raise ValueError(f"Non-daily timestamp: {path.name}")
    df.index = pd.DatetimeIndex(dates).tz_localize(None)
    if df.index.has_duplicates:
        raise ValueError(f"Duplicate dates: {path.name}")
    return df.sort_index()


def load(data_dir: Path, last_closed: str, symbols: tuple[str, ...] | list[str] | None = None) -> Panel:
    closes, volumes, fund = {}, {}, {}
    files = {}
    paths = sorted((data_dir / "ohlcv").glob("*.csv"))
    if symbols is not None:
        paths = [data_dir / "ohlcv" / f"{s}.csv" for s in sorted(symbols)]
    for p in paths:
        if not p.exists():
            raise ValueError(f"Missing OHLCV file: {p.name}")
        d = _daily_csv(p).loc[:last_closed]
        if p.stem in CUTOFF:
            d = d.loc[:CUTOFF[p.stem]]
        if not {"close", "quote_volume"} <= set(d.columns):
            raise ValueError(f"Missing close or original quote_volume: {p.name}")
        closes[p.stem] = pd.to_numeric(d["close"], errors="raise")
        volumes[p.stem] = pd.to_numeric(d["quote_volume"], errors="raise")
        # Semantic hashes are prefix-only: appended future bars cannot change a past binding.
        canonical = d[["close", "quote_volume"]].to_csv(index_label="date", float_format="%.17g")
        files[f"ohlcv/{p.name}"] = hashlib.sha256(canonical.encode()).hexdigest()
    if not closes or "BTC" not in closes:
        raise ValueError("BTC and OHLCV history are required")
    close = pd.DataFrame(closes)
    if close.empty:
        raise ValueError("No observations before requested close")
    idx = pd.date_range(close.index.min(), last_closed, freq="D")
    close = close.reindex(idx)
    qv = pd.DataFrame(volumes).reindex(index=idx, columns=close.columns)
    validate_panel(close, qv)
    for p in sorted((data_dir / "funding").glob("*.csv")):
        if p.stem not in close:
            continue
        d = _daily_csv(p).loc[:last_closed]
        fund[p.stem] = pd.to_numeric(d["funding_daily"], errors="raise")
        files[f"funding/{p.name}"] = hashlib.sha256(d[["funding_daily"]].to_csv(index_label="date", float_format="%.17g").encode()).hexdigest()
    observed = pd.DataFrame(fund).reindex(index=idx, columns=close.columns)
    observed = observed.replace([np.inf, -np.inf], np.nan)
    btc = observed["BTC"]
    funding = observed.apply(lambda c: c.fillna(btc)).fillna(0.0003)
    source = pd.DataFrame("OBSERVED", index=idx, columns=close.columns)
    for c in source:
        source.loc[observed[c].isna() & btc.notna(), c] = "BTC_PROXY"
        source.loc[observed[c].isna() & btc.isna(), c] = "DEFAULT_PROXY_0.0003"
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(f"{name}\0{value}\n".encode())
    return Panel(close, qv, funding, source, digest.hexdigest(), files)
