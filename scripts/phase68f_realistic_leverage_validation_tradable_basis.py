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
DEFAULT_DECISIONS = PHASE66G_DIR / "phase66g_production_candidate_decisions.csv"

PHASE68F_DIR = OUTPUTS / "phase68f_realistic_leverage_validation_tradable_basis"


@dataclass(frozen=True)
class ValidationVariant:
    model: str
    target_leverage: float


VARIANTS: list[ValidationVariant] = [
    ValidationVariant("phase68f_66g_1p00x_baseline", 1.00),
    ValidationVariant("phase68f_66g_1p10x_candidate", 1.10),
    ValidationVariant("phase68f_66g_1p25x_candidate", 1.25),
    ValidationVariant("phase68f_66g_1p50x_candidate", 1.50),
]


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
    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return out


def load_governance_decisions(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Decisions file sa nenašiel: {path}")

    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "decision_date",
                "period_start",
                "period_end",
                "selected_asset",
                "selected",
                "governed_asset",
            ]
        )

    date_col = pick_col(df, ["decision_date", "date", "ts", "datetime"], "decision_date")
    asset_col = pick_col(df, ["selected_asset", "asset", "chosen_asset", "weekly_authorized_asset"], "selected_asset")

    tmp = pd.DataFrame()
    tmp["decision_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)

    if "period_start" in df.columns:
        tmp["period_start"] = pd.to_datetime(df["period_start"], errors="coerce").dt.tz_localize(None)
    else:
        tmp["period_start"] = pd.NaT

    if "period_end" in df.columns:
        tmp["period_end"] = pd.to_datetime(df["period_end"], errors="coerce").dt.tz_localize(None)
    else:
        tmp["period_end"] = pd.NaT

    tmp["selected_asset"] = df[asset_col].astype(str)
    if "selected" in df.columns:
        tmp["selected"] = pd.to_numeric(df["selected"], errors="coerce").fillna(0).astype(int)
    else:
        tmp["selected"] = 1

    tmp["governed_asset"] = tmp["selected_asset"].map(normalize_asset_label)
    tmp = tmp.dropna(subset=["decision_date"]).sort_values("decision_date").reset_index(drop=True)
    return tmp


def build_governance_transition_calendar(
    decisions_df: pd.DataFrame,
    paper_dates: pd.Series,
) -> tuple[pd.DataFrame, int, dict]:
    meta = {
        "decision_rows_total": int(len(decisions_df)),
        "selected_rows_used": 0,
        "governance_switch_rows": 0,
        "mapped_transition_rows": 0,
        "unmapped_transition_rows": 0,
        "mapping_sources": {},
    }

    if decisions_df.empty:
        return pd.DataFrame(
            columns=[
                "decision_date",
                "period_start",
                "period_end",
                "prev_governed_asset",
                "governed_asset",
                "execution_day",
                "execution_source",
            ]
        ), 0, meta

    selected_rows = decisions_df.loc[decisions_df["selected"] == 1].copy()
    if selected_rows.empty:
        selected_rows = decisions_df.copy()

    selected_rows = selected_rows.sort_values("decision_date").reset_index(drop=True)
    meta["selected_rows_used"] = int(len(selected_rows))

    selected_rows["prev_governed_asset"] = selected_rows["governed_asset"].shift(1)
    selected_rows["governance_switch"] = (
        (selected_rows["governed_asset"] != selected_rows["prev_governed_asset"])
        & selected_rows["prev_governed_asset"].notna()
    )

    switch_rows = selected_rows.loc[selected_rows["governance_switch"]].copy().reset_index(drop=True)
    governance_switch_count = int(len(switch_rows))
    meta["governance_switch_rows"] = governance_switch_count

    if switch_rows.empty:
        return pd.DataFrame(
            columns=[
                "decision_date",
                "period_start",
                "period_end",
                "prev_governed_asset",
                "governed_asset",
                "execution_day",
                "execution_source",
            ]
        ), governance_switch_count, meta

    paper_dates_sorted = pd.Series(pd.to_datetime(paper_dates).dropna().sort_values().unique())

    def _first_paper_date_on_or_after(ts: pd.Timestamp) -> pd.Timestamp | pd.NaT:
        if pd.isna(ts):
            return pd.NaT
        eligible = paper_dates_sorted.loc[paper_dates_sorted >= ts]
        if eligible.empty:
            return pd.NaT
        return pd.Timestamp(eligible.iloc[0])

    exec_days = []
    exec_sources = []

    for _, row in switch_rows.iterrows():
        execution_day = pd.NaT
        source = "unmapped"

        if pd.notna(row["period_start"]):
            execution_day = _first_paper_date_on_or_after(pd.Timestamp(row["period_start"]))
            if pd.notna(execution_day):
                source = "period_start"

        if pd.isna(execution_day):
            execution_day = _first_paper_date_on_or_after(pd.Timestamp(row["decision_date"]))
            if pd.notna(execution_day):
                source = "decision_date_fallback"

        exec_days.append(execution_day)
        exec_sources.append(source)

    switch_rows["execution_day"] = exec_days
    switch_rows["execution_source"] = exec_sources

    mapped = switch_rows.loc[switch_rows["execution_day"].notna()].copy()
    if not mapped.empty:
        mapped = mapped.sort_values(["execution_day", "decision_date"]).drop_duplicates(
            subset=["execution_day"], keep="last"
        ).reset_index(drop=True)

    meta["mapped_transition_rows"] = int(len(mapped))
    meta["unmapped_transition_rows"] = int(len(switch_rows) - len(mapped))
    meta["mapping_sources"] = (
        mapped["execution_source"].value_counts(dropna=False).to_dict() if not mapped.empty else {}
    )

    return mapped[
        [
            "decision_date",
            "period_start",
            "period_end",
            "prev_governed_asset",
            "governed_asset",
            "execution_day",
            "execution_source",
        ]
    ].copy(), governance_switch_count, meta


def add_daily_position_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    prev_asset = out["held_asset"].shift(1)
    out["asset_transition_day"] = ((out["held_asset"] != prev_asset) & prev_asset.notna()).fillna(False)

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
    out["switch_day_forced_1x"] = out["is_exposed"] & out["asset_transition_day"]
    out["entry_buffer_day_forced_1x"] = out["is_exposed"] & (~out["asset_transition_day"]) & (out["days_in_position"] == 2)
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


def build_validation_wrapper(
    base_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    tradable_transition_df: pd.DataFrame,
    variant: ValidationVariant,
    annual_borrow_cost: float,
    tradable_transition_slippage_bps: float,
    trend_activation_threshold: float,
    stress_lookback_days: int,
    stress_off_threshold: float,
    stress_on_threshold: float,
) -> pd.DataFrame:
    merged = base_df.merge(trend_df, on="date", how="left")

    if merged["trend_score"].isna().any():
        merged["trend_score"] = merged["trend_score"].ffill().bfill()

    merged = add_daily_position_flags(merged)
    merged = add_baseline_stress_state(
        merged,
        lookback_days=stress_lookback_days,
        off_threshold=stress_off_threshold,
        on_threshold=stress_on_threshold,
    )

    tradable_day_map = {}
    if not tradable_transition_df.empty:
        tradable_day_map = (
            tradable_transition_df.set_index("execution_day")["governed_asset"].to_dict()
        )

    merged["tradable_transition_day"] = merged["date"].isin(list(tradable_day_map.keys()))
    merged["tradable_governed_asset"] = merged["date"].map(tradable_day_map).fillna("")

    merged["cash_day"] = ~merged["is_exposed"]
    merged["trend_gate_pass"] = pd.to_numeric(merged["trend_score"], errors="coerce").fillna(-999.0) >= trend_activation_threshold
    merged["trend_block_day"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_day_forced_1x"])
        & (~merged["trend_gate_pass"])
    )
    merged["stress_block_day"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_day_forced_1x"])
        & merged["trend_gate_pass"]
        & merged["stress_block_active"]
    )

    merged["leverage_eligible"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_day_forced_1x"])
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

    tradable_slippage_rate = float(tradable_transition_slippage_bps) / 10000.0
    merged["tradable_slippage_cost"] = np.where(
        merged["tradable_transition_day"],
        tradable_slippage_rate,
        0.0,
    )

    merged["realistic_ret_gross"] = merged["base_ret"] * merged["effective_leverage"]
    merged["realistic_ret"] = merged["realistic_ret_gross"] - merged["daily_borrow_cost"] - merged["tradable_slippage_cost"]
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
                merged["entry_buffer_day_forced_1x"],
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

    merged["trend_activation_threshold"] = float(trend_activation_threshold)
    merged["stress_off_threshold"] = float(stress_off_threshold)
    merged["stress_on_threshold"] = float(stress_on_threshold)
    merged["tradable_transition_slippage_bps"] = float(tradable_transition_slippage_bps)

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


def summarize_variant(
    model: str,
    df: pd.DataFrame,
    annual_borrow_cost: float,
    governance_switch_count: int,
    tradable_transition_count: int,
) -> dict:
    since2023 = subset_since(df, "2023-01-01")
    since2025 = subset_since(df, "2025-01-01")

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
        "tradable_transition_slippage_bps": float(df["tradable_transition_slippage_bps"].iloc[0]),
        "cagr_pct": round(cagr_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "calmar": round(calmar, 4) if pd.notna(calmar) else np.nan,
        "since2023_cagr_pct": round(compute_cagr_pct(since2023["realistic_ret"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2025_cagr_pct": round(compute_cagr_pct(since2025["realistic_ret"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "worst_day_pct": round(float(df["realistic_ret"].min() * 100.0), 2) if not df.empty else np.nan,
        "borrow_cost_total_pct": round(float(df["daily_borrow_cost"].sum() * 100.0), 4),
        "tradable_slippage_cost_total_pct": round(float(df["tradable_slippage_cost"].sum() * 100.0), 4),
        "governance_switch_count": int(governance_switch_count),
        "exposure_days": int(df["is_exposed"].sum()),
        "asset_transition_count": int(df["asset_transition_day"].sum()),
        "tradable_transition_count": int(tradable_transition_count),
        "eligible_days": int(df["leverage_eligible"].sum()),
        "leverage_active_days": int(df["leverage_active"].sum()),
        "trend_block_days": int(df["trend_block_day"].sum()),
        "stress_block_days": int(df["stress_block_day"].sum()),
        "held_asset_now": str(df["held_asset"].iloc[-1]) if not df.empty else "",
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
        "tradable_slippage_cost_total_pct",
    ]:
        out[f"delta_vs_1p00x_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(ref.get(metric), errors="coerce")
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE68F realistic leverage validation with governance-linked tradable transition basis")
    parser.add_argument("--paper", type=str, default=str(DEFAULT_PAPER))
    parser.add_argument("--trend-history", type=str, default=str(DEFAULT_TREND))
    parser.add_argument("--decisions", type=str, default=str(DEFAULT_DECISIONS))
    parser.add_argument("--annual-borrow-cost", type=float, default=0.12)
    parser.add_argument("--tradable-transition-slippage-bps", type=float, default=10.0)
    parser.add_argument("--trend-activation-threshold", type=float, default=0.10)
    parser.add_argument("--stress-lookback-days", type=int, default=20)
    parser.add_argument("--stress-off-threshold", type=float, default=-0.08)
    parser.add_argument("--stress-on-threshold", type=float, default=-0.04)
    args = parser.parse_args()

    ensure_dir(PHASE68F_DIR)
    papers_dir = PHASE68F_DIR / "papers"
    ensure_dir(papers_dir)

    paper_path = Path(args.paper)
    trend_path = Path(args.trend_history)
    decisions_path = Path(args.decisions)

    if not paper_path.exists():
        raise FileNotFoundError(f"Input paper sa nenašiel: {paper_path}")
    if not trend_path.exists():
        raise FileNotFoundError(f"Trend history sa nenašiel: {trend_path}")
    if not decisions_path.exists():
        raise FileNotFoundError(f"Decisions file sa nenašiel: {decisions_path}")

    log("[PHASE68F] Start")
    log(f"[PHASE68F] Input paper: {paper_path}")
    log(f"[PHASE68F] Trend history: {trend_path}")
    log(f"[PHASE68F] Decisions: {decisions_path}")
    log(f"[PHASE68F] Annual borrow cost: {args.annual_borrow_cost:.4f}")
    log(f"[PHASE68F] Tradable transition slippage bps: {args.tradable_transition_slippage_bps:.2f}")
    log(f"[PHASE68F] Trend activation threshold: {args.trend_activation_threshold:.4f}")
    log(f"[PHASE68F] Stress off / on: {args.stress_off_threshold:.4f} / {args.stress_on_threshold:.4f}")

    base_df = load_base_paper(paper_path)
    trend_df = load_trend_history(trend_path)
    decisions_df = load_governance_decisions(decisions_path)

    tradable_transition_df, governance_switch_count, mapping_meta = build_governance_transition_calendar(
        decisions_df=decisions_df,
        paper_dates=base_df["date"],
    )
    tradable_transition_count = int(len(tradable_transition_df))

    transition_calendar_path = PHASE68F_DIR / "phase68f_tradable_transition_calendar.csv"
    tradable_transition_df.to_csv(transition_calendar_path, index=False)

    summary_rows: list[dict] = []

    for variant in VARIANTS:
        log(f"[PHASE68F] running {variant.model} | target_leverage={variant.target_leverage:.2f}x")

        wrapped = build_validation_wrapper(
            base_df=base_df,
            trend_df=trend_df,
            tradable_transition_df=tradable_transition_df,
            variant=variant,
            annual_borrow_cost=float(args.annual_borrow_cost),
            tradable_transition_slippage_bps=float(args.tradable_transition_slippage_bps),
            trend_activation_threshold=float(args.trend_activation_threshold),
            stress_lookback_days=int(args.stress_lookback_days),
            stress_off_threshold=float(args.stress_off_threshold),
            stress_on_threshold=float(args.stress_on_threshold),
        )

        summary_rows.append(
            summarize_variant(
                model=variant.model,
                df=wrapped,
                annual_borrow_cost=float(args.annual_borrow_cost),
                governance_switch_count=int(governance_switch_count),
                tradable_transition_count=int(tradable_transition_count),
            )
        )

        wrapped.to_csv(papers_dir / f"{variant.model}_paper.csv", index=False)
        log(f"[PHASE68F] done {variant.model}")

    summary_df = pd.DataFrame(summary_rows)

    baseline_row = summary_df.loc[summary_df["model"] == "phase68f_66g_1p00x_baseline"]
    if baseline_row.empty:
        raise ValueError("Chýba 1.00x baseline row.")
    baseline = baseline_row.iloc[0].to_dict()

    compare_rows = [add_delta_cols(row, baseline) for row in summary_rows]
    compare_df = pd.DataFrame(compare_rows)
    compare_df = compare_df.sort_values(
        by=[
            "since2025_cagr_pct",
            "calmar",
            "cagr_pct",
            "max_drawdown_pct",
        ],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    focus_df = compare_df.loc[compare_df["model"] == "phase68f_66g_1p25x_candidate"]
    focus = focus_df.iloc[0].to_dict() if not focus_df.empty else compare_df.iloc[0].to_dict()

    summary_path = PHASE68F_DIR / "phase68f_realistic_leverage_summary.csv"
    compare_path = PHASE68F_DIR / "phase68f_realistic_leverage_compare.csv"
    manifest_path = PHASE68F_DIR / "phase68f_realistic_leverage_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)

    manifest = {
        "phase": "phase68f_realistic_leverage_validation_tradable_basis",
        "official_compare_baseline": "phase68f_66g_1p00x_baseline",
        "input_paper": str(paper_path),
        "trend_history": str(trend_path),
        "decisions_file": str(decisions_path),
        "params": {
            "annual_borrow_cost": float(args.annual_borrow_cost),
            "tradable_transition_slippage_bps": float(args.tradable_transition_slippage_bps),
            "trend_activation_threshold": float(args.trend_activation_threshold),
            "stress_lookback_days": int(args.stress_lookback_days),
            "stress_off_threshold": float(args.stress_off_threshold),
            "stress_on_threshold": float(args.stress_on_threshold),
            "cash_forced_1x": True,
            "switch_day_forced_1x": True,
            "entry_buffer_day_forced_1x": True,
            "slippage_basis": "governance-linked tradable transition day mapped from decision layer",
        },
        "transition_mapping_meta": mapping_meta,
        "governance_switch_count": int(governance_switch_count),
        "tradable_transition_count": int(tradable_transition_count),
        "transition_calendar_file": str(transition_calendar_path),
        "variants": [asdict(v) for v in VARIANTS],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "papers_dir": str(papers_dir),
        "notes": [
            "Opravený slippage basis: už nie daily held_asset transitions.",
            "Slippage sa ráta len na governance-linked tradable transition day.",
            "Metriky sú explicitne oddelené: governance_switch_count, exposure_days, asset_transition_count, tradable_transition_count.",
            "Borrow cost je účtovaný len pri reálne aktívnom leverage.",
            "Ostatné pravidlá ostávajú fixné oproti predchádzajúcej realistickej validation vetve.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE68F FOCUS RESULT (1.25x) ===")
    log(f"model: {focus['model']}")
    log(f"target_leverage: {float(focus['target_leverage']):.2f}x")
    log(f"cagr_pct: {float(focus['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(focus['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(focus['calmar']):.4f}")
    log(f"since2023_cagr_pct: {float(focus['since2023_cagr_pct']):.2f}")
    log(f"since2025_cagr_pct: {float(focus['since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_cagr_pct: {float(focus['delta_vs_1p00x_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_since2025_cagr_pct: {float(focus['delta_vs_1p00x_since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_max_drawdown_pct: {float(focus['delta_vs_1p00x_max_drawdown_pct']):.2f}")
    log(f"delta_vs_1p00x_calmar: {float(focus['delta_vs_1p00x_calmar']):.4f}")
    log(f"governance_switch_count: {int(pd.to_numeric(focus['governance_switch_count'], errors='coerce'))}")
    log(f"exposure_days: {int(pd.to_numeric(focus['exposure_days'], errors='coerce'))}")
    log(f"asset_transition_count: {int(pd.to_numeric(focus['asset_transition_count'], errors='coerce'))}")
    log(f"tradable_transition_count: {int(pd.to_numeric(focus['tradable_transition_count'], errors='coerce'))}")
    log(f"borrow_cost_total_pct: {float(focus['borrow_cost_total_pct']):.4f}")
    log(f"tradable_slippage_cost_total_pct: {float(focus['tradable_slippage_cost_total_pct']):.4f}")
    log("")

    log(f"[PHASE68F] Saved summary -> {summary_path}")
    log(f"[PHASE68F] Saved compare -> {compare_path}")
    log(f"[PHASE68F] Saved manifest -> {manifest_path}")
    log(f"[PHASE68F] Saved transition calendar -> {transition_calendar_path}")
    log(f"[PHASE68F] Saved papers -> {papers_dir}")


if __name__ == "__main__":
    main()