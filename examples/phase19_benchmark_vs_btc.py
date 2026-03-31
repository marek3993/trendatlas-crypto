from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data" / "ohlcv"

ALWAYS_DAILY_PATH = OUTPUTS_DIR / "phase18_always_daily.csv"
SOFT_KILL_4H_PATH = OUTPUTS_DIR / "phase18_soft_kill_4h.csv"

OUT_CSV = OUTPUTS_DIR / "phase19_benchmark_vs_btc.csv"
OUT_JSON = OUTPUTS_DIR / "phase19_benchmark_vs_btc.json"


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


def resolve_btc_daily_path() -> Path:
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Chýba adresár s daily dátami: {DATA_DIR}")

    patterns = [
        "BTCUSDT.csv",
        "btcusdt.csv",
        "BTCUSDT*.csv",
        "btcusdt*.csv",
        "*BTC*USDT*.csv",
        "*btc*usdt*.csv",
    ]

    matches = []
    for pattern in patterns:
        matches.extend(DATA_DIR.glob(pattern))

    matches = [p for p in matches if p.is_file()]

    if not matches:
        all_csv = sorted([p.name for p in DATA_DIR.glob("*.csv")])
        raise FileNotFoundError(
            "Nenašiel som BTC daily CSV v data\\ohlcv. "
            f"Dostupné CSV: {all_csv[:20]}"
        )

    matches = sorted(set(matches), key=lambda p: p.name.lower())
    return matches[0]


def load_strategy_equity(csv_path: Path, label: str) -> pd.Series:
    if not csv_path.exists():
        raise FileNotFoundError(f"Chýba súbor: {csv_path}")

    df = pd.read_csv(csv_path)

    date_col = find_date_col(df)
    equity_col = find_equity_col(df, label)

    out = df[[date_col, equity_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce").dt.normalize()
    out[equity_col] = pd.to_numeric(out[equity_col], errors="coerce")

    out = out.dropna(subset=[date_col, equity_col])
    out = out.drop_duplicates(subset=[date_col]).sort_values(date_col)

    s = out.set_index(date_col)[equity_col].astype(float)
    s.name = label

    if len(s) < 3:
        raise ValueError(f"{label}: equity séria je príliš krátka po načítaní")

    return s


def load_btc_close() -> pd.Series:
    csv_path = resolve_btc_daily_path()
    df = pd.read_csv(csv_path)

    date_col = find_date_col(df)

    close_col = None
    for col in ["close", "Close", "adj_close", "Adj Close"]:
        if col in df.columns:
            close_col = col
            break

    if close_col is None:
        raise ValueError(f"BTC CSV: nenašiel som close stĺpec. Stĺpce: {list(df.columns)}")

    out = df[[date_col, close_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce").dt.normalize()
    out[close_col] = pd.to_numeric(out[close_col], errors="coerce")

    out = out.dropna(subset=[date_col, close_col])
    out = out.drop_duplicates(subset=[date_col]).sort_values(date_col)

    s = out.set_index(date_col)[close_col].astype(float)
    s.name = "btc_close"
    return s


def calc_drawdown(equity: pd.Series) -> pd.Series:
    running_max = equity.cummax()
    return equity / running_max - 1.0


def calc_metrics_from_equity(equity: pd.Series) -> Dict[str, float]:
    equity = equity.dropna().astype(float)
    if len(equity) < 3:
        raise ValueError("Príliš krátka equity séria na výpočet metrík")

    rets = equity.pct_change().fillna(0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0

    days = (equity.index[-1] - equity.index[0]).days
    years = days / 365.25 if days > 0 else np.nan
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years and years > 0 else np.nan

    dd = calc_drawdown(equity)
    max_dd = dd.min()

    daily_vol = rets.std(ddof=0)
    downside = rets[rets < 0].std(ddof=0)

    sharpe = (rets.mean() / daily_vol) * np.sqrt(365) if daily_vol and daily_vol > 0 else np.nan
    sortino = (rets.mean() / downside) * np.sqrt(365) if downside and downside > 0 else np.nan

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
    }


def align_series(
    always_daily: pd.Series,
    soft_kill_4h: pd.Series,
    btc_close: pd.Series,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    common_index = always_daily.index.intersection(soft_kill_4h.index).intersection(btc_close.index)
    common_index = common_index.sort_values()

    if len(common_index) < 30:
        raise ValueError("Príliš malý spoločný prienik dát medzi stratégiami a BTC")

    ad = always_daily.reindex(common_index).dropna()
    sk = soft_kill_4h.reindex(common_index).dropna()
    btc = btc_close.reindex(common_index).dropna()

    common_index = ad.index.intersection(sk.index).intersection(btc.index).sort_values()

    ad = ad.reindex(common_index)
    sk = sk.reindex(common_index)
    btc = btc.reindex(common_index)

    if len(common_index) < 30:
        raise ValueError("Po dropna ostal príliš malý spoločný interval")

    btc_equity = btc / btc.iloc[0]

    return ad, sk, btc_equity


def main() -> None:
    always_daily = load_strategy_equity(ALWAYS_DAILY_PATH, "always_daily")
    soft_kill_4h = load_strategy_equity(SOFT_KILL_4H_PATH, "soft_kill_4h")
    btc_close = load_btc_close()

    always_daily, soft_kill_4h, btc_equity = align_series(always_daily, soft_kill_4h, btc_close)

    metrics = {
        "always_daily": calc_metrics_from_equity(always_daily),
        "soft_kill_4h": calc_metrics_from_equity(soft_kill_4h),
        "btc_buy_hold": calc_metrics_from_equity(btc_equity),
    }

    rows = []
    for name, m in metrics.items():
        row = {"model": name}
        row.update(m)
        rows.append(row)

    out_df = pd.DataFrame(rows)
    out_df = out_df[
        [
            "model",
            "start_date",
            "end_date",
            "days",
            "years",
            "start_equity",
            "end_equity",
            "total_return_pct",
            "cagr_pct",
            "max_drawdown_pct",
            "sharpe",
            "sortino",
        ]
    ]

    out_df.to_csv(OUT_CSV, index=False)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print("\n=== BENCHMARK VS BTC ===")
    print(out_df.to_string(index=False))
    print(f"\nUložené CSV:  {OUT_CSV}")
    print(f"Uložené JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()