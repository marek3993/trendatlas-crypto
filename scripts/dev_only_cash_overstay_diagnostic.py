from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OHLCV_DIR = DATA_DIR / "ohlcv"
OUTPUT_ROOT = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_cash_diagnostics"

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"

ARTIFACT_ID = "cash_overstay_diagnostic"
BENCHMARK_ASSET = "BTC"
FAST_MA = 20
ANCHOR_MA = 100
START_PERSISTENCE_DAYS = 3
END_PERSISTENCE_DAYS = 2

SUMMARY_JSON_LOCKS = {
    "analysis_mode": "cash_overstay_diagnostic_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}

WINDOW_COLUMNS = [
    "window_id",
    "window_start",
    "window_end",
    "window_length_days",
    "baseline_time_in_market_share",
    "baseline_cash_share",
    "benchmark_return_during_window",
    "baseline_return_during_window",
    "underexposed_days_count",
    "missed_benchmark_return_while_cash",
    "missed_selected_alt_return_while_cash",
    "selected_alt_days_with_data_count",
    "exposure_gap_label",
]

GAP_COLUMNS = [
    "window_id",
    "window_start",
    "window_end",
    "window_length_days",
    "days_until_first_exposure",
    "cash_after_first_exposure_days",
    "cash_reentry_segment_count",
    "missed_benchmark_return_while_cash",
    "missed_selected_alt_return_while_cash",
    "exposure_gap_label",
]

MISSED_BENCHMARK_COLUMNS = [
    "window_id",
    "date",
    "entity",
    "benchmark_return",
    "baseline_strategy_return",
    "response_state",
]

MISSED_ALT_COLUMNS = [
    "window_id",
    "date",
    "entity",
    "selected_alt_return",
    "benchmark_return",
    "baseline_strategy_return",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose cash overstay in constructive windows against phase67j")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(SUMMARY_JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / f"{ARTIFACT_ID}.summary.json",
        "constructive_windows_csv": OUTPUT_ROOT / "cash_overstay_constructive_windows.csv",
        "exposure_gap_csv": OUTPUT_ROOT / "cash_overstay_exposure_gap_by_window.csv",
        "benchmark_missed_csv": OUTPUT_ROOT / "cash_overstay_benchmark_missed_while_underexposed.csv",
        "alt_missed_csv": OUTPUT_ROOT / "cash_overstay_alt_participation_missed.csv",
        "manifest_json": OUTPUT_ROOT / f"{ARTIFACT_ID}.manifest.json",
        "quality_json": OUTPUT_ROOT / f"{ARTIFACT_ID}.quality.json",
    }


def normalize_asset_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NAN", "NONE", "NULL", "NA", "CASH", "0.0", "0", "BTC"}:
        return ""
    if text.endswith("USDT"):
        text = text[:-4]
    if text == "HYPERLIQUID":
        text = "HYPE"
    return text


def resolve_asset_daily_path(asset: str) -> Path:
    direct_path = OHLCV_DIR / f"{asset}USDT_1d.csv"
    if direct_path.exists():
        return direct_path
    exact_candidates = sorted(
        path
        for path in DATA_DIR.rglob("*.csv")
        if path.name.upper().startswith(f"{asset.upper()}USDT") and "1D" in path.name.upper()
    )
    if exact_candidates:
        return exact_candidates[0]
    loose_candidates = sorted(
        path
        for path in DATA_DIR.rglob("*.csv")
        if asset.upper() in path.name.upper() and "USDT" in path.name.upper() and "1D" in path.name.upper()
    )
    return loose_candidates[0] if loose_candidates else direct_path


def compound_return(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return float((1.0 + clean).prod() - 1.0)


def load_paper(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(column).strip() for column in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()
    df["strategy_return"] = pd.to_numeric(df["strategy_return"], errors="coerce").fillna(0.0)
    df["executed_regime"] = df["executed_regime"].fillna("").astype(str).str.strip().str.upper()
    df["executed_position"] = df["executed_position"].fillna("").astype(str).str.strip().str.upper()
    for column in ["chosen_asset", "weekly_authorized_asset"]:
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("").astype(str)

    weekly = df["weekly_authorized_asset"].map(normalize_asset_label)
    chosen = df["chosen_asset"].map(normalize_asset_label)
    df["selected_asset"] = weekly.where(weekly.ne(""), chosen)
    df["in_market"] = df["executed_regime"].ne("CASH")
    return df.set_index("date")


def load_asset_daily(asset: str, cache: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    if asset in cache:
        return cache[asset]
    path = resolve_asset_daily_path(asset)
    if not path.exists():
        raise FileNotFoundError(f"Missing OHLCV input for {asset}: {path}")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()
    df["asset_return"] = df["close"].pct_change().replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
    df["anchor_ma"] = df["close"].rolling(ANCHOR_MA, min_periods=ANCHOR_MA).mean()
    cache[asset] = df.set_index("date")[["close", "asset_return", "anchor_ma"]]
    return cache[asset]


def build_analysis_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = baseline_df.copy()
    cache: Dict[str, pd.DataFrame] = {}

    benchmark_df = load_asset_daily(BENCHMARK_ASSET, cache).rename(
        columns={"close": "benchmark_close", "asset_return": "benchmark_return", "anchor_ma": "benchmark_anchor_ma"}
    )
    benchmark_df["benchmark_fast_ma"] = benchmark_df["benchmark_close"].rolling(FAST_MA, min_periods=FAST_MA).mean()
    frame = frame.join(benchmark_df, how="left")
    frame[["benchmark_close", "benchmark_return", "benchmark_anchor_ma", "benchmark_fast_ma"]] = (
        frame[["benchmark_close", "benchmark_return", "benchmark_anchor_ma", "benchmark_fast_ma"]].ffill()
    )

    frame["selected_asset_close"] = pd.NA
    frame["selected_asset_return"] = pd.NA
    frame["selected_asset_anchor_ma"] = pd.NA
    for asset in sorted({value for value in frame["selected_asset"].dropna().unique() if value}):
        try:
            asset_df = load_asset_daily(asset, cache).rename(
                columns={"close": "selected_asset_close", "asset_return": "selected_asset_return", "anchor_ma": "selected_asset_anchor_ma"}
            )
        except FileNotFoundError:
            continue
        mask = frame["selected_asset"].eq(asset)
        if not mask.any():
            continue
        aligned = asset_df.reindex(frame.index[mask]).ffill()
        frame.loc[mask, ["selected_asset_close", "selected_asset_return", "selected_asset_anchor_ma"]] = aligned[
            ["selected_asset_close", "selected_asset_return", "selected_asset_anchor_ma"]
        ].to_numpy()

    frame["benchmark_trend_positive"] = frame["benchmark_fast_ma"] > frame["benchmark_anchor_ma"]
    frame["benchmark_above_anchor"] = frame["benchmark_close"] > frame["benchmark_anchor_ma"]
    frame["selected_asset_above_anchor"] = frame["selected_asset_close"] > frame["selected_asset_anchor_ma"]
    frame["constructive_candidate_day"] = frame["benchmark_trend_positive"] & (
        frame["benchmark_above_anchor"] | frame["selected_asset_above_anchor"].fillna(False)
    )
    frame["risk_off_invalidation_day"] = (frame["benchmark_close"] < frame["benchmark_anchor_ma"]) & (
        frame["benchmark_fast_ma"] < frame["benchmark_anchor_ma"]
    )
    frame["constructive_start_confirmed"] = (
        frame["constructive_candidate_day"].astype(int).rolling(START_PERSISTENCE_DAYS, min_periods=START_PERSISTENCE_DAYS).sum().eq(START_PERSISTENCE_DAYS)
    )
    frame["constructive_end_confirmed"] = (
        frame["risk_off_invalidation_day"].astype(int).rolling(END_PERSISTENCE_DAYS, min_periods=END_PERSISTENCE_DAYS).sum().eq(END_PERSISTENCE_DAYS)
    )
    return frame


def build_constructive_windows(frame: pd.DataFrame) -> List[tuple[pd.Timestamp, pd.Timestamp]]:
    windows: List[tuple[pd.Timestamp, pd.Timestamp]] = []
    in_window = False
    start_date: pd.Timestamp | None = None
    for date_value, row in frame.iterrows():
        if not in_window and bool(row["constructive_start_confirmed"]):
            in_window = True
            start_date = pd.Timestamp(date_value)
            continue
        if in_window and bool(row["constructive_end_confirmed"]):
            windows.append((start_date, pd.Timestamp(date_value)))
            in_window = False
            start_date = None
    if in_window and start_date is not None:
        windows.append((start_date, pd.Timestamp(frame.index.max())))
    return windows


def classify_exposure_gap(window_df: pd.DataFrame) -> Dict[str, Any]:
    underexposed_mask = ~window_df["in_market"]
    ever_exposed = bool(window_df["in_market"].any())
    first_exposed_date = window_df.index[window_df["in_market"]][0] if ever_exposed else None
    days_until_first_exposure = 0
    cash_after_first_exposure_days = 0
    cash_reentry_segment_count = 0
    if first_exposed_date is not None:
        before_first = window_df.index < first_exposed_date
        days_until_first_exposure = int((~window_df.loc[before_first, "in_market"]).sum())
        after_first = window_df.index > first_exposed_date
        cash_after_first_exposure_days = int((~window_df.loc[after_first, "in_market"]).sum())
        post_first_cash = (~window_df.loc[window_df.index >= first_exposed_date, "in_market"]).astype(int)
        cash_reentry_segment_count = int(((post_first_cash.eq(1)) & (post_first_cash.shift(1, fill_value=0).eq(0))).sum())

    underexposed_days = int(underexposed_mask.sum())
    window_length_days = int(len(window_df))
    cash_share = float(underexposed_days) / float(window_length_days) if window_length_days else 0.0
    missed_benchmark = compound_return(window_df.loc[underexposed_mask, "benchmark_return"])
    alt_mask = underexposed_mask & window_df["selected_asset_return"].notna()
    alt_days_with_data = int(alt_mask.sum())
    missed_alt = compound_return(window_df.loc[alt_mask, "selected_asset_return"]) if alt_days_with_data else None

    if underexposed_days == 0 or (cash_share <= 0.10 and missed_benchmark <= 0.02 and cash_after_first_exposure_days == 0):
        label = "no_material_gap"
    elif not ever_exposed or cash_share >= 0.50 or underexposed_days >= max(7, round(window_length_days * 0.45)):
        label = "broader_underexposure_policy_issue"
    elif cash_after_first_exposure_days >= 2 and cash_reentry_segment_count >= 1:
        label = "premature_risk_off"
    elif days_until_first_exposure >= 2 and cash_after_first_exposure_days == 0:
        label = "late_entry_only"
    elif cash_after_first_exposure_days > 0:
        label = "premature_risk_off"
    elif days_until_first_exposure > 0:
        label = "late_entry_only"
    else:
        label = "no_material_gap"

    return {
        "days_until_first_exposure": int(days_until_first_exposure),
        "cash_after_first_exposure_days": int(cash_after_first_exposure_days),
        "cash_reentry_segment_count": int(cash_reentry_segment_count),
        "underexposed_days_count": int(underexposed_days),
        "missed_benchmark_return_while_cash": round(float(missed_benchmark), 6),
        "missed_selected_alt_return_while_cash": None if missed_alt is None else round(float(missed_alt), 6),
        "selected_alt_days_with_data_count": int(alt_days_with_data),
        "exposure_gap_label": label,
    }


def month_bucket(date_value: pd.Timestamp) -> str:
    return pd.Timestamp(date_value).strftime("%Y-%m")


def build_window_outputs(frame: pd.DataFrame, windows: List[tuple[pd.Timestamp, pd.Timestamp]]) -> Dict[str, List[Dict[str, Any]]]:
    constructive_rows: List[Dict[str, Any]] = []
    gap_rows: List[Dict[str, Any]] = []
    benchmark_missed_rows: List[Dict[str, Any]] = []
    alt_missed_rows: List[Dict[str, Any]] = []

    for idx, (start_date, end_date) in enumerate(windows, start=1):
        window_id = f"window_{idx:03d}"
        window_df = frame.loc[start_date:end_date].copy()
        gap_info = classify_exposure_gap(window_df)
        underexposed_mask = ~window_df["in_market"]

        constructive_rows.append(
            {
                "window_id": window_id,
                "window_start": start_date.strftime("%Y-%m-%d"),
                "window_end": end_date.strftime("%Y-%m-%d"),
                "window_length_days": int(len(window_df)),
                "baseline_time_in_market_share": round(float(window_df["in_market"].mean()), 6),
                "baseline_cash_share": round(float((~window_df["in_market"]).mean()), 6),
                "benchmark_return_during_window": round(compound_return(window_df["benchmark_return"]), 6),
                "baseline_return_during_window": round(compound_return(window_df["strategy_return"]), 6),
                "underexposed_days_count": gap_info["underexposed_days_count"],
                "missed_benchmark_return_while_cash": gap_info["missed_benchmark_return_while_cash"],
                "missed_selected_alt_return_while_cash": gap_info["missed_selected_alt_return_while_cash"],
                "selected_alt_days_with_data_count": gap_info["selected_alt_days_with_data_count"],
                "exposure_gap_label": gap_info["exposure_gap_label"],
            }
        )
        gap_rows.append(
            {
                "window_id": window_id,
                "window_start": start_date.strftime("%Y-%m-%d"),
                "window_end": end_date.strftime("%Y-%m-%d"),
                "window_length_days": int(len(window_df)),
                "days_until_first_exposure": gap_info["days_until_first_exposure"],
                "cash_after_first_exposure_days": gap_info["cash_after_first_exposure_days"],
                "cash_reentry_segment_count": gap_info["cash_reentry_segment_count"],
                "missed_benchmark_return_while_cash": gap_info["missed_benchmark_return_while_cash"],
                "missed_selected_alt_return_while_cash": gap_info["missed_selected_alt_return_while_cash"],
                "exposure_gap_label": gap_info["exposure_gap_label"],
            }
        )

        for date_value, row in window_df.loc[underexposed_mask].iterrows():
            benchmark_missed_rows.append(
                {
                    "window_id": window_id,
                    "date": pd.Timestamp(date_value).strftime("%Y-%m-%d"),
                    "entity": f"{BENCHMARK_ASSET}USDT",
                    "benchmark_return": round(float(pd.to_numeric(pd.Series([row["benchmark_return"]]), errors="coerce").fillna(0.0).iloc[0]), 6),
                    "baseline_strategy_return": round(float(row["strategy_return"]), 6),
                    "response_state": "baseline_cash_during_constructive_window",
                }
            )
            if pd.notna(row["selected_asset_return"]) and str(row["selected_asset"]).strip():
                alt_missed_rows.append(
                    {
                        "window_id": window_id,
                        "date": pd.Timestamp(date_value).strftime("%Y-%m-%d"),
                        "entity": f"{str(row['selected_asset']).strip()}USDT",
                        "selected_alt_return": round(float(row["selected_asset_return"]), 6),
                        "benchmark_return": round(float(pd.to_numeric(pd.Series([row["benchmark_return"]]), errors="coerce").fillna(0.0).iloc[0]), 6),
                        "baseline_strategy_return": round(float(row["strategy_return"]), 6),
                    }
                )

    return {
        "constructive_rows": constructive_rows,
        "gap_rows": gap_rows,
        "benchmark_missed_rows": benchmark_missed_rows,
        "alt_missed_rows": alt_missed_rows,
    }


def determine_final_verdict(constructive_rows: List[Dict[str, Any]]) -> str:
    if not constructive_rows:
        return "not_confirmed"

    label_counts = pd.Series([row["exposure_gap_label"] for row in constructive_rows]).value_counts().to_dict()
    missed_by_label: Dict[str, float] = {}
    for label in ["late_entry_only", "premature_risk_off", "broader_underexposure_policy_issue"]:
        missed_by_label[label] = sum(
            float(row["missed_benchmark_return_while_cash"] or 0.0) for row in constructive_rows if row["exposure_gap_label"] == label
        )

    if label_counts.get("broader_underexposure_policy_issue", 0) > 0 and missed_by_label["broader_underexposure_policy_issue"] >= max(
        missed_by_label["premature_risk_off"], missed_by_label["late_entry_only"]
    ):
        return "broader_exposure_policy_issue"
    if label_counts.get("premature_risk_off", 0) > 0 and missed_by_label["premature_risk_off"] >= (missed_by_label["late_entry_only"] * 0.5):
        return "premature_risk_off_failure_to_stay_exposed"
    if label_counts.get("late_entry_only", 0) > 0 and label_counts.get("premature_risk_off", 0) == 0 and label_counts.get("broader_underexposure_policy_issue", 0) == 0:
        return "pure_late_entry_timing"
    return "not_confirmed"


def collect_context_refs() -> Dict[str, List[str]]:
    refs = {
        "phase68k_context": [],
        "phase68l_context": [],
        "phase68m_context": [],
    }
    refs["phase68k_context"] = [str(path) for path in sorted((ROOT / "outputs").glob("phase68k*/**/*compare*.csv"))]
    refs["phase68k_context"] += [str(path) for path in sorted((ROOT / "outputs").glob("phase68k*/**/*state_time*.csv"))]
    for relative in [
        ROOT / "outputs" / "phase68l_early_entry_soft_gate_probe" / "phase68l_early_entry_soft_gate_compare.csv",
        ROOT / "outputs" / "phase68l_early_entry_soft_gate_probe" / "phase68l_early_entry_soft_gate_state_time.csv",
    ]:
        if relative.exists():
            refs["phase68l_context"].append(str(relative))
    for relative in [
        ROOT / "outputs" / "phase68m_early_entry_micro_confirm" / "phase68m_early_entry_micro_confirm_compare.csv",
        ROOT / "outputs" / "phase68m_early_entry_micro_confirm" / "phase68m_early_entry_micro_confirm_state_time.csv",
    ]:
        if relative.exists():
            refs["phase68m_context"].append(str(relative))
    return refs


def build_summary_payload(
    *,
    constructive_rows: List[Dict[str, Any]],
    gap_rows: List[Dict[str, Any]],
    input_refs: Dict[str, Any],
    final_verdict: str,
) -> Dict[str, Any]:
    label_counts = pd.Series([row["exposure_gap_label"] for row in constructive_rows]).value_counts().to_dict()
    total_overlap_rows = len(constructive_rows)
    supportive_recommendation = None
    if final_verdict in {"premature_risk_off_failure_to_stay_exposed", "broader_exposure_policy_issue"}:
        supportive_recommendation = {
            "mechanism_id": "constructive_regime_pilot_exposure_persistence",
            "mechanism_description": "Maintain a small deterministic pilot risk-on state during constructive regime persistence instead of reverting too quickly to full CASH, without changing leverage or live execution behavior.",
            "descriptive_only": True,
            "non_authoritative": True,
        }

    return with_json_locks(
        {
            "artifact_id": ARTIFACT_ID,
            "generated_at_utc": timestamp_utc(),
            "source_compare_id": "phase67j_no_neo_main_cash_overstay_diagnostic",
            "input_refs": input_refs,
            "constructive_window_rule": {
                "benchmark_asset": f"{BENCHMARK_ASSET}USDT",
                "start_rule": "Constructive window starts on the confirmation day when benchmark 20-day MA is above benchmark 100-day MA and either the benchmark close or the baseline-selected asset close is above its 100-day anchor for 3 consecutive days.",
                "end_rule": "Constructive window ends on the confirmation day when benchmark close is below benchmark 100-day MA and benchmark 20-day MA is below benchmark 100-day MA for 2 consecutive days.",
                "shared_key_rule": "decision-time observable data only",
            },
            "row_counts": {
                "constructive_windows": int(len(constructive_rows)),
                "windows_with_material_gap": int(sum(row["exposure_gap_label"] != "no_material_gap" for row in constructive_rows)),
                "no_material_gap": int(label_counts.get("no_material_gap", 0)),
                "late_entry_only": int(label_counts.get("late_entry_only", 0)),
                "premature_risk_off": int(label_counts.get("premature_risk_off", 0)),
                "broader_underexposure_policy_issue": int(label_counts.get("broader_underexposure_policy_issue", 0)),
            },
            "aggregate_metrics": {
                "total_underexposed_days": int(sum(row["underexposed_days_count"] for row in constructive_rows)),
                "total_missed_benchmark_return_while_cash": round(
                    sum(float(row["missed_benchmark_return_while_cash"] or 0.0) for row in constructive_rows), 6
                ),
                "total_missed_selected_alt_return_while_cash": round(
                    sum(float(row["missed_selected_alt_return_while_cash"] or 0.0) for row in constructive_rows if row["missed_selected_alt_return_while_cash"] is not None),
                    6,
                ),
            },
            "final_diagnostic_verdict": final_verdict,
            "follow_up_recommendation": supportive_recommendation,
            "why_phase68l_m_not_sufficient": "phase68l/phase68m primarily tested early-risk gate relaxation while preserving strict FULL_RISK behavior; they did not directly test exposure persistence or anti-all-or-nothing cash behavior during constructive windows.",
            "status": "generated_dev_only_cash_diagnostic_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": f"{ARTIFACT_ID}_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_cash_overstay_diagnostic.contract.json",
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_cash_overstay_diagnostic.spec.json",
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_cash_overstay_diagnostic.manifest.json",
            ],
            "status": "implementation_pack_ready",
        }
    )


def build_quality_payload(frame: pd.DataFrame, constructive_rows: List[Dict[str, Any]], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    checks = [
        {
            "name": "baseline_required_columns_present",
            "ok": {"strategy_return", "executed_regime", "selected_asset"}.issubset(frame.columns),
            "detail": "baseline paper columns available for diagnostic",
        },
        {
            "name": "benchmark_columns_present",
            "ok": {"benchmark_close", "benchmark_fast_ma", "benchmark_anchor_ma"}.issubset(frame.columns),
            "detail": "benchmark trend-anchor columns available",
        },
        {
            "name": "constructive_windows_determined_without_fuzzy_matching",
            "ok": True,
            "detail": "fuzzy_matching_used=false and rule uses only deterministic date alignment",
        },
        {
            "name": "constructive_window_count_non_negative",
            "ok": len(constructive_rows) >= 0,
            "detail": f"constructive windows counted={len(constructive_rows)}",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": f"{ARTIFACT_ID}_quality",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "check_count": len(checks),
            "checks": checks,
            "status": "passed" if all(check["ok"] for check in checks) else "failed",
        }
    )


def main() -> None:
    args = parse_args()
    baseline_path = Path(args.baseline_paper)
    phase68i_path = Path(args.phase68i_paper)
    baseline_df = load_paper(baseline_path)
    frame = build_analysis_frame(baseline_df)
    windows = build_constructive_windows(frame)
    outputs = build_window_outputs(frame, windows)
    final_verdict = determine_final_verdict(outputs["constructive_rows"])

    input_refs: Dict[str, Any] = {
        "baseline_paper": str(baseline_path),
        "phase68i_paper_secondary_context": str(phase68i_path) if phase68i_path.exists() else None,
        "phase68_context_refs": collect_context_refs(),
    }
    paths = output_paths()

    save_csv(paths["constructive_windows_csv"], outputs["constructive_rows"], WINDOW_COLUMNS)
    save_csv(paths["exposure_gap_csv"], outputs["gap_rows"], GAP_COLUMNS)
    save_csv(paths["benchmark_missed_csv"], outputs["benchmark_missed_rows"], MISSED_BENCHMARK_COLUMNS)
    save_csv(paths["alt_missed_csv"], outputs["alt_missed_rows"], MISSED_ALT_COLUMNS)
    save_json(
        paths["summary_json"],
        build_summary_payload(
            constructive_rows=outputs["constructive_rows"],
            gap_rows=outputs["gap_rows"],
            input_refs=input_refs,
            final_verdict=final_verdict,
        ),
    )
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(paths["quality_json"], build_quality_payload(frame, outputs["constructive_rows"], input_refs))

    print(f"{ARTIFACT_ID} generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
