from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data" / "ohlcv"

ALWAYS_DAILY_PATH = OUTPUTS_DIR / "phase18_always_daily.csv"
SOFT_KILL_4H_PATH = OUTPUTS_DIR / "phase18_soft_kill_4h.csv"

OUT_RESULTS_CSV = OUTPUTS_DIR / "phase20_swing_overlay_scan_results.csv"
OUT_BEST_JSON = OUTPUTS_DIR / "phase20_swing_overlay_scan_best.json"
OUT_TOP_CSV = OUTPUTS_DIR / "phase20_swing_overlay_scan_top20.csv"

UNIVERSE = [
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


def find_date_col(df: pd.DataFrame) -> str:
    candidates = [
        "date",
        "Date",
        "datetime",
        "Datetime",
        "timestamp",
        "Timestamp",
        "time",
        "Time",
        "open_time",
        "Open time",
    ]
    for col in candidates:
        if col in df.columns:
            return col

    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    if unnamed:
        return unnamed[0]

    first_col = df.columns[0]
    sample = pd.to_datetime(df[first_col], errors="coerce")
    if sample.notna().sum() >= max(3, int(len(df) * 0.5)):
        return first_col

    raise ValueError(f"Nenašiel som dátumový stĺpec. Stĺpce: {list(df.columns)}")


def find_price_col(df: pd.DataFrame) -> str:
    for col in ["close", "Close", "adj_close", "Adj Close"]:
        if col in df.columns:
            return col
    raise ValueError(f"Nenašiel som close stĺpec. Stĺpce: {list(df.columns)}")


def find_equity_col(df: pd.DataFrame, label: str) -> str:
    date_col = find_date_col(df)

    candidates = [
        "equity",
        "portfolio_value",
        "strategy_equity",
        "account_value",
        "nav",
        "close_equity",
        "total_equity",
        "balance",
        "capital",
    ]
    for col in candidates:
        if col in df.columns:
            return col

    numeric_cols = []
    for col in df.columns:
        if col == date_col:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() >= max(3, int(len(df) * 0.7)):
            numeric_cols.append(col)

    if len(numeric_cols) == 1:
        return numeric_cols[0]

    preferred = [
        c
        for c in numeric_cols
        if any(x in str(c).lower() for x in ["equity", "nav", "value", "balance", "capital"])
    ]
    if preferred:
        return preferred[0]

    raise ValueError(f"{label}: nenašiel som equity stĺpec. Stĺpce: {list(df.columns)}")


def resolve_symbol_csv(symbol: str) -> Path:
    patterns = [
        f"{symbol}.csv",
        f"{symbol.lower()}.csv",
        f"{symbol}_*.csv",
        f"{symbol.lower()}_*.csv",
        f"*{symbol}*.csv",
        f"*{symbol.lower()}*.csv",
    ]

    matches = []
    for pattern in patterns:
        matches.extend(DATA_DIR.glob(pattern))

    matches = [p for p in matches if p.is_file()]
    if not matches:
        raise FileNotFoundError(f"Nenašiel som CSV pre {symbol} v {DATA_DIR}")

    matches = sorted(set(matches), key=lambda p: p.name.lower())
    return matches[0]


def load_close_series(symbol: str) -> pd.Series:
    path = resolve_symbol_csv(symbol)
    df = pd.read_csv(path)

    date_col = find_date_col(df)
    close_col = find_price_col(df)

    out = df[[date_col, close_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce").dt.normalize()
    out[close_col] = pd.to_numeric(out[close_col], errors="coerce")
    out = out.dropna(subset=[date_col, close_col]).drop_duplicates(subset=[date_col]).sort_values(date_col)

    s = out.set_index(date_col)[close_col].astype(float)
    s.name = symbol
    return s


def load_strategy_equity(csv_path: Path, label: str) -> pd.Series:
    if not csv_path.exists():
        raise FileNotFoundError(f"Chýba súbor: {csv_path}")

    df = pd.read_csv(csv_path)
    date_col = find_date_col(df)
    equity_col = find_equity_col(df, label)

    out = df[[date_col, equity_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce").dt.normalize()
    out[equity_col] = pd.to_numeric(out[equity_col], errors="coerce")
    out = out.dropna(subset=[date_col, equity_col]).drop_duplicates(subset=[date_col]).sort_values(date_col)

    s = out.set_index(date_col)[equity_col].astype(float)
    s.name = label
    return s


def calc_drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def calc_metrics_from_equity(equity: pd.Series) -> Dict[str, float]:
    equity = equity.dropna().astype(float)
    rets = equity.pct_change().fillna(0.0)

    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    days = (equity.index[-1] - equity.index[0]).days
    years = days / 365.25 if days > 0 else np.nan
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years and years > 0 else np.nan

    dd = calc_drawdown(equity)
    max_dd = dd.min()

    vol = rets.std(ddof=0)
    downside = rets[rets < 0].std(ddof=0)

    sharpe = (rets.mean() / vol) * np.sqrt(365) if vol and vol > 0 else np.nan
    sortino = (rets.mean() / downside) * np.sqrt(365) if downside and downside > 0 else np.nan

    exposure = float((rets != 0).mean())

    return {
        "start_date": equity.index[0].strftime("%Y-%m-%d"),
        "end_date": equity.index[-1].strftime("%Y-%m-%d"),
        "days": int(days),
        "years": float(years) if pd.notna(years) else np.nan,
        "start_equity": float(equity.iloc[0]),
        "end_equity": float(equity.iloc[-1]),
        "total_return_pct": float(total_return * 100.0),
        "cagr_pct": float(cagr * 100.0) if pd.notna(cagr) else np.nan,
        "max_drawdown_pct": float(max_dd * 100.0),
        "sharpe": float(sharpe) if pd.notna(sharpe) else np.nan,
        "sortino": float(sortino) if pd.notna(sortino) else np.nan,
        "active_day_fraction": exposure,
    }


def build_universe_close_df(symbols: List[str]) -> pd.DataFrame:
    cols = []
    for symbol in symbols:
        s = load_close_series(symbol)
        cols.append(s)
    df = pd.concat(cols, axis=1).sort_index()
    return df


def apply_cooldown(kill_signal: pd.Series, cooldown_days: int) -> pd.Series:
    kill_signal = kill_signal.fillna(False).astype(bool)
    out = pd.Series(False, index=kill_signal.index)

    remaining = 0
    for i, dt in enumerate(kill_signal.index):
        if kill_signal.iloc[i]:
            remaining = max(remaining, cooldown_days + 1)
        if remaining > 0:
            out.iloc[i] = True
            remaining -= 1

    return out


def build_overlay_signal(closes: pd.DataFrame, mode: str, breadth_threshold: float) -> pd.Series:
    btc = closes["BTCUSDT"]

    ret2 = btc / btc.shift(2) - 1.0
    ret3 = btc / btc.shift(3) - 1.0

    cross_ret2 = closes / closes.shift(2) - 1.0
    cross_ret3 = closes / closes.shift(3) - 1.0

    breadth2 = (cross_ret2 > 0).mean(axis=1)
    breadth3 = (cross_ret3 > 0).mean(axis=1)

    signal_map = {
        "btc_2d_neg": ret2 < 0,
        "btc_3d_neg": ret3 < 0,
        "breadth_2d_weak": breadth2 < breadth_threshold,
        "breadth_3d_weak": breadth3 < breadth_threshold,
        "combo_any_2d": (ret2 < 0) | (breadth2 < breadth_threshold),
        "combo_any_3d": (ret3 < 0) | (breadth3 < breadth_threshold),
        "combo_all_2d": (ret2 < 0) & (breadth2 < breadth_threshold),
        "combo_all_3d": (ret3 < 0) & (breadth3 < breadth_threshold),
        "combo_mixed": ((ret2 < 0) & (breadth3 < breadth_threshold)) | ((ret3 < 0) & (breadth2 < breadth_threshold)),
    }

    if mode not in signal_map:
        raise ValueError(f"Neznámy mode: {mode}")

    return signal_map[mode].fillna(False).astype(bool)


def simulate_overlay(
    base_equity: pd.Series,
    kill_signal: pd.Series,
    kill_multiplier: float,
    cooldown_days: int,
) -> pd.Series:
    kill_active = apply_cooldown(kill_signal, cooldown_days)
    risk_multiplier = pd.Series(1.0, index=kill_active.index)
    risk_multiplier[kill_active] = kill_multiplier

    base_rets = base_equity.pct_change().fillna(0.0)
    aligned_mult = risk_multiplier.reindex(base_rets.index).fillna(1.0)

    exec_mult = aligned_mult.shift(1).fillna(1.0)
    overlay_rets = base_rets * exec_mult

    overlay_equity = (1.0 + overlay_rets).cumprod()
    overlay_equity.iloc[0] = 1.0
    return overlay_equity


def score_row(row: pd.Series) -> float:
    sharpe = row["sharpe"]
    dd = abs(row["max_drawdown_pct"])
    cagr = row["cagr_pct"]
    return float((sharpe * 25.0) + (cagr * 0.35) - (dd * 0.30))


def main() -> None:
    always_daily = load_strategy_equity(ALWAYS_DAILY_PATH, "always_daily")
    soft_kill_4h = load_strategy_equity(SOFT_KILL_4H_PATH, "soft_kill_4h")
    closes = build_universe_close_df(UNIVERSE)

    common_index = always_daily.index.intersection(soft_kill_4h.index).intersection(closes.index)
    common_index = common_index.sort_values()

    if len(common_index) < 200:
        raise ValueError("Príliš malý spoločný interval dát")

    always_daily = always_daily.reindex(common_index).dropna()
    soft_kill_4h = soft_kill_4h.reindex(common_index).dropna()
    closes = closes.reindex(common_index).ffill().dropna()

    common_index = always_daily.index.intersection(soft_kill_4h.index).intersection(closes.index).sort_values()
    always_daily = always_daily.reindex(common_index)
    soft_kill_4h = soft_kill_4h.reindex(common_index)
    closes = closes.reindex(common_index)

    results = []

    base_metrics = calc_metrics_from_equity(always_daily)
    results.append(
        {
            "model": "always_daily",
            "overlay_mode": "none",
            "breadth_threshold": np.nan,
            "kill_multiplier": 1.0,
            "cooldown_days": 0,
            "kill_days_pct": 0.0,
            **base_metrics,
        }
    )

    soft_metrics = calc_metrics_from_equity(soft_kill_4h)
    results.append(
        {
            "model": "soft_kill_4h",
            "overlay_mode": "reference",
            "breadth_threshold": np.nan,
            "kill_multiplier": np.nan,
            "cooldown_days": np.nan,
            "kill_days_pct": np.nan,
            **soft_metrics,
        }
    )

    overlay_modes = [
        "btc_2d_neg",
        "btc_3d_neg",
        "breadth_2d_weak",
        "breadth_3d_weak",
        "combo_any_2d",
        "combo_any_3d",
        "combo_all_2d",
        "combo_all_3d",
        "combo_mixed",
    ]
    breadth_thresholds = [0.35, 0.40, 0.50, 0.60]
    kill_multipliers = [0.00, 0.25, 0.50]
    cooldown_days_list = [0, 1, 2, 3]

    for mode in overlay_modes:
        for breadth_threshold in breadth_thresholds:
            raw_signal = build_overlay_signal(closes, mode, breadth_threshold)

            for kill_multiplier in kill_multipliers:
                for cooldown_days in cooldown_days_list:
                    overlay_equity = simulate_overlay(
                        base_equity=always_daily,
                        kill_signal=raw_signal,
                        kill_multiplier=kill_multiplier,
                        cooldown_days=cooldown_days,
                    )
                    metrics = calc_metrics_from_equity(overlay_equity)

                    kill_active = apply_cooldown(raw_signal, cooldown_days)
                    kill_days_pct = float(kill_active.mean() * 100.0)

                    row = {
                        "model": f"phase20_{mode}",
                        "overlay_mode": mode,
                        "breadth_threshold": breadth_threshold,
                        "kill_multiplier": kill_multiplier,
                        "cooldown_days": cooldown_days,
                        "kill_days_pct": kill_days_pct,
                        **metrics,
                    }
                    results.append(row)

    out_df = pd.DataFrame(results)

    out_df["score"] = out_df.apply(score_row, axis=1)
    out_df = out_df.sort_values(
        ["score", "sharpe", "cagr_pct", "max_drawdown_pct"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    out_df.to_csv(OUT_RESULTS_CSV, index=False)
    out_df.head(20).to_csv(OUT_TOP_CSV, index=False)

    best_row = out_df.iloc[0].to_dict()
    with open(OUT_BEST_JSON, "w", encoding="utf-8") as f:
        json.dump(best_row, f, indent=2)

    print("\n=== PHASE 20 SWING OVERLAY SCAN: TOP 20 ===")
    print(
        out_df[
            [
                "model",
                "overlay_mode",
                "breadth_threshold",
                "kill_multiplier",
                "cooldown_days",
                "kill_days_pct",
                "total_return_pct",
                "cagr_pct",
                "max_drawdown_pct",
                "sharpe",
                "sortino",
                "score",
            ]
        ].head(20).to_string(index=False)
    )

    print(f"\nUložené CSV:  {OUT_RESULTS_CSV}")
    print(f"Uložené TOP:  {OUT_TOP_CSV}")
    print(f"Uložené JSON: {OUT_BEST_JSON}")


if __name__ == "__main__":
    main()