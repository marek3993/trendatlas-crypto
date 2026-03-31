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

OUT_SUMMARY_CSV = OUTPUTS_DIR / "phase28_final_compare_v2_summary.csv"
OUT_EQUITY_CSV = OUTPUTS_DIR / "phase28_final_compare_v2_equity_curves.csv"
OUT_MONTHLY_CSV = OUTPUTS_DIR / "phase28_final_compare_v2_monthly_returns.csv"
OUT_YEARLY_CSV = OUTPUTS_DIR / "phase28_final_compare_v2_yearly_returns.csv"
OUT_JSON = OUTPUTS_DIR / "phase28_final_compare_v2_summary.json"

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

BASE_KILL_MULTIPLIER = 0.50


def find_date_col(df: pd.DataFrame) -> str:
    candidates = [
        "date", "Date", "datetime", "Datetime", "timestamp", "Timestamp",
        "time", "Time", "open_time", "Open time", "ts",
    ]
    for col in candidates:
        if col in df.columns:
            return col

    unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
    if unnamed:
        return unnamed[0]

    first_col = df.columns[0]
    sample = pd.to_datetime(df[first_col], errors="coerce")
    if sample.notna().sum() >= max(3, int(len(df) * 0.5)):
        return first_col

    raise ValueError(f"No datetime column found. Columns: {list(df.columns)}")


def find_price_col(df: pd.DataFrame) -> str:
    for col in ["close", "Close", "adj_close", "Adj Close"]:
        if col in df.columns:
            return col
    raise ValueError(f"No close column found. Columns: {list(df.columns)}")


def clean_sel(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.strip()
    out = out.replace(
        {
            "": "CASH",
            "nan": "CASH",
            "NaN": "CASH",
            "None": "CASH",
            "none": "CASH",
            "NULL": "CASH",
            "null": "CASH",
        }
    )
    return out.fillna("CASH")


def resolve_symbol_csv(symbol: str) -> Path:
    patterns = [
        f"{symbol}.csv",
        f"{symbol.lower()}.csv",
        f"{symbol}_*.csv",
        f"{symbol.lower()}_*.csv",
        f"*{symbol}*.csv",
        f"*{symbol.lower()}*.csv",
    ]
    matches: List[Path] = []
    for pattern in patterns:
        matches.extend(DATA_DIR.glob(pattern))

    matches = [p for p in matches if p.is_file()]
    if not matches:
        raise FileNotFoundError(f"CSV for {symbol} not found in {DATA_DIR}")

    matches = sorted(set(matches), key=lambda p: p.name.lower())
    return matches[0]


def load_daily_close_series(symbol: str) -> pd.Series:
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


def load_universe_daily_closes(symbols: List[str]) -> pd.DataFrame:
    return pd.concat([load_daily_close_series(symbol) for symbol in symbols], axis=1).sort_index()


def load_stream(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path)
    ts_col = find_date_col(df)

    required = ["selected", "gross_exposure", "strategy_ret", "turnover", "cost"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    out = out.rename(columns={ts_col: "ts"})
    out["date"] = out["ts"].dt.normalize()

    out["selected"] = clean_sel(out["selected"])
    for c in ["gross_exposure", "strategy_ret", "turnover", "cost"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)

    return out


def build_kill_signal(closes: pd.DataFrame) -> pd.Series:
    btc = closes["BTCUSDT"]
    ret3 = btc / btc.shift(3) - 1.0
    return (ret3 < 0).astype("boolean").fillna(False).astype(bool)


def rolling_comp(series: pd.Series, n: int) -> pd.Series:
    return (1.0 + series.fillna(0.0)).rolling(n).apply(np.prod, raw=True) - 1.0


def build_lagged_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    lag_ret = out["strategy_ret"].shift(1).fillna(0.0)
    out["lag1_ret"] = lag_ret
    out["lag2_ret"] = rolling_comp(lag_ret, 2).fillna(0.0)
    out["lag3_ret"] = rolling_comp(lag_ret, 3).fillna(0.0)
    return out


def calc_drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def calc_metrics_from_returns(ts: pd.Series, rets: pd.Series, exposure: pd.Series) -> Dict[str, float]:
    ts = pd.to_datetime(ts)
    rets = pd.to_numeric(rets, errors="coerce").fillna(0.0)
    exposure = pd.to_numeric(exposure, errors="coerce").fillna(0.0)

    equity = (1.0 + rets).cumprod()

    days = (ts.iloc[-1] - ts.iloc[0]).days
    years = days / 365.25 if days > 0 else np.nan
    total_return = equity.iloc[-1] - 1.0
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0 if years and years > 0 else np.nan

    dd = calc_drawdown(equity)
    max_dd = dd.min()

    bars_per_year = 365.25 * 6.0
    vol = rets.std(ddof=0)
    downside = rets[rets < 0].std(ddof=0)

    sharpe = (rets.mean() / vol) * np.sqrt(bars_per_year) if vol and vol > 0 else np.nan
    sortino = (rets.mean() / downside) * np.sqrt(bars_per_year) if downside and downside > 0 else np.nan

    return {
        "start_ts": ts.iloc[0].strftime("%Y-%m-%d %H:%M:%S"),
        "end_ts": ts.iloc[-1].strftime("%Y-%m-%d %H:%M:%S"),
        "bars": int(len(ts)),
        "days": int(days),
        "years": float(years) if pd.notna(years) else np.nan,
        "total_return_pct": float(total_return * 100.0),
        "cagr_pct": float(cagr * 100.0) if pd.notna(cagr) else np.nan,
        "max_drawdown_pct": float(max_dd * 100.0),
        "sharpe": float(sharpe) if pd.notna(sharpe) else np.nan,
        "sortino": float(sortino) if pd.notna(sortino) else np.nan,
        "avg_exposure": float((exposure > 0).mean()),
    }


def run_model(df: pd.DataFrame, kill_signal_daily: pd.Series, mode: str) -> pd.DataFrame:
    out = df.copy()

    kill_exec = kill_signal_daily.shift(1).astype("boolean").fillna(False).astype(bool)
    mapped_kill = out["date"].map(kill_exec)
    out["kill_day"] = pd.Series(mapped_kill, index=out.index).astype("boolean").fillna(False).astype(bool)

    if mode == "always_daily":
        out["overlay_multiplier"] = 1.0
    elif mode == "phase20_btc_3d_neg_k05":
        out["overlay_multiplier"] = np.where(out["kill_day"], BASE_KILL_MULTIPLIER, 1.0)
    elif mode == "phase27_lag2_gt_3pct":
        out["override_day"] = out["lag2_ret"] > 0.03
        out["overlay_multiplier"] = np.where(out["kill_day"], BASE_KILL_MULTIPLIER, 1.0)
        out.loc[out["kill_day"] & out["override_day"], "overlay_multiplier"] = 1.0
    else:
        raise ValueError(f"Unknown mode: {mode}")

    out["final_ret"] = out["strategy_ret"] * out["overlay_multiplier"]
    out["final_gross_exposure"] = out["gross_exposure"] * out["overlay_multiplier"]
    out["final_equity"] = (1.0 + out["final_ret"]).cumprod()
    out["final_equity"] = out["final_equity"] / out["final_equity"].iloc[0]
    out["final_selected"] = np.where(out["overlay_multiplier"] < 0.999999, "HALF_RISK", out["selected"])

    return out


def make_period_return_table(ts: pd.Series, rets: pd.Series, freq: str, period_col: str) -> pd.DataFrame:
    df = pd.DataFrame({
        "ts": pd.to_datetime(ts),
        "ret": pd.to_numeric(rets, errors="coerce").fillna(0.0),
    })
    df[period_col] = df["ts"].dt.to_period(freq).astype(str)

    grouped = (
        df.groupby(period_col)["ret"]
        .apply(lambda s: (1.0 + s).prod() - 1.0)
        .reset_index(name="period_return")
    )
    grouped["period_return_pct"] = grouped["period_return"] * 100.0
    return grouped[[period_col, "period_return_pct"]]


def main() -> None:
    df = load_stream(ALWAYS_DAILY_PATH)
    closes = load_universe_daily_closes(UNIVERSE)

    common_start = max(df["date"].min(), closes.index.min())
    common_end = min(df["date"].max(), closes.index.max())

    df = df[(df["date"] >= common_start) & (df["date"] <= common_end)].copy()
    closes = closes[(closes.index >= common_start) & (closes.index <= common_end)].copy()

    df = build_lagged_features(df)
    kill_signal = build_kill_signal(closes)

    model_keys = [
        "always_daily",
        "phase20_btc_3d_neg_k05",
        "phase27_lag2_gt_3pct",
    ]

    label_map = {
        "always_daily": "Always Daily",
        "phase20_btc_3d_neg_k05": "BTC 3D Negative x0.50",
        "phase27_lag2_gt_3pct": "Balanced Override v2",
    }

    summary_rows = []
    equity_curves = pd.DataFrame({"ts": df["ts"]})
    monthly_tables = []
    yearly_tables = []

    for key in model_keys:
        bt = run_model(df, kill_signal, key)

        metrics = calc_metrics_from_returns(
            ts=bt["ts"],
            rets=bt["final_ret"],
            exposure=bt["final_gross_exposure"],
        )
        summary_rows.append(
            {
                "model": key,
                "label": label_map[key],
                **metrics,
            }
        )

        equity_curves[key] = bt["final_equity"].values

        monthly = make_period_return_table(bt["ts"], bt["final_ret"], "M", "month")
        monthly = monthly.rename(columns={"period_return_pct": key})
        monthly_tables.append(monthly)

        yearly = make_period_return_table(bt["ts"], bt["final_ret"], "Y", "year")
        yearly = yearly.rename(columns={"period_return_pct": key})
        yearly_tables.append(yearly)

        detail_path = OUTPUTS_DIR / f"{key}_phase28_detail.csv"
        bt[
            [
                "ts",
                "date",
                "selected",
                "gross_exposure",
                "strategy_ret",
                "kill_day",
                "overlay_multiplier",
                "final_ret",
                "final_gross_exposure",
                "final_equity",
            ]
        ].to_csv(detail_path, index=False)

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df[
        [
            "model",
            "label",
            "start_ts",
            "end_ts",
            "bars",
            "days",
            "years",
            "total_return_pct",
            "cagr_pct",
            "max_drawdown_pct",
            "sharpe",
            "sortino",
            "avg_exposure",
        ]
    ]
    summary_df = summary_df.sort_values(["sharpe", "cagr_pct"], ascending=[False, False]).reset_index(drop=True)

    monthly_df = monthly_tables[0]
    for t in monthly_tables[1:]:
        monthly_df = monthly_df.merge(t, on="month", how="outer")
    monthly_df = monthly_df.sort_values("month").reset_index(drop=True)

    yearly_df = yearly_tables[0]
    for t in yearly_tables[1:]:
        yearly_df = yearly_df.merge(t, on="year", how="outer")
    yearly_df = yearly_df.sort_values("year").reset_index(drop=True)

    summary_df.to_csv(OUT_SUMMARY_CSV, index=False)
    equity_curves.to_csv(OUT_EQUITY_CSV, index=False)
    monthly_df.to_csv(OUT_MONTHLY_CSV, index=False)
    yearly_df.to_csv(OUT_YEARLY_CSV, index=False)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary_rows, f, indent=2)

    print("\n=== PHASE 28 FINAL COMPARE V2 SUMMARY ===")
    print(summary_df.to_string(index=False))

    print("\n=== YEARLY RETURNS (%) ===")
    print(yearly_df.to_string(index=False))

    print(f"\nSaved summary CSV: {OUT_SUMMARY_CSV}")
    print(f"Saved equity CSV:  {OUT_EQUITY_CSV}")
    print(f"Saved monthly CSV: {OUT_MONTHLY_CSV}")
    print(f"Saved yearly CSV:  {OUT_YEARLY_CSV}")
    print(f"Saved JSON:        {OUT_JSON}")


if __name__ == "__main__":
    main()