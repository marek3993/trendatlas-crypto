from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.paper import StrategyParams
from market_regime_v1.scoring import TrendState, compute_score_frame

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

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ohlcv"
MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"
OUTPUT_DIR = ROOT / "outputs"

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

TARGET_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df = df.rename(columns=RENAME_MAP)

    date_col = next((c for c in DATE_CANDIDATES if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path} nemá dátumový stĺpec")

    df[date_col] = pd.to_datetime(df[date_col], utc=False, errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    req = ["open", "high", "low", "close", "volume"]
    df = df[req].apply(pd.to_numeric, errors="coerce").dropna()
    return df


def load_macro_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.set_index("date").sort_index()

    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
    df = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    return df


def trend_state(score: float) -> TrendState:
    if score >= 35.0:
        return TrendState.BULLISH
    if score <= -35.0:
        return TrendState.BEARISH
    return TrendState.NEUTRAL


def row_conf(row: pd.Series, cols: list[str]) -> float:
    vals = row[cols].astype(float)
    row_mean = float(vals.mean())
    mad = float((vals - row_mean).abs().mean())
    conf = 100.0 * (1.0 - (mad / 80.0))
    return max(0.0, min(100.0, conf))


def build_asset_table(
    symbol: str,
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame,
    params: StrategyParams,
) -> pd.DataFrame:
    features = compute_feature_frame(ohlcv, macro_df=macro_df)
    scores = compute_score_frame(features)

    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]
    volume = ohlcv["volume"]

    close_ret_next = close.pct_change().shift(-1)

    rows = []
    position = 0

    for i in range(260, len(features)):
        idx = features.index[i]
        srow = scores.loc[idx]

        st_score = float(srow[ST_COLS].mean())
        lt_score = float(srow[LT_COLS].mean())
        mr_score = float(srow[MR_COLS].mean())

        st_conf = row_conf(srow, ST_COLS)
        lt_conf = row_conf(srow, LT_COLS)
        confidence = min(st_conf, lt_conf)

        yz_val = float(features.loc[idx, "yz_vol_20"]) if "yz_vol_20" in features.columns else 0.0
        atr_val = float(features.loc[idx, "atr_pct"]) if "atr_pct" in features.columns else 0.0

        if yz_val > 0.9:
            regime = "chaos"
        elif atr_val > 80:
            regime = "transition"
        elif abs(st_score) < 20 and abs(lt_score) < 20:
            regime = "range"
        else:
            regime = "transition"

        st_state = trend_state(st_score)
        lt_state = trend_state(lt_score)
        general_score = 0.6 * lt_score + 0.4 * st_score
        directional_bias = 0.45 * lt_score + 0.35 * st_score + 0.20 * mr_score

        enter_long = (
            st_state == TrendState.BULLISH
            and lt_state == TrendState.BULLISH
            and confidence >= params.enter_conf
            and regime != "chaos"
            and mr_score >= params.long_mr_floor
            and lt_score >= params.min_lt_score_long
            and st_score >= params.min_st_score_long
            and yz_val <= params.max_yz_vol_entry
            and atr_val <= params.max_atr_pct_entry
        )

        hold_long = (
            lt_state != TrendState.BEARISH
            and confidence >= params.hold_conf
            and directional_bias > params.exit_long_bias
            and (not params.exit_on_chaos or regime != "chaos")
            and (not params.exit_on_transition or regime != "transition")
        )

        if position == 0:
            if enter_long:
                position = 1
        elif position == 1:
            if not hold_long:
                position = 0

        base_rank = 0.55 * lt_score + 0.30 * st_score + 0.15 * confidence
        ret_next = float(close_ret_next.loc[idx]) if idx in close_ret_next.index and pd.notna(close_ret_next.loc[idx]) else np.nan

        rows.append(
            {
                "ts": idx,
                "symbol": symbol,
                "open": float(ohlcv.loc[idx, "open"]),
                "high": float(high.loc[idx]),
                "low": float(low.loc[idx]),
                "close": float(close.loc[idx]),
                "volume": float(volume.loc[idx]),
                "active_long": position,
                "ret_next": ret_next,
                "st_score": st_score,
                "lt_score": lt_score,
                "mr_score": mr_score,
                "confidence": confidence,
                "yz_vol_20": yz_val,
                "atr_pct": atr_val,
                "general_score": general_score,
                "base_rank": base_rank,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=[
                "open", "high", "low", "close", "volume", "active_long", "ret_next",
                "st_score", "lt_score", "mr_score", "confidence", "yz_vol_20",
                "atr_pct", "general_score", "base_rank"
            ]
        ).rename_axis("ts")
    return out.set_index("ts")


def enrich_phase14(base_tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close_df = pd.concat({s: t["close"] for s, t in base_tables.items()}, axis=1).sort_index()
    high_df = pd.concat({s: t["high"] for s, t in base_tables.items()}, axis=1).sort_index()
    low_df = pd.concat({s: t["low"] for s, t in base_tables.items()}, axis=1).sort_index()
    vol_df = pd.concat({s: t["volume"] for s, t in base_tables.items()}, axis=1).sort_index()

    ret1 = close_df.pct_change(1)
    ret3 = close_df.pct_change(3)
    ret7 = close_df.pct_change(7)
    ret14 = close_df.pct_change(14)
    ret20 = close_df.pct_change(20)
    ret90 = close_df.pct_change(90)

    btc7 = ret7["BTCUSDT"]
    btc14 = ret14["BTCUSDT"]
    btc20 = ret20["BTCUSDT"]
    btc90 = ret90["BTCUSDT"]

    rs7 = ret7.sub(btc7, axis=0).fillna(0.0)
    rs14 = ret14.sub(btc14, axis=0).fillna(0.0)
    rs20 = ret20.sub(btc20, axis=0).fillna(0.0)
    rs90 = ret90.sub(btc90, axis=0).fillna(0.0)

    xs7 = (rs7.rank(axis=1, pct=True) - 0.5) * 200.0
    xs14 = (rs14.rank(axis=1, pct=True) - 0.5) * 200.0
    xs20 = (rs20.rank(axis=1, pct=True) - 0.5) * 200.0
    xs90 = (rs90.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_persist = (0.6 * xs20 + 0.4 * xs90).rolling(5).mean().fillna(0.0)

    accel_3v20 = (xs7 - xs20).fillna(0.0)
    accel_14v90 = (xs14 - xs90).fillna(0.0)

    rolling_high_20 = high_df.shift(1).rolling(20).max()
    rolling_high_30 = high_df.shift(1).rolling(30).max()
    breakout20 = ((close_df / rolling_high_20) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    breakout30 = ((close_df / rolling_high_30) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    vol_med20 = vol_df.shift(1).rolling(20).median()
    vol_burst = (vol_df / vol_med20).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    daily_range = (high_df - low_df) / close_df.replace(0.0, np.nan)
    range_expansion = (daily_range / daily_range.shift(1).rolling(10).median()).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    dollar_vol = (close_df * vol_df).rolling(20).median()
    dv_rank = dollar_vol.rank(axis=1, pct=True).fillna(0.0)

    breadth14 = (rs14 > 0).mean(axis=1).fillna(0.0)
    breadth7 = (rs7 > 0).mean(axis=1).fillna(0.0)

    out = {}
    for symbol, tbl in base_tables.items():
        tmp = tbl.copy()
        tmp["ret1"] = ret1[symbol].reindex(tmp.index).fillna(0.0)
        tmp["ret3"] = ret3[symbol].reindex(tmp.index).fillna(0.0)
        tmp["ret7"] = ret7[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_7"] = xs7[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_14"] = xs14[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_20"] = xs20[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_90"] = xs90[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_persist"] = xs_persist[symbol].reindex(tmp.index).fillna(0.0)
        tmp["accel_3v20"] = accel_3v20[symbol].reindex(tmp.index).fillna(0.0)
        tmp["accel_14v90"] = accel_14v90[symbol].reindex(tmp.index).fillna(0.0)
        tmp["breakout20"] = breakout20[symbol].reindex(tmp.index).fillna(0.0)
        tmp["breakout30"] = breakout30[symbol].reindex(tmp.index).fillna(0.0)
        tmp["vol_burst"] = vol_burst[symbol].reindex(tmp.index).fillna(0.0)
        tmp["range_expansion"] = range_expansion[symbol].reindex(tmp.index).fillna(0.0)
        tmp["dv_rank_20"] = dv_rank[symbol].reindex(tmp.index).fillna(0.0)
        tmp["breadth14"] = breadth14.reindex(tmp.index).fillna(0.0)
        tmp["breadth7"] = breadth7.reindex(tmp.index).fillna(0.0)
        out[symbol] = tmp
    return out


def baseline_rs_score(row: pd.Series) -> float:
    return (
        float(row["base_rank"])
        + 0.35 * float(row["xs_rank_20"])
        + 0.20 * float(row["xs_rank_90"])
        + 0.15 * float(row["xs_rank_persist"])
    )


def spike_score(row: pd.Series, model: str) -> float:
    base = (
        0.35 * float(row["xs_rank_7"])
        + 0.20 * float(row["xs_rank_14"])
        + 0.25 * float(row["accel_3v20"])
        + 0.15 * float(row["accel_14v90"])
    )

    breakout = 220.0 * float(row["breakout20"]) + 160.0 * float(row["breakout30"])
    volume = 28.0 * clamp(float(row["vol_burst"]) - 1.0, 0.0, 4.0)
    range_ex = 16.0 * clamp(float(row["range_expansion"]) - 1.0, 0.0, 4.0)

    if model == "spike_loose":
        return base + 0.18 * breakout

    if model == "spike_breakout":
        return base + 0.24 * breakout + volume

    if model == "spike_breakout_volume":
        return base + 0.26 * breakout + volume + range_ex

    if model == "spike_hunter":
        return (
            base
            + 0.30 * breakout
            + 1.10 * volume
            + 0.90 * range_ex
            + 0.15 * float(row["base_rank"])
        )

    raise ValueError(f"Unknown model: {model}")


def candidate_ok_baseline(row: pd.Series) -> bool:
    return (
        int(row["active_long"]) == 1
        and pd.notna(row["ret_next"])
        and float(row["confidence"]) >= 35.0
        and float(row["yz_vol_20"]) <= 0.7
        and float(row["atr_pct"]) <= 70.0
    )


def candidate_ok_spike(row: pd.Series, model: str) -> bool:
    if pd.isna(row["ret_next"]):
        return False

    if float(row["dv_rank_20"]) < 0.25:
        return False

    if float(row["breadth14"]) < 0.35:
        return False

    if float(row["yz_vol_20"]) > 1.2:
        return False

    if model == "spike_loose":
        return (
            float(row["xs_rank_7"]) >= 20.0
            and float(row["accel_3v20"]) >= 5.0
            and float(row["breakout20"]) >= -0.01
            and float(row["vol_burst"]) >= 1.05
        )

    if model == "spike_breakout":
        return (
            float(row["xs_rank_7"]) >= 25.0
            and float(row["accel_3v20"]) >= 10.0
            and float(row["breakout20"]) >= 0.0
            and float(row["vol_burst"]) >= 1.10
        )

    if model == "spike_breakout_volume":
        return (
            float(row["xs_rank_7"]) >= 25.0
            and float(row["accel_3v20"]) >= 10.0
            and (float(row["breakout20"]) >= 0.0 or float(row["breakout30"]) >= 0.0)
            and float(row["vol_burst"]) >= 1.20
            and float(row["range_expansion"]) >= 1.05
        )

    if model == "spike_hunter":
        return (
            float(row["xs_rank_7"]) >= 20.0
            and float(row["accel_3v20"]) >= 8.0
            and (float(row["breakout20"]) >= -0.005 or float(row["breakout30"]) >= -0.005)
            and float(row["vol_burst"]) >= 1.15
            and float(row["range_expansion"]) >= 1.00
            and float(row["breadth7"]) >= 0.30
        )

    raise ValueError(f"Unknown model: {model}")


def run_model(
    asset_tables: dict[str, pd.DataFrame],
    model: str,
    total_cost_bps: float = 15.0,
    market_score_floor: float = 10.0,
) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(tbl.index) for tbl in asset_tables.values()]))
    symbols = sorted(asset_tables.keys())
    trade_cost = total_cost_bps / 10000.0

    prev_weights = {s: 0.0 for s in symbols}
    rows = []

    for dt in all_dates:
        candidates = []
        market_scores = []
        best_available_next = -999.0

        for symbol, tbl in asset_tables.items():
            if dt not in tbl.index:
                continue

            row = tbl.loc[dt]
            market_scores.append(float(row["general_score"]))

            if pd.notna(row["ret_next"]):
                best_available_next = max(best_available_next, float(row["ret_next"]))

            if model == "baseline_rs":
                ok = candidate_ok_baseline(row)
                score = baseline_rs_score(row)
            else:
                ok = candidate_ok_spike(row, model)
                score = spike_score(row, model)

            if not ok:
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "rank_score": score,
                    "ret_next": float(row["ret_next"]),
                }
            )

        market_score = float(np.mean(market_scores)) if market_scores else 0.0

        target_weights = {s: 0.0 for s in symbols}
        selected = []
        selected_symbol = "CASH"
        selected_ret_next = 0.0

        if market_score >= market_score_floor and candidates:
            candidates = sorted(candidates, key=lambda x: x["rank_score"], reverse=True)
            selected = candidates[:1]
            selected_symbol = selected[0]["symbol"]
            selected_ret_next = float(selected[0]["ret_next"])
            target_weights[selected_symbol] = 1.0

        raw_ret = 0.0
        gross_exposure = 0.0
        for symbol in symbols:
            if target_weights[symbol] > 0:
                raw_ret += target_weights[symbol] * selected_ret_next
                gross_exposure += target_weights[symbol]

        turnover = sum(abs(target_weights[s] - prev_weights[s]) for s in symbols)
        cost = turnover * trade_cost
        strategy_ret = raw_ret - cost

        rows.append(
            {
                "ts": dt,
                "selected": selected_symbol,
                "n_selected": 0 if selected_symbol == "CASH" else 1,
                "gross_exposure": gross_exposure,
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
                "selected_ret_next": selected_ret_next,
                "best_available_next": best_available_next if best_available_next > -900 else np.nan,
                "captured_spike_day": int(selected_ret_next >= 0.10),
                "available_spike_day": int(best_available_next >= 0.10) if best_available_next > -900 else 0,
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=[
                "selected", "n_selected", "gross_exposure", "raw_strategy_ret", "turnover",
                "cost", "strategy_ret", "selected_ret_next", "best_available_next",
                "captured_spike_day", "available_spike_day", "equity"
            ]
        ).rename_axis("ts")

    out = out.set_index("ts")
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    return out


def compute_summary(paper: pd.DataFrame) -> dict:
    if paper.empty:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": 0,
        }

    rets = paper["strategy_ret"].fillna(0.0)
    if len(rets) < 20:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": int((paper["turnover"] > 0).sum()),
        }

    equity = (1.0 + rets).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)

    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / 365.25
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    rolling_peak = equity.cummax()
    drawdown = equity / rolling_peak - 1.0
    max_drawdown = float(drawdown.min())

    vol = float(rets.std())
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(365.25))

    downside = rets[rets < 0].std()
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(365.25))

    trade_count = int((paper["turnover"] > 0).sum())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": trade_count,
    }


def split_windows(paper: pd.DataFrame, window_size: int = 180) -> list[pd.DataFrame]:
    if paper.empty:
        return []

    out = []
    for start in range(0, len(paper), window_size):
        part = paper.iloc[start:start + window_size].copy()
        if len(part) > 20:
            out.append(part)
    return out


def spike_stats(paper: pd.DataFrame) -> dict:
    available = int(paper["available_spike_day"].sum()) if "available_spike_day" in paper.columns else 0
    captured = int(paper["captured_spike_day"].sum()) if "captured_spike_day" in paper.columns else 0
    capture_ratio = (captured / available) if available > 0 else 0.0

    spike_only = paper.loc[paper["captured_spike_day"] == 1, "selected_ret_next"] if "captured_spike_day" in paper.columns else pd.Series(dtype=float)
    avg_captured = float(spike_only.mean()) if len(spike_only) > 0 else 0.0

    return {
        "available_spike_days": available,
        "captured_spike_days": captured,
        "spike_capture_ratio": round(capture_ratio, 3),
        "avg_captured_spike_ret_pct": round(avg_captured * 100.0, 2),
    }


def result_row(model: str, paper: pd.DataFrame) -> dict:
    full = compute_summary(paper)
    spikes = spike_stats(paper)

    wins = []
    for i, win in enumerate(split_windows(paper, 180), start=1):
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
        + 20.0 * spikes["spike_capture_ratio"]
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
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    macro = load_macro_csv(MACRO_PATH)
    assets = {s: load_ohlcv_csv(DATA_DIR / f"{s}_1d.csv") for s in TARGET_SYMBOLS}

    base_params = StrategyParams(
        enter_conf=40.0,
        hold_conf=30.0,
        long_mr_floor=-90.0,
        short_mr_ceiling=80.0,
        exit_long_bias=0.0,
        exit_short_bias=10.0,
        allow_long=True,
        allow_short=False,
        fee_bps=5.0,
        slippage_bps=5.0,
        exit_on_chaos=True,
        min_lt_score_long=0.0,
        min_st_score_long=-100.0,
        max_yz_vol_entry=999.0,
        max_atr_pct_entry=100.0,
        exit_on_transition=False,
    )

    base_tables = {}
    for symbol, ohlcv in assets.items():
        print(f"počítam {symbol}...", flush=True)
        base_tables[symbol] = build_asset_table(symbol, ohlcv, macro, base_params)

    asset_tables = enrich_phase14(base_tables)

    models = [
        "baseline_rs",
        "spike_loose",
        "spike_breakout",
        "spike_breakout_volume",
        "spike_hunter",
    ]

    rows = []
    for model in models:
        print(f"testujem {model}...", flush=True)
        paper = run_model(asset_tables, model=model)
        rows.append(result_row(model, paper))
        paper.to_csv(OUTPUT_DIR / f"phase14_{model}.csv")

    out = pd.DataFrame(rows).sort_values(
        ["robust_score", "spike_capture_ratio", "full_cagr_pct"],
        ascending=False,
    ).reset_index(drop=True)

    out.to_csv(OUTPUT_DIR / "phase14_true_spike_hunter_results.csv", index=False)

    best = out.iloc[0].to_dict()
    with open(OUTPUT_DIR / "phase14_true_spike_hunter_best.json", "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\nPHASE 14 TRUE SPIKE HUNTER")
    print(out.to_string(index=False))
    print("\nuložené:")
    print("outputs\\phase14_true_spike_hunter_results.csv")
    print("outputs\\phase14_true_spike_hunter_best.json")
    print("outputs\\phase14_baseline_rs.csv")
    print("outputs\\phase14_spike_loose.csv")
    print("outputs\\phase14_spike_breakout.csv")
    print("outputs\\phase14_spike_breakout_volume.csv")
    print("outputs\\phase14_spike_hunter.csv")


if __name__ == "__main__":
    main()