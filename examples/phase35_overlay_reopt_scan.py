from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.scoring import compute_score_frame

ROOT = Path(__file__).resolve().parents[1]
DAILY_DIR = ROOT / "data" / "ohlcv"
MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"
OUTPUT_DIR = ROOT / "outputs"

DATE_CANDIDATES = ["timestamp", "date", "datetime", "time", "open_time"]
RENAME_MAP = {
    "Date": "date",
    "Timestamp": "timestamp",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Open time": "open_time",
}

TARGET_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
]

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

TRADING_DAYS_PER_YEAR = 365.25
TOTAL_COST_BPS = 15.0
TRADE_COST = TOTAL_COST_BPS / 10000.0

# fixed winner selector from phase34
ACCEL_WEIGHT = 0.25
MARKET_THRESHOLD = 0.0
SELECT_CONF_MIN = 35.0
YZ_CAP = 0.70
ENTER_CONF_MIN = 35.0
HOLD_CONF_MIN = 30.0
ST_BULL_THRESHOLD = 35.0
LT_BULL_THRESHOLD = 35.0

KILL_MULTIPLIERS = [0.50, 0.60, 0.75]
RESTORE_THRESHOLDS = [0.02, 0.03, 0.04]

OUT_RESULTS_CSV = OUTPUT_DIR / "phase35_overlay_reopt_scan_results.csv"
OUT_JSON = OUTPUT_DIR / "phase35_overlay_reopt_scan_best.json"


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df = df.rename(columns=RENAME_MAP)

    date_col = next((c for c in DATE_CANDIDATES if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path} nemá dátumový stĺpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()


def load_macro_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.set_index("date").sort_index()
    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
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


def rolling_comp(series: pd.Series, n: int) -> pd.Series:
    return (1.0 + series.fillna(0.0)).rolling(n).apply(np.prod, raw=True) - 1.0


def build_daily_tables(
    assets: dict[str, pd.DataFrame],
    macro_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    out = {}

    for symbol, ohlcv in assets.items():
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
                    "ts": idx,
                    "close": float(ohlcv.loc[idx, "close"]),
                    "active_long": position,
                    "confidence": confidence,
                    "yz_vol_20": yz_val,
                    "atr_pct": atr_val,
                    "general_score": general_score,
                    "base_rank": base_rank,
                    "ret_next_1d": ret_next,
                }
            )

        out[symbol] = pd.DataFrame(rows).set_index("ts").sort_index()

    close_df = pd.concat({s: t["close"] for s, t in out.items()}, axis=1).sort_index()

    ret20 = close_df.pct_change(20)
    ret90 = close_df.pct_change(90)

    btc20 = ret20["BTCUSDT"]
    btc90 = ret90["BTCUSDT"]

    rs20 = ret20.sub(btc20, axis=0).fillna(0.0)
    rs90 = ret90.sub(btc90, axis=0).fillna(0.0)

    xs20 = (rs20.rank(axis=1, pct=True) - 0.5) * 200.0
    xs90 = (rs90.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_persist = (0.6 * xs20 + 0.4 * xs90).rolling(5).mean().fillna(0.0)
    xs_accel = (xs20 - xs90).clip(lower=0.0).fillna(0.0)

    for symbol, tbl in out.items():
        tbl["xs20"] = xs20[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs90"] = xs90[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_persist"] = xs_persist[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_accel"] = xs_accel[symbol].reindex(tbl.index).fillna(0.0)

    return out


def select_daily_top1(asset_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
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

            if (
                int(row["active_long"]) == 1
                and float(row["confidence"]) >= SELECT_CONF_MIN
                and float(row["yz_vol_20"]) <= YZ_CAP
                and float(row["atr_pct"]) <= 70.0
            ):
                score = (
                    float(row["base_rank"])
                    + 0.35 * float(row["xs20"])
                    + 0.20 * float(row["xs90"])
                    + 0.15 * float(row["xs_persist"])
                    + ACCEL_WEIGHT * float(row["xs_accel"])
                )
                candidates.append((symbol, score))

        market_score = float(np.mean(market_scores)) if market_scores else 0.0
        selected = "CASH"

        if market_score >= MARKET_THRESHOLD and candidates:
            candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
            selected = candidates[0][0]

        rows.append({"ts": dt, "selected": selected})

    return pd.DataFrame(rows).set_index("ts").sort_index()


def run_daily_model(
    daily_selection: pd.DataFrame,
    daily_tables: dict[str, pd.DataFrame],
    btc_close: pd.Series,
    mode: str,
    kill_multiplier: float,
    restore_threshold: float,
) -> pd.DataFrame:
    all_dates = sorted(daily_selection.index)
    prev_selected = "CASH"
    prev_exposure = 0.0
    rows = []

    btc_ret3 = btc_close / btc_close.shift(3) - 1.0
    kill_signal = (btc_ret3 < 0).astype("boolean").fillna(False).astype(bool)

    selected_ret_hist: list[float] = []

    for dt in all_dates:
        selected = str(daily_selection.loc[dt, "selected"])
        kill_day = bool(kill_signal.get(dt, False))

        if selected == "CASH":
            target_exposure = 0.0
            selected_ret_next = 0.0
            lag2 = 0.0
        else:
            if dt not in daily_tables[selected].index:
                target_exposure = 0.0
                selected_ret_next = 0.0
                lag2 = 0.0
            else:
                row = daily_tables[selected].loc[dt]
                selected_ret_next = float(row["ret_next_1d"])

                lag2 = 0.0
                if len(selected_ret_hist) >= 2:
                    lag2 = float(np.prod([1.0 + x for x in selected_ret_hist[-2:]]) - 1.0)

                if mode == "aggressive":
                    target_exposure = 1.0
                elif mode == "balanced":
                    if kill_day:
                        target_exposure = 1.0 if lag2 > restore_threshold else kill_multiplier
                    else:
                        target_exposure = 1.0
                else:
                    raise ValueError(mode)

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
                "kill_day": int(kill_day),
                "lag2_realized": lag2,
            }
        )

        prev_selected = selected
        prev_exposure = target_exposure
        selected_ret_hist.append(selected_ret_next if selected != "CASH" else 0.0)

    out = pd.DataFrame(rows).set_index("ts").sort_index()
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    return out


def compute_summary(paper: pd.DataFrame) -> dict:
    rets = paper["strategy_ret"].fillna(0.0)
    equity = (1.0 + rets).cumprod()

    total_return = float(equity.iloc[-1] - 1.0)
    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std(ddof=0))
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(TRADING_DAYS_PER_YEAR))

    downside = rets[rets < 0].std(ddof=0)
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(TRADING_DAYS_PER_YEAR))

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((paper["turnover"] > 0).sum()),
        "avg_exposure": round(float(paper["gross_exposure"].mean()), 3),
        "cash_days_pct": round(float((paper["gross_exposure"] <= 0.0).mean() * 100.0), 2),
        "kill_days_pct": round(float((paper["kill_day"] == 1).mean() * 100.0), 2),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("načítavam daily dáta...", flush=True)
    daily_assets = {s: load_ohlcv_csv(DAILY_DIR / f"{s}_1d.csv") for s in TARGET_SYMBOLS}

    print("načítavam macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    print("počítam daily tables...", flush=True)
    daily_tables = build_daily_tables(daily_assets, macro)

    print("počítam daily selection...", flush=True)
    daily_selection = select_daily_top1(daily_tables)
    daily_selection.to_csv(OUTPUT_DIR / "phase35_daily_selection_winner.csv")

    btc_close = daily_assets["BTCUSDT"]["close"].copy()

    aggressive = run_daily_model(
        daily_selection=daily_selection,
        daily_tables=daily_tables,
        btc_close=btc_close,
        mode="aggressive",
        kill_multiplier=1.0,
        restore_threshold=999.0,
    )
    aggressive.to_csv(OUTPUT_DIR / "phase35_aggressive_reference.csv")
    aggr_summary = compute_summary(aggressive)

    rows = []
    for kill_multiplier, restore_threshold in product(KILL_MULTIPLIERS, RESTORE_THRESHOLDS):
        variant = f"k{kill_multiplier:.2f}_r{restore_threshold:.2f}".replace(".", "p")
        print(f"testujem {variant} ...", flush=True)

        balanced = run_daily_model(
            daily_selection=daily_selection,
            daily_tables=daily_tables,
            btc_close=btc_close,
            mode="balanced",
            kill_multiplier=kill_multiplier,
            restore_threshold=restore_threshold,
        )
        balanced.to_csv(OUTPUT_DIR / f"phase35_{variant}_balanced.csv")
        b = compute_summary(balanced)

        score = (
            14.0 * b["sharpe"]
            + 0.20 * b["cagr_pct"]
            - 0.60 * abs(b["max_drawdown_pct"])
            - 0.03 * b["cash_days_pct"]
        )

        rows.append(
            {
                "variant": variant,
                "kill_multiplier": kill_multiplier,
                "restore_threshold": restore_threshold,
                "score": round(score, 3),

                "aggr_total_return_pct": aggr_summary["total_return_pct"],
                "aggr_cagr_pct": aggr_summary["cagr_pct"],
                "aggr_max_drawdown_pct": aggr_summary["max_drawdown_pct"],
                "aggr_sharpe": aggr_summary["sharpe"],

                "bal_total_return_pct": b["total_return_pct"],
                "bal_cagr_pct": b["cagr_pct"],
                "bal_max_drawdown_pct": b["max_drawdown_pct"],
                "bal_sharpe": b["sharpe"],
                "bal_sortino": b["sortino"],
                "bal_trade_count": b["trade_count"],
                "bal_cash_days_pct": b["cash_days_pct"],
                "bal_kill_days_pct": b["kill_days_pct"],
            }
        )

    out = pd.DataFrame(rows).sort_values(
        ["score", "bal_sharpe", "bal_cagr_pct"],
        ascending=False,
    ).reset_index(drop=True)

    out.to_csv(OUT_RESULTS_CSV, index=False)

    best = out.iloc[0].to_dict()
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\n=== PHASE 35 OVERLAY RE-OPT SCAN ===")
    print(out.to_string(index=False))
    print("\n=== AGGRESSIVE REFERENCE ===")
    print(json.dumps(aggr_summary, indent=2))
    print("\nuložené:")
    print(OUT_RESULTS_CSV)
    print(OUT_JSON)


if __name__ == "__main__":
    main()