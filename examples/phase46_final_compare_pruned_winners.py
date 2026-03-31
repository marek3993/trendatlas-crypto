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

ALL_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
]

UNIVERSE_VARIANTS = {
    "phase42_full12": ALL_SYMBOLS,
    "phase45_without_BNBUSDT": [s for s in ALL_SYMBOLS if s != "BNBUSDT"],
    "phase45_without_BNBUSDT_and_DOGEUSDT": [s for s in ALL_SYMBOLS if s not in {"BNBUSDT", "DOGEUSDT"}],
}

LABELS = {
    "old_baseline": "Old Baseline",
    "phase42_full12": "Full12 Winner",
    "phase45_without_BNBUSDT": "No BNB",
    "phase45_without_BNBUSDT_and_DOGEUSDT": "No BNB + No DOGE",
}

BASELINE_PATH_CANDIDATES = [
    OUTPUT_DIR / "phase39_old_baseline_daily.csv",
    OUTPUT_DIR / "phase36_old_baseline_daily.csv",
]

FOCUS_WINDOWS = [
    ("2021-01-01", "2021-04-30", "2021_Q1_to_Apr"),
    ("2021-07-01", "2021-12-31", "2021_H2"),
    ("2024-02-01", "2024-03-31", "2024_Feb_Mar"),
    ("2025-04-01", "2025-07-31", "2025_Apr_Jul"),
]

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

TRADING_DAYS_PER_YEAR = 365.25
TOTAL_COST_BPS = 15.0
TRADE_COST = TOTAL_COST_BPS / 10000.0

# phase42 winner
BASE_RANK_WEIGHT = 1.00
XS20_WEIGHT = 0.35
XS90_WEIGHT = 0.20
XS_PERSIST_WEIGHT = 0.10
ACCEL_WEIGHT = 0.20
RET5_WEIGHT = 0.15

MARKET_THRESHOLD = 0.0
SELECT_CONF_MIN = 35.0
YZ_CAP = 0.70
ENTER_CONF_MIN = 35.0
HOLD_CONF_MIN = 30.0
ST_BULL_THRESHOLD = 35.0
LT_BULL_THRESHOLD = 35.0

OUT_SUMMARY_CSV = OUTPUT_DIR / "phase46_final_compare_pruned_summary.csv"
OUT_EQUITY_CSV = OUTPUT_DIR / "phase46_final_compare_pruned_equity_curves.csv"
OUT_YEARLY_CSV = OUTPUT_DIR / "phase46_final_compare_pruned_yearly_returns.csv"
OUT_FOCUS_CSV = OUTPUT_DIR / "phase46_final_compare_pruned_focus_windows.csv"
OUT_JSON = OUTPUT_DIR / "phase46_final_compare_pruned_best.json"


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


def load_existing_baseline() -> pd.DataFrame:
    chosen = None
    for path in BASELINE_PATH_CANDIDATES:
        if path.exists():
            chosen = path
            break
    if chosen is None:
        raise FileNotFoundError("Chýba old baseline CSV.")

    df = pd.read_csv(chosen)

    ts_col = None
    for c in ["ts", "timestamp", "date", "datetime"]:
        if c in df.columns:
            ts_col = c
            break
    if ts_col is None:
        unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
        if unnamed:
            ts_col = unnamed[0]
    if ts_col is None:
        raise ValueError(f"{chosen} nemá časový stĺpec")

    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).copy().sort_values(ts_col)
    df = df.rename(columns={ts_col: "ts"})
    df = df.set_index("ts")

    if "strategy_ret" not in df.columns:
        raise ValueError(f"{chosen} nemá strategy_ret")

    for col in ["strategy_ret", "turnover", "cost", "selected_ret_next", "best_available_next", "gross_exposure"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["strategy_ret"] = df["strategy_ret"].fillna(0.0)
    if "turnover" not in df.columns:
        df["turnover"] = 0.0
    if "cost" not in df.columns:
        df["cost"] = 0.0
    if "gross_exposure" not in df.columns:
        df["gross_exposure"] = np.where(df.get("selected", "CASH") != "CASH", 1.0, 0.0)
    if "selected" not in df.columns:
        df["selected"] = "CASH"
    if "selected_ret_next" not in df.columns:
        df["selected_ret_next"] = 0.0
    if "best_available_next" not in df.columns:
        df["best_available_next"] = 0.0

    df["equity"] = (1.0 + df["strategy_ret"]).cumprod()
    df["in_market"] = (df["gross_exposure"] > 0.0).astype(int)
    df["leader_gap_ret"] = np.where(df["in_market"] == 1, df["best_available_next"] - df["selected_ret_next"], 0.0)
    df["missed_leader_bar"] = (df["in_market"] == 1) & (df["leader_gap_ret"] > 0.0)
    df["pain_bar"] = (df["in_market"] == 1) & (df["leader_gap_ret"] > 0.02)
    return df


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
    out = {}

    for symbol in symbols:
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


def candidate_score(row: pd.Series) -> float:
    return (
        BASE_RANK_WEIGHT * float(row["base_rank"])
        + XS20_WEIGHT * float(row["xs20"])
        + XS90_WEIGHT * float(row["xs90"])
        + XS_PERSIST_WEIGHT * float(row["xs_persist"])
        + ACCEL_WEIGHT * max(float(row["xs_accel"]), 0.0)
        + RET5_WEIGHT * max(float(row["thrust_ret5"]), 0.0)
    )


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
                candidates.append((symbol, candidate_score(row)))

        market_score = float(np.mean(market_scores)) if market_scores else 0.0
        selected = "CASH"

        if market_score >= MARKET_THRESHOLD and candidates:
            candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
            selected = candidates[0][0]

        rows.append({"ts": dt, "selected": selected})

    return pd.DataFrame(rows).set_index("ts").sort_index()


def run_daily_model(selection: pd.DataFrame, daily_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
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
    downside = 0.0 if pd.isna(downside) else float(downside)
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(TRADING_DAYS_PER_YEAR))

    in_market = int(paper["in_market"].sum())
    missed = int(paper["missed_leader_bar"].sum())
    pain = int(paper["pain_bar"].sum())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((paper["turnover"] > 0).sum()),
        "cash_days_pct": round(float((paper["gross_exposure"] <= 0.0).mean() * 100.0), 2),
        "missed_leader_pct_of_in_market": round(100.0 * missed / max(in_market, 1), 2),
        "pain_bar_pct_of_in_market": round(100.0 * pain / max(in_market, 1), 2),
        "sum_leader_gap_ret": round(float(paper["leader_gap_ret"].clip(lower=0.0).sum()), 4),
    }


def compute_yearly_returns(paper: pd.DataFrame) -> pd.DataFrame:
    daily_ret = paper["strategy_ret"].copy()
    yearly = ((1.0 + daily_ret).resample("YE").prod() - 1.0) * 100.0
    out = yearly.to_frame("ret_pct").reset_index()
    out["year"] = out["ts"].dt.year.astype(str)
    return out[["year", "ret_pct"]]


def summarize_focus_window(paper: pd.DataFrame, start_date: str, end_date: str, label: str) -> dict:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    w = paper[(paper.index >= start) & (paper.index <= end)].copy()

    if w.empty:
        return {
            "window": label,
            "total_return_pct": np.nan,
            "cagr_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "cash_days_pct": np.nan,
            "missed_leader_pct_of_in_market": np.nan,
            "pain_bar_pct_of_in_market": np.nan,
            "sum_leader_gap_ret": np.nan,
        }

    s = compute_summary(w)
    return {
        "window": label,
        "total_return_pct": s["total_return_pct"],
        "cagr_pct": s["cagr_pct"],
        "max_drawdown_pct": s["max_drawdown_pct"],
        "cash_days_pct": s["cash_days_pct"],
        "missed_leader_pct_of_in_market": s["missed_leader_pct_of_in_market"],
        "pain_bar_pct_of_in_market": s["pain_bar_pct_of_in_market"],
        "sum_leader_gap_ret": s["sum_leader_gap_ret"],
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("načítavam old baseline...", flush=True)
    baseline_paper = load_existing_baseline()

    print("načítavam daily dáta...", flush=True)
    all_assets = {s: load_ohlcv_csv(DAILY_DIR / f"{s}_1d.csv") for s in ALL_SYMBOLS}

    print("načítavam macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    papers: dict[str, pd.DataFrame] = {
        "old_baseline": baseline_paper,
    }

    for label, symbols in UNIVERSE_VARIANTS.items():
        print(f"počítam {label} ...", flush=True)
        daily_tables = build_daily_tables(all_assets, macro, symbols)
        selection = select_daily_top1(daily_tables)
        paper = run_daily_model(selection, daily_tables)
        papers[label] = paper

    summary_rows = []
    for key, paper in papers.items():
        s = compute_summary(paper)
        summary_rows.append({"model": key, "label": LABELS[key], **s})

    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["sharpe", "cagr_pct"],
        ascending=[False, False],
    ).reset_index(drop=True)
    summary_df.to_csv(OUT_SUMMARY_CSV, index=False)

    equity_df = pd.DataFrame(index=sorted(set().union(*[set(p.index) for p in papers.values()])))
    for key, paper in papers.items():
        equity_df[key] = paper["equity"].reindex(equity_df.index)
    equity_df.index.name = "ts"
    equity_df.to_csv(OUT_EQUITY_CSV)

    yearly_frames = []
    for key, paper in papers.items():
        yr = compute_yearly_returns(paper)
        yr = yr.rename(columns={"ret_pct": key})
        yearly_frames.append(yr.set_index("year"))

    yearly_df = pd.concat(yearly_frames, axis=1).reset_index()
    yearly_df.to_csv(OUT_YEARLY_CSV, index=False)

    focus_rows = []
    for key, paper in papers.items():
        for start_date, end_date, label in FOCUS_WINDOWS:
            row = summarize_focus_window(paper, start_date, end_date, label)
            focus_rows.append({"model": key, "label": LABELS[key], **row})

    focus_df = pd.DataFrame(focus_rows)
    focus_df.to_csv(OUT_FOCUS_CSV, index=False)

    best = summary_df.iloc[0].to_dict()
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\n=== PHASE 46 FINAL COMPARE PRUNED WINNERS ===")
    print(summary_df.to_string(index=False))

    print("\n=== YEARLY RETURNS (%) ===")
    print(yearly_df.to_string(index=False))

    print("\n=== FOCUS WINDOWS ===")
    print(focus_df.to_string(index=False))

    print("\nuložené:")
    print(OUT_SUMMARY_CSV)
    print(OUT_EQUITY_CSV)
    print(OUT_YEARLY_CSV)
    print(OUT_FOCUS_CSV)
    print(OUT_JSON)


if __name__ == "__main__":
    main()