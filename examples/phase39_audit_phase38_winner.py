from __future__ import annotations

import json
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

# phase36 baseline
BASE_ACCEL_WEIGHT = 0.00
BASE_THRUST_WEIGHT = 0.00
BASE_MARKET_THRESHOLD = 10.0
BASE_SELECT_CONF_MIN = 35.0
BASE_YZ_CAP = 0.70
BASE_ENTER_CONF_MIN = 40.0
BASE_HOLD_CONF_MIN = 30.0
BASE_ST_BULL_THRESHOLD = 35.0
BASE_LT_BULL_THRESHOLD = 35.0

# phase38 winner
WIN_ACCEL_WEIGHT = 0.25
WIN_THRUST_MODE = "ret5"
WIN_THRUST_WEIGHT = 0.10
WIN_MARKET_THRESHOLD = 0.0
WIN_SELECT_CONF_MIN = 35.0
WIN_YZ_CAP = 0.70
WIN_ENTER_CONF_MIN = 35.0
WIN_HOLD_CONF_MIN = 30.0
WIN_ST_BULL_THRESHOLD = 35.0
WIN_LT_BULL_THRESHOLD = 35.0

OUT_BASE_CSV = OUTPUT_DIR / "phase39_old_baseline_daily.csv"
OUT_WINNER_CSV = OUTPUT_DIR / "phase39_phase38_winner_daily.csv"
OUT_COMPARE_WINDOWS_CSV = OUTPUT_DIR / "phase39_compare_focus_windows.csv"
OUT_MISSED_DETAIL_CSV = OUTPUT_DIR / "phase39_winner_missed_run_detail.csv"
OUT_MISSED_WINDOWS_CSV = OUTPUT_DIR / "phase39_winner_missed_run_windows.csv"
OUT_SUMMARY_JSON = OUTPUT_DIR / "phase39_phase38_winner_summary.json"

FOCUS_WINDOWS = [
    ("2021-01-01", "2021-04-30", "2021_Q1_to_Apr"),
    ("2021-07-01", "2021-12-31", "2021_H2"),
    ("2024-02-01", "2024-03-31", "2024_Feb_Mar"),
    ("2025-04-01", "2025-07-31", "2025_Apr_Jul"),
]


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


def build_daily_tables(
    assets: dict[str, pd.DataFrame],
    macro_df: pd.DataFrame,
    enter_conf_min: float,
    hold_conf_min: float,
    st_bull_threshold: float,
    lt_bull_threshold: float,
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
                bull(st_score, st_bull_threshold)
                and bull(lt_score, lt_bull_threshold)
                and confidence >= enter_conf_min
                and regime != "chaos"
                and mr_score >= -90.0
            )

            hold_long = (
                not bear(lt_score, lt_bull_threshold)
                and confidence >= hold_conf_min
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
    ret5 = close_df.pct_change(5)

    btc20 = ret20["BTCUSDT"]
    btc90 = ret90["BTCUSDT"]

    rs20 = ret20.sub(btc20, axis=0).fillna(0.0)
    rs90 = ret90.sub(btc90, axis=0).fillna(0.0)

    xs20 = (rs20.rank(axis=1, pct=True) - 0.5) * 200.0
    xs90 = (rs90.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_persist = (0.6 * xs20 + 0.4 * xs90).rolling(5).mean().fillna(0.0)
    xs_accel = (xs20 - xs90).fillna(0.0)

    thrust_ret5 = (ret5.rank(axis=1, pct=True) - 0.5) * 200.0
    thrust_xs_accel = (xs_accel.rank(axis=1, pct=True) - 0.5) * 200.0
    thrust_combo = (0.5 * thrust_ret5 + 0.5 * thrust_xs_accel).fillna(0.0)

    best_next = close_df.pct_change().shift(-1).max(axis=1)

    for symbol, tbl in out.items():
        tbl["xs20"] = xs20[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs90"] = xs90[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_persist"] = xs_persist[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_accel"] = xs_accel[symbol].reindex(tbl.index).fillna(0.0)
        tbl["thrust_ret5"] = thrust_ret5[symbol].reindex(tbl.index).fillna(0.0)
        tbl["thrust_xs_accel"] = thrust_xs_accel[symbol].reindex(tbl.index).fillna(0.0)
        tbl["thrust_combo"] = thrust_combo[symbol].reindex(tbl.index).fillna(0.0)
        tbl["best_available_next"] = best_next.reindex(tbl.index).fillna(0.0)

    return out


def thrust_value(row: pd.Series, thrust_mode: str) -> float:
    if thrust_mode == "ret5":
        return float(row["thrust_ret5"])
    if thrust_mode == "xs_accel":
        return float(row["thrust_xs_accel"])
    if thrust_mode == "combo":
        return float(row["thrust_combo"])
    raise ValueError(thrust_mode)


def select_daily_top1(
    asset_tables: dict[str, pd.DataFrame],
    accel_weight: float,
    thrust_weight: float,
    thrust_mode: str,
    market_threshold: float,
    select_conf_min: float,
    yz_cap: float,
) -> pd.DataFrame:
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
                and float(row["confidence"]) >= select_conf_min
                and float(row["yz_vol_20"]) <= yz_cap
                and float(row["atr_pct"]) <= 70.0
            ):
                score = (
                    float(row["base_rank"])
                    + 0.35 * float(row["xs20"])
                    + 0.20 * float(row["xs90"])
                    + 0.15 * float(row["xs_persist"])
                    + accel_weight * max(float(row["xs_accel"]), 0.0)
                    + thrust_weight * max(thrust_value(row, thrust_mode), 0.0)
                )
                candidates.append((symbol, score))

        market_score = float(np.mean(market_scores)) if market_scores else 0.0
        selected = "CASH"

        if market_score >= market_threshold and candidates:
            candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
            selected = candidates[0][0]

        rows.append({"ts": dt, "selected": selected})

    return pd.DataFrame(rows).set_index("ts").sort_index()


def run_daily_model(
    daily_selection: pd.DataFrame,
    daily_tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    all_dates = sorted(daily_selection.index)
    prev_selected = "CASH"
    prev_exposure = 0.0
    rows = []

    for dt in all_dates:
        selected = str(daily_selection.loc[dt, "selected"])

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
                "in_market": int(target_exposure > 0.0),
                "cash_day": int(target_exposure <= 0.0),
            }
        )

        prev_selected = selected
        prev_exposure = target_exposure

    out = pd.DataFrame(rows).set_index("ts").sort_index()
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    out["leader_gap_ret"] = np.where(out["in_market"] == 1, out["best_available_next"] - out["selected_ret_next"], 0.0)
    out["missed_leader_bar"] = (out["in_market"] == 1) & (out["leader_gap_ret"] > 0.0)
    out["pain_bar"] = (out["in_market"] == 1) & (out["leader_gap_ret"] > 0.02)
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

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "trade_count": int((paper["turnover"] > 0).sum()),
        "cash_days_pct": round(float((paper["gross_exposure"] <= 0.0).mean() * 100.0), 2),
    }


def summarize_focus_window(df: pd.DataFrame, label: str, start_date: str, end_date: str) -> dict:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    w = df[(df.index >= start) & (df.index <= end)].copy()

    if w.empty:
        return {
            "window": label,
            "bars": 0,
            "total_return_pct": np.nan,
            "cagr_pct": np.nan,
            "cash_days_pct": np.nan,
            "missed_leader_bar_pct_of_in_market": np.nan,
            "pain_bar_pct_of_in_market": np.nan,
            "sum_leader_gap_ret": np.nan,
        }

    s = compute_summary(w)
    in_market = int(w["in_market"].sum())
    missed = int(w["missed_leader_bar"].sum())
    pain = int(w["pain_bar"].sum())

    return {
        "window": label,
        "bars": int(len(w)),
        "total_return_pct": s["total_return_pct"],
        "cagr_pct": s["cagr_pct"],
        "cash_days_pct": s["cash_days_pct"],
        "missed_leader_bar_pct_of_in_market": round(100.0 * missed / max(in_market, 1), 2),
        "pain_bar_pct_of_in_market": round(100.0 * pain / max(in_market, 1), 2),
        "sum_leader_gap_ret": round(float(w["leader_gap_ret"].clip(lower=0.0).sum()), 4),
    }


def build_missed_windows(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["grp"] = (work["missed_leader_bar"] != work["missed_leader_bar"].shift(1)).cumsum()

    rows = []
    for _, g in work.groupby("grp"):
        if not bool(g["missed_leader_bar"].iloc[0]):
            continue

        rows.append(
            {
                "start_ts": g.index[0],
                "end_ts": g.index[-1],
                "selected_mode": g["selected"].mode().iloc[0] if len(g["selected"].mode()) else g["selected"].iloc[0],
                "bars": int(len(g)),
                "days": int((g.index[-1] - g.index[0]).days) + 1,
                "sum_selected_ret_next": float(g["selected_ret_next"].sum()),
                "sum_best_available_next": float(g["best_available_next"].sum()),
                "sum_leader_gap_ret": float(g["leader_gap_ret"].sum()),
                "compound_selected_ret_next": float((1.0 + g["selected_ret_next"]).prod() - 1.0),
                "compound_best_available_next": float((1.0 + g["best_available_next"]).prod() - 1.0),
                "compound_gap_approx": float(((1.0 + g["best_available_next"]).prod() - 1.0) - ((1.0 + g["selected_ret_next"]).prod() - 1.0)),
                "pain_bars_gt_2pct_gap": int((g["leader_gap_ret"] > 0.02).sum()),
                "turnover_sum": float(g["turnover"].sum()),
                "cost_sum": float(g["cost"].sum()),
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["compound_gap_approx", "sum_leader_gap_ret"], ascending=[False, False]).reset_index(drop=True)
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("načítavam daily dáta...", flush=True)
    daily_assets = {s: load_ohlcv_csv(DAILY_DIR / f"{s}_1d.csv") for s in TARGET_SYMBOLS}

    print("načítavam macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    print("počítam baseline tables...", flush=True)
    base_tables = build_daily_tables(
        assets=daily_assets,
        macro_df=macro,
        enter_conf_min=BASE_ENTER_CONF_MIN,
        hold_conf_min=BASE_HOLD_CONF_MIN,
        st_bull_threshold=BASE_ST_BULL_THRESHOLD,
        lt_bull_threshold=BASE_LT_BULL_THRESHOLD,
    )
    base_sel = select_daily_top1(
        asset_tables=base_tables,
        accel_weight=BASE_ACCEL_WEIGHT,
        thrust_weight=BASE_THRUST_WEIGHT,
        thrust_mode="ret5",
        market_threshold=BASE_MARKET_THRESHOLD,
        select_conf_min=BASE_SELECT_CONF_MIN,
        yz_cap=BASE_YZ_CAP,
    )
    base_paper = run_daily_model(base_sel, base_tables)
    base_paper.to_csv(OUT_BASE_CSV)

    print("počítam phase38 winner tables...", flush=True)
    win_tables = build_daily_tables(
        assets=daily_assets,
        macro_df=macro,
        enter_conf_min=WIN_ENTER_CONF_MIN,
        hold_conf_min=WIN_HOLD_CONF_MIN,
        st_bull_threshold=WIN_ST_BULL_THRESHOLD,
        lt_bull_threshold=WIN_LT_BULL_THRESHOLD,
    )
    win_sel = select_daily_top1(
        asset_tables=win_tables,
        accel_weight=WIN_ACCEL_WEIGHT,
        thrust_weight=WIN_THRUST_WEIGHT,
        thrust_mode=WIN_THRUST_MODE,
        market_threshold=WIN_MARKET_THRESHOLD,
        select_conf_min=WIN_SELECT_CONF_MIN,
        yz_cap=WIN_YZ_CAP,
    )
    win_paper = run_daily_model(win_sel, win_tables)
    win_paper.to_csv(OUT_WINNER_CSV)

    compare_rows = []
    for start_date, end_date, label in FOCUS_WINDOWS:
        b = summarize_focus_window(base_paper, label, start_date, end_date)
        w = summarize_focus_window(win_paper, label, start_date, end_date)

        compare_rows.append(
            {
                "window": label,
                "base_total_return_pct": b["total_return_pct"],
                "winner_total_return_pct": w["total_return_pct"],
                "delta_total_return_pct": round(float(w["total_return_pct"] - b["total_return_pct"]), 2),
                "base_cash_days_pct": b["cash_days_pct"],
                "winner_cash_days_pct": w["cash_days_pct"],
                "delta_cash_days_pct": round(float(w["cash_days_pct"] - b["cash_days_pct"]), 2),
                "base_missed_leader_pct_of_in_market": b["missed_leader_bar_pct_of_in_market"],
                "winner_missed_leader_pct_of_in_market": w["missed_leader_bar_pct_of_in_market"],
                "delta_missed_leader_pct": round(float(w["missed_leader_bar_pct_of_in_market"] - b["missed_leader_bar_pct_of_in_market"]), 2),
                "base_pain_bar_pct_of_in_market": b["pain_bar_pct_of_in_market"],
                "winner_pain_bar_pct_of_in_market": w["pain_bar_pct_of_in_market"],
                "delta_pain_bar_pct": round(float(w["pain_bar_pct_of_in_market"] - b["pain_bar_pct_of_in_market"]), 2),
                "base_sum_leader_gap_ret": b["sum_leader_gap_ret"],
                "winner_sum_leader_gap_ret": w["sum_leader_gap_ret"],
                "delta_sum_leader_gap_ret": round(float(w["sum_leader_gap_ret"] - b["sum_leader_gap_ret"]), 4),
            }
        )

    compare_df = pd.DataFrame(compare_rows)
    compare_df.to_csv(OUT_COMPARE_WINDOWS_CSV, index=False)

    missed_detail = win_paper[
        [
            "selected",
            "gross_exposure",
            "strategy_ret",
            "selected_ret_next",
            "best_available_next",
            "leader_gap_ret",
            "in_market",
            "missed_leader_bar",
            "pain_bar",
            "turnover",
            "cost",
        ]
    ].copy()
    missed_detail.to_csv(OUT_MISSED_DETAIL_CSV)

    missed_windows = build_missed_windows(win_paper)
    missed_windows.to_csv(OUT_MISSED_WINDOWS_CSV, index=False)

    base_summary = compute_summary(base_paper)
    winner_summary = compute_summary(win_paper)

    overall = {
        "base_summary": base_summary,
        "winner_summary": winner_summary,
        "focus_windows": compare_rows,
        "winner_missed_leader_bars": int(win_paper["missed_leader_bar"].sum()),
        "winner_missed_leader_bar_pct_of_in_market": round(
            float(100.0 * win_paper["missed_leader_bar"].sum() / max(int(win_paper["in_market"].sum()), 1)), 2
        ),
        "winner_pain_bar_pct_of_in_market": round(
            float(100.0 * win_paper["pain_bar"].sum() / max(int(win_paper["in_market"].sum()), 1)), 2
        ),
        "winner_sum_leader_gap_ret": round(float(win_paper["leader_gap_ret"].clip(lower=0.0).sum()), 4),
    }

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(overall, f, indent=2)

    print("\n=== PHASE 39 PHASE38 WINNER AUDIT ===")
    print("\nBASE SUMMARY")
    print(json.dumps(base_summary, indent=2))
    print("\nWINNER SUMMARY")
    print(json.dumps(winner_summary, indent=2))
    print("\n=== FOCUS WINDOWS COMPARE ===")
    print(compare_df.to_string(index=False))

    print("\n=== TOP 20 WINNER MISSED-RUN WINDOWS ===")
    if missed_windows.empty:
        print("No missed-run windows found.")
    else:
        print(missed_windows.head(20).to_string(index=False))

    print("\nuložené:")
    print(OUT_BASE_CSV)
    print(OUT_WINNER_CSV)
    print(OUT_COMPARE_WINDOWS_CSV)
    print(OUT_MISSED_DETAIL_CSV)
    print(OUT_MISSED_WINDOWS_CSV)
    print(OUT_SUMMARY_JSON)


if __name__ == "__main__":
    main()