from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IDEATION_POLICY_PATH = ROOT / "research_os" / "policies" / "research_os_ideation_policy_v1.json"
MUTATION_POLICY_PATH = ROOT / "research_os" / "policies" / "research_os_mutation_space_policy_v1.json"
OUTPUT_DIR = ROOT / "outputs" / "research_os_ideation_v1"
OUTPUT_JSON = OUTPUT_DIR / "ideation_hypotheses.json"
OUTPUT_CSV = OUTPUT_DIR / "ideation_summary.csv"
OUTPUT_LOG = OUTPUT_DIR / "ideation_decision_log.jsonl"


class IdeationError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise IdeationError(f"Missing required json: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def make_id(label: str) -> str:
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
    return f"hyp_{digest}"


def wave_templates(wave: str) -> list[dict[str, Any]]:
    if wave == "wave2":
        return [
            {
                "hypothesis_label": "core_loss_shape_response_v1",
                "mutation_family": "loss_shape_response",
                "family_name": "loss_shape_response",
                "hypothesis_text": "Differentiate single shock days from clustered weakness and apply different recovery, brake and re-entry logic.",
                "rationale": "Baseline may respond the same way to single shocks and clustered weakness even though they imply different recovery behavior.",
                "known_baseline_weakness": "Same response to different stress shapes.",
                "exact_mechanism_of_improvement": "Classify shock vs clustered weakness and trigger different recovery/brake/re-entry rules.",
                "new_state_or_new_classification": "New stress-shape classifier and state-dependent response logic.",
                "exact_compare_target": "phase66g_production_soft_filters",
                "why_not_parameter_tuning": "Introduces a new state classification and response logic, not a threshold or weight tweak.",
                "primary_expected_metric_improvement": "DD",
                "why_expected_edge_should_survive_strict_scoring": "Targets a distinct stress-shape failure mode with explicit differentiated response rules.",
                "loss_shape_classifier_name": "shock_vs_clustered_weakness_classifier",
                "shock_vs_cluster_logic": "single_day_shock_vs_multi_day_clustered_weakness",
                "recovery_or_brake_rule": "shock_gets_fast_stabilization_check_cluster_gets_slower_reentry_and_brake"
            }
        ]

    return [
        {
            "hypothesis_label": "core_signal_disagreement_veto_v1",
            "mutation_family": "signal_disagreement_veto",
            "family_name": "signal_disagreement_veto",
            "hypothesis_text": "Block or reduce risk-on activation when trend state, leader strength and market-state confirmation disagree on ambiguous regime days.",
            "rationale": "Baseline appears vulnerable to false risk-on activation on ambiguous regime days when internal confirmation layers disagree.",
            "known_baseline_weakness": "False risk-on activation on ambiguous regime days.",
            "exact_mechanism_of_improvement": "Introduce a veto/reduction rule when named confirmation layers disagree instead of allowing normal risk-on activation.",
            "new_state_or_new_classification": "New veto logic across confirmation layers.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_not_parameter_tuning": "Introduces a new logical relationship between signals rather than changing a threshold or weight.",
            "primary_expected_metric_improvement": "Calmar",
            "why_expected_edge_should_survive_strict_scoring": "Targets one named false activation pattern with a discrete veto mechanism.",
            "disagreement_layers_named": "trend_state_vs_leader_strength_vs_market_state_confirmation",
            "veto_or_reduction_mode": "risk_on_block_or_reduced_activation",
            "named_false_activation_pattern": "ambiguous_regime_day_false_risk_on"
        },
        {
            "hypothesis_label": "core_transition_state_machine_v1",
            "mutation_family": "transition_state_machine",
            "family_name": "transition_state_machine",
            "hypothesis_text": "Add an explicit transition state between cash and full risk-on and require follow-through before full activation.",
            "rationale": "Baseline appears vulnerable to churn during cash-to-risk-on and risk-on-to-cash transition windows.",
            "known_baseline_weakness": "Churn on cash ↔ risk-on transitions.",
            "exact_mechanism_of_improvement": "Insert a new transition state that must pass a follow-through confirmation before full risk-on activation.",
            "new_state_or_new_classification": "New transition state and transition flow rule.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_not_parameter_tuning": "Introduces a new state and new flow rules, not a parameter shift.",
            "primary_expected_metric_improvement": "DD",
            "why_expected_edge_should_survive_strict_scoring": "Targets the transition window failure mode directly instead of tuning stable-state parameters.",
            "named_transition_state": "pending_risk_on_transition",
            "follow_through_requirement": "second_step_confirmation_before_full_activation",
            "named_transition_failure_mode": "cash_risk_on_transition_churn"
        },
        {
            "hypothesis_label": "core_trend_acceleration_confirmation_v1",
            "mutation_family": "trend_acceleration_confirmation",
            "family_name": "trend_acceleration_confirmation",
            "hypothesis_text": "Require trend direction or acceleration confirmation, not just positive trend level, before risk-on activation in weakening but still-positive trend states.",
            "rationale": "Baseline can enter late into weakening but still-positive trends because it relies too much on level and too little on strengthening vs weakening.",
            "known_baseline_weakness": "Late entries into weakening but still-positive trend.",
            "exact_mechanism_of_improvement": "Augment level-based trend logic with a direction/acceleration confirmation transform before activation.",
            "new_state_or_new_classification": "New signal transform from level-only to level-plus-acceleration confirmation.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_not_parameter_tuning": "Changes signal type from level-only to level-plus-acceleration, not just a threshold adjustment.",
            "primary_expected_metric_improvement": "since2025",
            "why_expected_edge_should_survive_strict_scoring": "Targets a named late-entry failure mode with a new confirmation transform.",
            "trend_signal_name": "trend_score",
            "acceleration_or_direction_transform": "trend_direction_or_acceleration_confirmation",
            "named_late_entry_failure_mode": "weakening_but_positive_trend_late_entry"
        }
    ]


def validate_candidate(candidate: dict[str, Any], ideation_policy: dict[str, Any], mutation_policy: dict[str, Any]) -> tuple[bool, str]:
    for field in ideation_policy["global_required_fields"]:
        if candidate.get(field) in (None, "", []):
            return False, f"missing_global_field:{field}"

    family = candidate["mutation_family"]
    for field in ideation_policy["family_specific_required_fields"].get(family, []):
        if candidate.get(field) in (None, "", []):
            return False, f"missing_family_field:{field}"

    if candidate["hypothesis_text"] == candidate["hypothesis_label"]:
        return False, "generic_shell:hypothesis_text_equals_label"

    lowered = candidate["hypothesis_text"].lower()
    for phrase in ideation_policy["anti_generic_guards"]["reject_vague_phrases"]:
        if phrase.lower() in lowered:
            return False, "generic_shell:vague_phrase"

    if candidate["primary_expected_metric_improvement"] not in ideation_policy["allowed_primary_expected_metric_improvement"]:
        return False, "invalid_primary_metric_target"

    if family in mutation_policy["blocked_families"]:
        return False, "blocked_family"

    return True, "valid"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--wave", default="wave1", choices=["wave1", "wave2"])
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise IdeationError("choose exactly one of --dry-run or --execute")

    ideation_policy = load_json(IDEATION_POLICY_PATH)
    mutation_policy = load_json(MUTATION_POLICY_PATH)

    selected: list[dict[str, Any]] = []
    for payload in wave_templates(args.wave):
        candidate = {
            "hypothesis_id": make_id(payload["hypothesis_label"]),
            "branch": "core",
            "segment_owner": "core_strategy",
            "baseline_reference": "phase66g_production_soft_filters",
            **payload
        }
        ok, reason = validate_candidate(candidate, ideation_policy, mutation_policy)
        append_jsonl(OUTPUT_LOG, {
            "ts": now_utc(),
            "wave": args.wave,
            "family": candidate["mutation_family"],
            "hypothesis_label": candidate["hypothesis_label"],
            "decision": "accepted" if ok else "blocked",
            "reason": reason
        })
        if ok:
            selected.append(candidate)

    summary_rows = [{
        "hypothesis_id": h["hypothesis_id"],
        "hypothesis_label": h["hypothesis_label"],
        "mutation_family": h["mutation_family"],
        "baseline_reference": h["baseline_reference"],
        "primary_expected_metric_improvement": h["primary_expected_metric_improvement"]
    } for h in selected]

    if args.execute:
        write_json(OUTPUT_JSON, {
            "wave": args.wave,
            "hypotheses": selected,
            "policy_version": ideation_policy["policy_version"]
        })
        write_csv(
            OUTPUT_CSV,
            summary_rows,
            [
                "hypothesis_id",
                "hypothesis_label",
                "mutation_family",
                "baseline_reference",
                "primary_expected_metric_improvement"
            ]
        )
        print(f"[SAVED] wave={args.wave}")
        print(f"[SAVED] hypotheses={len(selected)}")
        print(f"[SAVED] json={OUTPUT_JSON}")
        print(f"[SAVED] csv={OUTPUT_CSV}")
    else:
        print(f"[DRY-RUN] wave={args.wave}")
        print(f"[DRY-RUN] hypotheses={len(selected)}")
        for row in summary_rows:
            print(f"[DRY-RUN] {row['hypothesis_label']} | {row['mutation_family']} | {row['primary_expected_metric_improvement']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)