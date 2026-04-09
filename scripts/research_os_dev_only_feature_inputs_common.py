from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PHASE67_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
PHASE68_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
CORE_OHLCV_DIR = ROOT / "data" / "ohlcv"
TOP100_OHLCV_DIR = ROOT / "data" / "ohlcv_phase67_top100"
EPSILON = 1e-9


def normalize_asset_label(value: object, *, ensure_suffix: bool = True) -> str:
    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return ""
    if ensure_suffix and not text.endswith("USDT"):
        return f"{text}USDT"
    if not ensure_suffix and text.endswith("USDT"):
        return text[:-4]
    return text


def round_value(value: float) -> float:
    return round(float(value), 6)


def load_active_leader_rows(asset_filter: str = "") -> pd.DataFrame:
    phase67 = pd.read_csv(PHASE67_PAPER_PATH)
    phase67["date"] = pd.to_datetime(phase67["date"], errors="coerce")
    phase67 = phase67.dropna(subset=["date"]).copy()
    phase67["executed_regime"] = phase67["executed_regime"].fillna("").astype(str).str.strip().str.upper()
    phase67["asset"] = phase67["chosen_asset"].map(normalize_asset_label)
    rows = phase67[(phase67["executed_regime"] != "CASH") & (phase67["asset"] != "")].copy()

    normalized_filter = normalize_asset_label(asset_filter)
    if normalized_filter:
        rows = rows[rows["asset"] == normalized_filter].copy()

    return rows.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)


def load_phase68_context() -> pd.DataFrame:
    phase68 = pd.read_csv(PHASE68_PAPER_PATH)
    phase68["date"] = pd.to_datetime(phase68["date"], errors="coerce")
    phase68 = phase68.dropna(subset=["date"]).copy()

    numeric_columns = [
        "base_ret",
        "trend_score",
        "crossed_up_today",
        "crossed_down_today",
        "asset_transition_day",
        "tradable_transition_day",
        "stress_block_day",
        "trend_block_day",
        "days_in_position",
        "stress_block_active",
        "cash_day",
        "trend_gate_pass",
        "leverage_eligible",
    ]
    for column in numeric_columns:
        if column in phase68.columns:
            phase68[column] = pd.to_numeric(phase68[column], errors="coerce").fillna(0.0)

    keep_columns = ["date"] + [column for column in numeric_columns if column in phase68.columns]
    return phase68[keep_columns].sort_values("date").drop_duplicates(subset=["date"], keep="last").set_index("date")


def load_daily_ohlcv(
    symbol: str,
    cache: Dict[str, pd.DataFrame],
    directories: Iterable[Path] | None = None,
) -> pd.DataFrame:
    normalized_symbol = normalize_asset_label(symbol)
    if normalized_symbol in cache:
        return cache[normalized_symbol]

    search_dirs = list(directories or [TOP100_OHLCV_DIR, CORE_OHLCV_DIR])
    path = None
    for directory in search_dirs:
        candidate = directory / f"{normalized_symbol}_1d.csv"
        if candidate.exists():
            path = candidate
            break

    if path is None:
        raise FileNotFoundError(f"Missing OHLCV input for {normalized_symbol}")

    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).set_index("date")
    df["base_ret"] = df["close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["ret_3d"] = df["close"].pct_change(3).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["range_pct"] = ((df["high"] - df["low"]) / df["close"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df["range_pct"] = df["range_pct"].fillna(0.0)
    df["body_size"] = (df["close"] - df["open"]).abs()
    df["bar_range"] = (df["high"] - df["low"]).replace(0.0, np.nan)
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["wick_total"] = df["upper_wick"] + df["lower_wick"]
    df["wick_share"] = (df["wick_total"] / (df["bar_range"] + EPSILON)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["body_share"] = (df["body_size"] / (df["bar_range"] + EPSILON)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["realized_volatility_10"] = df["base_ret"].rolling(10).std(ddof=0)
    df["dollar_volume_proxy"] = (df["close"] * df["volume"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["turnover_proxy"] = (df["dollar_volume_proxy"] * df["range_pct"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    cache[normalized_symbol] = df
    return df


def load_close_matrix(directory: Path) -> pd.DataFrame:
    series_list: List[pd.Series] = []
    for path in sorted(directory.glob("*USDT_1d.csv")):
        symbol = path.stem.replace("_1d", "").upper()
        frame = pd.read_csv(path, usecols=["date", "close"])
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).copy()
        frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        series_list.append(frame.set_index("date")["close"].rename(symbol))

    if not series_list:
        return pd.DataFrame()

    return pd.concat(series_list, axis=1).sort_index()
