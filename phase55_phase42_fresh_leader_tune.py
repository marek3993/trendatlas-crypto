from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.scoring import compute_score_frame

OUTPUTS = ROOT / "outputs"
OUT_DIR = OUTPUTS / "phase55_phase42_fresh_leader_tune"
DATA_DIR = ROOT / "data" / "ohlcv"
MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ALL_SYMBOLS = [
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

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

TRADING_DAYS_PER_YEAR = 365.25
TOTAL_COST_BPS = 15.0
TRADE_COST = TOTAL_COST_BPS / 10000.0

MARKET_THRESHOLD = 0.0
SELECT_CONF_MIN = 35.0
YZ_CAP = 0.70
ENTER_CONF_MIN = 35.0
HOLD_CONF_MIN = 30.0
ST_BULL_THRESHOLD = 35.0
LT_BULL_THRESHOLD = 35.0

SINCE_2023 = pd.Timestamp("2023-01-01")
SINCE_2025 = pd.Timestamp("2025-01-01")

MODEL_LABELS = {
    "phase55_phase42_core": "Phase42 core",
    "phase55_fresh_light": "Fresh leader light",
    "phase55_fresh_medium": "Fresh leader medium",
    "phase55_fresh_heavy": "Fresh leader heavy",
}

WEIGHT_CONFIGS = {
    "phase55_phase42_core": {
        "base_rank": 1.00,
        "xs20": 0.35,
        "xs90": 0.20,
        "xs_persist": 0.10,
        "xs_accel": 0.20,
        "ret5": 0.15,
    },
    "phase55_fresh_light": {
        "base_rank": 1.00,
        "xs20": 0.38,
        "xs90": 0.18,
        "xs_persist": 0.08,
        "xs_accel": 0.26,
        "ret5": 0.18,
    },
    "phase55_fresh_medium": {
        "base_rank": 0.95,
        "xs20": 0.42,
        "xs90": 0.16,
        "xs_persist": 0.06,
        "xs_accel": 0.32,
        "ret5": 0.22,
    },
    "phase55_fresh_heavy": {
        "base_rank": 0.90,
        "xs20": 0.46,
        "xs90": 0.12,
        "xs_persist": 0.04,
        "xs_accel": 0.40,
        "ret5": 0.28,
    },
}


def normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(
        columns={
            "Date": "date",
            "Timestamp": "timestamp",
            "Datetime": "datetime",
            "Time": "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Open time": "open_time",
            "Open Time": "open_time",
        }
    )


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df = normalize_ohlcv_columns(df)

    date_col = next((c for c in ["timestamp", "date", "datetime", "time", "open_time"] if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path} nema datumovy stlpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    for c in ["open", "high", "low", "close", "volume"]:
        if c not in df.columns:
            raise ValueError(f"{path} nema stlpec {c}")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()


def load_macro_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalize_ohlcv_columns(df)

    if "date" not in df.columns:
        raise ValueError(f"{path} nema date stlpec")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.set_index("date").sort_index()

    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{path} nema makro stlpce: {missing}")

    return df[cols].apply(pd.to_numeric, errors="coerce").dropna()


def row_conf(row: pd.Series, cols: list[str]) -> float:
    vals = row[cols].astype(float)
    row_mean = float(vals.mean())
    mad = float((vals - row_mean).abs().mean())
    conf = 100.0 * (1.0 - (mad / 80.0))
    return max(0.0, min(100.0, conf))


def bull(score: float, threshold: float) -> bool:
    return score >= threshold


def bear(score: float, threshold: float) -> bool:
    return score <= -threshold


def build_daily_tables(
    assets: dict[str, pd.DataFrame],
    macro_df: pd.DataFrame,
    symbols: list[str],
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        print(f"build_daily_tables: {symbol}", flush=True)
        ohlcv = assets[symbol]
        features = compute_feature_frame(ohlcv, macro_df=macro_df)
        scores = compute_score_frame(features)

        rows = []
        position = 0

        for i in range(260, len(features) - 1):
            idx = features.index[i]
            next_idx = features.index[i + 1]
            srow = scores.loc[idx]

            st_score = float(srow[ST_COLS].mean())
            lt_score = float(srow[LT_COLS].mean())
            mr_score = float(srow[MR_COLS].mean())
            confidence = min(row_conf(srow, ST_COLS), row_conf(srow, LT_COLS))

            yz_val = float(features.loc[idx, "yz_vol_20"]) if "yz_vol_20" in features.columns else 0.0
            atr_val = float(features.loc[idx, "atr_pct"]) if "atr_pct" in features.columns else 0.0

            regime = "transition"
            if yz_val > 0.9:
                regime = "chaos"
            elif atr_val > 80:
                regime = "transition"
            elif abs(st_score) < 20 and abs(lt_score) < 20:
                regime = "range"

            directional_bias = 0.45 * lt_score + 0.35 * st_score + 0.20 * mr_score
            general_score = 0.6 * lt_score + 0.4 * st_score

            enter_long = (
                bull(st_score, ST_BULL_THRESHOLD)
                and bull(lt_score, LT_BULL_THRESHOLD)
                and confidence >= ENTER_CONF_MIN
                and regime != "chaos"
                and mr_score >= -90.0
            )

            hold_long = (
                not bear(lt_score, LT_BULL_THRESHOLD)
                and confidence >= HOLD_CONF_MIN
                and directional_bias > 0.0
                and regime != "chaos"
            )

            if position == 0:
                if enter_long:
                    position = 1
            elif position == 1:
                if not hold_long:
                    position = 0

            base_rank = 0.55 * lt_score + 0.30 * st_score + 0.15 * confidence
            ret_next = float(ohlcv.loc[next_idx, "close"] / ohlcv.loc[idx, "close"] - 1.0)

            rows.append(
                {
                    "ts": pd.Timestamp(idx).normalize(),
                    "close": float(ohlcv.loc[idx, "close"]),
                    "active_long": position,
                    "confidence": confidence,
                    "yz_vol_20": yz_val,
                    "atr_pct": atr_val,
                    "general_score": general_score,
                    "base_rank": base_rank,
                    "ret_next_1d": ret_next,
                    "st_score": st_score,
                    "lt_score": lt_score,
                }
            )

        out[symbol] = pd.DataFrame(rows).drop_duplicates(subset=["ts"]).set_index("ts").sort_index()

    close_df = pd.concat({s: t["close"] for s, t in out.items()}, axis=1).sort_index()
    btc_proxy = close_df["BTCUSDT"] if "BTCUSDT" in close_df.columns else close_df.mean(axis=1)

    ret20 = close_df.pct_change(20)
    ret90 = close_df.pct_change(90)
    ret5 = close_df.pct_change(5)

    if "BTCUSDT" in ret20.columns:
        btc20 = ret20["BTCUSDT"]
        btc90 = ret90["BTCUSDT"]
    else:
        btc20 = btc_proxy.pct_change(20)
        btc90 = btc_proxy.pct_change(90)

    rs20 = ret20.sub(btc20, axis=0).fillna(0.0)
    rs90 = ret90.sub(btc90, axis=0).fillna(0.0)

    xs20 = (rs20.rank(axis=1, pct=True) - 0.5) * 200.0
    xs90 = (rs90.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_persist = (0.6 * xs20 + 0.4 * xs90).rolling(5).mean().fillna(0.0)
    xs_accel = (xs20 - xs90).fillna(0.0)
    thrust_ret5 = (ret5.rank(axis=1, pct=True) - 0.5) * 200.0
    best_next = close_df.pct_change().shift(-1).max(axis=1)

    for symbol, tbl in out.items():
        tbl["xs20"] = xs20[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs90"] = xs90[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_persist"] = xs_persist[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_accel"] = xs_accel[symbol].reindex(tbl.index).fillna(0.0)
        tbl["thrust_ret5"] = thrust_ret5[symbol].reindex(tbl.index).fillna(0.0)
        tbl["best_available_next"] = best_next.reindex(tbl.index).fillna(0.0)

    return out


def candidate_score(row: pd.Series, weights: dict) -> float:
    return (
        weights["base_rank"] * float(row["base_rank"])
        + weights["xs20"] * float(row["xs20"])
        + weights["xs90"] * float(row["xs90"])
        + weights["xs_persist"] * float(row["xs_persist"])
        + weights["xs_accel"] * max(float(row["xs_accel"]), 0.0)
        + weights["ret5"] * max(float(row["thrust_ret5"]), 0.0)
    )


def candidate_ok(row: pd.Series) -> bool:
    return (
        int(row["active_long"]) == 1
        and float(row["confidence"]) >= SELECT_CONF_MIN
        and float(row["yz_vol_20"]) <= YZ_CAP
        and float(row["atr_pct"]) <= 70.0
    )


def select_daily_top1_variant(asset_tables: dict[str, pd.DataFrame], model_key: str) -> pd.DataFrame:
    weights = WEIGHT_CONFIGS[model_key]
    all_dates = sorted(set().union(*[set(t.index) for t in asset_tables.values()]))
    rows = []

    for dt in all_dates:
        candidates = []
        market_scores = []

        for symbol, tbl in asset_tables.items():
            if dt not in tbl.index:
                continue

            row = tbl.loc[dt]
            market_scores.append(float(row["general_score"]))

            if candidate_ok(row):
                candidates.append((symbol, candidate_score(row, weights)))

        market_score = float(np.mean(market_scores)) if market_scores else 0.0
        selected = "CASH"

        if market_score >= MARKET_THRESHOLD and candidates:
            candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
            selected = candidates[0][0]

        rows.append({"ts": dt, "selected": selected})

    return pd.DataFrame(rows).set_index("ts").sort_index()


def run_daily_model(selection: pd.DataFrame, daily_tables: dict[str, pd.DataFrame], model_key: str) -> pd.DataFrame:
    all_dates = sorted(selection.index)
    prev_selected = "CASH"
    prev_exposure = 0.0
    rows = []

    for dt in all_dates:
        selected = str(selection.loc[dt, "selected"])

        if selected == "CASH":
            target_exposure = 0.0
            selected_ret_next = 0.0
            best_available_next = 0.0
        else:
            row = daily_tables[selected].loc[dt]
            target_exposure = 1.0
            selected_ret_next = float(row["ret_next_1d"])
            best_available_next = float(row["best_available_next"])

        turnover = abs(target_exposure - prev_exposure)
        if selected != prev_selected and (selected != "CASH" or prev_selected != "CASH"):
            turnover = max(turnover, prev_exposure + target_exposure)

        raw_ret = target_exposure * selected_ret_next
        cost = turnover * TRADE_COST
        strategy_ret = raw_ret - cost

        rows.append(
            {
                "ts": dt,
                "selected": selected,
                "gross_exposure": target_exposure,
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
                "selected_ret_next": selected_ret_next,
                "best_available_next": best_available_next,
            }
        )

        prev_selected = selected
        prev_exposure = target_exposure

    out = pd.DataFrame(rows).set_index("ts").sort_index()
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    out["in_market"] = (out["gross_exposure"] > 0.0).astype(int)
    out["leader_gap_ret"] = np.where(out["in_market"] == 1, out["best_available_next"] - out["selected_ret_next"], 0.0)
    out["missed_leader_bar"] = (out["in_market"] == 1) & (out["leader_gap_ret"] > 0.0)
    out["pain_bar"] = (out["in_market"] == 1) & (out["leader_gap_ret"] > 0.02)
    out["model_key"] = model_key
    return out


def compute_summary(model_df: pd.DataFrame) -> dict:
    rets = pd.to_numeric(model_df["strategy_ret"], errors="coerce").fillna(0.0)
    equity = (1.0 + rets).cumprod()

    total_return = float(equity.iloc[-1] - 1.0)
    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std(ddof=0))
    sharpe = float((rets.mean() / (vol + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR))
    downside = rets[rets < 0].std(ddof=0)
    downside = 0.0 if pd.isna(downside) else float(downside)
    sortino = float((rets.mean() / (downside + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR))

    in_market = int((model_df["gross_exposure"] > 0.0).sum())
    missed = int(model_df.get("missed_leader_bar", pd.Series(index=model_df.index, data=False)).sum())
    pain = int(model_df.get("pain_bar", pd.Series(index=model_df.index, data=False)).sum())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((pd.to_numeric(model_df["turnover"], errors="coerce").fillna(0.0) > 0).sum()),
        "cash_days_pct": round(float((pd.to_numeric(model_df["gross_exposure"], errors="coerce").fillna(0.0) <= 0.0).mean() * 100.0), 2),
        "missed_leader_pct_of_in_market": round(100.0 * missed / max(in_market, 1), 2),
        "pain_bar_pct_of_in_market": round(100.0 * pain / max(in_market, 1), 2),
        "sum_leader_gap_ret": round(float(pd.to_numeric(model_df.get("leader_gap_ret", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0).sum()), 4),
    }


def compute_window_summary(model_df: pd.DataFrame, start_dt: pd.Timestamp, prefix: str) -> dict:
    sub = model_df.loc[model_df.index >= start_dt].copy()
    if sub.empty:
        return {
            f"{prefix}_total_return_pct": np.nan,
            f"{prefix}_cagr_pct": np.nan,
            f"{prefix}_max_drawdown_pct": np.nan,
            f"{prefix}_trade_count": np.nan,
            f"{prefix}_cash_days_pct": np.nan,
        }

    s = compute_summary(sub)
    return {
        f"{prefix}_total_return_pct": s["total_return_pct"],
        f"{prefix}_cagr_pct": s["cagr_pct"],
        f"{prefix}_max_drawdown_pct": s["max_drawdown_pct"],
        f"{prefix}_trade_count": s["trade_count"],
        f"{prefix}_cash_days_pct": s["cash_days_pct"],
    }


def main() -> None:
    print("Loading OHLCV...", flush=True)
    all_assets = {s: load_ohlcv_csv(DATA_DIR / f"{s}_1d.csv") for s in ALL_SYMBOLS}

    print("Loading macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    print("Building daily tables full universe...", flush=True)
    daily_full = build_daily_tables(all_assets, macro, ALL_SYMBOLS)

    model_runs: Dict[str, pd.DataFrame] = {}

    variants = [
        "phase55_phase42_core",
        "phase55_fresh_light",
        "phase55_fresh_medium",
        "phase55_fresh_heavy",
    ]

    for model_key in variants:
        print(f"Running {model_key}...", flush=True)
        selection = select_daily_top1_variant(daily_full, model_key)
        paper = run_daily_model(selection, daily_full, model_key=model_key)
        model_runs[model_key] = paper
        paper.to_csv(OUT_DIR / f"{model_key}_paper.csv")

    summary_rows = []
    for model_key, df in model_runs.items():
        row = {
            "model": model_key,
            "label": MODEL_LABELS[model_key],
            **compute_summary(df),
            **compute_window_summary(df, SINCE_2023, "since2023"),
            **compute_window_summary(df, SINCE_2025, "since2025"),
        }
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["since2025_cagr_pct", "since2023_cagr_pct", "cagr_pct"],
        ascending=[False, False, False],
    )
    summary_df.to_csv(OUT_DIR / "phase55_phase42_fresh_leader_tune_summary.csv", index=False)

    eq = pd.DataFrame(index=sorted(set().union(*[set(df.index) for df in model_runs.values()])))
    eq.index.name = "ts"
    for model_key, df in model_runs.items():
        eq[model_key] = df["equity"].reindex(eq.index).ffill()
    eq = eq.reset_index()
    eq.to_csv(OUT_DIR / "phase55_phase42_fresh_leader_tune_equity_curves.csv", index=False)

    print("\n=== PHASE55 PHASE42 FRESH LEADER TUNE ===\n")
    print(summary_df.to_string(index=False))
    print(f"\nSaved summary: {OUT_DIR / 'phase55_phase42_fresh_leader_tune_summary.csv'}")
    print(f"Saved equity curves: {OUT_DIR / 'phase55_phase42_fresh_leader_tune_equity_curves.csv'}")
    print(f"Saved daily papers to: {OUT_DIR}")


if __name__ == "__main__":
    main()