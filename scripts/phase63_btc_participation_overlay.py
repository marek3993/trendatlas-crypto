from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from freshness_lineage import build_producer_lineage, to_portable_path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
PHASE63_DIR = OUTPUTS / "phase63_btc_participation_overlay"

CURRENT_INTERNAL_WINNER_KEY = "phase61_restore_trx_sol_base"
CURRENT_INTERNAL_WINNER_LABEL = "Restore BNB vs TRX/SOL"
LATEST_BEST_BASELINE_KEY = "phase42 core"

EXPLICIT_BASE_PAPER_PATH = (
    OUTPUTS / "phase60_selective_restore_robustness" / "phase60_restore_trx_sol_base_paper.csv"
)


@dataclass
class VariantConfig:
    name: str
    btc_fast_ma: int
    btc_slow_ma: int
    btc_ret_lb: int
    btc_ret_min: float
    btc_risk_ma: int
    btc_risk_buffer: float
    btc_vol_lb: int
    btc_vol_cap: float
    weak_base_lb: int
    weak_base_threshold: float
    cooldown_days: int = 0


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def safe_read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported file type: {path}")


def parseable_datetime_ratio(series: pd.Series) -> float:
    s = series.copy()
    if s.empty:
        return 0.0
    s = s.astype(str).str.strip()
    s = s.replace({"": np.nan, "nan": np.nan, "NaT": np.nan, "None": np.nan})
    s = s.dropna()
    if s.empty:
        return 0.0
    sample = s.head(200)
    parsed = pd.to_datetime(sample, errors="coerce", utc=False)
    return float(parsed.notna().mean()) if len(sample) else 0.0


def detect_date_column(df: pd.DataFrame) -> str:
    preferred = [
        "date",
        "datetime",
        "timestamp",
        "time",
        "dt",
        "index",
        "ts",
        "open_time",
        "open time",
        "close_time",
        "close time",
        "Unnamed: 0",
    ]
    for col in preferred:
        if col in df.columns:
            return col

    for col in df.columns:
        lc = str(col).lower()
        if "date" in lc or "time" in lc or lc.startswith("unnamed"):
            ratio = parseable_datetime_ratio(df[col])
            if ratio >= 0.6:
                return col

    best_col = None
    best_ratio = 0.0
    for col in df.columns:
        ratio = parseable_datetime_ratio(df[col])
        if ratio > best_ratio:
            best_ratio = ratio
            best_col = col

    if best_col is not None and best_ratio >= 0.6:
        return best_col

    raise ValueError("Nenašiel som dátumový stĺpec.")


def detect_equity_column(df: pd.DataFrame) -> str | None:
    for col in ["equity", "portfolio_value", "strategy_equity", "nav", "balance", "value", "cum_equity"]:
        if col in df.columns:
            return col
    for col in df.columns:
        lc = str(col).lower()
        if "equity" in lc or "portfolio" in lc or "nav" in lc or "balance" in lc:
            return col
    return None


def detect_return_column(df: pd.DataFrame) -> str | None:
    for col in ["daily_return", "ret", "return", "strategy_return", "portfolio_return", "pnl_pct"]:
        if col in df.columns:
            return col
    for col in df.columns:
        lc = str(col).lower()
        if "return" in lc or lc == "ret":
            return col
    return None


def detect_selected_asset_column(df: pd.DataFrame) -> str | None:
    for col in [
        "selected_symbol",
        "selected_asset",
        "symbol",
        "asset",
        "leader",
        "pick",
        "holding",
        "position_symbol",
        "position",
        "executed_position",
        "signal_position",
        "final_position",
    ]:
        if col in df.columns:
            return col
    for col in df.columns:
        lc = str(col).lower()
        if any(x in lc for x in ["symbol", "asset", "leader", "pick", "holding", "position"]):
            return col
    return None


def detect_close_column(df: pd.DataFrame) -> str:
    for col in ["close", "Close", "adj_close", "price", "last"]:
        if col in df.columns:
            return col
    for col in df.columns:
        if str(col).lower() == "close":
            return col
    raise ValueError("Nenašiel som close stĺpec.")


def standardize_date_index(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_columns(df)
    date_col = detect_date_column(out)
    out[date_col] = pd.to_datetime(out[date_col], utc=False, errors="coerce").dt.tz_localize(None)
    out = out.dropna(subset=[date_col]).sort_values(date_col).drop_duplicates(subset=[date_col], keep="last")
    out = out.set_index(date_col)
    return out


def compute_daily_return_from_equity(equity: pd.Series) -> pd.Series:
    return equity.astype(float).pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_equity(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def sharpe_ratio(daily_ret: pd.Series) -> float:
    x = daily_ret.dropna()
    if len(x) < 2:
        return 0.0
    vol = x.std(ddof=0)
    if vol == 0 or np.isnan(vol):
        return 0.0
    return float((x.mean() / vol) * np.sqrt(365.25))


def sortino_ratio(daily_ret: pd.Series) -> float:
    x = daily_ret.dropna()
    if len(x) < 2:
        return 0.0
    downside = x[x < 0]
    if len(downside) == 0:
        return 0.0
    dd = downside.std(ddof=0)
    if dd == 0 or np.isnan(dd):
        return 0.0
    return float((x.mean() / dd) * np.sqrt(365.25))


def calc_metrics(df: pd.DataFrame, label: str) -> dict:
    eq = df["equity"].astype(float)
    ret = df["strategy_return"].astype(float)

    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    cagr = annualize_return(total_return, len(df))
    max_dd = max_drawdown_from_equity(eq)
    sharpe = sharpe_ratio(ret)
    sortino = sortino_ratio(ret)

    regime = df["executed_regime"].fillna("CASH").astype(str)
    pos = df["executed_position"].fillna("CASH").astype(str)
    trade_count = int((pos != pos.shift(1)).sum() - 1) if len(pos) else 0

    return {
        "model": label,
        "label": label,
        "start_date": df.index.min().date().isoformat(),
        "end_date": df.index.max().date().isoformat(),
        "days": int(len(df)),
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "trade_count": trade_count,
        "cash_days_pct": float((regime == "CASH").mean() * 100.0),
        "btc_days_pct": float((regime == "BTC").mean() * 100.0),
        "base_days_pct": float((regime == "BASE").mean() * 100.0),
    }


def window_metrics(df: pd.DataFrame, start_date: str) -> dict:
    sub = df[df.index >= pd.Timestamp(start_date)].copy()
    if sub.empty:
        return {
            f"since{start_date[:4]}_total_return_pct": np.nan,
            f"since{start_date[:4]}_cagr_pct": np.nan,
            f"since{start_date[:4]}_max_drawdown_pct": np.nan,
        }
    m = calc_metrics(sub, f"since{start_date[:4]}")
    return {
        f"since{start_date[:4]}_total_return_pct": m["total_return_pct"],
        f"since{start_date[:4]}_cagr_pct": m["cagr_pct"],
        f"since{start_date[:4]}_max_drawdown_pct": m["max_drawdown_pct"],
    }


def discover_candidate_files() -> list[Path]:
    roots = [OUTPUTS, ROOT / "data", ROOT / "artifacts", ROOT]
    found: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for ext in ("*.csv", "*.parquet", "*.pq"):
            found.extend(base.rglob(ext))
    return found


def resolve_base_strategy_file(path: Path, winner_key: str) -> Path:
    explicit = Path(path)
    explicit_name = explicit.name.lower()

    if explicit.exists():
        try:
            preview = safe_read_table(explicit)
            preview = normalize_columns(preview)
            _ = detect_date_column(preview)
            if detect_return_column(preview) is None and detect_equity_column(preview) is None:
                raise ValueError("missing return/equity column")
            log(f"[BASE] Using explicit base paper: {explicit}")
            return explicit
        except Exception as exc:
            log(f"[BASE] Explicit base paper unreadable, falling back to discovery: {explicit} | {exc}")

    candidates = []
    target_names = [explicit_name, f"{winner_key}_paper.csv".lower()]

    for candidate in discover_candidate_files():
        try:
            candidate_resolved = candidate.resolve()
        except Exception:
            candidate_resolved = candidate

        if PHASE63_DIR.resolve() in candidate_resolved.parents:
            continue

        candidate_name = candidate.name.lower()
        if candidate_name in target_names:
            name_priority = 1 if candidate_name == explicit_name else 0
            candidates.append((name_priority, candidate))

    if not candidates:
        raise FileNotFoundError(
            f"Could not resolve upstream base paper for winner_key={winner_key}. "
            f"Explicit path was stale/missing: {explicit}"
        )

    candidates = sorted(
        candidates,
        key=lambda item: (item[0], item[1].stat().st_mtime, str(item[1])),
        reverse=True,
    )
    resolved = candidates[0][1]
    log(f"[BASE] Resolved winner base paper from upstream outputs: {resolved}")
    return resolved


def load_base_strategy(path: Path) -> pd.DataFrame:
    raw = safe_read_table(path)
    raw = standardize_date_index(raw)

    ret_col = detect_return_column(raw)
    eq_col = detect_equity_column(raw)
    selected_col = detect_selected_asset_column(raw)

    out = pd.DataFrame(index=raw.index.copy())

    if ret_col is not None:
        out["base_return"] = pd.to_numeric(raw[ret_col], errors="coerce").fillna(0.0)
    elif eq_col is not None:
        eq = pd.to_numeric(raw[eq_col], errors="coerce").ffill().bfill()
        out["base_return"] = compute_daily_return_from_equity(eq)
    else:
        raise ValueError("Base strategy súbor nemá ani return ani equity stĺpec.")

    if selected_col is not None:
        out["base_selected_symbol"] = raw[selected_col].astype(str).str.upper().str.strip()
    else:
        out["base_selected_symbol"] = "ALT"

    out["base_selected_symbol"] = out["base_selected_symbol"].replace({"NAN": "ALT", "": "ALT"}).fillna("ALT")
    out["base_rolling_ret_10"] = (1.0 + out["base_return"]).rolling(10, min_periods=10).apply(np.prod, raw=True) - 1.0
    out["base_rolling_ret_20"] = (1.0 + out["base_return"]).rolling(20, min_periods=20).apply(np.prod, raw=True) - 1.0
    out["base_rolling_ret_30"] = (1.0 + out["base_return"]).rolling(30, min_periods=30).apply(np.prod, raw=True) - 1.0
    return out


def score_btc_file(path: Path) -> tuple[int, int]:
    full = str(path).lower()
    score = 0
    if "btc" in full:
        score += 40
    if "btcusdt" in full:
        score += 40
    if any(x in full for x in ["1d", "daily", "day"]):
        score += 15
    if path.suffix.lower() in {".csv", ".parquet", ".pq"}:
        score += 5
    if any(x in full for x in ["funding", "premium", "basis", "oi"]):
        score -= 30
    return score, -len(full)


def discover_btc_price_file() -> Path:
    files = discover_candidate_files()
    ranked = sorted(files, key=score_btc_file, reverse=True)

    for path in ranked[:150]:
        try:
            df = safe_read_table(path)
            df = normalize_columns(df)
            _ = detect_date_column(df)
            _ = detect_close_column(df)
            log(f"[DISCOVER] BTC file: {path}")
            return path
        except Exception:
            continue

    raise FileNotFoundError(
        "Nenašiel som BTC daily close súbor. "
        "Daj BTCUSDT daily CSV/parquet do data/ alebo outputs/."
    )


def load_btc_prices(path: Path) -> pd.DataFrame:
    raw = safe_read_table(path)
    raw = standardize_date_index(raw)
    close_col = detect_close_column(raw)

    out = pd.DataFrame(index=raw.index.copy())
    out["btc_close"] = pd.to_numeric(raw[close_col], errors="coerce")
    out = out.dropna(subset=["btc_close"]).sort_index()
    out["btc_return"] = out["btc_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def merge_inputs(base_df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.DataFrame:
    df = base_df.join(btc_df[["btc_close", "btc_return"]], how="left")
    df["btc_close"] = df["btc_close"].ffill().bfill()
    df["btc_return"] = df["btc_return"].fillna(0.0)

    if df["btc_close"].isna().all():
        raise ValueError("BTC close sa nepodarilo zosúladiť s dátumami stratégie.")

    return df


def build_variant_grid() -> list[VariantConfig]:
    variants: list[VariantConfig] = []
    names = set()

    fasts = [20, 30, 50]
    slows = [100, 150, 200]
    ret_lbs = [20, 30, 60]
    ret_mins = [0.04, 0.08, 0.12]
    risk_mas = [150, 200]
    risk_buffers = [-0.03, 0.00]
    vol_lbs = [20, 30]
    vol_caps = [0.045, 0.060]
    weak_lbs = [10, 20, 30]
    weak_thresholds = [-0.02, 0.00, 0.02]
    cooldowns = [0, 3]

    for fast in fasts:
        for slow in slows:
            if fast >= slow:
                continue
            for ret_lb in ret_lbs:
                for ret_min in ret_mins:
                    for risk_ma in risk_mas:
                        for risk_buffer in risk_buffers:
                            for vol_lb in vol_lbs:
                                for vol_cap in vol_caps:
                                    for weak_lb in weak_lbs:
                                        for weak_thr in weak_thresholds:
                                            for cooldown in cooldowns:
                                                name = (
                                                    f"phase63_btcpref_f{fast}_s{slow}_r{ret_lb}"
                                                    f"_m{int(ret_min*100):02d}_rm{risk_ma}"
                                                    f"_rb{int(risk_buffer*100):+03d}"
                                                    f"_v{vol_lb}_{int(vol_cap*1000):03d}"
                                                    f"_wb{weak_lb}_wt{int(weak_thr*100):+03d}"
                                                    f"_cd{cooldown}"
                                                )
                                                if name in names:
                                                    continue
                                                names.add(name)
                                                variants.append(
                                                    VariantConfig(
                                                        name=name,
                                                        btc_fast_ma=fast,
                                                        btc_slow_ma=slow,
                                                        btc_ret_lb=ret_lb,
                                                        btc_ret_min=ret_min,
                                                        btc_risk_ma=risk_ma,
                                                        btc_risk_buffer=risk_buffer,
                                                        btc_vol_lb=vol_lb,
                                                        btc_vol_cap=vol_cap,
                                                        weak_base_lb=weak_lb,
                                                        weak_base_threshold=weak_thr,
                                                        cooldown_days=cooldown,
                                                    )
                                                )

    handpicked = [
        VariantConfig(
            name="phase63_btcpref_default",
            btc_fast_ma=30,
            btc_slow_ma=150,
            btc_ret_lb=30,
            btc_ret_min=0.08,
            btc_risk_ma=200,
            btc_risk_buffer=0.0,
            btc_vol_lb=20,
            btc_vol_cap=0.060,
            weak_base_lb=20,
            weak_base_threshold=0.00,
            cooldown_days=0,
        ),
        VariantConfig(
            name="phase63_btcpref_conservative",
            btc_fast_ma=20,
            btc_slow_ma=150,
            btc_ret_lb=20,
            btc_ret_min=0.08,
            btc_risk_ma=150,
            btc_risk_buffer=-0.03,
            btc_vol_lb=20,
            btc_vol_cap=0.045,
            weak_base_lb=20,
            weak_base_threshold=0.02,
            cooldown_days=3,
        ),
        VariantConfig(
            name="phase63_btcpref_rescue",
            btc_fast_ma=20,
            btc_slow_ma=100,
            btc_ret_lb=20,
            btc_ret_min=0.04,
            btc_risk_ma=200,
            btc_risk_buffer=0.0,
            btc_vol_lb=30,
            btc_vol_cap=0.060,
            weak_base_lb=10,
            weak_base_threshold=-0.02,
            cooldown_days=0,
        ),
    ]
    for v in handpicked:
        if v.name not in names:
            variants.append(v)

    return variants


def compute_regime_columns(df: pd.DataFrame, cfg: VariantConfig) -> pd.DataFrame:
    out = df.copy()

    out["btc_fast_ma"] = out["btc_close"].rolling(cfg.btc_fast_ma, min_periods=cfg.btc_fast_ma).mean()
    out["btc_slow_ma"] = out["btc_close"].rolling(cfg.btc_slow_ma, min_periods=cfg.btc_slow_ma).mean()
    out["btc_risk_ma"] = out["btc_close"].rolling(cfg.btc_risk_ma, min_periods=cfg.btc_risk_ma).mean()
    out["btc_ret_lb"] = out["btc_close"].pct_change(cfg.btc_ret_lb)
    out["btc_vol"] = out["btc_return"].rolling(cfg.btc_vol_lb, min_periods=cfg.btc_vol_lb).std(ddof=0)

    out["btc_trend_ok"] = (
        (out["btc_close"] > out["btc_fast_ma"])
        & (out["btc_fast_ma"] > out["btc_slow_ma"])
        & (out["btc_ret_lb"] >= cfg.btc_ret_min)
    )

    out["risk_off"] = (
        (out["btc_close"] < (out["btc_risk_ma"] * (1.0 + cfg.btc_risk_buffer)))
        | (out["btc_vol"] > cfg.btc_vol_cap)
    )

    base_col_map = {
        10: "base_rolling_ret_10",
        20: "base_rolling_ret_20",
        30: "base_rolling_ret_30",
    }
    base_ret_col = base_col_map[cfg.weak_base_lb]
    out["base_strength_lb"] = out[base_ret_col]
    out["base_is_weak"] = out["base_strength_lb"] <= cfg.weak_base_threshold

    out["btc_preference_raw"] = out["btc_trend_ok"] & (~out["risk_off"]) & out["base_is_weak"]

    if cfg.cooldown_days > 0:
        raw = out["btc_preference_raw"].fillna(False).astype(bool).values
        locked = np.zeros(len(raw), dtype=bool)
        hold = 0
        for i, flag in enumerate(raw):
            if flag:
                hold = cfg.cooldown_days
            elif hold > 0:
                hold -= 1
            locked[i] = flag or hold > 0
        out["btc_preference"] = locked
    else:
        out["btc_preference"] = out["btc_preference_raw"].fillna(False)

    return out


def simulate_variant(base_input: pd.DataFrame, cfg: VariantConfig) -> pd.DataFrame:
    df = compute_regime_columns(base_input, cfg)

    base_pos = df["base_selected_symbol"].fillna("ALT").astype(str).str.upper()

    df["signal_regime"] = np.where(
        df["risk_off"].fillna(True),
        "CASH",
        np.where(df["btc_preference"].fillna(False), "BTC", "BASE"),
    )

    df["signal_position"] = np.where(
        df["signal_regime"] == "BTC",
        "BTC",
        np.where(df["signal_regime"] == "CASH", "CASH", base_pos),
    )

    df["executed_regime"] = df["signal_regime"].shift(1).fillna("CASH")
    df["executed_position"] = df["signal_position"].shift(1).fillna("CASH")

    df["strategy_return"] = np.where(
        df["executed_regime"] == "BTC",
        df["btc_return"].fillna(0.0),
        np.where(df["executed_regime"] == "CASH", 0.0, df["base_return"].fillna(0.0)),
    )

    df["equity"] = (1.0 + pd.Series(df["strategy_return"], index=df.index)).cumprod()

    return df[
        [
            "base_return",
            "btc_return",
            "btc_close",
            "base_selected_symbol",
            "base_strength_lb",
            "base_is_weak",
            "signal_regime",
            "signal_position",
            "executed_regime",
            "executed_position",
            "strategy_return",
            "equity",
            "btc_fast_ma",
            "btc_slow_ma",
            "btc_risk_ma",
            "btc_ret_lb",
            "btc_vol",
            "btc_trend_ok",
            "risk_off",
            "btc_preference",
        ]
    ].copy()


def build_baseline_rows(base_df: pd.DataFrame, phase61_label: str) -> tuple[pd.DataFrame, dict]:
    out = base_df.copy()
    out["base_strength_lb"] = np.nan
    out["base_is_weak"] = False
    out["signal_regime"] = np.where(out["base_selected_symbol"].astype(str).str.upper().eq("CASH"), "CASH", "BASE")
    out["signal_position"] = out["base_selected_symbol"].fillna("ALT").astype(str).str.upper()
    out["executed_regime"] = out["signal_regime"]
    out["executed_position"] = out["signal_position"]
    out["strategy_return"] = out["base_return"].fillna(0.0)
    out["equity"] = (1.0 + out["strategy_return"]).cumprod()

    row = calc_metrics(out, phase61_label)
    row.update(window_metrics(out, "2021-01-01"))
    row.update(window_metrics(out, "2023-01-01"))
    row.update(window_metrics(out, "2025-01-01"))
    return out, row


def add_delta(df: pd.DataFrame, baseline_model: str) -> pd.DataFrame:
    out = df.copy()
    hit = out[out["model"].astype(str).str.lower() == baseline_model.lower()]
    if hit.empty:
        return out
    base = hit.iloc[0]
    for metric in ["cagr_pct", "max_drawdown_pct", "since2021_cagr_pct", "since2023_cagr_pct", "since2025_cagr_pct"]:
        if metric in out.columns:
            out[f"delta_vs_{baseline_model}_{metric}"] = (
                pd.to_numeric(out[metric], errors="coerce")
                - pd.to_numeric(base.get(metric), errors="coerce")
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE63 BTC participation overlay")
    parser.add_argument("--top-n-save", type=int, default=10)
    parser.add_argument("--winner-key", type=str, default=CURRENT_INTERNAL_WINNER_KEY)
    parser.add_argument("--winner-label", type=str, default=CURRENT_INTERNAL_WINNER_LABEL)
    parser.add_argument("--baseline-key", type=str, default=LATEST_BEST_BASELINE_KEY)
    parser.add_argument("--base-paper-path", type=str, default=str(EXPLICIT_BASE_PAPER_PATH))
    parser.add_argument("--only-model", type=str, default="")
    args = parser.parse_args()

    ensure_dir(PHASE63_DIR)

    log("[PHASE63] Start")
    log(f"[PHASE63] Winner key: {args.winner_key}")
    log(f"[PHASE63] Winner label: {args.winner_label}")
    log(f"[PHASE63] Baseline key: {args.baseline_key}")

    base_file = resolve_base_strategy_file(Path(args.base_paper_path), args.winner_key)
    btc_file = discover_btc_price_file()

    base_df = load_base_strategy(base_file)
    btc_df = load_btc_prices(btc_file)
    merged = merge_inputs(base_df, btc_df)

    variants = build_variant_grid()
    if args.only_model:
        variants = [v for v in variants if v.name == args.only_model]
        if not variants:
            raise ValueError(f"Requested only-model not found in phase63 grid: {args.only_model}")
    log(f"[PHASE63] Variants: {len(variants)}")

    base_paper, base_row = build_baseline_rows(merged, args.winner_key)

    rows: list[dict] = [base_row]
    papers_for_top: dict[str, pd.DataFrame] = {args.winner_key: base_paper}

    for i, cfg in enumerate(variants, start=1):
        try:
            paper = simulate_variant(merged, cfg)
            row = calc_metrics(paper, cfg.name)
            row.update(window_metrics(paper, "2021-01-01"))
            row.update(window_metrics(paper, "2023-01-01"))
            row.update(window_metrics(paper, "2025-01-01"))

            row["btc_fast_ma"] = cfg.btc_fast_ma
            row["btc_slow_ma"] = cfg.btc_slow_ma
            row["btc_ret_lb_days"] = cfg.btc_ret_lb
            row["btc_ret_min"] = cfg.btc_ret_min
            row["btc_risk_ma"] = cfg.btc_risk_ma
            row["btc_risk_buffer"] = cfg.btc_risk_buffer
            row["btc_vol_lb"] = cfg.btc_vol_lb
            row["btc_vol_cap"] = cfg.btc_vol_cap
            row["weak_base_lb"] = cfg.weak_base_lb
            row["weak_base_threshold"] = cfg.weak_base_threshold
            row["cooldown_days"] = cfg.cooldown_days

            rows.append(row)
            papers_for_top[cfg.name] = paper

            if i % 100 == 0:
                log(f"[PHASE63] done {i}/{len(variants)}")
        except Exception as e:
            log(f"[WARN] {cfg.name} failed: {e}")

    summary = pd.DataFrame(rows)

    for col in ["since2023_cagr_pct", "cagr_pct", "since2025_cagr_pct", "max_drawdown_pct"]:
        if col not in summary.columns:
            summary[col] = np.nan

    summary = summary.sort_values(
        by=["since2023_cagr_pct", "cagr_pct", "since2025_cagr_pct", "max_drawdown_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    summary["source"] = np.where(summary["model"].eq(args.winner_key), "explicit_phase61_base_paper", "phase63_overlay")

    combined_compare = summary.head(20).copy()
    combined_compare = add_delta(combined_compare, args.winner_key)

    summary_path = PHASE63_DIR / "phase63_overlay_summary.csv"
    compare_path = PHASE63_DIR / "phase63_overlay_top_compare.csv"
    manifest_path = PHASE63_DIR / "phase63_manifest.json"

    summary.to_csv(summary_path, index=False)
    combined_compare.to_csv(compare_path, index=False)

    top_models = summary["model"].head(max(args.top_n_save, 1)).astype(str).tolist()
    if args.winner_key not in top_models:
        top_models.append(args.winner_key)

    for model in top_models:
        paper = papers_for_top.get(model)
        if paper is None:
            continue
        out_path = PHASE63_DIR / f"{model}_paper.csv"
        tmp = paper.copy().reset_index().rename(columns={paper.index.name or "index": "date"})
        tmp.to_csv(out_path, index=False)

    primary_output_model = next((model for model in top_models if model.lower().startswith("phase63")), top_models[0])
    primary_output_path = PHASE63_DIR / f"{primary_output_model}_paper.csv"

    manifest = {
        "phase": "phase63_btc_participation_overlay",
        "winner_input_key": args.winner_key,
        "winner_label": args.winner_label,
        "baseline_key": args.baseline_key,
        "base_file": to_portable_path(base_file, ROOT),
        "btc_file": to_portable_path(btc_file, ROOT),
        "summary_file": to_portable_path(summary_path, ROOT),
        "compare_file": to_portable_path(compare_path, ROOT),
        "top_saved_models": top_models,
        "variant_count_total": int(len(variants)),
        "execution_model": "signal_t -> execute_t_plus_1",
        "freshness_lineage": build_producer_lineage(
            producer_script=__file__,
            source_file=base_file,
            raw_file=btc_file,
            output_file=primary_output_path,
            date_semantics="execution_date",
            repo_root=ROOT,
        ),
        "notes": [
            "BASE = explicitný phase61 winner paper",
            "BTC = preferovaný len keď BTC trend je OK a base leader je slabý",
            "CASH = risk-off režim",
            "Phase61 baseline sa neberie z compare summary ani equity curves",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    best = summary.iloc[0].to_dict()
    log("")
    log("=== PHASE63 TOP RESULT ===")
    log(f"model: {best.get('model')}")
    log(f"cagr_pct: {best.get('cagr_pct'):.2f}")
    log(f"max_drawdown_pct: {best.get('max_drawdown_pct'):.2f}")
    log(f"since2023_cagr_pct: {best.get('since2023_cagr_pct'):.2f}")
    log(f"since2025_cagr_pct: {best.get('since2025_cagr_pct'):.2f}")
    log("")
    log(f"[PHASE63] Saved summary -> {summary_path}")
    log(f"[PHASE63] Saved compare -> {compare_path}")
    log(f"[PHASE63] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
