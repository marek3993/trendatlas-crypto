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

CANDIDATES = [
    {"name": "combo_all_2d_b035_k0_cd0", "mode": "combo_all_2d", "breadth_threshold": 0.35, "kill_multiplier": 0.0, "cooldown_days": 0},
    {"name": "combo_mixed_b035_k0_cd0", "mode": "combo_mixed", "breadth_threshold": 0.35, "kill_multiplier": 0.0, "cooldown_days": 0},
    {"name": "btc_3d_neg_b035_k0_cd0", "mode": "btc_3d_neg", "breadth_threshold": 0.35, "kill_multiplier": 0.0, "cooldown_days": 0},
    {"name": "btc_2d_neg_b035_k0_cd0", "mode": "btc_2d_neg", "breadth_threshold": 0.35, "kill_multiplier": 0.0, "cooldown_days": 0},
]

OUT_SUMMARY_CSV = OUTPUTS_DIR / "phase20b_audit_overlay_summary.csv"
OUT_SUMMARY_JSON = OUTPUTS_DIR / "phase20b_audit_overlay_summary.json"


def find_date_col(df: pd.DataFrame) -> str:
    candidates = [
        "date", "Date", "datetime", "Datetime", "timestamp", "Timestamp",
        "time", "Time", "open_time", "Open time",
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


def find_equity_col(df: pd.DataFrame, label: str) -> str:
    date_col = find_date_col(df)

    candidates = [
        "equity", "portfolio_value", "strategy_equity", "account_value",
        "nav", "close_equity", "total_equity", "balance", "capital",
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
        c for c in numeric_cols
        if any(x in str(c).lower() for x in ["equity", "nav", "value", "balance", "capital"])
    ]
    if preferred:
        return preferred[0]

    raise ValueError(f"{label}: nenašiel som equity stĺpec. Stĺpce: {list(df.columns)}")


def find_price_col(df: pd.DataFrame) -> str:
    for col in ["close", "Close", "adj_close", "Adj Close"]:
        if col in df.columns:
            return col
    raise ValueError(f"Nenašiel som close stĺpec. Stĺpce: {list(df.columns)}")


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


def build_universe_close_df(symbols: List[str]) -> pd.DataFrame:
    return pd.concat([load_close_series(s) for s in symbols], axis=1).sort_index()


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


def apply_cooldown(kill_signal: pd.Series, cooldown_days: int) -> pd.Series:
    kill_signal = kill_signal.fillna(False).astype(bool)
    out = pd.Series(False, index=kill_signal.index)

    remaining = 0
    for i in range(len(kill_signal)):
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


def calc_drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def calc_metrics(equity: pd.Series) -> Dict[str, float]:
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

    return {
        "total_return_pct": float(total_return * 100.0),
        "cagr_pct": float(cagr * 100.0) if pd.notna(cagr) else np.nan,
        "max_drawdown_pct": float(max_dd * 100.0),
        "sharpe": float(sharpe) if pd.notna(sharpe) else np.nan,
        "sortino": float(sortino) if pd.notna(sortino) else np.nan,
    }


def simulate_overlay(base_equity: pd.Series, kill_signal: pd.Series, kill_multiplier: float, cooldown_days: int):
    base_rets = base_equity.pct_change().fillna(0.0)

    kill_active = apply_cooldown(kill_signal, cooldown_days)
    risk_multiplier = pd.Series(1.0, index=base_rets.index)
    risk_multiplier.loc[kill_active] = kill_multiplier

    exec_multiplier = risk_multiplier.shift(1).fillna(1.0)
    overlay_rets = base_rets * exec_multiplier
    overlay_equity = (1.0 + overlay_rets).cumprod()
    overlay_equity.iloc[0] = 1.0

    detail = pd.DataFrame(
        {
            "base_equity": base_equity,
            "base_ret": base_rets,
            "kill_signal_raw": kill_signal.reindex(base_rets.index).fillna(False).astype(bool),
            "kill_active": kill_active.reindex(base_rets.index).fillna(False).astype(bool),
            "exec_multiplier": exec_multiplier,
            "overlay_ret": overlay_rets,
            "overlay_equity": overlay_equity,
        }
    )
    detail["ret_removed"] = detail["base_ret"] - detail["overlay_ret"]

    return overlay_equity, detail


def main() -> None:
    always_daily = load_strategy_equity(ALWAYS_DAILY_PATH, "always_daily")
    closes = build_universe_close_df(UNIVERSE)

    common_index = always_daily.index.intersection(closes.index).sort_values()
    if len(common_index) < 200:
        raise ValueError("Príliš malý spoločný interval dát")

    always_daily = always_daily.reindex(common_index).dropna()
    closes = closes.reindex(common_index).ffill().dropna()

    common_index = always_daily.index.intersection(closes.index).sort_values()
    always_daily = always_daily.reindex(common_index)
    closes = closes.reindex(common_index)

    base_metrics = calc_metrics(always_daily)
    print("\n=== BASE always_daily ===")
    print(json.dumps(base_metrics, indent=2))

    summary_rows = []

    for cfg in CANDIDATES:
        name = cfg["name"]
        mode = cfg["mode"]
        breadth_threshold = cfg["breadth_threshold"]
        kill_multiplier = cfg["kill_multiplier"]
        cooldown_days = cfg["cooldown_days"]

        kill_signal = build_overlay_signal(closes, mode, breadth_threshold)
        overlay_equity, detail = simulate_overlay(
            base_equity=always_daily,
            kill_signal=kill_signal,
            kill_multiplier=kill_multiplier,
            cooldown_days=cooldown_days,
        )
        overlay_metrics = calc_metrics(overlay_equity)

        killed = detail["exec_multiplier"] < 0.999999
        killed_pos = killed & (detail["base_ret"] > 0)
        killed_neg = killed & (detail["base_ret"] < 0)
        killed_zero = killed & (detail["base_ret"] == 0)

        row = {
            "candidate": name,
            "mode": mode,
            "breadth_threshold": breadth_threshold,
            "kill_multiplier": kill_multiplier,
            "cooldown_days": cooldown_days,
            "base_total_return_pct": base_metrics["total_return_pct"],
            "base_cagr_pct": base_metrics["cagr_pct"],
            "base_max_drawdown_pct": base_metrics["max_drawdown_pct"],
            "base_sharpe": base_metrics["sharpe"],
            "overlay_total_return_pct": overlay_metrics["total_return_pct"],
            "overlay_cagr_pct": overlay_metrics["cagr_pct"],
            "overlay_max_drawdown_pct": overlay_metrics["max_drawdown_pct"],
            "overlay_sharpe": overlay_metrics["sharpe"],
            "overlay_sortino": overlay_metrics["sortino"],
            "killed_days": int(killed.sum()),
            "killed_days_pct": float(killed.mean() * 100.0),
            "killed_positive_days": int(killed_pos.sum()),
            "killed_negative_days": int(killed_neg.sum()),
            "killed_zero_days": int(killed_zero.sum()),
            "killed_positive_days_pct_of_killed": float(killed_pos.sum() / killed.sum() * 100.0) if killed.sum() > 0 else np.nan,
            "killed_negative_days_pct_of_killed": float(killed_neg.sum() / killed.sum() * 100.0) if killed.sum() > 0 else np.nan,
            "sum_removed_ret": float(detail["ret_removed"].sum()),
            "sum_removed_positive_ret": float(detail.loc[killed_pos, "ret_removed"].sum()),
            "sum_removed_negative_ret": float(detail.loc[killed_neg, "ret_removed"].sum()),
            "avg_removed_ret_per_killed_day": float(detail.loc[killed, "ret_removed"].mean()) if killed.sum() > 0 else np.nan,
        }
        summary_rows.append(row)

        detail_path = OUTPUTS_DIR / f"phase20b_detail_{name}.csv"
        detail.reset_index().rename(columns={"index": "date"}).to_csv(detail_path, index=False)

        print(f"\n=== {name} ===")
        print(json.dumps(row, indent=2))
        print(f"Detail CSV: {detail_path}")

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values(
        ["overlay_sharpe", "overlay_cagr_pct", "overlay_max_drawdown_pct"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    summary_df.to_csv(OUT_SUMMARY_CSV, index=False)

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary_rows, f, indent=2)

    print(f"\nUložené summary CSV:  {OUT_SUMMARY_CSV}")
    print(f"Uložené summary JSON: {OUT_SUMMARY_JSON}")


if __name__ == "__main__":
    main()