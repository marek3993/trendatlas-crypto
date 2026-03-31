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

OUT_RESULTS_CSV = OUTPUTS_DIR / "phase23_fast_reentry_results.csv"
OUT_EQUITY_CSV = OUTPUTS_DIR / "phase23_fast_reentry_equity_curves.csv"
OUT_JSON = OUTPUTS_DIR / "phase23_fast_reentry_best.json"

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

REENTRY_CANDIDATES = [
    {"model": "phase23_btc1d_pos", "reentry_mode": "btc_1d_pos"},
    {"model": "phase23_btc2d_pos", "reentry_mode": "btc_2d_pos"},
    {"model": "phase23_breadth1d_50", "reentry_mode": "breadth_1d_ge_050"},
    {"model": "phase23_breadth1d_60", "reentry_mode": "breadth_1d_ge_060"},
    {"model": "phase23_btc1d_and_breadth50", "reentry_mode": "btc_1d_pos_and_breadth_1d_ge_050"},
    {"model": "phase23_btc1d_and_breadth60", "reentry_mode": "btc_1d_pos_and_breadth_1d_ge_060"},
    {"model": "phase23_btc2d_and_breadth50", "reentry_mode": "btc_2d_pos_and_breadth_1d_ge_050"},
    {"model": "phase23_btc1d_or_breadth60", "reentry_mode": "btc_1d_pos_or_breadth_1d_ge_060"},
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


def load_phase18_stream(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path)
    ts_col = find_date_col(df)

    required = ["strategy_ret", "gross_exposure", "selected", "turnover", "cost"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{label}: missing columns: {missing}")

    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    out = out.rename(columns={ts_col: "ts"})
    out["date"] = out["ts"].dt.normalize()

    for col in ["strategy_ret", "gross_exposure", "turnover", "cost"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    out["selected"] = out["selected"].astype(str).fillna("CASH")
    out["model"] = label
    return out


def build_signal_pack(closes: pd.DataFrame) -> pd.DataFrame:
    btc = closes["BTCUSDT"]

    btc_1d = btc / btc.shift(1) - 1.0
    btc_2d = btc / btc.shift(2) - 1.0
    btc_3d = btc / btc.shift(3) - 1.0

    cross_1d = closes / closes.shift(1) - 1.0
    breadth_1d = (cross_1d > 0).mean(axis=1)

    sig = pd.DataFrame(index=closes.index)
    sig["kill_btc_3d_neg"] = (btc_3d < 0).astype("boolean").fillna(False).astype(bool)

    sig["btc_1d_pos"] = (btc_1d > 0).astype("boolean").fillna(False).astype(bool)
    sig["btc_2d_pos"] = (btc_2d > 0).astype("boolean").fillna(False).astype(bool)
    sig["breadth_1d_ge_050"] = (breadth_1d >= 0.50).astype("boolean").fillna(False).astype(bool)
    sig["breadth_1d_ge_060"] = (breadth_1d >= 0.60).astype("boolean").fillna(False).astype(bool)

    sig["btc_1d_pos_and_breadth_1d_ge_050"] = sig["btc_1d_pos"] & sig["breadth_1d_ge_050"]
    sig["btc_1d_pos_and_breadth_1d_ge_060"] = sig["btc_1d_pos"] & sig["breadth_1d_ge_060"]
    sig["btc_2d_pos_and_breadth_1d_ge_050"] = sig["btc_2d_pos"] & sig["breadth_1d_ge_050"]
    sig["btc_1d_pos_or_breadth_1d_ge_060"] = sig["btc_1d_pos"] | sig["breadth_1d_ge_060"]

    return sig


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


def run_fast_reentry_backtest(
    base_df: pd.DataFrame,
    signals: pd.DataFrame,
    reentry_mode: str,
    model_name: str,
) -> pd.DataFrame:
    df = base_df.copy()

    kill_day = signals["kill_btc_3d_neg"].shift(1).astype("boolean").fillna(False).astype(bool)
    reentry_day = signals[reentry_mode].shift(1).astype("boolean").fillna(False).astype(bool)

    mapped_kill = df["date"].map(kill_day)
    mapped_kill = pd.Series(mapped_kill, index=df.index).astype("boolean").fillna(False).astype(bool)

    mapped_reentry = df["date"].map(reentry_day)
    mapped_reentry = pd.Series(mapped_reentry, index=df.index).astype("boolean").fillna(False).astype(bool)

    df["kill_day"] = mapped_kill
    df["reentry_day"] = mapped_reentry

    df["overlay_multiplier"] = np.where(df["kill_day"], BASE_KILL_MULTIPLIER, 1.0)
    df.loc[df["kill_day"] & df["reentry_day"], "overlay_multiplier"] = 1.0

    df["final_ret"] = df["strategy_ret"] * df["overlay_multiplier"]
    df["final_gross_exposure"] = df["gross_exposure"] * df["overlay_multiplier"]
    df["final_selected"] = np.where(df["overlay_multiplier"] < 0.999999, "FAST_REENTRY_OVERLAY", df["selected"])
    df["final_equity"] = (1.0 + df["final_ret"]).cumprod()
    df["final_equity"] = df["final_equity"] / df["final_equity"].iloc[0]
    df["final_model"] = model_name

    return df


def main() -> None:
    always_daily = load_phase18_stream(ALWAYS_DAILY_PATH, "always_daily")
    closes = load_universe_daily_closes(UNIVERSE)

    common_start = max(always_daily["date"].min(), closes.index.min())
    common_end = min(always_daily["date"].max(), closes.index.max())

    always_daily = always_daily[(always_daily["date"] >= common_start) & (always_daily["date"] <= common_end)].copy()
    closes = closes[(closes.index >= common_start) & (closes.index <= common_end)].copy()

    if len(always_daily) < 100 or len(closes) < 100:
        raise ValueError("Common interval is too small.")

    signals = build_signal_pack(closes)

    results = []
    equity_curves = pd.DataFrame({"ts": always_daily["ts"]})

    base_metrics = calc_metrics_from_returns(
        ts=always_daily["ts"],
        rets=always_daily["strategy_ret"],
        exposure=always_daily["gross_exposure"],
    )
    results.append(
        {
            "model": "always_daily",
            "reentry_mode": "none",
            "kill_multiplier": 1.0,
            "kill_day_pct": 0.0,
            "reentry_day_pct": 0.0,
            **base_metrics,
        }
    )
    equity_curves["always_daily"] = (1.0 + always_daily["strategy_ret"]).cumprod()

    current_balanced = run_fast_reentry_backtest(
        base_df=always_daily,
        signals=signals.assign(never_reenter=False),
        reentry_mode="never_reenter",
        model_name="phase20_btc_3d_neg_k05",
    )
    current_metrics = calc_metrics_from_returns(
        ts=current_balanced["ts"],
        rets=current_balanced["final_ret"],
        exposure=current_balanced["final_gross_exposure"],
    )
    results.append(
        {
            "model": "phase20_btc_3d_neg_k05",
            "reentry_mode": "none",
            "kill_multiplier": BASE_KILL_MULTIPLIER,
            "kill_day_pct": float(current_balanced["kill_day"].mean() * 100.0),
            "reentry_day_pct": 0.0,
            **current_metrics,
        }
    )
    equity_curves["phase20_btc_3d_neg_k05"] = current_balanced["final_equity"].values

    for cfg in REENTRY_CANDIDATES:
        model_name = cfg["model"]
        reentry_mode = cfg["reentry_mode"]

        df = run_fast_reentry_backtest(
            base_df=always_daily,
            signals=signals,
            reentry_mode=reentry_mode,
            model_name=model_name,
        )

        metrics = calc_metrics_from_returns(
            ts=df["ts"],
            rets=df["final_ret"],
            exposure=df["final_gross_exposure"],
        )

        results.append(
            {
                "model": model_name,
                "reentry_mode": reentry_mode,
                "kill_multiplier": BASE_KILL_MULTIPLIER,
                "kill_day_pct": float(df["kill_day"].mean() * 100.0),
                "reentry_day_pct": float((df["kill_day"] & df["reentry_day"]).mean() * 100.0),
                **metrics,
            }
        )

        equity_curves[model_name] = df["final_equity"].values

        detail_path = OUTPUTS_DIR / f"{model_name}_detail.csv"
        df[
            [
                "ts",
                "date",
                "selected",
                "gross_exposure",
                "strategy_ret",
                "kill_day",
                "reentry_day",
                "overlay_multiplier",
                "final_ret",
                "final_gross_exposure",
                "final_selected",
                "final_equity",
            ]
        ].to_csv(detail_path, index=False)

    results_df = pd.DataFrame(results)
    results_df = results_df[
        [
            "model",
            "reentry_mode",
            "kill_multiplier",
            "kill_day_pct",
            "reentry_day_pct",
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

    print("\n=== PHASE 23 FAST RE-ENTRY RESULTS ===")
    print(results_df.to_string(index=False))
    print(f"\nSaved results CSV: {OUT_RESULTS_CSV}")
    print(f"Saved equity CSV:  {OUT_EQUITY_CSV}")
    print(f"Saved best JSON:   {OUT_JSON}")


if __name__ == "__main__":
    main()