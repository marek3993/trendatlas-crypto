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


def build_asset_signal_table(
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

        rank_score = 0.55 * lt_score + 0.30 * st_score + 0.15 * confidence

        ret_next = float(close_ret_next.loc[idx]) if idx in close_ret_next.index and pd.notna(close_ret_next.loc[idx]) else np.nan

        rows.append(
            {
                "ts": idx,
                "symbol": symbol,
                "active_long": position,
                "rank_score": rank_score,
                "ret_next": ret_next,
                "st_score": st_score,
                "lt_score": lt_score,
                "mr_score": mr_score,
                "confidence": confidence,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["active_long", "rank_score", "ret_next", "st_score", "lt_score", "mr_score", "confidence"]).rename_axis("ts")
    return out.set_index("ts")


def run_topn_portfolio(asset_tables: dict[str, pd.DataFrame], top_n: int, fee_bps: float = 5.0, slippage_bps: float = 5.0) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(tbl.index) for tbl in asset_tables.values()]))
    symbols = sorted(asset_tables.keys())
    trade_cost = (fee_bps + slippage_bps) / 10000.0

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
            candidates.append((symbol, float(row["rank_score"]), float(row["ret_next"])))

        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[:top_n]

        target_weights = {s: 0.0 for s in symbols}
        if selected:
            w = 1.0 / len(selected)
            for symbol, _, _ in selected:
                target_weights[symbol] = w

        raw_ret = 0.0
        held_symbols = []
        for symbol, rank_score, ret_next in selected:
            raw_ret += target_weights[symbol] * ret_next
            held_symbols.append(symbol)

        turnover = sum(abs(target_weights[s] - prev_weights[s]) for s in symbols)
        cost = turnover * trade_cost
        strategy_ret = raw_ret - cost

        rows.append(
            {
                "ts": dt,
                "n_selected": len(selected),
                "selected": ",".join(held_symbols),
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["n_selected", "selected", "raw_strategy_ret", "turnover", "cost", "strategy_ret", "equity"]).rename_axis("ts")

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
            "avg_selected": 0.0,
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
            "avg_selected": float(paper["n_selected"].mean()) if "n_selected" in paper.columns else 0.0,
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
    avg_selected = float(paper["n_selected"].mean())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": trade_count,
        "avg_selected": round(avg_selected, 2),
    }


def split_folds(paper: pd.DataFrame, n_folds: int = 3) -> list[pd.DataFrame]:
    if paper.empty or len(paper) < 180:
        return [paper]

    edges = np.linspace(0, len(paper), n_folds + 1, dtype=int)
    folds = []
    for i in range(n_folds):
        part = paper.iloc[edges[i]:edges[i + 1]].copy()
        if len(part) > 20:
            folds.append(part)
    return folds


def robust_score(fold_df: pd.DataFrame) -> float:
    if fold_df.empty:
        return -9999.0

    median_sharpe = float(fold_df["sharpe"].median())
    median_sortino = float(fold_df["sortino"].median())
    median_cagr = float(fold_df["cagr_pct"].median())
    median_return = float(fold_df["total_return_pct"].median())
    worst_dd = float(fold_df["max_drawdown_pct"].min())
    positive_ratio = float((fold_df["total_return_pct"] > 0).mean())
    median_trades = float(fold_df["trade_count"].median())

    score = (
        12.0 * median_sharpe
        + 8.0 * median_sortino
        + 0.30 * median_cagr
        + 0.10 * median_return
        - 0.35 * abs(worst_dd)
        + 12.0 * positive_ratio
        - max(0.0, 8.0 - median_trades) * 0.75
    )
    return round(score, 3)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    macro = load_macro_csv(MACRO_PATH)
    files = sorted(DATA_DIR.glob("*_1d.csv"))
    assets = {path.stem.replace("_1d", ""): load_ohlcv_csv(path) for path in files}

    params = StrategyParams(
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

    asset_tables = {}
    for symbol, ohlcv in assets.items():
        print(f"počítam signály {symbol}...", flush=True)
        asset_tables[symbol] = build_asset_signal_table(symbol, ohlcv, macro, params)

    rows = []

    for top_n in [1, 2, 3]:
        print(f"počítam top_{top_n}...", flush=True)
        paper = run_topn_portfolio(asset_tables, top_n=top_n, fee_bps=5.0, slippage_bps=5.0)
        full = compute_summary(paper)

        fold_rows = []
        for fold_i, fold in enumerate(split_folds(paper, 3), start=1):
            s = compute_summary(fold)
            s["fold"] = fold_i
            fold_rows.append(s)

        fold_df = pd.DataFrame(fold_rows)

        rows.append(
            {
                "top_n": top_n,
                "robust_score": robust_score(fold_df),
                "median_fold_sharpe": round(float(fold_df["sharpe"].median()), 3),
                "median_fold_sortino": round(float(fold_df["sortino"].median()), 3),
                "median_fold_cagr_pct": round(float(fold_df["cagr_pct"].median()), 2),
                "median_fold_return_pct": round(float(fold_df["total_return_pct"].median()), 2),
                "worst_fold_dd_pct": round(float(fold_df["max_drawdown_pct"].min()), 2),
                "positive_fold_ratio": round(float((fold_df["total_return_pct"] > 0).mean()), 3),
                "full_total_return_pct": full["total_return_pct"],
                "full_cagr_pct": full["cagr_pct"],
                "full_max_drawdown_pct": full["max_drawdown_pct"],
                "full_sharpe": full["sharpe"],
                "full_sortino": full["sortino"],
                "full_trade_count": full["trade_count"],
                "avg_selected": full["avg_selected"],
            }
        )

        paper.to_csv(OUTPUT_DIR / f"phase4_top{top_n}_paper.csv")

    out = pd.DataFrame(rows).sort_values("robust_score", ascending=False).reset_index(drop=True)
    out.to_csv(OUTPUT_DIR / "phase4_topn_selection.csv", index=False)

    best = out.iloc[0].to_dict()
    with open(OUTPUT_DIR / "best_topn_selection.json", "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\nPHASE 4 TOP-N SELECTION")
    print(out.to_string(index=False))
    print("\nuložené:")
    print("outputs\\phase4_topn_selection.csv")
    print("outputs\\best_topn_selection.json")
    print("outputs\\phase4_top1_paper.csv")
    print("outputs\\phase4_top2_paper.csv")
    print("outputs\\phase4_top3_paper.csv")


if __name__ == "__main__":
    main()