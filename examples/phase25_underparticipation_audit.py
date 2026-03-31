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

OUT_RESULTS_CSV = OUTPUTS_DIR / "phase26_selected_coin_override_results.csv"
OUT_EQUITY_CSV = OUTPUTS_DIR / "phase26_selected_coin_override_equity_curves.csv"
OUT_JSON = OUTPUTS_DIR / "phase26_selected_coin_override_best.json"

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

OVERRIDE_CANDIDATES = [
    {"model": "phase26_sel_1bar_gt_0", "mode": "selected_1bar_gt_0"},
    {"model": "phase26_sel_1bar_gt_2pct", "mode": "selected_1bar_gt_0p02"},
    {"model": "phase26_sel_2bar_gt_3pct", "mode": "selected_2bar_gt_0p03"},
    {"model": "phase26_sel_3bar_gt_5pct", "mode": "selected_3bar_gt_0p05"},
    {"model": "phase26_turnover_only", "mode": "turnover_gt_0"},
    {"model": "phase26_turnover_sel_1bar_gt_0", "mode": "turnover_gt_0_and_selected_1bar_gt_0"},
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

    required = [
        "daily_selected",
        "selected",
        "gross_exposure",
        "strategy_ret",
        "selected_ret_next",
        "turnover",
        "cost",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    out = out.rename(columns={ts_col: "ts"})
    out["date"] = out["ts"].dt.normalize()

    out["daily_selected"] = clean_sel(out["daily_selected"])
    out["selected"] = clean_sel(out["selected"])

    for c in ["gross_exposure", "strategy_ret", "selected_ret_next", "turnover", "cost"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)

    return out


def build_kill_signal(closes: pd.DataFrame) -> pd.Series:
    btc = closes["BTCUSDT"]
    ret3 = btc / btc.shift(3) - 1.0
    signal = ret3 < 0
    return signal.astype("boolean").fillna(False).astype(bool)


def build_selected_override_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["selected_1bar_ret"] = out["selected_ret_next"].fillna(0.0)

    def rolling_comp(series: pd.Series, n: int) -> pd.Series:
        return (1.0 + series.fillna(0.0)).rolling(n).apply(np.prod, raw=True) - 1.0

    out["selected_2bar_ret"] = (
        out.groupby("selected", group_keys=False)["selected_ret_next"]
        .apply(lambda s: rolling_comp(s, 2))
        .fillna(0.0)
    )
    out["selected_3bar_ret"] = (
        out.groupby("selected", group_keys=False)["selected_ret_next"]
        .apply(lambda s: rolling_comp(s, 3))
        .fillna(0.0)
    )

    out["ov_selected_1bar_gt_0"] = out["selected_1bar_ret"] > 0.0
    out["ov_selected_1bar_gt_0p02"] = out["selected_1bar_ret"] > 0.02
    out["ov_selected_2bar_gt_0p03"] = out["selected_2bar_ret"] > 0.03
    out["ov_selected_3bar_gt_0p05"] = out["selected_3bar_ret"] > 0.05
    out["ov_turnover_gt_0"] = out["turnover"] > 0.0
    out["ov_turnover_gt_0_and_selected_1bar_gt_0"] = out["ov_turnover_gt_0"] & out["ov_selected_1bar_gt_0"]

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


def run_backtest(df: pd.DataFrame, kill_signal_daily: pd.Series, override_mode: str | None, model_name: str) -> pd.DataFrame:
    out = df.copy()

    kill_exec = kill_signal_daily.shift(1).astype("boolean").fillna(False).astype(bool)
    out["kill_day"] = out["date"].map(kill_exec).astype("boolean").fillna(False).astype(bool)

    if override_mode is None:
        out["override_day"] = False
    else:
        col_map = {
            "selected_1bar_gt_0": "ov_selected_1bar_gt_0",
            "selected_1bar_gt_0p02": "ov_selected_1bar_gt_0p02",
            "selected_2bar_gt_0p03": "ov_selected_2bar_gt_0p03",
            "selected_3bar_gt_0p05": "ov_selected_3bar_gt_0p05",
            "turnover_gt_0": "ov_turnover_gt_0",
            "turnover_gt_0_and_selected_1bar_gt_0": "ov_turnover_gt_0_and_selected_1bar_gt_0",
        }
        flag_col = col_map[override_mode]
        out["override_day"] = out[flag_col].astype(bool)

    out["overlay_multiplier"] = np.where(out["kill_day"], BASE_KILL_MULTIPLIER, 1.0)
    out.loc[out["kill_day"] & out["override_day"], "overlay_multiplier"] = 1.0

    out["final_ret"] = out["strategy_ret"] * out["overlay_multiplier"]
    out["final_gross_exposure"] = out["gross_exposure"] * out["overlay_multiplier"]
    out["final_selected"] = np.where(out["overlay_multiplier"] < 0.999999, "HALF_RISK", out["selected"])
    out["final_equity"] = (1.0 + out["final_ret"]).cumprod()
    out["final_equity"] = out["final_equity"] / out["final_equity"].iloc[0]
    out["final_model"] = model_name

    return out


def main() -> None:
    df = load_stream(ALWAYS_DAILY_PATH)
    closes = load_universe_daily_closes(UNIVERSE)

    common_start = max(df["date"].min(), closes.index.min())
    common_end = min(df["date"].max(), closes.index.max())

    df = df[(df["date"] >= common_start) & (df["date"] <= common_end)].copy()
    closes = closes[(closes.index >= common_start) & (closes.index <= common_end)].copy()

    df = build_selected_override_flags(df)
    kill_signal = build_kill_signal(closes)

    results = []
    equity_curves = pd.DataFrame({"ts": df["ts"]})

    # aggressive
    aggressive = run_backtest(df, kill_signal, None, "always_daily")
    aggressive["overlay_multiplier"] = 1.0
    aggressive["final_ret"] = aggressive["strategy_ret"]
    aggressive["final_gross_exposure"] = aggressive["gross_exposure"]
    aggressive["final_equity"] = (1.0 + aggressive["final_ret"]).cumprod()
    aggressive["final_equity"] = aggressive["final_equity"] / aggressive["final_equity"].iloc[0]

    aggressive_metrics = calc_metrics_from_returns(
        ts=aggressive["ts"],
        rets=aggressive["final_ret"],
        exposure=aggressive["final_gross_exposure"],
    )
    results.append(
        {
            "model": "always_daily",
            "override_mode": "none",
            "kill_day_pct": 0.0,
            "override_used_pct": 0.0,
            **aggressive_metrics,
        }
    )
    equity_curves["always_daily"] = aggressive["final_equity"].values

    # base balanced
    balanced = run_backtest(df, kill_signal, "selected_1bar_gt_0", "phase20_btc_3d_neg_k05")
    balanced["override_day"] = False
    balanced["overlay_multiplier"] = np.where(balanced["kill_day"], BASE_KILL_MULTIPLIER, 1.0)
    balanced["final_ret"] = balanced["strategy_ret"] * balanced["overlay_multiplier"]
    balanced["final_gross_exposure"] = balanced["gross_exposure"] * balanced["overlay_multiplier"]
    balanced["final_equity"] = (1.0 + balanced["final_ret"]).cumprod()
    balanced["final_equity"] = balanced["final_equity"] / balanced["final_equity"].iloc[0]

    balanced_metrics = calc_metrics_from_returns(
        ts=balanced["ts"],
        rets=balanced["final_ret"],
        exposure=balanced["final_gross_exposure"],
    )
    results.append(
        {
            "model": "phase20_btc_3d_neg_k05",
            "override_mode": "none",
            "kill_day_pct": float(balanced["kill_day"].mean() * 100.0),
            "override_used_pct": 0.0,
            **balanced_metrics,
        }
    )
    equity_curves["phase20_btc_3d_neg_k05"] = balanced["final_equity"].values

    for cfg in OVERRIDE_CANDIDATES:
        model_name = cfg["model"]
        mode = cfg["mode"]

        bt = run_backtest(df, kill_signal, mode, model_name)

        metrics = calc_metrics_from_returns(
            ts=bt["ts"],
            rets=bt["final_ret"],
            exposure=bt["final_gross_exposure"],
        )

        results.append(
            {
                "model": model_name,
                "override_mode": mode,
                "kill_day_pct": float(bt["kill_day"].mean() * 100.0),
                "override_used_pct": float((bt["kill_day"] & bt["override_day"]).mean() * 100.0),
                **metrics,
            }
        )

        equity_curves[model_name] = bt["final_equity"].values

        detail_path = OUTPUTS_DIR / f"{model_name}_detail.csv"
        bt[
            [
                "ts",
                "date",
                "selected",
                "gross_exposure",
                "strategy_ret",
                "selected_ret_next",
                "turnover",
                "kill_day",
                "override_day",
                "overlay_multiplier",
                "final_ret",
                "final_gross_exposure",
                "final_equity",
            ]
        ].to_csv(detail_path, index=False)

    results_df = pd.DataFrame(results)
    results_df = results_df[
        [
            "model",
            "override_mode",
            "kill_day_pct",
            "override_used_pct",
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
    results_df = results_df.sort_values(["sharpe", "cagr_pct"], ascending=[False, False]).reset_index(drop=True)

    results_df.to_csv(OUT_RESULTS_CSV, index=False)
    equity_curves.to_csv(OUT_EQUITY_CSV, index=False)

    best_row = results_df.iloc[0].to_dict()
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(best_row, f, indent=2)

    print("\n=== PHASE 26 SELECTED COIN OVERRIDE RESULTS ===")
    print(results_df.to_string(index=False))
    print(f"\nSaved results CSV: {OUT_RESULTS_CSV}")
    print(f"Saved equity CSV:  {OUT_EQUITY_CSV}")
    print(f"Saved best JSON:   {OUT_JSON}")


if __name__ == "__main__":
    main()