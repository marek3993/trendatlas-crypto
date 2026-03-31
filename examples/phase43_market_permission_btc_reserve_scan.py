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
ALT_SYMBOLS = [s for s in TARGET_SYMBOLS if s != "BTCUSDT"]

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

TRADING_DAYS_PER_YEAR = 365.25
TOTAL_COST_BPS = 15.0
TRADE_COST = TOTAL_COST_BPS / 10000.0

# fixed gates
SELECT_CONF_MIN = 35.0
YZ_CAP = 0.70
ENTER_CONF_MIN = 35.0
HOLD_CONF_MIN = 30.0
ST_BULL_THRESHOLD = 35.0
LT_BULL_THRESHOLD = 35.0

# fixed winner ranking mix from phase42
BASE_RANK_WEIGHT = 1.00
XS20_WEIGHT = 0.35
XS90_WEIGHT = 0.20
XS_PERSIST_WEIGHT = 0.10
ACCEL_WEIGHT = 0.20
RET5_WEIGHT = 0.15

# scan
ENTER_SHORT_VALUES = [7, 14]
ENTER_LONG_VALUES = [21, 28]
EXIT_LONG_VALUES = [21, 35]
ALT_OPEN_VALUES = [0.55, 0.65]
ALT_CLOSE_VALUES = [0.35, 0.45]
RESERVE_MODES = ["btc", "btc_eth"]

OUT_RESULTS_CSV = OUTPUT_DIR / "phase43_market_permission_btc_reserve_scan_results.csv"
OUT_JSON = OUTPUT_DIR / "phase43_market_permission_btc_reserve_scan_best.json"


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


def select_top1_from_symbols(
    dt: pd.Timestamp,
    symbols: list[str],
    daily_tables: dict[str, pd.DataFrame],
) -> str:
    candidates = []

    for symbol in symbols:
        tbl = daily_tables[symbol]
        if dt not in tbl.index:
            continue
        row = tbl.loc[dt]

        if (
            int(row["active_long"]) == 1
            and float(row["confidence"]) >= SELECT_CONF_MIN
            and float(row["yz_vol_20"]) <= YZ_CAP
            and float(row["atr_pct"]) <= 70.0
        ):
            candidates.append((symbol, candidate_score(row)))

    if not candidates:
        return "CASH"

    candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def build_market_series(daily_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close_df = pd.concat({s: t["close"] for s, t in daily_tables.items()}, axis=1).sort_index()
    idx = close_df.index

    ew_close = close_df.mean(axis=1)
    mkt_ret_7 = ew_close.pct_change(7)
    mkt_ret_14 = ew_close.pct_change(14)
    mkt_ret_21 = ew_close.pct_change(21)
    mkt_ret_28 = ew_close.pct_change(28)
    mkt_ret_35 = ew_close.pct_change(35)

    btc_close = close_df["BTCUSDT"]
    alt_close_df = close_df[ALT_SYMBOLS]

    alt_rel_14 = alt_close_df.divide(alt_close_df.shift(14)).subtract(
        btc_close.divide(btc_close.shift(14)),
        axis=0,
    )
    alt_breadth_14 = (alt_rel_14 > 0).mean(axis=1)

    out = pd.DataFrame(index=idx)
    out["mkt_ret_7"] = mkt_ret_7
    out["mkt_ret_14"] = mkt_ret_14
    out["mkt_ret_21"] = mkt_ret_21
    out["mkt_ret_28"] = mkt_ret_28
    out["mkt_ret_35"] = mkt_ret_35
    out["alt_breadth_14"] = alt_breadth_14
    return out


def get_mkt_ret(row: pd.Series, lookback: int) -> float:
    col = f"mkt_ret_{lookback}"
    if col not in row.index:
        raise ValueError(f"Chýba market return stĺpec: {col}")
    val = row[col]
    if pd.isna(val):
        return np.nan
    return float(val)


def build_permission_selection(
    daily_tables: dict[str, pd.DataFrame],
    market_df: pd.DataFrame,
    enter_short: int,
    enter_long: int,
    exit_long: int,
    alt_open_th: float,
    alt_close_th: float,
    reserve_mode: str,
) -> pd.DataFrame:
    rows = []
    risk_on = False
    alt_gate = False

    for dt in market_df.index:
        row = market_df.loc[dt]

        enter_short_val = get_mkt_ret(row, enter_short)
        enter_long_val = get_mkt_ret(row, enter_long)
        exit_long_val = get_mkt_ret(row, exit_long)

        enter_ok = (
            pd.notna(enter_short_val)
            and pd.notna(enter_long_val)
            and enter_short_val > 0.0
            and enter_long_val > 0.0
        )
        exit_ok = pd.notna(exit_long_val) and exit_long_val < 0.0

        if not risk_on:
            if enter_ok:
                risk_on = True
        else:
            if exit_ok:
                risk_on = False
                alt_gate = False

        if risk_on:
            breadth = float(row["alt_breadth_14"]) if pd.notna(row["alt_breadth_14"]) else 0.0
            if not alt_gate and breadth >= alt_open_th:
                alt_gate = True
            elif alt_gate and breadth <= alt_close_th:
                alt_gate = False
        else:
            alt_gate = False

        if not risk_on:
            selected = "CASH"
            state = "cash"
        else:
            if alt_gate:
                selected = select_top1_from_symbols(dt, ALT_SYMBOLS, daily_tables)
                if selected == "CASH":
                    selected = "BTCUSDT"
                state = "alt_gate_open"
            else:
                if reserve_mode == "btc":
                    selected = "BTCUSDT"
                elif reserve_mode == "btc_eth":
                    selected = select_top1_from_symbols(dt, ["BTCUSDT", "ETHUSDT"], daily_tables)
                    if selected == "CASH":
                        selected = "BTCUSDT"
                else:
                    raise ValueError(reserve_mode)
                state = "reserve"

        rows.append(
            {
                "ts": dt,
                "selected": selected,
                "risk_on": int(risk_on),
                "alt_gate": int(alt_gate),
                "state": state,
                "alt_breadth_14": float(row["alt_breadth_14"]) if pd.notna(row["alt_breadth_14"]) else np.nan,
            }
        )

    return pd.DataFrame(rows).set_index("ts").sort_index()


def run_daily_model(selection: pd.DataFrame, daily_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    all_dates = sorted(selection.index)
    prev_selected = "CASH"
    prev_exposure = 0.0
    rows = []

    for dt in all_dates:
        selected = str(selection.loc[dt, "selected"])
        state = str(selection.loc[dt, "state"])

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
                "state": state,
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

    reserve_days_pct = float((paper["state"] == "reserve").mean() * 100.0)
    alt_gate_days_pct = float((paper["state"] == "alt_gate_open").mean() * 100.0)

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((paper["turnover"] > 0).sum()),
        "cash_days_pct": round(float((paper["gross_exposure"] <= 0.0).mean() * 100.0), 2),
        "reserve_days_pct": round(reserve_days_pct, 2),
        "alt_gate_days_pct": round(alt_gate_days_pct, 2),
        "missed_leader_pct_of_in_market": round(100.0 * missed / max(in_market, 1), 2),
        "pain_bar_pct_of_in_market": round(100.0 * pain / max(in_market, 1), 2),
        "sum_leader_gap_ret": round(float(paper["leader_gap_ret"].clip(lower=0.0).sum()), 4),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("načítavam daily dáta...", flush=True)
    assets = {s: load_ohlcv_csv(DAILY_DIR / f"{s}_1d.csv") for s in TARGET_SYMBOLS}

    print("načítavam macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    print("počítam daily tables...", flush=True)
    daily_tables = build_daily_tables(assets, macro)

    print("počítam market series...", flush=True)
    market_df = build_market_series(daily_tables)

    rows = []
    for enter_short, enter_long, exit_long, alt_open_th, alt_close_th, reserve_mode in product(
        ENTER_SHORT_VALUES,
        ENTER_LONG_VALUES,
        EXIT_LONG_VALUES,
        ALT_OPEN_VALUES,
        ALT_CLOSE_VALUES,
        RESERVE_MODES,
    ):
        if alt_close_th >= alt_open_th:
            continue

        variant = (
            f"es{enter_short}"
            f"_el{enter_long}"
            f"_xl{exit_long}"
            f"_ao{int(alt_open_th*100)}"
            f"_ac{int(alt_close_th*100)}"
            f"_{reserve_mode}"
        )
        print(f"testujem {variant} ...", flush=True)

        selection = build_permission_selection(
            daily_tables=daily_tables,
            market_df=market_df,
            enter_short=enter_short,
            enter_long=enter_long,
            exit_long=exit_long,
            alt_open_th=alt_open_th,
            alt_close_th=alt_close_th,
            reserve_mode=reserve_mode,
        )
        selection.to_csv(OUTPUT_DIR / f"phase43_{variant}_selection.csv")

        paper = run_daily_model(selection, daily_tables)
        paper.to_csv(OUTPUT_DIR / f"phase43_{variant}_paper.csv")

        s = compute_summary(paper)

        score = (
            12.0 * s["sharpe"]
            + 0.20 * s["cagr_pct"]
            - 0.60 * abs(s["max_drawdown_pct"])
            - 0.03 * s["cash_days_pct"]
            - 0.04 * s["missed_leader_pct_of_in_market"]
            - 0.03 * s["pain_bar_pct_of_in_market"]
            - 0.50 * s["sum_leader_gap_ret"]
        )

        rows.append(
            {
                "variant": variant,
                "enter_short": enter_short,
                "enter_long": enter_long,
                "exit_long": exit_long,
                "alt_open_th": alt_open_th,
                "alt_close_th": alt_close_th,
                "reserve_mode": reserve_mode,
                "score": round(score, 3),
                **s,
            }
        )

    out = pd.DataFrame(rows).sort_values(
        ["score", "sharpe", "cagr_pct"],
        ascending=False,
    ).reset_index(drop=True)

    out.to_csv(OUT_RESULTS_CSV, index=False)

    best = out.iloc[0].to_dict()
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\n=== PHASE 43 MARKET PERMISSION + BTC RESERVE SCAN ===")
    print(out.to_string(index=False))
    print("\nuložené:")
    print(OUT_RESULTS_CSV)
    print(OUT_JSON)


if __name__ == "__main__":
    main()