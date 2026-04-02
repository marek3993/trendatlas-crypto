from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

PHASE66G_DIR = OUTPUTS / "phase66g_production_candidate_live"
DEFAULT_PAPER = PHASE66G_DIR / "phase66g_production_soft_filters_paper.csv"
DEFAULT_TREND = PHASE66G_DIR / "phase66g_trend_barometer_history.csv"

PHASE68D_DIR = OUTPUTS / "phase68d_realistic_1p50x_activation_tuning"


@dataclass(frozen=True)
class ActivationVariant:
    model: str
    target_leverage: float
    trend_activation_threshold: float
    stress_off_threshold: float
    stress_on_threshold: float


BASELINE_VARIANT = ActivationVariant(
    model="phase68d_66g_1p00x_realistic_baseline",
    target_leverage=1.00,
    trend_activation_threshold=0.10,
    stress_off_threshold=-0.08,
    stress_on_threshold=-0.04,
)

VARIANTS: list[ActivationVariant] = [
    ActivationVariant("phase68d_1p50x_act_A", 1.50, -0.05, -0.06, -0.02),
    ActivationVariant("phase68d_1p50x_act_B", 1.50, -0.05, -0.08, -0.04),
    ActivationVariant("phase68d_1p50x_act_C", 1.50, -0.05, -0.10, -0.06),
    ActivationVariant("phase68d_1p50x_act_D", 1.50, 0.00, -0.06, -0.02),
    ActivationVariant("phase68d_1p50x_act_E", 1.50, 0.00, -0.08, -0.04),
    ActivationVariant("phase68d_1p50x_act_F", 1.50, 0.00, -0.10, -0.06),
    ActivationVariant("phase68d_1p50x_act_G", 1.50, 0.05, -0.06, -0.02),
    ActivationVariant("phase68d_1p50x_act_H", 1.50, 0.05, -0.08, -0.04),
    ActivationVariant("phase68d_1p50x_act_I", 1.50, 0.05, -0.10, -0.06),
    ActivationVariant("phase68d_1p50x_act_J", 1.50, 0.10, -0.06, -0.02),
    ActivationVariant("phase68d_1p50x_act_K", 1.50, 0.10, -0.08, -0.04),
    ActivationVariant("phase68d_1p50x_act_L", 1.50, 0.10, -0.10, -0.06),
]

SUCCESS_RULE = {
    "min_since2025_delta_vs_baseline_pct": 0.01,
    "max_dd_worsen_vs_baseline_pct": -3.00,
    "min_calmar_delta_vs_baseline": 0.00,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def pick_col(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    lower_map = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    raise KeyError(f"Chýba required column pre {label}. Kandidáti: {candidates}")


def normalize_asset_label(raw: str) -> str:
    s = str(raw).strip().upper()
    if s in {"", "NAN", "NONE", "NULL", "BASELINE", "CORE"}:
        return "CASH"
    return s


def load_base_paper(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = pick_col(df, ["date", "ts", "datetime", "timestamp"], "date")
    ret_col = pick_col(
        df,
        ["strategy_ret", "daily_ret", "ret", "return", "strategy_return", "portfolio_ret", "equity_ret"],
        "strategy_ret",
    )
    asset_col = pick_col(
        df,
        ["held_asset_public", "chosen_asset", "selected_asset", "asset", "weekly_authorized_asset", "current_asset"],
        "held_asset",
    )

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    out["base_ret"] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)
    out["held_asset"] = df[asset_col].astype(str).map(normalize_asset_label)

    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    out["is_exposed"] = ~out["held_asset"].isin(["CASH", "USD", "USDT"])
    return out


def load_trend_history(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = pick_col(df, ["date", "ts", "datetime", "timestamp"], "date")
    trend_score_col = pick_col(df, ["trend_score"], "trend_score")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    out["trend_score"] = pd.to_numeric(df[trend_score_col], errors="coerce")

    for key in ["trend_state_label", "buy_threshold", "prev_trend_score", "crossed_up_today", "crossed_down_today"]:
        try:
            col = pick_col(df, [key], key)
            out[key] = df[col]
        except KeyError:
            pass

    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return out


def add_position_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    prev_asset = out["held_asset"].shift(1)
    out["switch_day"] = ((out["held_asset"] != prev_asset) & prev_asset.notna()).fillna(False)

    days_in_position: list[int] = []
    current_asset = None
    counter = 0
    for asset in out["held_asset"].astype(str):
        if asset != current_asset:
            current_asset = asset
            counter = 1
        else:
            counter += 1
        days_in_position.append(counter)

    out["days_in_position"] = days_in_position
    out["entry_buffer_day"] = out["is_exposed"] & (~out["switch_day"]) & (out["days_in_position"] == 2)
    return out


def add_baseline_stress_state(
    df: pd.DataFrame,
    lookback_days: int,
    off_threshold: float,
    on_threshold: float,
) -> pd.DataFrame:
    out = df.copy()

    out["baseline_equity_curve"] = (1.0 + out["base_ret"]).cumprod()
    rolling_peak = out["baseline_equity_curve"].rolling(lookback_days, min_periods=1).max()
    out["baseline_dd_lookback"] = (out["baseline_equity_curve"] / rolling_peak) - 1.0

    stress_active: list[bool] = []
    active = False
    for dd in out["baseline_dd_lookback"].astype(float):
        if not active and dd <= off_threshold:
            active = True
        elif active and dd >= on_threshold:
            active = False
        stress_active.append(active)

    out["stress_block_active"] = stress_active
    return out


def build_realistic_wrapper(
    base_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    variant: ActivationVariant,
    annual_borrow_cost: float,
    stress_lookback_days: int,
) -> pd.DataFrame:
    merged = base_df.merge(trend_df, on="date", how="left")

    if merged["trend_score"].isna().any():
        merged["trend_score"] = merged["trend_score"].ffill().bfill()

    merged = add_position_flags(merged)
    merged = add_baseline_stress_state(
        merged,
        lookback_days=stress_lookback_days,
        off_threshold=float(variant.stress_off_threshold),
        on_threshold=float(variant.stress_on_threshold),
    )

    merged["cash_day"] = ~merged["is_exposed"]
    merged["trend_gate_pass"] = pd.to_numeric(merged["trend_score"], errors="coerce").fillna(-999.0) >= float(
        variant.trend_activation_threshold
    )
    merged["switch_day_forced_1x"] = merged["is_exposed"] & merged["switch_day"]
    merged["entry_buffer_forced_1x"] = merged["entry_buffer_day"]
    merged["trend_block_day"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_forced_1x"])
        & (~merged["trend_gate_pass"])
    )
    merged["stress_block_day"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_forced_1x"])
        & merged["trend_gate_pass"]
        & merged["stress_block_active"]
    )

    merged["leverage_eligible"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_forced_1x"])
        & merged["trend_gate_pass"]
        & (~merged["stress_block_active"])
    )

    merged["target_leverage"] = float(variant.target_leverage)
    merged["effective_leverage"] = np.where(
        merged["leverage_eligible"],
        float(variant.target_leverage),
        1.00,
    )

    borrowed_fraction = np.maximum(merged["effective_leverage"] - 1.0, 0.0)
    daily_borrow_rate = float(annual_borrow_cost) / 365.25

    merged["daily_borrow_cost"] = borrowed_fraction * daily_borrow_rate
    merged["realistic_ret"] = (merged["base_ret"] * merged["effective_leverage"]) - merged["daily_borrow_cost"]
    merged["realistic_ret"] = merged["realistic_ret"].clip(lower=-0.999999)
    merged["equity_curve"] = (1.0 + merged["realistic_ret"]).cumprod()
    merged["leverage_active"] = merged["effective_leverage"] > 1.0

    merged["leverage_state_reason"] = np.where(
        merged["cash_day"],
        "cash",
        np.where(
            merged["switch_day_forced_1x"],
            "switch_day",
            np.where(
                merged["entry_buffer_forced_1x"],
                "entry_buffer_day",
                np.where(
                    merged["stress_block_day"],
                    "stress_block",
                    np.where(
                        merged["trend_block_day"],
                        "trend_gate",
                        "leverage_on" if variant.target_leverage > 1.0 else "baseline_1x",
                    ),
                ),
            ),
        ),
    )

    merged["trend_activation_threshold"] = float(variant.trend_activation_threshold)
    merged["stress_off_threshold"] = float(variant.stress_off_threshold)
    merged["stress_on_threshold"] = float(variant.stress_on_threshold)

    return merged


def compute_cagr_pct(ret_series: pd.Series, date_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    start_dt = pd.to_datetime(date_series.iloc[0])
    end_dt = pd.to_datetime(date_series.iloc[-1])
    days = max((end_dt - start_dt).days, 1)
    years = days / 365.25
    if years <= 0:
        return np.nan
    return float(((eq.iloc[-1] ** (1.0 / years)) - 1.0) * 100.0)


def compute_max_drawdown_pct(ret_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min() * 100.0)


def subset_since(df: pd.DataFrame, start_date: str) -> pd.DataFrame:
    return df.loc[df["date"] >= pd.Timestamp(start_date)].copy().reset_index(drop=True)


def summarize_variant(model: str, df: pd.DataFrame, annual_borrow_cost: float) -> dict:
    since2023 = subset_since(df, "2023-01-01")
    since2025 = subset_since(df, "2025-01-01")

    held = df["held_asset"].astype(str)
    switch_count = int((held != held.shift(1)).sum() - 1) if len(held) else 0

    cagr_pct = compute_cagr_pct(df["realistic_ret"], df["date"])
    max_dd_pct = compute_max_drawdown_pct(df["realistic_ret"])
    calmar = np.nan
    if pd.notna(cagr_pct) and pd.notna(max_dd_pct) and abs(max_dd_pct) > 1e-9:
        calmar = cagr_pct / abs(max_dd_pct)

    return {
        "model": model,
        "target_leverage": float(df["target_leverage"].iloc[0]),
        "trend_activation_threshold": float(df["trend_activation_threshold"].iloc[0]),
        "stress_off_threshold": float(df["stress_off_threshold"].iloc[0]),
        "stress_on_threshold": float(df["stress_on_threshold"].iloc[0]),
        "annual_borrow_cost_pct": float(annual_borrow_cost * 100.0),
        "cagr_pct": round(cagr_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "calmar": round(calmar, 4) if pd.notna(calmar) else np.nan,
        "since2023_cagr_pct": round(compute_cagr_pct(since2023["realistic_ret"], since2023["date"]), 2)
        if not since2023.empty
        else np.nan,
        "since2025_cagr_pct": round(compute_cagr_pct(since2025["realistic_ret"], since2025["date"]), 2)
        if not since2025.empty
        else np.nan,
        "worst_day_pct": round(float(df["realistic_ret"].min() * 100.0), 2) if not df.empty else np.nan,
        "borrow_cost_total_pct": round(float(df["daily_borrow_cost"].sum() * 100.0), 4),
        "eligible_days": int(df["leverage_eligible"].sum()),
        "eligible_days_pct": round(float(df["leverage_eligible"].mean() * 100.0), 2),
        "leverage_active_days": int(df["leverage_active"].sum()),
        "leverage_active_days_pct": round(float(df["leverage_active"].mean() * 100.0), 2),
        "switch_days_forced_1x": int(df["switch_day_forced_1x"].sum()),
        "entry_buffer_days_forced_1x": int(df["entry_buffer_forced_1x"].sum()),
        "trend_block_days": int(df["trend_block_day"].sum()),
        "stress_block_days": int(df["stress_block_day"].sum()),
        "selection_count": int(df["is_exposed"].sum()),
        "switch_count": int(max(switch_count, 0)),
        "unique_selected_assets": int(held[~held.isin(["CASH", "USD", "USDT"])].nunique()),
        "held_asset_now": str(held.iloc[-1]) if not df.empty else "",
        "latest_available_date": df["date"].max().strftime("%Y-%m-%d") if not df.empty else "",
    }


def add_delta_cols(row: dict, ref: dict) -> dict:
    out = row.copy()
    for metric in [
        "cagr_pct",
        "max_drawdown_pct",
        "calmar",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
        "worst_day_pct",
        "borrow_cost_total_pct",
    ]:
        out[f"delta_vs_realistic_baseline_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(ref.get(metric), errors="coerce")
        )
    return out


def build_pass_flag(row: pd.Series) -> bool:
    since2025_delta = pd.to_numeric(row.get("delta_vs_realistic_baseline_since2025_cagr_pct"), errors="coerce")
    dd_delta = pd.to_numeric(row.get("delta_vs_realistic_baseline_max_drawdown_pct"), errors="coerce")
    calmar_delta = pd.to_numeric(row.get("delta_vs_realistic_baseline_calmar"), errors="coerce")

    if pd.isna(since2025_delta) or pd.isna(dd_delta) or pd.isna(calmar_delta):
        return False
    if since2025_delta < SUCCESS_RULE["min_since2025_delta_vs_baseline_pct"]:
        return False
    if dd_delta < SUCCESS_RULE["max_dd_worsen_vs_baseline_pct"]:
        return False
    if calmar_delta < SUCCESS_RULE["min_calmar_delta_vs_baseline"]:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE68D realistic 1.50x activation tuning over current 66G baseline")
    parser.add_argument("--paper", type=str, default=str(DEFAULT_PAPER))
    parser.add_argument("--trend-history", type=str, default=str(DEFAULT_TREND))
    parser.add_argument("--annual-borrow-cost", type=float, default=0.12)
    parser.add_argument("--stress-lookback-days", type=int, default=20)
    args = parser.parse_args()

    ensure_dir(PHASE68D_DIR)
    papers_dir = PHASE68D_DIR / "papers"
    ensure_dir(papers_dir)

    paper_path = Path(args.paper)
    trend_path = Path(args.trend_history)
    if not paper_path.exists():
        raise FileNotFoundError(f"Input paper sa nenašiel: {paper_path}")
    if not trend_path.exists():
        raise FileNotFoundError(f"Trend history sa nenašiel: {trend_path}")

    log("[PHASE68D] Start")
    log(f"[PHASE68D] Input paper: {paper_path}")
    log(f"[PHASE68D] Trend history: {trend_path}")
    log(f"[PHASE68D] Annual borrow cost: {args.annual_borrow_cost:.4f}")
    log(f"[PHASE68D] Stress lookback days: {args.stress_lookback_days}")

    base_df = load_base_paper(paper_path)
    trend_df = load_trend_history(trend_path)

    all_variants = [BASELINE_VARIANT] + VARIANTS
    summary_rows: list[dict] = []

    for variant in all_variants:
        log(
            f"[PHASE68D] running {variant.model} | "
            f"lev={variant.target_leverage:.2f}x "
            f"trend_thr={variant.trend_activation_threshold:+.2f} "
            f"stress_off={variant.stress_off_threshold:+.2f} "
            f"stress_on={variant.stress_on_threshold:+.2f}"
        )

        wrapped = build_realistic_wrapper(
            base_df=base_df,
            trend_df=trend_df,
            variant=variant,
            annual_borrow_cost=float(args.annual_borrow_cost),
            stress_lookback_days=int(args.stress_lookback_days),
        )

        summary_rows.append(
            summarize_variant(
                model=variant.model,
                df=wrapped,
                annual_borrow_cost=float(args.annual_borrow_cost),
            )
        )

        wrapped.to_csv(papers_dir / f"{variant.model}_paper.csv", index=False)
        log(f"[PHASE68D] done {variant.model}")

    summary_df = pd.DataFrame(summary_rows)

    baseline_row = summary_df.loc[summary_df["model"] == BASELINE_VARIANT.model]
    if baseline_row.empty:
        raise ValueError("Chýba realistic baseline row.")
    baseline = baseline_row.iloc[0].to_dict()

    compare_rows = [add_delta_cols(row, baseline) for row in summary_rows]
    compare_df = pd.DataFrame(compare_rows)
    compare_df["passes_success_rule"] = compare_df.apply(build_pass_flag, axis=1)

    compare_df = compare_df.sort_values(
        by=[
            "passes_success_rule",
            "delta_vs_realistic_baseline_since2025_cagr_pct",
            "delta_vs_realistic_baseline_calmar",
            "delta_vs_realistic_baseline_cagr_pct",
            "delta_vs_realistic_baseline_max_drawdown_pct",
        ],
        ascending=[False, False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    candidate_compare = compare_df[compare_df["model"].astype(str) != BASELINE_VARIANT.model].copy()
    top = candidate_compare.iloc[0].to_dict() if not candidate_compare.empty else compare_df.iloc[0].to_dict()

    summary_path = PHASE68D_DIR / "phase68d_realistic_1p50x_activation_summary.csv"
    compare_path = PHASE68D_DIR / "phase68d_realistic_1p50x_activation_compare.csv"
    manifest_path = PHASE68D_DIR / "phase68d_realistic_1p50x_activation_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)

    manifest = {
        "phase": "phase68d_realistic_1p50x_activation_tuning",
        "official_compare_baseline": BASELINE_VARIANT.model,
        "input_paper": str(paper_path),
        "trend_history": str(trend_path),
        "params": {
            "annual_borrow_cost": float(args.annual_borrow_cost),
            "stress_lookback_days": int(args.stress_lookback_days),
            "switch_day_forced_1x": True,
            "entry_buffer_day_forced_1x": True,
            "cash_forced_1x": True,
            "target_leverage_fixed_for_candidates": 1.50,
        },
        "baseline_variant": asdict(BASELINE_VARIANT),
        "candidate_variants": [asdict(v) for v in VARIANTS],
        "success_rule": SUCCESS_RULE,
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "papers_dir": str(papers_dir),
        "notes": [
            "Phase68D nemení leverage level na candidates, fixne drží 1.50x.",
            "Sweepuje len trend_activation_threshold a stress thresholds.",
            "Cash = vždy 1.00x.",
            "Switch day = 1.00x.",
            "Prvý full day po switchi = 1.00x.",
            "Official compare baseline je phase68d_66g_1p00x_realistic_baseline.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE68D TOP RESULT ===")
    log(f"model: {top['model']}")
    log(f"target_leverage: {float(top['target_leverage']):.2f}x")
    log(f"trend_activation_threshold: {float(top['trend_activation_threshold']):.2f}")
    log(f"stress_off_threshold: {float(top['stress_off_threshold']):.2f}")
    log(f"stress_on_threshold: {float(top['stress_on_threshold']):.2f}")
    log(f"cagr_pct: {float(top['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(top['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(top['calmar']):.4f}")
    log(f"since2023_cagr_pct: {float(top['since2023_cagr_pct']):.2f}")
    log(f"since2025_cagr_pct: {float(top['since2025_cagr_pct']):.2f}")
    log(f"worst_day_pct: {float(top['worst_day_pct']):.2f}")
    log(f"delta_vs_realistic_baseline_cagr_pct: {float(top['delta_vs_realistic_baseline_cagr_pct']):.2f}")
    log(f"delta_vs_realistic_baseline_since2025_cagr_pct: {float(top['delta_vs_realistic_baseline_since2025_cagr_pct']):.2f}")
    log(f"delta_vs_realistic_baseline_max_drawdown_pct: {float(top['delta_vs_realistic_baseline_max_drawdown_pct']):.2f}")
    log(f"delta_vs_realistic_baseline_calmar: {float(top['delta_vs_realistic_baseline_calmar']):.4f}")
    log(f"eligible_days: {int(pd.to_numeric(top.get('eligible_days'), errors='coerce'))}")
    log(f"leverage_active_days: {int(pd.to_numeric(top.get('leverage_active_days'), errors='coerce'))}")
    log(f"trend_block_days: {int(pd.to_numeric(top.get('trend_block_days'), errors='coerce'))}")
    log(f"stress_block_days: {int(pd.to_numeric(top.get('stress_block_days'), errors='coerce'))}")
    log(f"borrow_cost_total_pct: {float(top['borrow_cost_total_pct']):.4f}")
    log(f"passes_success_rule: {bool(top.get('passes_success_rule', False))}")
    log(f"held_asset_now: {top['held_asset_now']}")
    log("")

    log(f"[PHASE68D] Saved summary -> {summary_path}")
    log(f"[PHASE68D] Saved compare -> {compare_path}")
    log(f"[PHASE68D] Saved manifest -> {manifest_path}")
    log(f"[PHASE68D] Saved papers -> {papers_dir}")


if __name__ == "__main__":
    main()