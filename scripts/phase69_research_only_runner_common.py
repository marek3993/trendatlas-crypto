from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional


PRIMARY_COMPARE_TARGET = "phase67j_no_neo_main"
SECONDARY_COMPARE_TARGET = "phase68i_dynamic_ladder_candidate"
SECONDARY_COMPARE_USAGE = "overlay_context_suitability_only"
LEVERAGE_POLICY = "downstream_only_evidence_gated"
SUPPORTED_MECHANISM_FAMILY_IDS = frozenset(
    {
        "pre_move_compression_release_quality",
        "micro_acceleration_before_expansion",
        "participation_divergence_instability_filter",
        "compression_release_quality_context_gate",
        "instability_veto_confirmed_divergence",
        "instability_veto_confirmed_divergence_selective_toxic_subset",
    }
)

PRE_WINDOW = 3
FORWARD_WINDOW = 3
STRICT_SCORE_PENALTY = 0.01
RESEARCH_STATUS = "mechanism_scored_minimal_engine_v1"
VETO_STYLE_FAMILIES = {
    "participation_divergence_instability_filter",
    "instability_veto_confirmed_divergence",
    "instability_veto_confirmed_divergence_selective_toxic_subset",
}


@dataclass(frozen=True)
class FamilyConfig:
    family_id: str
    state_label: str
    evidence_gate_reason: str
    family_note: str


def get_supported_mechanism_family_ids() -> tuple[str, ...]:
    return tuple(sorted(SUPPORTED_MECHANISM_FAMILY_IDS))


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def timestamp_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


class Runtime:
    def __init__(self, script_name: str) -> None:
        self.script_name = script_name
        self.started = time.monotonic()

    def log(self, message: str) -> None:
        print(f"[{timestamp_local()}] [{self.script_name}] {message}", flush=True)

    def finish(self) -> None:
        elapsed = time.monotonic() - self.started
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")


def parse_args(script_name: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{script_name} phase69 mechanism-first runner")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--mechanism", required=True)
    parser.add_argument("--primary-compare-target", required=True)
    parser.add_argument("--primary-compare-paper", required=True)
    parser.add_argument("--secondary-compare-target", default="")
    parser.add_argument("--secondary-compare-usage", default="")
    parser.add_argument("--leverage-policy", required=True)
    parser.add_argument("--failure-criteria", required=True)
    parser.add_argument("--stop-condition", action="append", default=[])
    parser.add_argument("--run-dir", default="")
    return parser.parse_args()


def save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def require_file(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"missing required {label}: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_dir():
        raise RuntimeError(f"missing required {label}: {path}")
    return path


def to_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def resolve_run_dir(args: argparse.Namespace) -> Path:
    raw = args.run_dir or os.environ.get("RESEARCH_OS_RUN_DIR", "")
    if not raw:
        raise RuntimeError("missing run dir: use --run-dir or RESEARCH_OS_RUN_DIR")
    return require_dir(Path(raw), "run_dir")


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_secondary_compare_paper(project_root: Path, args: argparse.Namespace) -> Optional[Path]:
    if not args.secondary_compare_target:
        return None
    if args.secondary_compare_target != SECONDARY_COMPARE_TARGET:
        raise RuntimeError(
            f"secondary compare must be {SECONDARY_COMPARE_TARGET} when provided, got {args.secondary_compare_target}"
        )
    if args.secondary_compare_usage != SECONDARY_COMPARE_USAGE:
        raise RuntimeError(
            f"secondary compare usage must be {SECONDARY_COMPARE_USAGE}, got {args.secondary_compare_usage}"
        )
    return require_file(
        project_root / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv",
        "secondary_compare_paper",
    )


def validate_contract(args: argparse.Namespace) -> None:
    if args.mode != "research":
        raise RuntimeError(f"mode must be research, got {args.mode}")
    if args.primary_compare_target != PRIMARY_COMPARE_TARGET:
        raise RuntimeError(
            f"primary compare target must remain {PRIMARY_COMPARE_TARGET}, got {args.primary_compare_target}"
        )
    if args.leverage_policy != LEVERAGE_POLICY:
        raise RuntimeError(f"leverage policy must remain {LEVERAGE_POLICY}, got {args.leverage_policy}")
    if bool(args.secondary_compare_target) != bool(args.secondary_compare_usage):
        raise RuntimeError("secondary compare target and usage must either both exist or both be empty")
    if not args.stop_condition:
        raise RuntimeError("at least one stop condition is required")


def event_kind(row: Dict[str, str]) -> str:
    labels: List[str] = []
    if to_bool(row.get("crossed_up_today", "")):
        labels.append("cross_up")
    if to_bool(row.get("tradable_transition_day", "")):
        labels.append("tradable_transition")
    if to_bool(row.get("asset_transition_day", "")):
        labels.append("asset_transition")
    return "+".join(labels) if labels else "context_only"


def forward_baseline_return(
    baseline_by_date: Dict[str, Dict[str, str]],
    overlay_rows: List[Dict[str, str]],
    start_idx: int,
) -> Optional[float]:
    growth = 1.0
    for idx in range(start_idx + 1, start_idx + 1 + FORWARD_WINDOW):
        if idx >= len(overlay_rows):
            return None
        next_date = overlay_rows[idx].get("date", "")
        next_baseline = baseline_by_date.get(next_date)
        if next_baseline is None:
            return None
        growth *= 1.0 + to_float(next_baseline.get("strategy_return", 0.0))
    return growth - 1.0


def build_events(
    baseline_rows: List[Dict[str, str]],
    overlay_rows: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    baseline_by_date = {row.get("date", ""): row for row in baseline_rows}
    events: List[Dict[str, Any]] = []

    for idx, row in enumerate(overlay_rows):
        trigger = (
            to_bool(row.get("crossed_up_today", ""))
            or to_bool(row.get("tradable_transition_day", ""))
            or to_bool(row.get("asset_transition_day", ""))
        )
        if not trigger or idx < PRE_WINDOW or idx + FORWARD_WINDOW >= len(overlay_rows):
            continue

        date_value = row.get("date", "")
        baseline_row = baseline_by_date.get(date_value)
        if baseline_row is None:
            continue

        forward_return = forward_baseline_return(baseline_by_date, overlay_rows, idx)
        if forward_return is None:
            continue

        pre_rows = overlay_rows[idx - PRE_WINDOW : idx]
        pre_abs_returns = [abs(to_float(item.get("base_ret", 0.0))) for item in pre_rows]
        if not pre_abs_returns:
            continue

        events.append(
            {
                "date": date_value,
                "event_kind": event_kind(row),
                "forward_baseline_return_h3": forward_return,
                "baseline_regime_on_event": baseline_row.get("executed_regime", ""),
                "baseline_asset_on_event": baseline_row.get("chosen_asset", ""),
                "pre_mean_abs_base_ret": mean(pre_abs_returns),
                "pre_abs_range": max(pre_abs_returns) - min(pre_abs_returns),
                "trend_accel": to_float(row.get("trend_score", 0.0)) - to_float(row.get("prev_trend_score", 0.0)),
                "trend_build": to_float(row.get("trend_score", 0.0)) - to_float(pre_rows[0].get("trend_score", 0.0)),
                "trend_gate_pass": to_bool(row.get("trend_gate_pass", "")),
                "stress_active": to_bool(row.get("stress_block_active", "")),
                "trend_block": to_bool(row.get("trend_block_day", "")),
                "stress_block": to_bool(row.get("stress_block_day", "")),
                "leverage_eligible": to_bool(row.get("leverage_eligible", "")),
                "crossed_up_today": to_bool(row.get("crossed_up_today", "")),
                "tradable_transition_day": to_bool(row.get("tradable_transition_day", "")),
                "asset_transition_day": to_bool(row.get("asset_transition_day", "")),
                "target_leverage": to_float(row.get("target_leverage", 1.0), 1.0),
                "overlay_trend_score": to_float(row.get("trend_score", 0.0)),
                "overlay_equity_curve": to_float(row.get("equity_curve", 0.0)),
            }
        )

    return events


def select_family(event: Dict[str, Any], family_id: str, medians: Dict[str, float]) -> Dict[str, Any]:
    if family_id not in SUPPORTED_MECHANISM_FAMILY_IDS:
        raise RuntimeError(f"unsupported family_id: {family_id}")

    if family_id == "pre_move_compression_release_quality":
        checks = [
            event["pre_mean_abs_base_ret"] <= medians["pre_mean_abs_base_ret"],
            event["pre_abs_range"] <= medians["pre_abs_range"],
            event["trend_accel"] > 0.0,
            event["trend_gate_pass"],
            not event["stress_active"],
            not event["trend_block"],
        ]
        mechanism_signal = mean([1.0 if value else 0.0 for value in checks])
        selected = mechanism_signal >= (5.0 / 6.0) and (event["crossed_up_today"] or event["tradable_transition_day"])
        vetoed = False
        label = "compression_release_quality"
    elif family_id == "micro_acceleration_before_expansion":
        checks = [
            event["trend_build"] > medians["trend_build"],
            event["trend_accel"] > 0.0,
            event["trend_gate_pass"],
            event["leverage_eligible"],
            not event["stress_active"],
        ]
        mechanism_signal = mean([1.0 if value else 0.0 for value in checks])
        selected = mechanism_signal >= 0.8
        vetoed = False
        label = "micro_acceleration_before_expansion"
    elif family_id == "participation_divergence_instability_filter":
        instability_flags = [
            event["trend_block"],
            event["stress_block"],
            not event["trend_gate_pass"],
            not event["leverage_eligible"],
            event["trend_accel"] <= 0.0,
            event["pre_mean_abs_base_ret"] > medians["pre_mean_abs_base_ret"],
        ]
        instability_count = sum(1 for value in instability_flags if value)
        mechanism_signal = 1.0 - (instability_count / len(instability_flags))
        vetoed = instability_count >= 4
        selected = not vetoed
        label = "participation_divergence_instability_filter"
    elif family_id == "compression_release_quality_context_gate":
        context_checks = [
            event["pre_mean_abs_base_ret"] <= medians["pre_mean_abs_base_ret"],
            event["pre_abs_range"] <= medians["pre_abs_range"],
            event["trend_accel"] > 0.0,
            event["trend_build"] > medians["trend_build"],
            event["trend_gate_pass"],
            event["leverage_eligible"],
            not event["stress_active"],
            not event["trend_block"],
            not event["stress_block"],
        ]
        mechanism_signal = mean([1.0 if value else 0.0 for value in context_checks])
        selected = mechanism_signal >= (7.0 / 9.0) and (event["crossed_up_today"] or event["tradable_transition_day"])
        vetoed = False
        label = "compression_release_quality_context_gate"
    elif family_id == "instability_veto_confirmed_divergence":
        divergence_confirmed = (
            (
                event["pre_mean_abs_base_ret"] > medians["pre_mean_abs_base_ret"]
                and event["pre_abs_range"] > medians["pre_abs_range"]
            )
            or (event["trend_accel"] <= 0.0 and event["trend_build"] <= medians["trend_build"])
        )
        instability_flags = [
            event["trend_block"],
            event["stress_block"],
            event["stress_active"],
            not event["trend_gate_pass"],
            not event["leverage_eligible"],
        ]
        instability_count = sum(1 for value in instability_flags if value)
        vetoed = divergence_confirmed and instability_count >= 2
        mechanism_signal = 1.0 - (
            min(instability_count, len(instability_flags)) / len(instability_flags)
        )
        if divergence_confirmed:
            mechanism_signal = max(mechanism_signal - 0.2, 0.0)
        selected = not vetoed
        label = "instability_veto_confirmed_divergence"
    elif family_id == "instability_veto_confirmed_divergence_selective_toxic_subset":
        divergence_confirmed = (
            (
                event["pre_mean_abs_base_ret"] > medians["pre_mean_abs_base_ret"]
                and event["pre_abs_range"] > medians["pre_abs_range"]
            )
            or (event["trend_accel"] <= 0.0 and event["trend_build"] <= medians["trend_build"])
        )
        instability_flags = [
            event["trend_block"],
            event["stress_block"],
            event["stress_active"],
            not event["trend_gate_pass"],
            not event["leverage_eligible"],
        ]
        instability_count = sum(1 for value in instability_flags if value)
        selective_toxic_subset = divergence_confirmed and (
            instability_count >= 3
            or (
                instability_count >= 2
                and event["trend_accel"] <= 0.0
                and event["trend_build"] <= medians["trend_build"]
            )
            or (
                instability_count >= 2
                and event["stress_active"]
                and (event["trend_block"] or event["stress_block"])
            )
        )
        vetoed = selective_toxic_subset
        mechanism_signal = 1.0 - (
            min(instability_count, len(instability_flags)) / len(instability_flags)
        )
        if divergence_confirmed:
            mechanism_signal = max(mechanism_signal - 0.1, 0.0)
        if selective_toxic_subset:
            mechanism_signal = max(mechanism_signal - 0.15, 0.0)
        selected = not vetoed
        label = "instability_veto_confirmed_divergence_selective_toxic_subset"
    return {
        "mechanism_signal": mechanism_signal,
        "selected_for_family": selected,
        "vetoed_by_family": vetoed,
        "family_logic_label": label,
    }


def evaluate_family(events: List[Dict[str, Any]], config: FamilyConfig) -> Dict[str, Any]:
    if not events:
        raise RuntimeError("no phase69 trigger events available for mechanism evaluation")

    medians = {
        "pre_mean_abs_base_ret": median([event["pre_mean_abs_base_ret"] for event in events]),
        "pre_abs_range": median([event["pre_abs_range"] for event in events]),
        "trend_build": median([event["trend_build"] for event in events]),
    }

    evaluated_rows: List[Dict[str, Any]] = []
    for event in events:
        flags = select_family(event, config.family_id, medians)
        evaluated_rows.append({**event, **flags})

    reference_returns = [row["forward_baseline_return_h3"] for row in evaluated_rows]
    selected_rows = [row for row in evaluated_rows if row["selected_for_family"]]
    selected_returns = [row["forward_baseline_return_h3"] for row in selected_rows]
    vetoed_rows = [row for row in evaluated_rows if row["vetoed_by_family"]]
    vetoed_returns = [row["forward_baseline_return_h3"] for row in vetoed_rows]

    reference_avg = mean(reference_returns)
    selected_avg = mean(selected_returns)
    reference_win_rate = mean([1.0 if value > 0.0 else 0.0 for value in reference_returns])
    selected_win_rate = mean([1.0 if value > 0.0 else 0.0 for value in selected_returns])
    raw_edge = selected_avg - reference_avg

    if config.family_id in VETO_STYLE_FAMILIES:
        veto_avg = mean(vetoed_returns)
        veto_ratio = len(vetoed_rows) / len(evaluated_rows)
        avoided_damage = max(reference_avg - veto_avg, 0.0)
        strict_score = ((selected_avg - reference_avg) + avoided_damage) * veto_ratio - STRICT_SCORE_PENALTY
        coverage_ratio = veto_ratio
        compare_detail = {
            "vetoed_event_count": len(vetoed_rows),
            "vetoed_avg_forward_return_h3": veto_avg,
            "avoided_damage_h3": avoided_damage,
        }
    else:
        coverage_ratio = len(selected_rows) / len(evaluated_rows)
        strict_score = raw_edge * coverage_ratio - STRICT_SCORE_PENALTY
        compare_detail = {
            "vetoed_event_count": 0,
            "vetoed_avg_forward_return_h3": 0.0,
            "avoided_damage_h3": 0.0,
        }

    strict_verdict = "candidate_above_strict_threshold" if strict_score > 0.0 else "not_worthy_under_strict_scoring"

    return {
        "evaluated_rows": evaluated_rows,
        "selected_rows": selected_rows,
        "reference_event_count": len(evaluated_rows),
        "selected_event_count": len(selected_rows),
        "reference_avg_forward_return_h3": reference_avg,
        "selected_avg_forward_return_h3": selected_avg,
        "reference_win_rate": reference_win_rate,
        "selected_win_rate": selected_win_rate,
        "raw_edge_h3": raw_edge,
        "coverage_ratio": coverage_ratio,
        "score": strict_score,
        "strict_verdict": strict_verdict,
        **compare_detail,
    }


def build_summary_row(
    experiment_id: str,
    config: FamilyConfig,
    args: argparse.Namespace,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "model": experiment_id,
        "mechanism_family": config.family_id,
        "new_state_label": config.state_label,
        "research_status": RESEARCH_STATUS,
        "strict_scoring_ready": 1,
        "numeric_score_ready": 1,
        "score": result["score"],
        "primary_metric_value": result["score"],
        "strict_verdict": result["strict_verdict"],
        "reference_event_count": result["reference_event_count"],
        "selected_event_count": result["selected_event_count"],
        "coverage_ratio": result["coverage_ratio"],
        "selected_avg_forward_return_h3": result["selected_avg_forward_return_h3"],
        "reference_avg_forward_return_h3": result["reference_avg_forward_return_h3"],
        "selected_win_rate": result["selected_win_rate"],
        "reference_win_rate": result["reference_win_rate"],
        "raw_edge_h3": result["raw_edge_h3"],
        "primary_compare_target": args.primary_compare_target,
        "secondary_compare_target": args.secondary_compare_target,
        "secondary_compare_usage": args.secondary_compare_usage,
        "leverage_policy": args.leverage_policy,
        "hypothesis": args.hypothesis,
        "mechanism": args.mechanism,
        "failure_criteria": args.failure_criteria,
        "stop_conditions": " | ".join(args.stop_condition),
        "evidence_gate_reason": config.evidence_gate_reason,
        "family_note": config.family_note,
    }


def build_compare_row(
    experiment_id: str,
    args: argparse.Namespace,
    config: FamilyConfig,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "candidate_model": experiment_id,
        "baseline_model": args.primary_compare_target,
        "secondary_context_model": args.secondary_compare_target,
        "secondary_usage": args.secondary_compare_usage,
        "compare_valid": 1,
        "compare_scope": "primary_baseline_with_phase68i_overlay_context_only",
        "research_status": RESEARCH_STATUS,
        "strict_scoring_ready": 1,
        "score": result["score"],
        "primary_metric_value": result["score"],
        "strict_verdict": result["strict_verdict"],
        "reference_event_count": result["reference_event_count"],
        "selected_event_count": result["selected_event_count"],
        "vetoed_event_count": result["vetoed_event_count"],
        "coverage_ratio": result["coverage_ratio"],
        "selected_avg_forward_return_h3": result["selected_avg_forward_return_h3"],
        "reference_avg_forward_return_h3": result["reference_avg_forward_return_h3"],
        "vetoed_avg_forward_return_h3": result["vetoed_avg_forward_return_h3"],
        "raw_edge_h3": result["raw_edge_h3"],
        "avoided_damage_h3": result["avoided_damage_h3"],
        "family_note": config.family_note,
    }


def build_paper_rows(
    evaluated_rows: List[Dict[str, Any]],
    config: FamilyConfig,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for event in evaluated_rows:
        rows.append(
            {
                "date": event["date"],
                "mechanism_family": config.family_id,
                "event_kind": event["event_kind"],
                "family_logic_label": event["family_logic_label"],
                "selected_for_family": int(event["selected_for_family"]),
                "vetoed_by_family": int(event["vetoed_by_family"]),
                "mechanism_signal": event["mechanism_signal"],
                "forward_baseline_return_h3": event["forward_baseline_return_h3"],
                "pre_mean_abs_base_ret": event["pre_mean_abs_base_ret"],
                "pre_abs_range": event["pre_abs_range"],
                "trend_accel": event["trend_accel"],
                "trend_build": event["trend_build"],
                "trend_gate_pass": int(event["trend_gate_pass"]),
                "stress_active": int(event["stress_active"]),
                "trend_block": int(event["trend_block"]),
                "stress_block": int(event["stress_block"]),
                "leverage_eligible": int(event["leverage_eligible"]),
                "target_leverage": event["target_leverage"],
                "baseline_regime_on_event": event["baseline_regime_on_event"],
                "baseline_asset_on_event": event["baseline_asset_on_event"],
                "overlay_trend_score": event["overlay_trend_score"],
                "overlay_equity_curve": event["overlay_equity_curve"],
            }
        )
    return rows


def run_family(config: FamilyConfig, script_name: str) -> None:
    rt = Runtime(script_name)
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    args = parse_args(script_name)
    validate_contract(args)

    project_root = resolve_project_root()
    run_dir = resolve_run_dir(args)
    experiment_id = os.environ.get("RESEARCH_OS_EXPERIMENT_ID", config.family_id)

    baseline_paper = require_file(Path(args.primary_compare_paper), "primary_compare_paper")
    secondary_paper = resolve_secondary_compare_paper(project_root, args)
    if secondary_paper is None:
        raise RuntimeError("phase69 minimal mechanism engine requires secondary overlay/context paper")

    baseline_rows = read_csv_rows(baseline_paper)
    overlay_rows = read_csv_rows(secondary_paper)
    if not baseline_rows:
        raise RuntimeError(f"primary compare paper is empty: {baseline_paper}")
    if not overlay_rows:
        raise RuntimeError(f"secondary compare paper is empty: {secondary_paper}")

    events = build_events(baseline_rows, overlay_rows)
    result = evaluate_family(events, config)

    summary_path = run_dir / "summary.csv"
    compare_path = run_dir / "compare.csv"
    paper_path = run_dir / "paper.csv"
    report_path = run_dir / "phase69_runner_note.json"

    summary_row = build_summary_row(experiment_id, config, args, result)
    compare_row = build_compare_row(experiment_id, args, config, result)
    paper_rows = build_paper_rows(result["evaluated_rows"], config)

    save_csv(summary_path, [summary_row], list(summary_row.keys()))
    save_csv(compare_path, [compare_row], list(compare_row.keys()))
    save_csv(paper_path, paper_rows, list(paper_rows[0].keys()))
    save_json(
        report_path,
        {
            "experiment_id": experiment_id,
            "mechanism_family": config.family_id,
            "research_status": RESEARCH_STATUS,
            "strict_scoring_ready": True,
            "numeric_score_ready": True,
            "score": result["score"],
            "strict_verdict": result["strict_verdict"],
            "primary_compare_target": args.primary_compare_target,
            "primary_compare_paper": str(baseline_paper),
            "secondary_compare_target": args.secondary_compare_target,
            "secondary_compare_usage": args.secondary_compare_usage,
            "secondary_compare_paper": str(secondary_paper),
            "reference_event_count": result["reference_event_count"],
            "selected_event_count": result["selected_event_count"],
            "vetoed_event_count": result["vetoed_event_count"],
            "selected_avg_forward_return_h3": result["selected_avg_forward_return_h3"],
            "reference_avg_forward_return_h3": result["reference_avg_forward_return_h3"],
            "created_at": timestamp_utc(),
        },
    )

    rt.log(f"experiment_id={experiment_id}")
    rt.log(f"mechanism_family={config.family_id}")
    rt.log(f"reference_event_count={result['reference_event_count']}")
    rt.log(f"selected_event_count={result['selected_event_count']}")
    rt.log(f"score={result['score']}")
    rt.log(f"strict_verdict={result['strict_verdict']}")
    rt.finish()


def main_guard(config: FamilyConfig, script_name: str) -> None:
    try:
        run_family(config, script_name)
    except Exception as exc:
        print(f"[{timestamp_local()}] [{script_name}] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{timestamp_local()}] [{script_name}] TRACE {line}", flush=True)
        raise
