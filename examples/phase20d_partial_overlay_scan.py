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

OUT_RESULTS_CSV = OUTPUTS_DIR / "phase20d_partial_overlay_results.csv"
OUT_EQUITY_CSV = OUTPUTS_DIR / "phase20d_partial_overlay_equity_curves.csv"
OUT_JSON = OUTPUTS_DIR / "phase20d_partial_overlay_best.json"

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

KILL_MULTIPLIERS = [0.25, 0.50, 0.75]


def find_date_col(df: pd.DataFrame) -> str:
    candidates = [
        "date", "Date", "datetime", "Datetime", "timestamp", "Timestamp",
        "time", "Time", "open_time", "Open time", "ts",
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
    matches = []
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
    cols = [load_daily_close_series(symbol) for symbol in symbols]
    return pd.concat(cols, axis=1).sort_index()


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
    signal = (ret3 < 0)
    return signal.fillna(False).astype(bool)


def calc_drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def calc_metrics_from_returns(ts: pd.Series, rets: pd.Series, exposure: pd.Series | None = None) -> Dict[str, float]:
    ts = pd.to_datetime(ts)
    rets = pd.to_numeric(rets, errors="coerce").fillna(0.0)

    equity = (1.0 + rets).cumprod()

    days = (ts.iloc[-1] - ts.iloc[0]).days
    years = days / 365.25 if days > 0 else np.nan
    total_return = equity.iloc[-1] - 1.0
    cagr = (equity.iloc[-1]) ** (1.0 / years) - 1.0 if years and years > 0 else np.nan

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


def run_overlay_backtest(
    base_df: pd.DataFrame,
    daily_signal: pd.Series,
    kill_multiplier: float,
    model_name: str,
) -> pd.DataFrame:
    df = base_df.copy()

    exec_signal_by_day = daily_signal.shift(1)
    exec_signal_by_day = exec_signal_by_day.reindex(sorted(exec_signal_by_day.index)).astype("boolean").fillna(False).astype(bool)

    mapped_kill = df["date"].map(exec_signal_by_day)
    mapped_kill = pd.Series(mapped_kill, index=df.index).astype("boolean").fillna(False).astype(bool)

    df["overlay_kill_day"] = mapped_kill
    df["overlay_multiplier"] = np.where(df["overlay_kill_day"], kill_multiplier, 1.0)
    df["overlay_strategy_ret"] = df["strategy_ret"] * df["overlay_multiplier"]
    df["overlay_equity"] = (1.0 + df["overlay_strategy_ret"]).cumprod()
    df["overlay_equity"] = df["overlay_equity"] / df["overlay_equity"].iloc[0]
    df["overlay_selected"] = np.where(df["overlay_multiplier"] < 0.999999, "PARTIAL_OVERLAY", df["selected"])
    df["overlay_gross_exposure"] = df["gross_exposure"] * df["overlay_multiplier"]
    df["overlay_model"] = model_name

    return df


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
            "overlay_mode": "none",
            "kill_multiplier": 1.0,
            "kill_day_pct": 0.0,
            **base_metrics,
        }
    )
    equity_curves["always_daily"] = (1.0 + always_daily["strategy_ret"]).cumprod()

    soft_metrics = calc_metrics_from_returns(
        ts=soft_kill_4h["ts"],
        rets=soft_kill_4h["strategy_ret"],
        exposure=soft_kill_4h["gross_exposure"],
    )
    results.append(
        {
            "model": "soft_kill_4h",
            "overlay_mode": "reference",
            "kill_multiplier": np.nan,
            "kill_day_pct": np.nan,
            **soft_metrics,
        }
    )
    equity_curves["soft_kill_4h"] = (1.0 + soft_kill_4h["strategy_ret"]).cumprod()

    signal = build_btc_3d_neg_signal(closes)

    for kill_multiplier in KILL_MULTIPLIERS:
        model_name = f"phase20_btc_3d_neg_k{str(kill_multiplier).replace('.', '')}"

        overlay_df = run_overlay_backtest(
            base_df=always_daily,
            daily_signal=signal,
            kill_multiplier=kill_multiplier,
            model_name=model_name,
        )

        metrics = calc_metrics_from_returns(
            ts=overlay_df["ts"],
            rets=overlay_df["overlay_strategy_ret"],
            exposure=overlay_df["overlay_gross_exposure"],
        )

        exec_signal = signal.shift(1)
        exec_signal = exec_signal.reindex(sorted(exec_signal.index)).astype("boolean").fillna(False).astype(bool)
        kill_day_pct = float(exec_signal.mean() * 100.0)

        results.append(
            {
                "model": model_name,
                "overlay_mode": "btc_3d_neg",
                "kill_multiplier": kill_multiplier,
                "kill_day_pct": kill_day_pct,
                **metrics,
            }
        )

        equity_curves[model_name] = overlay_df["overlay_equity"].values

        detail_path = OUTPUTS_DIR / f"{model_name}_detail.csv"
        overlay_df[
            [
                "ts",
                "date",
                "selected",
                "gross_exposure",
                "strategy_ret",
                "overlay_kill_day",
                "overlay_multiplier",
                "overlay_strategy_ret",
                "overlay_gross_exposure",
                "overlay_selected",
                "overlay_equity",
            ]
        ].to_csv(detail_path, index=False)

    results_df = pd.DataFrame(results)
    results_df = results_df[
        [
            "model",
            "overlay_mode",
            "kill_multiplier",
            "kill_day_pct",
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

    print("\n=== PHASE 20D PARTIAL OVERLAY RESULTS ===")
    print(results_df.to_string(index=False))
    print(f"\nUložené results CSV: {OUT_RESULTS_CSV}")
    print(f"Uložené equity CSV:  {OUT_EQUITY_CSV}")
    print(f"Uložené best JSON:   {OUT_JSON}")


if __name__ == "__main__":
    main()
