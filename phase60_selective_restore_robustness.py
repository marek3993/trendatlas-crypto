from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.scoring import compute_score_frame

OUTPUTS = ROOT / "outputs"
OUT_DIR = OUTPUTS / "phase60_selective_restore_robustness"
DATA_DIR = ROOT / "data" / "ohlcv"
MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"

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

SINCE_2021 = pd.Timestamp("2021-01-01")
SINCE_2023 = pd.Timestamp("2023-01-01")
SINCE_2025 = pd.Timestamp("2025-01-01")
PINNED_PHASE60_DEPENDENCY_MODEL_KEY = "phase60_restore_trx_sol_base"
PINNED_PHASE60_DEPENDENCY_PAPER_PATH = OUT_DIR / f"{PINNED_PHASE60_DEPENDENCY_MODEL_KEY}_paper.csv"

MODEL_CONFIGS = {
    "phase60_phase42_core": None,
    "phase60_restore_trx_only_base": {
        "targets": {"TRXUSDT"},
        "lt_min": 55.0,
        "st_min": 40.0,
        "xs20_min": 30.0,
    },
    "phase60_restore_sol_only_base": {
        "targets": {"SOLUSDT"},
        "lt_min": 55.0,
        "st_min": 40.0,
        "xs20_min": 30.0,
    },
    "phase60_restore_trx_sol_base": {
        "targets": {"TRXUSDT", "SOLUSDT"},
        "lt_min": 55.0,
        "st_min": 40.0,
        "xs20_min": 30.0,
    },
    "phase60_restore_trx_sol_loose": {
        "targets": {"TRXUSDT", "SOLUSDT"},
        "lt_min": 50.0,
        "st_min": 35.0,
        "xs20_min": 25.0,
    },
    "phase60_restore_trx_sol_strict": {
        "targets": {"TRXUSDT", "SOLUSDT"},
        "lt_min": 60.0,
        "st_min": 45.0,
        "xs20_min": 35.0,
    },
}

MODEL_LABELS = {
    "phase60_phase42_core": "Phase42 core",
    "phase60_restore_trx_only_base": "Restore TRX only - base",
    "phase60_restore_sol_only_base": "Restore SOL only - base",
    "phase60_restore_trx_sol_base": "Restore TRX/SOL - base",
    "phase60_restore_trx_sol_loose": "Restore TRX/SOL - loose",
    "phase60_restore_trx_sol_strict": "Restore TRX/SOL - strict",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "PHASE60 selective restore robustness. Use --dependency-only for the targeted fast "
            "dependency refresh that materializes the pinned Phase60 paper consumed by Phase63; "
            "omitting it runs the full research grid."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--dependency-only",
        action="store_true",
        help=(
            "Targeted fast dependency refresh for the Phase63/Phase66G chain. "
            "Materializes only the pinned Phase60 paper plus support summary/equity outputs, "
            "not the full research grid."
        ),
    )
    parser.add_argument(
        "--model-key",
        type=str,
        default="",
        help=(
            "Explicit phase60_* model key for targeted fast dependency refresh. "
            f"Default with --dependency-only: {PINNED_PHASE60_DEPENDENCY_MODEL_KEY}"
        ),
    )
    parser.add_argument(
        "--only-model",
        type=str,
        default="",
        help=(
            "Legacy targeted model selector. Kept for pipeline compatibility; "
            "use --dependency-only/--model-key for the explicit fast dependency path."
        ),
    )
    return parser


def parse_args() -> argparse.Namespace:
    return build_arg_parser().parse_args()


def validate_model_key(model_key: str) -> str:
    key = str(model_key or "").strip()
    if key not in MODEL_CONFIGS:
        raise ValueError(f"Requested model not found in phase60 configs: {model_key}")
    return key


def resolve_requested_models(args: argparse.Namespace) -> tuple[list[str], str, bool]:
    if bool(getattr(args, "dependency_only", False)):
        model_key = str(args.model_key or PINNED_PHASE60_DEPENDENCY_MODEL_KEY).strip()
        return [validate_model_key(model_key)], "dependency_only_fast_refresh", True

    explicit_model_key = str(getattr(args, "model_key", "") or "").strip()
    if explicit_model_key:
        return [validate_model_key(explicit_model_key)], "targeted_fast_refresh", True

    only_model = str(getattr(args, "only_model", "") or "").strip()
    if only_model:
        return [validate_model_key(only_model)], "legacy_only_model_fast_refresh", True

    return list(MODEL_CONFIGS.keys()), "full_research_grid", False


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


def row_conf(row: pd.Series, cols: list[str]) -> float:
    vals = row[cols].astype(float)
    row_mean = float(vals.mean())
    mad = float((vals - row_mean).abs().mean())
    conf = 100.0 * (1.0 - (mad / 80.0))
    return max(0.0, min(100.0, conf))


def block_confidence(score_df: pd.DataFrame, cols: list[str]) -> pd.Series:
    row_mean = score_df[cols].mean(axis=1)
    mad = score_df[cols].sub(row_mean, axis=0).abs().mean(axis=1)
    conf = 100.0 * (1.0 - (mad / 80.0))
    return conf.clip(0.0, 100.0)


def bull(score: float, threshold: float) -> bool:
    return score >= threshold


def bear(score: float, threshold: float) -> bool:
    return score <= -threshold


def build_daily_tables(assets: dict[str, pd.DataFrame], macro_df: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        print(f"build_daily_tables: {symbol}", flush=True)
        ohlcv = assets[symbol]
        features = compute_feature_frame(ohlcv, macro_df=macro_df)
        scores = compute_score_frame(features)
        st_score = scores[ST_COLS].mean(axis=1).to_numpy(dtype=float)
        lt_score = scores[LT_COLS].mean(axis=1).to_numpy(dtype=float)
        mr_score = scores[MR_COLS].mean(axis=1).to_numpy(dtype=float)
        st_conf = block_confidence(scores, ST_COLS).to_numpy(dtype=float)
        lt_conf = block_confidence(scores, LT_COLS).to_numpy(dtype=float)
        confidence = np.minimum(st_conf, lt_conf)

        yz_vals = (
            pd.to_numeric(features["yz_vol_20"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            if "yz_vol_20" in features.columns
            else np.zeros(len(features), dtype=float)
        )
        atr_vals = (
            pd.to_numeric(features["atr_pct"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            if "atr_pct" in features.columns
            else np.zeros(len(features), dtype=float)
        )
        directional_bias = (0.45 * lt_score) + (0.35 * st_score) + (0.20 * mr_score)
        general_score = (0.6 * lt_score) + (0.4 * st_score)
        is_chaos = yz_vals > 0.9

        enter_long = (
            (st_score >= ST_BULL_THRESHOLD)
            & (lt_score >= LT_BULL_THRESHOLD)
            & (confidence >= ENTER_CONF_MIN)
            & (~is_chaos)
            & (mr_score >= -90.0)
        )
        hold_long = (
            (lt_score > -LT_BULL_THRESHOLD)
            & (confidence >= HOLD_CONF_MIN)
            & (directional_bias > 0.0)
            & (~is_chaos)
        )

        close_arr = pd.to_numeric(ohlcv["close"].reindex(features.index), errors="coerce").to_numpy(dtype=float)
        normalized_index = features.index.normalize()
        start_idx = 260
        end_idx = len(features) - 1
        position = 0
        active_long: list[int] = []

        for i in range(start_idx, end_idx):
            if position == 0:
                if enter_long[i]:
                    position = 1
            elif position == 1:
                if not hold_long[i]:
                    position = 0
            active_long.append(position)

        active_long_arr = np.asarray(active_long, dtype=int)
        row_slice = slice(start_idx, end_idx)
        next_slice = slice(start_idx + 1, end_idx + 1)
        ret_next = (close_arr[next_slice] / close_arr[row_slice]) - 1.0
        tbl = pd.DataFrame(
            {
                "ts": normalized_index[next_slice],
                "signal_ts": normalized_index[row_slice],
                "close": close_arr[row_slice],
                "active_long": active_long_arr,
                "confidence": confidence[row_slice],
                "yz_vol_20": yz_vals[row_slice],
                "atr_pct": atr_vals[row_slice],
                "general_score": general_score[row_slice],
                "base_rank": (0.55 * lt_score[row_slice]) + (0.30 * st_score[row_slice]) + (0.15 * confidence[row_slice]),
                "ret_next_1d": ret_next,
                "st_score": st_score[row_slice],
                "lt_score": lt_score[row_slice],
            }
        )

        out[symbol] = tbl.drop_duplicates(subset=["ts"]).set_index("ts").sort_index()

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


def candidate_ok(row: pd.Series) -> bool:
    return (
        int(row["active_long"]) == 1
        and float(row["confidence"]) >= SELECT_CONF_MIN
        and float(row["yz_vol_20"]) <= YZ_CAP
        and float(row["atr_pct"]) <= 70.0
    )


def bnb_rule_passes(bnb_candidate: dict, cfg: dict) -> bool:
    return (
        bnb_candidate["lt_score"] >= cfg["lt_min"]
        and bnb_candidate["st_score"] >= cfg["st_min"]
        and bnb_candidate["xs20"] >= cfg["xs20_min"]
    )


def select_daily_top1_variant(asset_tables: dict[str, pd.DataFrame], model_key: str) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(t.index) for t in asset_tables.values()]))
    rows = []
    cfg = MODEL_CONFIGS[model_key]

    for dt in all_dates:
        candidates = []
        market_scores = []

        for symbol, tbl in asset_tables.items():
            if dt not in tbl.index:
                continue

            row = tbl.loc[dt]
            market_scores.append(float(row["general_score"]))

            if candidate_ok(row):
                candidates.append(
                    {
                        "symbol": symbol,
                        "score": candidate_score(row),
                        "st_score": float(row["st_score"]),
                        "lt_score": float(row["lt_score"]),
                        "xs20": float(row["xs20"]),
                    }
                )

        market_score = float(np.mean(market_scores)) if market_scores else 0.0
        selected = "CASH"

        if market_score >= MARKET_THRESHOLD and candidates:
            candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
            top = candidates[0]

            if cfg is None:
                selected = top["symbol"]
            else:
                if top["symbol"] == "BNBUSDT":
                    if bnb_rule_passes(top, cfg):
                        selected = "BNBUSDT"
                    else:
                        next_non_bnb = next((c for c in candidates if c["symbol"] != "BNBUSDT"), None)
                        if next_non_bnb is not None and next_non_bnb["symbol"] in cfg["targets"]:
                            selected = "BNBUSDT"
                        else:
                            selected = next_non_bnb["symbol"] if next_non_bnb is not None else "CASH"
                else:
                    selected = top["symbol"]

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


def compute_summary(model_df: pd.DataFrame) -> dict:
    rets = pd.to_numeric(model_df["strategy_ret"], errors="coerce").fillna(0.0)
    equity = (1.0 + rets).cumprod()

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

    in_market = int((model_df["gross_exposure"] > 0.0).sum())
    missed = int(model_df.get("missed_leader_bar", pd.Series(index=model_df.index, data=False)).sum())
    pain = int(model_df.get("pain_bar", pd.Series(index=model_df.index, data=False)).sum())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((pd.to_numeric(model_df["turnover"], errors="coerce").fillna(0.0) > 0).sum()),
        "cash_days_pct": round(float((pd.to_numeric(model_df["gross_exposure"], errors="coerce").fillna(0.0) <= 0.0).mean() * 100.0), 2),
        "missed_leader_pct_of_in_market": round(100.0 * missed / max(in_market, 1), 2),
        "pain_bar_pct_of_in_market": round(100.0 * pain / max(in_market, 1), 2),
        "sum_leader_gap_ret": round(float(pd.to_numeric(model_df.get("leader_gap_ret", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0).sum()), 4),
    }


def compute_window_summary(model_df: pd.DataFrame, start_dt: pd.Timestamp, prefix: str) -> dict:
    sub = model_df.loc[model_df.index >= start_dt].copy()
    if sub.empty:
        return {
            f"{prefix}_total_return_pct": np.nan,
            f"{prefix}_cagr_pct": np.nan,
            f"{prefix}_max_drawdown_pct": np.nan,
            f"{prefix}_trade_count": np.nan,
            f"{prefix}_cash_days_pct": np.nan,
        }

    s = compute_summary(sub)
    return {
        f"{prefix}_total_return_pct": s["total_return_pct"],
        f"{prefix}_cagr_pct": s["cagr_pct"],
        f"{prefix}_max_drawdown_pct": s["max_drawdown_pct"],
        f"{prefix}_trade_count": s["trade_count"],
        f"{prefix}_cash_days_pct": s["cash_days_pct"],
    }


def main() -> None:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    model_keys, run_mode, targeted_fast_path = resolve_requested_models(args)

    print("[PHASE60] Start", flush=True)
    print(f"[PHASE60] Models: {len(model_keys)}", flush=True)
    print(f"[PHASE60] Run mode: {run_mode}", flush=True)

    print("Loading OHLCV...", flush=True)
    all_assets = {s: load_ohlcv_csv(DATA_DIR / f"{s}_1d.csv") for s in ALL_SYMBOLS}

    print("Loading macro...", flush=True)
    macro = load_macro_csv(MACRO_PATH)

    print("Building daily tables full universe...", flush=True)
    daily_full = build_daily_tables(all_assets, macro, ALL_SYMBOLS)

    model_runs: Dict[str, pd.DataFrame] = {}
    for model_key in model_keys:
        print(f"Running {model_key}...", flush=True)
        selection = select_daily_top1_variant(daily_full, model_key)
        paper = run_daily_model(selection, daily_full, model_key=model_key)
        model_runs[model_key] = paper
        paper.to_csv(OUT_DIR / f"{model_key}_paper.csv")

    summary_rows = []
    for model_key, df in model_runs.items():
        row = {
            "model": model_key,
            "label": MODEL_LABELS[model_key],
            **compute_summary(df),
            **compute_window_summary(df, SINCE_2021, "since2021"),
            **compute_window_summary(df, SINCE_2023, "since2023"),
            **compute_window_summary(df, SINCE_2025, "since2025"),
        }
        cfg = MODEL_CONFIGS[model_key]
        if cfg is None:
            row["targets"] = "none"
            row["lt_min"] = np.nan
            row["st_min"] = np.nan
            row["xs20_min"] = np.nan
        else:
            row["targets"] = ",".join(sorted(cfg["targets"]))
            row["lt_min"] = cfg["lt_min"]
            row["st_min"] = cfg["st_min"]
            row["xs20_min"] = cfg["xs20_min"]
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["since2025_cagr_pct", "since2023_cagr_pct", "cagr_pct"],
        ascending=[False, False, False],
    )
    summary_df.to_csv(OUT_DIR / "phase60_selective_restore_robustness_summary.csv", index=False)

    eq = pd.DataFrame(index=sorted(set().union(*[set(df.index) for df in model_runs.values()])))
    eq.index.name = "ts"
    for model_key, df in model_runs.items():
        eq[model_key] = df["equity"].reindex(eq.index).ffill()
    eq = eq.reset_index()
    eq.to_csv(OUT_DIR / "phase60_selective_restore_robustness_equity_curves.csv", index=False)

    if targeted_fast_path and PINNED_PHASE60_DEPENDENCY_MODEL_KEY in model_runs:
        pinned_paper_path = OUT_DIR / f"{PINNED_PHASE60_DEPENDENCY_MODEL_KEY}_paper.csv"
        if not pinned_paper_path.exists():
            raise RuntimeError(
                "Targeted Phase60 fast dependency refresh did not materialize the required "
                f"paper CSV for {PINNED_PHASE60_DEPENDENCY_MODEL_KEY}."
            )

    print("\n=== PHASE60 SELECTIVE RESTORE ROBUSTNESS ===\n")
    print(summary_df.to_string(index=False))
    print(f"\nSaved summary: {OUT_DIR / 'phase60_selective_restore_robustness_summary.csv'}")
    print(f"Saved equity curves: {OUT_DIR / 'phase60_selective_restore_robustness_equity_curves.csv'}")
    print(f"Saved daily papers to: {OUT_DIR}")


if __name__ == "__main__":
    main()
