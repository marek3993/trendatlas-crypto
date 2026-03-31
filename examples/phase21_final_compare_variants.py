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

OUT_SUMMARY_CSV = OUTPUTS_DIR / "phase21_final_compare_summary.csv"
OUT_EQUITY_CSV = OUTPUTS_DIR / "phase21_final_compare_equity_curves.csv"
OUT_MONTHLY_CSV = OUTPUTS_DIR / "phase21_final_compare_monthly_returns.csv"
OUT_YEARLY_CSV = OUTPUTS_DIR / "phase21_final_compare_yearly_returns.csv"
OUT_JSON = OUTPUTS_DIR / "phase21_final_compare_summary.json"

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
        "ts",
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
        raise FileNotFoundError(f"Nenašiel som CSV pre {symbol} v {DATA_DIR}")

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


def load_phase18_stream(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Chýba súbor: {path}")

    df = pd.read_csv(path)
    ts_col = find_date_col(df)

    required = ["strategy_ret", "equity", "gross_exposure", "selected"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{label}: chýbajú stĺpce: {missing}")

    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    out = out.rename(columns={ts_col: "ts"})
    out["date"] = out["ts"].dt.normalize()

    for col in ["strategy_ret", "equity", "gross_exposure"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    out["selected"] = out["selected"].astype(str)
    out["model"] = label
    return out


def build_btc_3d_neg_signal(closes: pd.DataFrame) -> pd.Series:
    btc = closes["BTCUSDT"]
    ret3 = btc / btc.shift(3) - 1.0
    signal = ret3 < 0
    return signal.astype("boolean").fillna(False).astype(bool)


def run_partial_overlay_backtest(
    base_df: pd.DataFrame,
    daily_signal: pd.Series,
    kill_multiplier: float,
    model_name: str,
) -> pd.DataFrame:
    df = base_df.copy()

    exec_signal_by_day = daily_signal.shift(1)
    exec_signal_by_day = exec_signal_by_day.astype("boolean").fillna(False).astype(bool)

    mapped = df["date"].map(exec_signal_by_day)
    mapped = pd.Series(mapped, index=df.index).astype("boolean").fillna(False).astype(bool)

    df["overlay_kill_day"] = mapped
    df["overlay_multiplier"] = np.where(df["overlay_kill_day"], kill_multiplier, 1.0)
    df["final_ret"] = df["strategy_ret"] * df["overlay_multiplier"]
    df["final_gross_exposure"] = df["gross_exposure"] * df["overlay_multiplier"]
    df["final_selected"] = np.where(df["overlay_multiplier"] < 0.999999, "BTC_3D_NEG_K05", df["selected"])
    df["final_equity"] = (1.0 + df["final_ret"]).cumprod()
    df["final_equity"] = df["final_equity"] / df["final_equity"].iloc[0]
    df["final_model"] = model_name
    return df


def calc_drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def calc_metrics_from_returns(ts: pd.Series, rets: pd.Series, exposure: pd.Series | None = None) -> Dict[str, float]:
    ts = pd.to_datetime(ts)
    rets = pd.to_numeric(rets, errors="coerce").fillna(0.0)
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

    active_fraction = float((exposure > 0).mean()) if exposure is not None else np.nan

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
        "avg_exposure": active_fraction,
    }


def make_period_return_table(ts: pd.Series, rets: pd.Series, freq: str, period_col: str) -> pd.DataFrame:
    df = pd.DataFrame({
        "ts": pd.to_datetime(ts),
        "ret": pd.to_numeric(rets, errors="coerce").fillna(0.0),
    })
    df[period_col] = df["ts"].dt.to_period(freq).astype(str)

    out = (
        df.groupby(period_col, as_index=False)["ret"]
        .apply(lambda s: (1.0 + s).prod() - 1.0)
        .rename(columns={"ret": "period_return"})
    )
    out["period_return_pct"] = out["period_return"] * 100.0
    return out[[period_col, "period_return_pct"]]


def main() -> None:
    always_daily = load_phase18_stream(ALWAYS_DAILY_PATH, "always_daily")
    soft_kill_4h = load_phase18_stream(SOFT_KILL_4H_PATH, "soft_kill_4h")
    closes = load_universe_daily_closes(UNIVERSE)

    common_start = max(
        always_daily["date"].min(),
        soft_kill_4h["date"].min(),
        closes.index.min(),
    )
    common_end = min(
        always_daily["date"].max(),
        soft_kill_4h["date"].max(),
        closes.index.max(),
    )

    always_daily = always_daily[(always_daily["date"] >= common_start) & (always_daily["date"] <= common_end)].copy()
    soft_kill_4h = soft_kill_4h[(soft_kill_4h["date"] >= common_start) & (soft_kill_4h["date"] <= common_end)].copy()
    closes = closes[(closes.index >= common_start) & (closes.index <= common_end)].copy()

    if len(always_daily) < 100 or len(soft_kill_4h) < 100 or len(closes) < 100:
        raise ValueError("Príliš malý spoločný interval")

    signal = build_btc_3d_neg_signal(closes)
    balanced_df = run_partial_overlay_backtest(
        base_df=always_daily,
        daily_signal=signal,
        kill_multiplier=0.50,
        model_name="phase20_btc_3d_neg_k05",
    )

    models = {
        "always_daily": {
            "ts": always_daily["ts"],
            "rets": always_daily["strategy_ret"],
            "exposure": always_daily["gross_exposure"],
            "equity": (1.0 + always_daily["strategy_ret"]).cumprod(),
        },
        "phase20_btc_3d_neg_k05": {
            "ts": balanced_df["ts"],
            "rets": balanced_df["final_ret"],
            "exposure": balanced_df["final_gross_exposure"],
            "equity": balanced_df["final_equity"],
        },
        "soft_kill_4h": {
            "ts": soft_kill_4h["ts"],
            "rets": soft_kill_4h["strategy_ret"],
            "exposure": soft_kill_4h["gross_exposure"],
            "equity": (1.0 + soft_kill_4h["strategy_ret"]).cumprod(),
        },
    }

    summary_rows = []
    monthly_tables = []
    yearly_tables = []

    equity_curves = pd.DataFrame({"ts": always_daily["ts"]})
    for model_name, obj in models.items():
        metrics = calc_metrics_from_returns(
            ts=obj["ts"],
            rets=obj["rets"],
            exposure=obj["exposure"],
        )
        summary_rows.append({"model": model_name, **metrics})
        equity_curves[model_name] = obj["equity"].values

        monthly = make_period_return_table(obj["ts"], obj["rets"], freq="M", period_col="month")
        monthly = monthly.rename(columns={"period_return_pct": model_name})
        monthly_tables.append(monthly)

        yearly = make_period_return_table(obj["ts"], obj["rets"], freq="Y", period_col="year")
        yearly = yearly.rename(columns={"period_return_pct": model_name})
        yearly_tables.append(yearly)

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df[
        [
            "model",
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

    print("\n=== PHASE 21 FINAL COMPARE SUMMARY ===")
    print(summary_df.to_string(index=False))

    print("\n=== YEARLY RETURNS (%) ===")
    print(yearly_df.to_string(index=False))

    print(f"\nUložené summary CSV: {OUT_SUMMARY_CSV}")
    print(f"Uložené equity CSV:  {OUT_EQUITY_CSV}")
    print(f"Uložené monthly CSV: {OUT_MONTHLY_CSV}")
    print(f"Uložené yearly CSV:  {OUT_YEARLY_CSV}")
    print(f"Uložené JSON:        {OUT_JSON}")


if __name__ == "__main__":
    main()