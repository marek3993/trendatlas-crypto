from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.scoring import compute_score_frame

# =========================================================
# PATHS
# =========================================================
OUTPUTS = ROOT / "outputs"
OUT_DIR = OUTPUTS / "leverage_phase_l1_l2"
DATA_DIR = ROOT / "data" / "ohlcv"
MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"
BTC_FILE = DATA_DIR / "BTCUSDT_1d.csv"

BASELINE_PATH_CANDIDATES = [
    OUTPUTS / "phase39_old_baseline_daily.csv",
    OUTPUTS / "phase36_old_baseline_daily.csv",
]

OUT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
# CONFIG
# =========================================================
ALL_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
    "TRXUSDT",
    "DOTUSDT",
]

UNIVERSE_VARIANTS = {
    "phase45_without_BNBUSDT": [s for s in ALL_SYMBOLS if s != "BNBUSDT"],
    "phase45_without_BNBUSDT_and_DOGEUSDT": [s for s in ALL_SYMBOLS if s not in {"BNBUSDT", "DOGEUSDT"}],
}

ST_COLS = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
LT_COLS = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
MR_COLS = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

TRADING_DAYS_PER_YEAR = 365.25
TOTAL_COST_BPS = 15.0
TRADE_COST = TOTAL_COST_BPS / 10000.0

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

FIXED_LADDER = [1.00, 1.25, 1.50, 1.75, 2.00]

VOL_TARGET_ANNUAL = 0.90
VOL_LMIN = 1.00
VOL_LMAX = 1.50

SLOW_HALFLIFE = 60
FAST_HALFLIFE = 20
MAX_DAILY_LEV_INCREASE = 0.10

# conservative flat financing placeholder
ANNUAL_FINANCING_RATE = 0.00


# =========================================================
# LOADERS
# =========================================================
def normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(
        columns={
            "Date": "date",
            "Timestamp": "timestamp",
            "Datetime": "datetime",
            "Time": "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Open time": "open_time",
            "Open Time": "open_time",
        }
    )


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df = normalize_ohlcv_columns(df)

    date_col = next((c for c in ["timestamp", "date", "datetime", "time", "open_time"] if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path} nema datumovy stlpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    for c in ["open", "high", "low", "close", "volume"]:
        if c not in df.columns:
            raise ValueError(f"{path} nema stlpec {c}")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()


def load_macro_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalize_ohlcv_columns(df)

    if "date" not in df.columns:
        raise ValueError(f"{path} nema date stlpec")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.set_index("date").sort_index()

    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{path} nema makro stlpce: {missing}")

    return df[cols].apply(pd.to_numeric, errors="coerce").dropna()


def load_existing_baseline() -> pd.DataFrame | None:
    chosen = None
    for path in BASELINE_PATH_CANDIDATES:
        if path.exists():
            chosen = path
            break

    if chosen is None:
        return None

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
        raise ValueError(f"{chosen} nema casovy stlpec")

    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).copy().sort_values(ts_col)
    df = df.rename(columns={ts_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    df = df.set_index("ts")

    for col in ["strategy_ret", "turnover", "cost", "selected_ret_next", "best_available_next", "gross_exposure"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["strategy_ret"] = df.get("strategy_ret", 0.0)
    df["turnover"] = df.get("turnover", 0.0)
    df["cost"] = df.get("cost", 0.0)
    df["gross_exposure"] = df.get("gross_exposure", np.where(df.get("selected", "CASH") != "CASH", 1.0, 0.0))
    df["selected"] = df.get("selected", "CASH")
    df["selected_ret_next"] = df.get("selected_ret_next", 0.0)
    df["best_available_next"] = df.get("best_available_next", 0.0)

    df["equity"] = (1.0 + pd.to_numeric(df["strategy_ret"], errors="coerce").fillna(0.0)).cumprod()
    df["in_market"] = (pd.to_numeric(df["gross_exposure"], errors="coerce").fillna(0.0) > 0.0).astype(int)
    df["leader_gap_ret"] = np.where(df["in_market"] == 1, df["best_available_next"] - df["selected_ret_next"], 0.0)
    df["missed_leader_bar"] = (df["in_market"] == 1) & (df["leader_gap_ret"] > 0.0)
    df["pain_bar"] = (df["in_market"] == 1) & (df["leader_gap_ret"] > 0.02)
    df["model_key"] = "old_baseline"
    return df


# =========================================================
# BASE MODEL BUILD
# =========================================================
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
    out: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        print(f"build_daily_tables: {symbol}", flush=True)
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
                    "ts": pd.Timestamp(idx).normalize(),
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

        out[symbol] = pd.DataFrame(rows).drop_duplicates(subset=["ts"]).set_index("ts").sort_index()

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


def run_daily_model(selection: pd.DataFrame, daily_tables: dict[str, pd.DataFrame], model_key: str) -> pd.DataFrame:
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
    out["model_key"] = model_key
    return out


def build_base_models() -> Dict[str, pd.DataFrame]:
    print("Loading OHLCV...", flush=True)
    all_assets = {s: load_ohlcv_csv(DATA_DIR / f"{s}_1d.csv") for s in ALL_SYMBOLS}

    print("Loading macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    models: Dict[str, pd.DataFrame] = {}

    baseline = load_existing_baseline()
    if baseline is not None:
        models["old_baseline"] = baseline

    for model_key, symbols in UNIVERSE_VARIANTS.items():
        print(f"Building base model: {model_key}", flush=True)
        daily_tables = build_daily_tables(all_assets, macro, symbols)
        selection = select_daily_top1(daily_tables)
        paper = run_daily_model(selection, daily_tables, model_key=model_key)
        models[model_key] = paper

    return models


# =========================================================
# LEVERAGE OVERLAYS
# =========================================================
def ewma_ann_vol(series: pd.Series, halflife: int) -> pd.Series:
    daily_vol = series.ewm(halflife=halflife, adjust=False, min_periods=max(10, halflife // 2)).std(bias=False)
    ann_vol = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)
    return ann_vol


def apply_fixed_leverage(base_df: pd.DataFrame, lev: float, label: str) -> pd.DataFrame:
    df = base_df.copy()
    base_ret = pd.to_numeric(df["selected_ret_next"], errors="coerce").fillna(0.0)
    in_market = (pd.to_numeric(df["gross_exposure"], errors="coerce").fillna(0.0) > 0).astype(float)

    leverage = pd.Series(np.where(in_market > 0, lev, 0.0), index=df.index, dtype=float)

    notional_exposure = leverage
    turnover = (notional_exposure - notional_exposure.shift(1).fillna(0.0)).abs()

    financing_daily = ANNUAL_FINANCING_RATE / TRADING_DAYS_PER_YEAR
    financing_cost = leverage * financing_daily

    raw_ret = leverage * base_ret
    trading_cost = turnover * TRADE_COST
    strategy_ret = raw_ret - trading_cost - financing_cost

    df["overlay_name"] = label
    df["base_strategy_ret"] = pd.to_numeric(df["strategy_ret"], errors="coerce").fillna(0.0)
    df["leverage"] = leverage
    df["notional_exposure"] = notional_exposure
    df["turnover_lev"] = turnover
    df["financing_cost"] = financing_cost
    df["trading_cost_lev"] = trading_cost
    df["strategy_ret_lev"] = strategy_ret
    df["equity_lev"] = (1.0 + df["strategy_ret_lev"]).cumprod()
    return df


def apply_vol_target_slow(base_df: pd.DataFrame, label: str) -> pd.DataFrame:
    df = base_df.copy()
    base_ret = pd.to_numeric(df["selected_ret_next"], errors="coerce").fillna(0.0)
    in_market = (pd.to_numeric(df["gross_exposure"], errors="coerce").fillna(0.0) > 0).astype(float)

    realized_vol = ewma_ann_vol(base_ret, SLOW_HALFLIFE)
    leverage = (VOL_TARGET_ANNUAL / realized_vol).clip(lower=VOL_LMIN, upper=VOL_LMAX)
    leverage = leverage.where(in_market > 0, 0.0).fillna(0.0)

    notional_exposure = leverage
    turnover = (notional_exposure - notional_exposure.shift(1).fillna(0.0)).abs()

    financing_daily = ANNUAL_FINANCING_RATE / TRADING_DAYS_PER_YEAR
    financing_cost = leverage * financing_daily

    raw_ret = leverage * base_ret
    trading_cost = turnover * TRADE_COST
    strategy_ret = raw_ret - trading_cost - financing_cost

    df["overlay_name"] = label
    df["base_strategy_ret"] = pd.to_numeric(df["strategy_ret"], errors="coerce").fillna(0.0)
    df["realized_vol_slow"] = realized_vol
    df["leverage"] = leverage
    df["notional_exposure"] = notional_exposure
    df["turnover_lev"] = turnover
    df["financing_cost"] = financing_cost
    df["trading_cost_lev"] = trading_cost
    df["strategy_ret_lev"] = strategy_ret
    df["equity_lev"] = (1.0 + df["strategy_ret_lev"]).cumprod()
    return df


def apply_vol_target_fastslow(base_df: pd.DataFrame, label: str) -> pd.DataFrame:
    df = base_df.copy()
    base_ret = pd.to_numeric(df["selected_ret_next"], errors="coerce").fillna(0.0)
    in_market = (pd.to_numeric(df["gross_exposure"], errors="coerce").fillna(0.0) > 0).astype(float)

    vol_fast = ewma_ann_vol(base_ret, FAST_HALFLIFE)
    vol_slow = ewma_ann_vol(base_ret, SLOW_HALFLIFE)
    vol_used = pd.concat([vol_fast.rename("fast"), vol_slow.rename("slow")], axis=1).max(axis=1)

    raw_leverage = (VOL_TARGET_ANNUAL / vol_used).clip(lower=VOL_LMIN, upper=VOL_LMAX)
    raw_leverage = raw_leverage.where(in_market > 0, 0.0).fillna(0.0)

    leverage_vals = []
    prev = 0.0
    for idx, target in raw_leverage.items():
        target = float(target)
        if target <= 0.0:
            lev = 0.0
        else:
            max_up = prev * (1.0 + MAX_DAILY_LEV_INCREASE)
            if prev <= 0.0:
                lev = min(target, VOL_LMIN)
            else:
                lev = min(target, max_up)
        leverage_vals.append(lev)
        prev = lev

    leverage = pd.Series(leverage_vals, index=raw_leverage.index, dtype=float)
    leverage = leverage.where(in_market > 0, 0.0).fillna(0.0)

    notional_exposure = leverage
    turnover = (notional_exposure - notional_exposure.shift(1).fillna(0.0)).abs()

    financing_daily = ANNUAL_FINANCING_RATE / TRADING_DAYS_PER_YEAR
    financing_cost = leverage * financing_daily

    raw_ret = leverage * base_ret
    trading_cost = turnover * TRADE_COST
    strategy_ret = raw_ret - trading_cost - financing_cost

    df["overlay_name"] = label
    df["base_strategy_ret"] = pd.to_numeric(df["strategy_ret"], errors="coerce").fillna(0.0)
    df["realized_vol_fast"] = vol_fast
    df["realized_vol_slow"] = vol_slow
    df["realized_vol_used"] = vol_used
    df["raw_leverage_target"] = raw_leverage
    df["leverage"] = leverage
    df["notional_exposure"] = notional_exposure
    df["turnover_lev"] = turnover
    df["financing_cost"] = financing_cost
    df["trading_cost_lev"] = trading_cost
    df["strategy_ret_lev"] = strategy_ret
    df["equity_lev"] = (1.0 + df["strategy_ret_lev"]).cumprod()
    return df


# =========================================================
# METRICS
# =========================================================
def max_time_under_water_days(equity: pd.Series) -> int:
    eq = equity.dropna()
    if eq.empty:
        return 0
    peak = eq.cummax()
    underwater = eq < peak
    max_run = 0
    current = 0
    for flag in underwater:
        if flag:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return int(max_run)


def rolling_compound_min(ret: pd.Series, window: int) -> float:
    if len(ret) < window:
        return np.nan
    vals = (1.0 + ret).rolling(window).apply(np.prod, raw=True) - 1.0
    return float(vals.min())


def compute_summary(model_df: pd.DataFrame, ret_col: str, eq_col: str) -> Dict[str, float]:
    rets = pd.to_numeric(model_df[ret_col], errors="coerce").fillna(0.0)
    equity = pd.to_numeric(model_df[eq_col], errors="coerce").fillna(method="ffill")

    total_return = float(equity.iloc[-1] - 1.0)
    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std(ddof=0))
    sharpe = float((rets.mean() / (vol + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR))
    downside = rets[rets < 0].std(ddof=0)
    downside = 0.0 if pd.isna(downside) else float(downside)
    sortino = float((rets.mean() / (downside + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR))

    leverage = pd.to_numeric(model_df.get("leverage", 0.0), errors="coerce").fillna(0.0)
    lev_change = leverage.diff().abs().fillna(leverage.abs())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "worst_day_pct": round(float(rets.min()) * 100.0, 2),
        "worst_3d_pct": round(rolling_compound_min(rets, 3) * 100.0, 2),
        "worst_5d_pct": round(rolling_compound_min(rets, 5) * 100.0, 2),
        "time_under_water_days_max": int(max_time_under_water_days(equity)),
        "avg_leverage": round(float(leverage.mean()), 3),
        "max_leverage": round(float(leverage.max()), 3),
        "max_leverage_hit_pct": round(float((leverage >= (VOL_LMAX - 1e-12)).mean() * 100.0), 2),
        "leverage_change_days_pct": round(float((lev_change > 1e-9).mean() * 100.0), 2),
        "trade_count_proxy": int((pd.to_numeric(model_df.get("turnover_lev", 0.0), errors="coerce").fillna(0.0) > 0).sum()),
        "cash_days_pct": round(float((leverage <= 0.0).mean() * 100.0), 2),
    }


# =========================================================
# RUN
# =========================================================
def save_overlay_result(model_key: str, overlay_key: str, df: pd.DataFrame) -> None:
    out_path = OUT_DIR / f"{model_key}__{overlay_key}.csv"
    df.to_csv(out_path)


def run() -> None:
    print("=== BUILD BASE MODELS ===", flush=True)
    base_models = build_base_models()

    active_models = [
        "phase45_without_BNBUSDT",
        "phase45_without_BNBUSDT_and_DOGEUSDT",
    ]

    summary_rows = []

    for model_key in active_models:
        print(f"\n=== LEVERAGE RESEARCH FOR {model_key} ===", flush=True)
        base_df = base_models[model_key].copy()

        # L1 fixed ladder
        for lev in FIXED_LADDER:
            overlay_key = f"fixed_{lev:.2f}x".replace(".", "p")
            print(f"Running {overlay_key}", flush=True)
            out = apply_fixed_leverage(base_df, lev=lev, label=overlay_key)
            save_overlay_result(model_key, overlay_key, out)
            s = compute_summary(out, ret_col="strategy_ret_lev", eq_col="equity_lev")
            summary_rows.append({"model_key": model_key, "overlay": overlay_key, "phase": "L1", **s})

        # L2 slow vol target
        overlay_key = "vol_target_slow_lmax_1p50"
        print(f"Running {overlay_key}", flush=True)
        out = apply_vol_target_slow(base_df, label=overlay_key)
        save_overlay_result(model_key, overlay_key, out)
        s = compute_summary(out, ret_col="strategy_ret_lev", eq_col="equity_lev")
        summary_rows.append({"model_key": model_key, "overlay": overlay_key, "phase": "L2", **s})

        # L2 fast/slow max + speed limit
        overlay_key = "vol_target_fastslow_lmax_1p50_speed_10pct"
        print(f"Running {overlay_key}", flush=True)
        out = apply_vol_target_fastslow(base_df, label=overlay_key)
        save_overlay_result(model_key, overlay_key, out)
        s = compute_summary(out, ret_col="strategy_ret_lev", eq_col="equity_lev")
        summary_rows.append({"model_key": model_key, "overlay": overlay_key, "phase": "L2", **s})

    summary_df = pd.DataFrame(summary_rows)

    phase_order = {"L1": 1, "L2": 2}
    summary_df["phase_order"] = summary_df["phase"].map(phase_order)
    summary_df = summary_df.sort_values(
        ["model_key", "phase_order", "cagr_pct", "max_drawdown_pct", "sharpe"],
        ascending=[True, True, False, False, False],
    ).drop(columns=["phase_order"])

    summary_path = OUT_DIR / "leverage_phase_l1_l2_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    print("\n=== DONE ===", flush=True)
    print(summary_df.to_string(index=False), flush=True)
    print(f"\nSaved summary: {summary_path}", flush=True)
    print(f"Saved daily outputs to: {OUT_DIR}", flush=True)


if __name__ == "__main__":
    run()