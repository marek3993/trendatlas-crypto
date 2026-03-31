from __future__ import annotations

import json
from itertools import product
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
    close_ret_next = ohlcv["close"].pct_change().shift(-1)

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
                "close": float(ohlcv.loc[idx, "close"]),
                "active_long": position,
                "ret_next": ret_next,
                "st_score": st_score,
                "lt_score": lt_score,
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
            columns=["close", "active_long", "ret_next", "st_score", "lt_score", "confidence", "yz_vol_20", "atr_pct", "general_score", "base_rank"]
        ).rename_axis("ts")
    return out.set_index("ts")


def enrich_rs(base_tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close_df = pd.concat({s: t["close"] for s, t in base_tables.items()}, axis=1).sort_index()

    ret20 = close_df.pct_change(20)
    ret90 = close_df.pct_change(90)

    btc20 = ret20["BTCUSDT"]
    btc90 = ret90["BTCUSDT"]

    rel20 = ret20.sub(btc20, axis=0).fillna(0.0)
    rel90 = ret90.sub(btc90, axis=0).fillna(0.0)

    xs20 = (rel20.rank(axis=1, pct=True) - 0.5) * 200.0
    xs90 = (rel90.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_persist = (0.6 * xs20 + 0.4 * xs90).rolling(5).mean().fillna(0.0)

    out = {}
    for symbol, tbl in base_tables.items():
        tmp = tbl.copy()
        tmp["xs_rank_20"] = xs20[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_90"] = xs90[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_persist"] = xs_persist[symbol].reindex(tmp.index).fillna(0.0)
        out[symbol] = tmp
    return out


def model_rank(row: pd.Series, model: str) -> float:
    score = float(row["base_rank"])
    if model == "rs":
        score += 0.35 * float(row["xs_rank_20"])
        score += 0.20 * float(row["xs_rank_90"])
        score += 0.15 * float(row["xs_rank_persist"])
    return score


def run_top1_model_with_controls(
    asset_tables: dict[str, pd.DataFrame],
    model: str,
    market_score_floor: float,
    min_confidence: float,
    max_yz_vol: float,
    max_atr_pct: float,
    btc_lt_floor: float,
    dynamic_weight: bool,
    kill_dd: float,
    cooldown_days: int,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(tbl.index) for tbl in asset_tables.values()]))
    symbols = sorted(asset_tables.keys())
    trade_cost = (fee_bps + slippage_bps) / 10000.0

    prev_weights = {s: 0.0 for s in symbols}
    rows = []

    equity = 1.0
    peak_equity = 1.0
    cooldown_left = 0

    for dt in all_dates:
        candidates = []
        market_scores = []

        btc_lt_score = None
        if "BTCUSDT" in asset_tables and dt in asset_tables["BTCUSDT"].index:
            btc_lt_score = float(asset_tables["BTCUSDT"].loc[dt, "lt_score"])

        for symbol, tbl in asset_tables.items():
            if dt not in tbl.index:
                continue
            row = tbl.loc[dt]
            market_scores.append(float(row["general_score"]))

            if int(row["active_long"]) != 1:
                continue
            if pd.isna(row["ret_next"]):
                continue
            if float(row["confidence"]) < min_confidence:
                continue
            if float(row["yz_vol_20"]) > max_yz_vol:
                continue
            if float(row["atr_pct"]) > max_atr_pct:
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "rank_score": model_rank(row, model),
                    "ret_next": float(row["ret_next"]),
                    "confidence": float(row["confidence"]),
                    "yz_vol_20": float(row["yz_vol_20"]),
                }
            )

        market_score = float(np.mean(market_scores)) if market_scores else 0.0

        target_weights = {s: 0.0 for s in symbols}
        selected = []

        risk_on = (
            cooldown_left <= 0
            and market_score >= market_score_floor
            and (btc_lt_score is not None and btc_lt_score >= btc_lt_floor)
        )

        if risk_on and candidates:
            candidates = sorted(candidates, key=lambda x: x["rank_score"], reverse=True)
            selected = candidates[:1]

            if dynamic_weight:
                conf_scale = clamp(selected[0]["confidence"] / 70.0, 0.35, 1.0)
                vol_scale = clamp(1.0 - max(0.0, selected[0]["yz_vol_20"] - 0.4), 0.35, 1.0)
                weight = clamp(conf_scale * vol_scale, 0.25, 1.0)
            else:
                weight = 1.0

            target_weights[selected[0]["symbol"]] = weight

        raw_ret = 0.0
        held_symbols = []
        for symbol in symbols:
            if target_weights[symbol] > 0:
                ret_next = next(x["ret_next"] for x in selected if x["symbol"] == symbol)
                raw_ret += target_weights[symbol] * ret_next
                held_symbols.append(symbol)

        turnover = sum(abs(target_weights[s] - prev_weights[s]) for s in symbols)
        cost = turnover * trade_cost
        strategy_ret = raw_ret - cost

        equity *= (1.0 + strategy_ret)
        peak_equity = max(peak_equity, equity)
        dd_now = equity / peak_equity - 1.0

        if kill_dd > 0 and dd_now <= -kill_dd and cooldown_left <= 0:
            cooldown_left = cooldown_days

        if cooldown_left > 0:
            cooldown_left -= 1

        rows.append(
            {
                "ts": dt,
                "selected": ",".join(held_symbols),
                "n_selected": len(held_symbols),
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
                "equity": equity,
                "dd_now": dd_now,
                "cooldown_left": cooldown_left,
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=["selected", "n_selected", "raw_strategy_ret", "turnover", "cost", "strategy_ret", "equity", "dd_now", "cooldown_left"]
        ).rename_axis("ts")

    return out.set_index("ts")


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

    n_days = max(len(rets), 1)
    years = n_days / 252.0
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    rolling_peak = equity.cummax()
    drawdown = equity / rolling_peak - 1.0
    max_drawdown = float(drawdown.min())

    vol = float(rets.std())
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(252))

    downside = rets[rets < 0].std()
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(252))

    trade_count = int((paper["turnover"] > 0).sum())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": trade_count,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    macro = load_macro_csv(MACRO_PATH)
    files = sorted(DATA_DIR.glob("*_1d.csv"))
    assets = {path.stem.replace("_1d", ""): load_ohlcv_csv(path) for path in files}

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

    rs_tables = enrich_rs(base_tables)

    all_dates = sorted(set().union(*[set(tbl.index) for tbl in rs_tables.values()]))
    if len(all_dates) < 1080:
        raise RuntimeError("Málo dát na phase 10")

    train_len = 720
    test_len = 180
    step = 180
    starts = list(range(0, len(all_dates) - train_len - test_len + 1, step))

    grid = list(product(
        ["base", "rs"],
        [10.0],
        [35.0],
        [0.7],
        [70.0],
        [-20.0, 0.0, 10.0],     # btc_lt_floor
        [False, True],          # dynamic_weight
        [0.0, 0.10, 0.15],      # kill_dd
        [0, 10, 20],            # cooldown_days
    ))

    window_rows = []
    oos_parts = []

    for w, start in enumerate(starts, start=1):
        train_start = all_dates[start]
        train_end = all_dates[start + train_len - 1]
        test_start = all_dates[start + train_len]
        test_end = all_dates[start + train_len + test_len - 1]

        best_cfg = None
        best_score = -999999.0

        for cfg in grid:
            model, market_score_floor, min_confidence, max_yz_vol, max_atr_pct, btc_lt_floor, dynamic_weight, kill_dd, cooldown_days = cfg

            if kill_dd == 0.0 and cooldown_days != 0:
                continue

            paper = run_top1_model_with_controls(
                asset_tables=rs_tables,
                model=model,
                market_score_floor=market_score_floor,
                min_confidence=min_confidence,
                max_yz_vol=max_yz_vol,
                max_atr_pct=max_atr_pct,
                btc_lt_floor=btc_lt_floor,
                dynamic_weight=dynamic_weight,
                kill_dd=kill_dd,
                cooldown_days=cooldown_days,
            )

            train_paper = paper.loc[(paper.index >= train_start) & (paper.index <= train_end)].copy()
            train_s = compute_summary(train_paper)

            train_score = (
                16.0 * train_s["sharpe"]
                + 12.0 * train_s["sortino"]
                + 0.15 * train_s["cagr_pct"]
                + 0.03 * train_s["total_return_pct"]
                - 0.80 * abs(train_s["max_drawdown_pct"])
            )

            if train_score > best_score:
                best_score = train_score
                best_cfg = {
                    "model": model,
                    "market_score_floor": market_score_floor,
                    "min_confidence": min_confidence,
                    "max_yz_vol": max_yz_vol,
                    "max_atr_pct": max_atr_pct,
                    "btc_lt_floor": btc_lt_floor,
                    "dynamic_weight": dynamic_weight,
                    "kill_dd": kill_dd,
                    "cooldown_days": cooldown_days,
                }

        test_paper_full = run_top1_model_with_controls(
            asset_tables=rs_tables,
            model=best_cfg["model"],
            market_score_floor=best_cfg["market_score_floor"],
            min_confidence=best_cfg["min_confidence"],
            max_yz_vol=best_cfg["max_yz_vol"],
            max_atr_pct=best_cfg["max_atr_pct"],
            btc_lt_floor=best_cfg["btc_lt_floor"],
            dynamic_weight=best_cfg["dynamic_weight"],
            kill_dd=best_cfg["kill_dd"],
            cooldown_days=best_cfg["cooldown_days"],
        )

        test_paper = test_paper_full.loc[(test_paper_full.index >= test_start) & (test_paper_full.index <= test_end)].copy()
        test_s = compute_summary(test_paper)

        tmp = test_paper.copy()
        tmp["window"] = w
        tmp["model"] = best_cfg["model"]
        oos_parts.append(tmp)

        window_rows.append(
            {
                "window": w,
                "train_start": str(train_start.date()),
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                **best_cfg,
                **test_s,
            }
        )

        print(f"window {w}/{len(starts)} hotovo", flush=True)

    wf = pd.DataFrame(window_rows)
    wf.to_csv(OUTPUT_DIR / "phase10_dd_control_windows.csv", index=False)

    oos = pd.concat(oos_parts).sort_index()
    oos = oos[~oos.index.duplicated(keep="first")]
    if not oos.empty:
        oos["equity"] = (1.0 + oos["strategy_ret"].fillna(0.0)).cumprod()
    oos.to_csv(OUTPUT_DIR / "phase10_dd_control_oos.csv")

    oos_summary = compute_summary(oos)
    chosen_models = wf["model"].value_counts().to_dict()

    result = {
        "windows": int(len(wf)),
        "base_chosen": int(chosen_models.get("base", 0)),
        "rs_chosen": int(chosen_models.get("rs", 0)),
        "median_test_sharpe": round(float(wf["sharpe"].median()), 3),
        "median_test_sortino": round(float(wf["sortino"].median()), 3),
        "median_test_cagr_pct": round(float(wf["cagr_pct"].median()), 2),
        "median_test_return_pct": round(float(wf["total_return_pct"].median()), 2),
        "worst_test_dd_pct": round(float(wf["max_drawdown_pct"].min()), 2),
        "positive_window_ratio": round(float((wf["total_return_pct"] > 0).mean()), 3),
        "oos_total_return_pct": oos_summary["total_return_pct"],
        "oos_cagr_pct": oos_summary["cagr_pct"],
        "oos_max_drawdown_pct": oos_summary["max_drawdown_pct"],
        "oos_sharpe": oos_summary["sharpe"],
        "oos_sortino": oos_summary["sortino"],
        "oos_trade_count": oos_summary["trade_count"],
    }

    with open(OUTPUT_DIR / "phase10_dd_control_summary.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nPHASE 10 DD CONTROL")
    print(pd.DataFrame([result]).to_string(index=False))
    print("\nWINDOWS")
    print(wf.to_string(index=False))
    print("\nuložené:")
    print("outputs\\phase10_dd_control_windows.csv")
    print("outputs\\phase10_dd_control_oos.csv")
    print("outputs\\phase10_dd_control_summary.json")


if __name__ == "__main__":
    main()