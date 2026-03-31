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


def model_rank(row: pd.Series) -> float:
    score = float(row["base_rank"])
    score += 0.35 * float(row["xs_rank_20"])
    score += 0.20 * float(row["xs_rank_90"])
    score += 0.15 * float(row["xs_rank_persist"])
    return score


def run_v1_paper(
    asset_tables: dict[str, pd.DataFrame],
    total_cost_bps: float = 15.0,
    market_score_floor: float = 10.0,
    min_confidence: float = 35.0,
    max_yz_vol: float = 0.7,
    max_atr_pct: float = 70.0,
) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(tbl.index) for tbl in asset_tables.values()]))
    symbols = sorted(asset_tables.keys())
    trade_cost = total_cost_bps / 10000.0

    prev_weights = {s: 0.0 for s in symbols}
    rows = []

    for dt in all_dates:
        candidates = []
        market_scores = []

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
                    "rank_score": model_rank(row),
                    "ret_next": float(row["ret_next"]),
                }
            )

        market_score = float(np.mean(market_scores)) if market_scores else 0.0

        target_weights = {s: 0.0 for s in symbols}
        selected = []
        selected_symbol = "CASH"

        if market_score >= market_score_floor and candidates:
            candidates = sorted(candidates, key=lambda x: x["rank_score"], reverse=True)
            selected = candidates[:1]
            selected_symbol = selected[0]["symbol"]
            target_weights[selected_symbol] = 1.0

        raw_ret = 0.0
        gross_exposure = 0.0
        for symbol in symbols:
            if target_weights[symbol] > 0:
                ret_next = next(x["ret_next"] for x in selected if x["symbol"] == symbol)
                raw_ret += target_weights[symbol] * ret_next
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
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=["selected", "n_selected", "gross_exposure", "raw_strategy_ret", "turnover", "cost", "strategy_ret", "equity"]
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
            "avg_exposure": 0.0,
        }

    rets = paper["strategy_ret"].fillna(0.0)
    equity = (1.0 + rets).cumprod()

    total_return = float(equity.iloc[-1] - 1.0)
    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / 365.25
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std())
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(365.25))

    downside = rets[rets < 0].std()
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(365.25))

    trade_count = int((paper["turnover"] > 0).sum())
    avg_exposure = float(paper["gross_exposure"].mean())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": trade_count,
        "avg_exposure": round(avg_exposure, 3),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    macro = load_macro_csv(MACRO_PATH)
    missing = [s for s in TARGET_SYMBOLS if not (DATA_DIR / f"{s}_1d.csv").exists()]
    if missing:
        raise RuntimeError(f"Chýbajú CSV: {missing}")

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

    rs_tables = enrich_rs(base_tables)

    paper = run_v1_paper(
        rs_tables,
        total_cost_bps=15.0,
        market_score_floor=10.0,
        min_confidence=35.0,
        max_yz_vol=0.7,
        max_atr_pct=70.0,
    )

    summary = compute_summary(paper)

    paper.to_csv(OUTPUT_DIR / "v1_paper.csv")

    with open(OUTPUT_DIR / "v1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nV1 PAPER SUMMARY")
    for k, v in summary.items():
        print(f"{k}: {v}")

    print("\nuložené:")
    print("outputs\\v1_paper.csv")
    print("outputs\\v1_summary.json")


if __name__ == "__main__":
    main()