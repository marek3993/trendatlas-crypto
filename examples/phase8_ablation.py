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
FUNDING_DIR = ROOT / "data" / "funding"
OUTPUT_DIR = ROOT / "outputs"

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def roll_z(s: pd.Series, window: int) -> pd.Series:
    mu = s.rolling(window).mean()
    sd = s.rolling(window).std()
    return ((s - mu) / (sd + 1e-9)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


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


def load_funding_daily(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["funding_rate"])

    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["funding_rate"] = pd.to_numeric(df["funding_rate"], errors="coerce")
    df = df.dropna(subset=["date", "funding_rate"]).copy()

    df["day"] = df["date"].dt.floor("D")
    daily = df.groupby("day", as_index=True)["funding_rate"].mean().to_frame()
    return daily


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


def build_base_table(
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
                "close", "active_long", "ret_next", "st_score", "lt_score", "mr_score",
                "confidence", "yz_vol_20", "atr_pct", "general_score", "base_rank"
            ]
        ).rename_axis("ts")
    return out.set_index("ts")


def enrich_tables(base_tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close_df = pd.concat({s: t["close"] for s, t in base_tables.items()}, axis=1).sort_index()
    st_df = pd.concat({s: t["st_score"] for s, t in base_tables.items()}, axis=1).sort_index()
    lt_df = pd.concat({s: t["lt_score"] for s, t in base_tables.items()}, axis=1).sort_index()

    ret20 = close_df.pct_change(20)
    ret90 = close_df.pct_change(90)

    btc20 = ret20["BTCUSDT"]
    btc90 = ret90["BTCUSDT"]

    rel20 = ret20.sub(btc20, axis=0).fillna(0.0)
    rel90 = ret90.sub(btc90, axis=0).fillna(0.0)

    xs20 = (rel20.rank(axis=1, pct=True) - 0.5) * 200.0
    xs90 = (rel90.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_combo = 0.6 * xs20 + 0.4 * xs90
    xs_persist = xs_combo.rolling(5).mean().fillna(0.0)

    breadth_lt = ((lt_df >= 35.0).mean(axis=1) - 0.5) * 200.0
    breadth_st = ((st_df >= 35.0).mean(axis=1) - 0.5) * 200.0
    breadth_state = 0.6 * breadth_lt + 0.4 * breadth_st
    breadth_mom_10 = breadth_state.diff(10).fillna(0.0)

    funding_tables = {}
    for symbol in base_tables.keys():
        fpath = FUNDING_DIR / f"{symbol}_funding.csv"
        f = load_funding_daily(fpath)
        if f.empty:
            funding_tables[symbol] = pd.DataFrame(
                index=base_tables[symbol].index,
                data={
                    "funding_ema3": 0.0,
                    "funding_ema7": 0.0,
                    "funding_z30": 0.0,
                    "funding_edge": 0.0,
                },
            )
            continue

        f = f.reindex(base_tables[symbol].index).ffill().fillna(0.0)
        f["funding_ema3"] = f["funding_rate"].ewm(span=3, adjust=False).mean()
        f["funding_ema7"] = f["funding_rate"].ewm(span=7, adjust=False).mean()
        f["funding_z30"] = roll_z(f["funding_rate"], 30).clip(-5, 5)

        rel20_z = roll_z(rel20[symbol], 90).reindex(f.index).fillna(0.0)

        funding_penalty = np.maximum(0.0, f["funding_z30"]) * np.maximum(0.0, -rel20_z)
        funding_bonus = np.maximum(0.0, -f["funding_z30"]) * np.maximum(0.0, rel20_z)
        funding_edge = (funding_bonus - funding_penalty) * 25.0

        funding_tables[symbol] = pd.DataFrame(
            index=f.index,
            data={
                "funding_ema3": f["funding_ema3"],
                "funding_ema7": f["funding_ema7"],
                "funding_z30": f["funding_z30"],
                "funding_edge": funding_edge,
            },
        )

    out = {}
    for symbol, tbl in base_tables.items():
        tmp = tbl.copy()
        tmp["rel_btc_20"] = (rel20[symbol] * 100.0).reindex(tmp.index).fillna(0.0)
        tmp["rel_btc_90"] = (rel90[symbol] * 100.0).reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_20"] = xs20[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_90"] = xs90[symbol].reindex(tmp.index).fillna(0.0)
        tmp["xs_rank_persist"] = xs_persist[symbol].reindex(tmp.index).fillna(0.0)
        tmp["breadth_state"] = breadth_state.reindex(tmp.index).fillna(0.0)
        tmp["breadth_mom_10"] = breadth_mom_10.reindex(tmp.index).fillna(0.0)

        f = funding_tables[symbol]
        for col in f.columns:
            tmp[col] = f[col].reindex(tmp.index).fillna(0.0)

        out[symbol] = tmp

    return out


def model_rank_and_market(row: pd.Series, model: str) -> tuple[float, float]:
    rank_score = float(row["base_rank"])
    market_score = float(row["general_score"])

    if model in {"rs", "rs_breadth", "rs_breadth_funding"}:
        rank_score += 0.35 * float(row["xs_rank_20"])
        rank_score += 0.20 * float(row["xs_rank_90"])
        rank_score += 0.15 * float(row["xs_rank_persist"])

    if model in {"rs_breadth", "rs_breadth_funding"}:
        market_score += 0.25 * float(row["breadth_state"])
        market_score += 0.05 * float(row["breadth_mom_10"])

    if model == "rs_breadth_funding":
        rank_score += float(row["funding_edge"])

    return rank_score, market_score


def run_model(asset_tables: dict[str, pd.DataFrame], model: str) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(tbl.index) for tbl in asset_tables.values()]))
    symbols = sorted(asset_tables.keys())
    trade_cost = (5.0 + 5.0) / 10000.0

    prev_weights = {s: 0.0 for s in symbols}
    rows = []

    for dt in all_dates:
        candidates = []

        for symbol, tbl in asset_tables.items():
            if dt not in tbl.index:
                continue

            row = tbl.loc[dt]
            if int(row["active_long"]) != 1:
                continue
            if pd.isna(row["ret_next"]):
                continue

            rank_score, market_score = model_rank_and_market(row, model)

            risk_on = (
                market_score >= 10.0
                and float(row["confidence"]) >= 35.0
                and float(row["yz_vol_20"]) <= 0.7
                and float(row["atr_pct"]) <= 70.0
            )

            if risk_on:
                candidates.append(
                    {
                        "symbol": symbol,
                        "rank_score": rank_score,
                        "ret_next": float(row["ret_next"]),
                    }
                )

        candidates = sorted(candidates, key=lambda x: x["rank_score"], reverse=True)
        selected = candidates[:1]

        target_weights = {s: 0.0 for s in symbols}
        if selected:
            target_weights[selected[0]["symbol"]] = 1.0

        raw_ret = 0.0
        held_symbols = []
        for symbol in symbols:
            if target_weights[symbol] > 0:
                ret_next = next(x["ret_next"] for x in selected if x["symbol"] == symbol)
                raw_ret += ret_next
                held_symbols.append(symbol)

        turnover = sum(abs(target_weights[s] - prev_weights[s]) for s in symbols)
        cost = turnover * trade_cost
        strategy_ret = raw_ret - cost

        rows.append(
            {
                "ts": dt,
                "selected": ",".join(held_symbols),
                "n_selected": len(held_symbols),
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=["selected", "n_selected", "raw_strategy_ret", "turnover", "cost", "strategy_ret", "equity"]
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


def split_windows(paper: pd.DataFrame, window_size: int = 180) -> list[pd.DataFrame]:
    if paper.empty:
        return []

    out = []
    for start in range(0, len(paper), window_size):
        part = paper.iloc[start:start + window_size].copy()
        if len(part) > 20:
            out.append(part)
    return out


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
        print(f"počítam base {symbol}...", flush=True)
        base_tables[symbol] = build_base_table(symbol, ohlcv, macro, base_params)

    asset_tables = enrich_tables(base_tables)

    models = ["base", "rs", "rs_breadth", "rs_breadth_funding"]
    rows = []

    for model in models:
        print(f"testujem {model}...", flush=True)
        paper = run_model(asset_tables, model)
        full = compute_summary(paper)

        win_rows = []
        for i, win in enumerate(split_windows(paper, 180), start=1):
            s = compute_summary(win)
            s["window"] = i
            win_rows.append(s)

        win_df = pd.DataFrame(win_rows)

        rows.append(
            {
                "model": model,
                "median_window_sharpe": round(float(win_df["sharpe"].median()), 3),
                "median_window_sortino": round(float(win_df["sortino"].median()), 3),
                "median_window_cagr_pct": round(float(win_df["cagr_pct"].median()), 2),
                "median_window_return_pct": round(float(win_df["total_return_pct"].median()), 2),
                "worst_window_dd_pct": round(float(win_df["max_drawdown_pct"].min()), 2),
                "positive_window_ratio": round(float((win_df["total_return_pct"] > 0).mean()), 3),
                "full_total_return_pct": full["total_return_pct"],
                "full_cagr_pct": full["cagr_pct"],
                "full_max_drawdown_pct": full["max_drawdown_pct"],
                "full_sharpe": full["sharpe"],
                "full_sortino": full["sortino"],
                "full_trade_count": full["trade_count"],
            }
        )

        paper.to_csv(OUTPUT_DIR / f"phase8_{model}_paper.csv")

    out = pd.DataFrame(rows).sort_values(
        ["median_window_sharpe", "full_sharpe"], ascending=False
    ).reset_index(drop=True)

    out.to_csv(OUTPUT_DIR / "phase8_ablation.csv", index=False)

    best = out.iloc[0].to_dict()
    with open(OUTPUT_DIR / "phase8_best_model.json", "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\nPHASE 8 ABLATION")
    print(out.to_string(index=False))
    print("\nuložené:")
    print("outputs\\phase8_ablation.csv")
    print("outputs\\phase8_best_model.json")
    print("outputs\\phase8_base_paper.csv")
    print("outputs\\phase8_rs_paper.csv")
    print("outputs\\phase8_rs_breadth_paper.csv")
    print("outputs\\phase8_rs_breadth_funding_paper.csv")


if __name__ == "__main__":
    main()