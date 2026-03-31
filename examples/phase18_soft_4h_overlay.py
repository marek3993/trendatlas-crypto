from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.scoring import compute_score_frame

ROOT = Path(__file__).resolve().parents[1]
DAILY_DIR = ROOT / "data" / "ohlcv"
H4_DIR = ROOT / "data" / "ohlcv_4h"
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

BARS_PER_DAY_4H = 6
BARS_PER_YEAR_4H = 365.25 * BARS_PER_DAY_4H


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


def bull(score: float) -> bool:
    return score >= 35.0


def bear(score: float) -> bool:
    return score <= -35.0


def build_daily_tables(assets: dict[str, pd.DataFrame], macro_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}

    for symbol, ohlcv in assets.items():
        features = compute_feature_frame(ohlcv, macro_df=macro_df)
        scores = compute_score_frame(features)

        rows = []
        position = 0

        for i in range(260, len(features)):
            idx = features.index[i]
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
                bull(st_score)
                and bull(lt_score)
                and confidence >= 40.0
                and regime != "chaos"
                and mr_score >= -90.0
            )

            hold_long = (
                not bear(lt_score)
                and confidence >= 30.0
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
                }
            )

        df = pd.DataFrame(rows)
        if df.empty:
            out[symbol] = pd.DataFrame(
                columns=["close", "active_long", "confidence", "yz_vol_20", "atr_pct", "general_score", "base_rank"]
            ).rename_axis("ts")
        else:
            out[symbol] = df.set_index("ts")

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

    for symbol, tbl in out.items():
        tbl["xs20"] = xs20[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs90"] = xs90[symbol].reindex(tbl.index).fillna(0.0)
        tbl["xs_persist"] = xs_persist[symbol].reindex(tbl.index).fillna(0.0)

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
                and float(row["confidence"]) >= 35.0
                and float(row["yz_vol_20"]) <= 0.7
                and float(row["atr_pct"]) <= 70.0
            ):
                score = (
                    float(row["base_rank"])
                    + 0.35 * float(row["xs20"])
                    + 0.20 * float(row["xs90"])
                    + 0.15 * float(row["xs_persist"])
                )
                candidates.append((symbol, score))

        market_score = float(np.mean(market_scores)) if market_scores else 0.0

        selected = "CASH"
        if market_score >= 10.0 and candidates:
            candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
            selected = candidates[0][0]

        rows.append({"ts": dt, "selected": selected})

    return pd.DataFrame(rows).set_index("ts").sort_index()


def build_4h_tables(assets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close_df = pd.concat({s: df["close"] for s, df in assets.items()}, axis=1).sort_index()
    high_df = pd.concat({s: df["high"] for s, df in assets.items()}, axis=1).sort_index()
    low_df = pd.concat({s: df["low"] for s, df in assets.items()}, axis=1).sort_index()
    vol_df = pd.concat({s: df["volume"] for s, df in assets.items()}, axis=1).sort_index()

    ret18 = close_df.pct_change(18)
    ret42 = close_df.pct_change(42)
    ret126 = close_df.pct_change(126)

    btc18 = ret18["BTCUSDT"]
    btc42 = ret42["BTCUSDT"]
    btc126 = ret126["BTCUSDT"]

    rs18 = ret18.sub(btc18, axis=0).fillna(0.0)
    rs42 = ret42.sub(btc42, axis=0).fillna(0.0)
    rs126 = ret126.sub(btc126, axis=0).fillna(0.0)

    xs18 = (rs18.rank(axis=1, pct=True) - 0.5) * 200.0
    xs42 = (rs42.rank(axis=1, pct=True) - 0.5) * 200.0
    xs126 = (rs126.rank(axis=1, pct=True) - 0.5) * 200.0
    accel = (xs18 - xs126).fillna(0.0)

    rolling_high_30 = high_df.shift(1).rolling(30).max()
    breakout30 = ((close_df / rolling_high_30) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    vol_burst = (vol_df / vol_df.shift(1).rolling(30).median()).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    breadth42 = (xs42 > 0).mean(axis=1).fillna(0.0)

    dollar_vol = (close_df * vol_df).rolling(30).median()
    dv_rank = dollar_vol.rank(axis=1, pct=True).fillna(0.0)

    out = {}
    for symbol, df in assets.items():
        t = df.copy()

        prev_close = t["close"].shift(1)
        tr = pd.concat(
            [
                (t["high"] - t["low"]).abs(),
                (t["high"] - prev_close).abs(),
                (t["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_pct = (tr.rolling(14).mean() / t["close"]) * 100.0

        ema42 = t["close"].ewm(span=42, adjust=False).mean()
        ema126 = t["close"].ewm(span=126, adjust=False).mean()
        ret_next = t["close"].pct_change().shift(-1)

        t["ret_next"] = ret_next
        t["ema42"] = ema42
        t["ema126"] = ema126
        t["atr_pct"] = atr_pct.fillna(0.0)

        t["xs18"] = xs18[symbol].reindex(t.index).fillna(0.0)
        t["xs42"] = xs42[symbol].reindex(t.index).fillna(0.0)
        t["xs126"] = xs126[symbol].reindex(t.index).fillna(0.0)
        t["accel"] = accel[symbol].reindex(t.index).fillna(0.0)
        t["breakout30"] = breakout30[symbol].reindex(t.index).fillna(0.0)
        t["vol_burst"] = vol_burst[symbol].reindex(t.index).fillna(0.0)
        t["breadth42"] = breadth42.reindex(t.index).fillna(0.0)
        t["dv_rank"] = dv_rank[symbol].reindex(t.index).fillna(0.0)

        out[symbol] = t

    return out


def overlay_exposure(row: pd.Series, model: str) -> float:
    close_ = float(row["close"])
    ema42 = float(row["ema42"])
    ema126 = float(row["ema126"])
    xs18 = float(row["xs18"])
    accel = float(row["accel"])
    dv_rank = float(row["dv_rank"])
    breadth42 = float(row["breadth42"])
    atr_pct = float(row["atr_pct"])
    breakout30 = float(row["breakout30"])
    vol_burst = float(row["vol_burst"])

    strong = (
        close_ > ema42 > ema126
        and xs18 > 0.0
        and accel > -5.0
        and dv_rank >= 0.25
        and breadth42 >= 0.35
        and atr_pct <= 10.0
    )

    neutral = (
        close_ > ema42
        and xs18 > -10.0
        and accel > -20.0
        and dv_rank >= 0.20
        and breadth42 >= 0.30
        and atr_pct <= 12.0
    )

    weak = (
        close_ > ema126
        and xs18 > -20.0
        and dv_rank >= 0.15
        and breadth42 >= 0.25
        and atr_pct <= 14.0
    )

    breakout_ok = breakout30 >= -0.005 and vol_burst >= 1.00

    if model == "always_daily":
        return 1.0

    if model == "soft_half_4h":
        if strong:
            return 1.0
        if neutral:
            return 0.5
        return 0.0

    if model == "soft_scale_4h":
        if strong:
            return 1.0
        if neutral:
            return 0.5
        if weak:
            return 0.25
        return 0.0

    if model == "soft_breakout_scale_4h":
        if strong and breakout_ok:
            return 1.0
        if strong:
            return 0.75
        if neutral and breakout_ok:
            return 0.5
        if weak:
            return 0.25
        return 0.0

    if model == "soft_kill_4h":
        emergency = close_ < ema126 and xs18 < -20.0 and breadth42 < 0.25
        if emergency:
            return 0.0
        if strong:
            return 1.0
        if neutral:
            return 0.75
        if weak:
            return 0.50
        return 0.25

    raise ValueError(f"Unknown model: {model}")


def get_daily_symbol_for_4h_ts(daily_sel: pd.Series, ts: pd.Timestamp) -> str:
    signal_day = ts.normalize() - pd.Timedelta(days=1)
    subset = daily_sel.loc[daily_sel.index <= signal_day]
    if len(subset) == 0:
        return "CASH"
    return str(subset.iloc[-1])


def run_overlay_model(
    daily_selection: pd.DataFrame,
    tables_4h: dict[str, pd.DataFrame],
    model: str,
    total_cost_bps: float = 15.0,
) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(t.index) for t in tables_4h.values()]))
    symbols = sorted(tables_4h.keys())
    trade_cost = total_cost_bps / 10000.0

    daily_sel = daily_selection["selected"].copy().sort_index()
    prev_weights = {s: 0.0 for s in symbols}
    rows = []

    for ts in all_dates:
        best_available_next = -999.0
        for s, tbl in tables_4h.items():
            if ts in tbl.index and pd.notna(tbl.loc[ts, "ret_next"]):
                best_available_next = max(best_available_next, float(tbl.loc[ts, "ret_next"]))

        daily_symbol = get_daily_symbol_for_4h_ts(daily_sel, ts)

        target_weights = {s: 0.0 for s in symbols}
        selected_symbol = "CASH"
        selected_ret_next = 0.0
        exposure = 0.0

        if daily_symbol != "CASH" and daily_symbol in tables_4h and ts in tables_4h[daily_symbol].index:
            row = tables_4h[daily_symbol].loc[ts]
            exposure = overlay_exposure(row, model)
            if exposure > 0.0:
                selected_symbol = daily_symbol
                selected_ret_next = float(row["ret_next"]) if pd.notna(row["ret_next"]) else 0.0
                target_weights[selected_symbol] = exposure

        raw_ret = exposure * selected_ret_next
        gross_exposure = exposure

        turnover = sum(abs(target_weights[s] - prev_weights[s]) for s in symbols)
        cost = turnover * trade_cost
        strategy_ret = raw_ret - cost

        rows.append(
            {
                "ts": ts,
                "daily_selected": daily_symbol,
                "selected": selected_symbol,
                "n_selected": 0 if selected_symbol == "CASH" else 1,
                "gross_exposure": gross_exposure,
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
                "selected_ret_next": selected_ret_next,
                "best_available_next": best_available_next if best_available_next > -900 else np.nan,
                "captured_spike_bar": int(raw_ret >= 0.04),
                "available_spike_bar": int(best_available_next >= 0.04) if best_available_next > -900 else 0,
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows).set_index("ts").sort_index()
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    return out


def compute_summary(paper: pd.DataFrame) -> dict:
    rets = paper["strategy_ret"].fillna(0.0)
    equity = (1.0 + rets).cumprod()

    total_return = float(equity.iloc[-1] - 1.0)
    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / 365.25
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std())
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(BARS_PER_YEAR_4H))

    downside = rets[rets < 0].std()
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(BARS_PER_YEAR_4H))

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((paper["turnover"] > 0).sum()),
        "avg_exposure": round(float(paper["gross_exposure"].mean()), 3),
    }


def spike_stats(paper: pd.DataFrame) -> dict:
    available = int(paper["available_spike_bar"].sum())
    captured = int(paper["captured_spike_bar"].sum())
    capture_ratio = (captured / available) if available > 0 else 0.0

    captured_only = paper.loc[paper["captured_spike_bar"] == 1, "raw_strategy_ret"]
    avg_captured = float(captured_only.mean()) if len(captured_only) > 0 else 0.0

    return {
        "available_spike_bars": available,
        "captured_spike_bars": captured,
        "spike_capture_ratio": round(capture_ratio, 3),
        "avg_captured_spike_ret_pct": round(avg_captured * 100.0, 2),
    }


def split_windows(paper: pd.DataFrame, window_size: int = 1080) -> list[pd.DataFrame]:
    out = []
    for start in range(0, len(paper), window_size):
        part = paper.iloc[start:start + window_size].copy()
        if len(part) > 30:
            out.append(part)
    return out


def result_row(model: str, paper: pd.DataFrame) -> dict:
    full = compute_summary(paper)
    spikes = spike_stats(paper)

    wins = []
    for i, win in enumerate(split_windows(paper, 1080), start=1):
        s = compute_summary(win)
        s["window"] = i
        wins.append(s)

    wf = pd.DataFrame(wins)

    median_sharpe = float(wf["sharpe"].median()) if not wf.empty else 0.0
    median_sortino = float(wf["sortino"].median()) if not wf.empty else 0.0
    median_cagr = float(wf["cagr_pct"].median()) if not wf.empty else 0.0
    median_ret = float(wf["total_return_pct"].median()) if not wf.empty else 0.0
    worst_dd = float(wf["max_drawdown_pct"].min()) if not wf.empty else 0.0
    pos_ratio = float((wf["total_return_pct"] > 0).mean()) if not wf.empty else 0.0

    robust_score = (
        14.0 * median_sharpe
        + 10.0 * median_sortino
        + 0.20 * median_cagr
        + 0.05 * median_ret
        - 0.60 * abs(worst_dd)
        + 8.0 * spikes["spike_capture_ratio"]
    )

    return {
        "model": model,
        "robust_score": round(robust_score, 3),
        "median_window_sharpe": round(median_sharpe, 3),
        "median_window_sortino": round(median_sortino, 3),
        "median_window_cagr_pct": round(median_cagr, 2),
        "median_window_return_pct": round(median_ret, 2),
        "worst_window_dd_pct": round(worst_dd, 2),
        "positive_window_ratio": round(pos_ratio, 3),
        **spikes,
        "full_total_return_pct": full["total_return_pct"],
        "full_cagr_pct": full["cagr_pct"],
        "full_max_drawdown_pct": full["max_drawdown_pct"],
        "full_sharpe": full["sharpe"],
        "full_sortino": full["sortino"],
        "full_trade_count": full["trade_count"],
        "full_avg_exposure": full["avg_exposure"],
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    macro = load_macro_csv(MACRO_PATH)

    daily_assets = {s: load_ohlcv_csv(DAILY_DIR / f"{s}_1d.csv") for s in TARGET_SYMBOLS}
    h4_assets = {s: load_ohlcv_csv(H4_DIR / f"{s}_4h.csv") for s in TARGET_SYMBOLS}

    print("počítam daily selection...", flush=True)
    daily_tables = build_daily_tables(daily_assets, macro)
    daily_selection = select_daily_top1(daily_tables)
    daily_selection.to_csv(OUTPUT_DIR / "phase18_daily_selection.csv")

    print("počítam 4h timing tables...", flush=True)
    h4_tables = build_4h_tables(h4_assets)

    models = [
        "always_daily",
        "soft_half_4h",
        "soft_scale_4h",
        "soft_breakout_scale_4h",
        "soft_kill_4h",
    ]

    rows = []
    for model in models:
        print(f"testujem {model}...", flush=True)
        paper = run_overlay_model(daily_selection, h4_tables, model=model, total_cost_bps=15.0)
        rows.append(result_row(model, paper))
        paper.to_csv(OUTPUT_DIR / f"phase18_{model}.csv")

    out = pd.DataFrame(rows).sort_values(
        ["robust_score", "full_sharpe", "full_cagr_pct"],
        ascending=False,
    ).reset_index(drop=True)

    out.to_csv(OUTPUT_DIR / "phase18_soft_4h_overlay_results.csv", index=False)

    best = out.iloc[0].to_dict()
    with open(OUTPUT_DIR / "phase18_soft_4h_overlay_best.json", "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\nPHASE 18 SOFT 4H OVERLAY")
    print(out.to_string(index=False))
    print("\nuložené:")
    print("outputs\\phase18_soft_4h_overlay_results.csv")
    print("outputs\\phase18_soft_4h_overlay_best.json")
    print("outputs\\phase18_daily_selection.csv")
    print("outputs\\phase18_always_daily.csv")
    print("outputs\\phase18_soft_half_4h.csv")
    print("outputs\\phase18_soft_scale_4h.csv")
    print("outputs\\phase18_soft_breakout_scale_4h.csv")
    print("outputs\\phase18_soft_kill_4h.csv")


if __name__ == "__main__":
    main()