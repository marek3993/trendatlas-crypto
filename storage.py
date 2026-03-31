from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from config import SETTINGS


def ensure_dirs() -> None:
    SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.raw_dir.mkdir(parents=True, exist_ok=True)
    for dataset in SETTINGS.datasets:
        (SETTINGS.raw_dir / dataset).mkdir(parents=True, exist_ok=True)


def _to_date(value: date | datetime | str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(value)


def day_path(dataset: str, symbol: str, day: date | datetime | str) -> Path:
    d = _to_date(day)
    return SETTINGS.raw_dir / dataset / symbol / f"{d.isoformat()}.parquet"


def write_parquet(df: pd.DataFrame, dataset: str, symbol: str, day: date | datetime | str) -> Path:
    path = day_path(dataset, symbol, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine=SETTINGS.parquet_engine)
    return path


def upsert_dedup(
    df: pd.DataFrame,
    dataset: str,
    symbol: str,
    day: date | datetime | str,
    keys: list[str],
) -> Path:
    path = day_path(dataset, symbol, day)

    if path.exists():
        old = pd.read_parquet(path, engine=SETTINGS.parquet_engine)
        df = pd.concat([old, df], ignore_index=True)

    df = df.drop_duplicates(subset=keys, keep="last").sort_values(keys).reset_index(drop=True)
    return write_parquet(df, dataset, symbol, day)


def _daterange(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def read_parquet_range(dataset: str, symbol: str, start: str | date, end: str | date) -> pd.DataFrame:
    start_d = _to_date(start)
    end_d = _to_date(end)

    parts: list[pd.DataFrame] = []
    for d in _daterange(start_d, end_d):
        path = day_path(dataset, symbol, d)
        if path.exists():
            parts.append(pd.read_parquet(path, engine=SETTINGS.parquet_engine))

    if not parts:
        return pd.DataFrame()

    return pd.concat(parts, ignore_index=True)