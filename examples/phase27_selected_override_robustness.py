from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data" / "ohlcv"

ALWAYS_DAILY_PATH = OUTPUTS_DIR / "phase18_always_daily.csv"

OUT_RESULTS_CSV = OUTPUTS_DIR / "phase27_selected_override_robustness_results.csv"
OUT_SUBPERIOD_CSV = OUTPUTS_DIR / "phase27_selected_override_robustness_subperiods.csv"
OUT_EQUITY_CSV = OUTPUTS_DIR / "phase27_selected_override_robustness_equity_curves.csv"
OUT_JSON = OUTPUTS_DIR / "phase27_selected_override_robustness_best.json"

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

CANDIDATES = [
    {"model": "lag2_gt_2pct", "bars": 2, "threshold": 0.020},
    {"model": "lag2_gt_2p5pct", "bars": 2, "threshold": 0.025},
    {"model": "lag2_gt_3pct", "bars": 2, "threshold": 0.030},
    {"model": "lag2_gt_3p5pct", "bars": 2, "threshold": 0.035},
    {"model": "lag2_gt_4pct", "bars": 2, "threshold": 0.040},
    {"model": "lag3_gt_4pct", "bars": 3, "threshold": 0.040},
    {"model": "lag3_gt_5pct", "bars": 3, "threshold": 0.050},
    {"model": "lag3_gt_6pct", "bars": 3, "threshold": 0.060},
]

SUBPERIODS = [
    ("2019-01-01", "2021-12-31", "2019_2021"),
    ("2022-01-01", "2023-12-31", "2022_2023"),
    ("2024-01-01", "2026-03-17", "2024_2026"),
]


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
    cols = [load_daily_close_series(symbol) for symbol in symbols]
    return pd.concat(cols, axis=1).sort_index()


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


def run_model(df: pd.DataFrame, kill_signal_daily: pd.Series, bars: int | None, threshold: float | None, model_name: str) -> pd.DataFrame:
    out = df.copy()

    kill_exec = kill_signal_daily.shift(1).astype("boolean").fillna(False).astype(bool)
    mapped_kill = out["date"].map(kill_exec)
    out["kill_day"] = pd.Series(mapped_kill, index=out.index).astype("boolean").fillna(False).astype(bool)

    if bars is None:
        out["override_day"] = False
    else:
        ret_col = f"lag{bars}_ret"
        out["override_day"] = out[ret_col] > threshold

    out["overlay_multiplier"] = np.where(out["kill_day"], BASE_KILL_MULTIPLIER, 1.0)
    out.loc[out["kill_day"] & out["override_day"], "overlay_multiplier"] = 1.0

    out["final_ret"] = out["strategy_ret"] * out["overlay_multiplier"]
    out["final_gross_exposure"] = out["gross_exposure"] * out["overlay_multiplier"]
    out["final_equity"] = (1.0 + out["final_ret"]).cumprod()
    out["final_equity"] = out["final_equity"] / out["final_equity"].iloc[0]
    out["final_model"] = model_name
    return out


def calc_subperiod_metrics(bt: pd.DataFrame, period_start: str, period_end: str) -> Dict[str, float]:
    start = pd.Timestamp(period_start)
    end = pd.Timestamp(period_end)

    sub = bt[(bt["date"] >= start) & (bt["date"] <= end)].copy()
    if len(sub) < 20:
        return {
            "bars": 0,
            "total_return_pct": np.nan,
            "cagr_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "sharpe": np.nan,
            "sortino": np.nan,
        }

    return calc_metrics_from_returns(
        ts=sub["ts"],
        rets=sub["final_ret"],
        exposure=sub["final_gross_exposure"],
    )


def main() -> None:
    df = load_stream(ALWAYS_DAILY_PATH)
    closes = load_universe_daily_closes(UNIVERSE)

    common_start = max(df["date"].min(), closes.index.min())
    common_end = min(df["date"].max(), closes.index.max())

    df = df[(df["date"] >= common_start) & (df["date"] <= common_end)].copy()
    closes = closes[(closes.index >= common_start) & (closes.index <= common_end)].copy()

    df = build_lagged_features(df)
    kill_signal = build_kill_signal(closes)

    results = []
    subperiod_rows = []
    equity_curves = pd.DataFrame({"ts": df["ts"]})

    models_to_run: List[Tuple[str, int | None, float | None]] = [
        ("always_daily", None, None),
        ("phase20_btc_3d_neg_k05", 999, 999),  # special case below
    ]
    models_to_run.extend([(c["model"], c["bars"], c["threshold"]) for c in CANDIDATES])

    for model_name, bars, threshold in models_to_run:
        if model_name == "always_daily":
            bt = run_model(df, kill_signal, None, None, model_name)
            bt["overlay_multiplier"] = 1.0
            bt["final_ret"] = bt["strategy_ret"]
            bt["final_gross_exposure"] = bt["gross_exposure"]
            bt["final_equity"] = (1.0 + bt["final_ret"]).cumprod()
            bt["final_equity"] = bt["final_equity"] / bt["final_equity"].iloc[0]
            override_mode = "none"
            override_used_pct = 0.0

        elif model_name == "phase20_btc_3d_neg_k05":
            bt = run_model(df, kill_signal, None, None, model_name)
            override_mode = "none"
            override_used_pct = 0.0

        else:
            bt = run_model(df, kill_signal, bars, threshold, model_name)
            override_mode = f"lag{bars}_gt_{threshold:.3f}"
            override_used_pct = float((bt["kill_day"] & bt["override_day"]).mean() * 100.0)

        metrics = calc_metrics_from_returns(
            ts=bt["ts"],
            rets=bt["final_ret"],
            exposure=bt["final_gross_exposure"],
        )

        results.append(
            {
                "model": model_name,
                "override_mode": override_mode,
                "kill_day_pct": float(bt["kill_day"].mean() * 100.0) if model_name != "always_daily" else 0.0,
                "override_used_pct": override_used_pct,
                **metrics,
            }
        )

        equity_curves[model_name] = bt["final_equity"].values

        for ps, pe, label in SUBPERIODS:
            subm = calc_subperiod_metrics(bt, ps, pe)
            subperiod_rows.append(
                {
                    "model": model_name,
                    "subperiod": label,
                    **subm,
                }
            )

    results_df = pd.DataFrame(results)
    results_df = results_df[
        [
            "model",
            "override_mode",
            "kill_day_pct",
            "override_used_pct",
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
    results_df = results_df.sort_values(["sharpe", "cagr_pct"], ascending=[False, False]).reset_index(drop=True)

    subperiod_df = pd.DataFrame(subperiod_rows)
    subperiod_df = subperiod_df.sort_values(["model", "subperiod"]).reset_index(drop=True)

    results_df.to_csv(OUT_RESULTS_CSV, index=False)
    subperiod_df.to_csv(OUT_SUBPERIOD_CSV, index=False)
    equity_curves.to_csv(OUT_EQUITY_CSV, index=False)

    best_row = results_df.iloc[0].to_dict()
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(best_row, f, indent=2)

    print("\n=== PHASE 27 SELECTED OVERRIDE ROBUSTNESS ===")
    print(results_df.to_string(index=False))

    print("\n=== PHASE 27 SUBPERIODS ===")
    print(subperiod_df.to_string(index=False))

    print(f"\nSaved results CSV:   {OUT_RESULTS_CSV}")
    print(f"Saved subperiod CSV: {OUT_SUBPERIOD_CSV}")
    print(f"Saved equity CSV:    {OUT_EQUITY_CSV}")
    print(f"Saved best JSON:     {OUT_JSON}")


if __name__ == "__main__":
    main()