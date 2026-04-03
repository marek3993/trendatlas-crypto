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
POLICY_PATH = ROOT / "research_os" / "policies" / "research_os_ideation_policy_v1.json"
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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_id(label: str) -> str:
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
    return f"hyp_{digest}"


def templates() -> dict[str, dict[str, Any]]:
    return {
        "ranking_weight_tuning_v2": {
            "hypothesis_label": "core_ranking_weight_tuning_v3",
            "hypothesis_text": "Retune the leadership persistence weight block to reduce false leader handoffs caused by unstable short-horizon ranking dominance.",
            "rationale": "Baseline 66G may overweight unstable short-horizon leader persistence; targeted weight correction could improve regime selection robustness.",
            "known_baseline_weakness": "Fragile leader handoff after unstable short-horizon ranking persistence.",
            "exact_mechanism_of_improvement": "Reduce short-horizon persistence weight and increase persistent confirmation weight within one named leadership weight block.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "exact_failure_mode_being_fixed": "False leader promotion after unstable ranking dominance.",
            "why_expected_edge_survives_strict_scoring": "Targets a specific baseline weakness with a named mechanism, not a broad weight sweep.",
            "primary_expected_metric_improvement": "Calmar",
            "weight_block_name": "leadership_persistence_block",
            "current_weight_problem": "Short-horizon persistence weight appears too influential.",
            "exact_weight_change": "Decrease short-horizon persistence coefficient and increase persistent confirmation coefficient.",
            "why_this_weight_change_addresses_baseline_weakness": "It reduces promotion of unstable leaders while preserving confirmed ones.",
            "expected_selection_effect": "Fewer fragile handoffs and cleaner leader retention."
        },
        "cooldown_tuning_v2": {
            "hypothesis_label": "core_cooldown_tuning_v3",
            "hypothesis_text": "Adjust only the post-switch fragility cooldown to suppress immediate reversal churn after one named fragile switch pattern.",
            "rationale": "Baseline may allow too-fast re-entry after a fragile post-switch state, causing avoidable churn.",
            "known_baseline_weakness": "Immediate reversal churn after fragile low-conviction switch.",
            "exact_mechanism_of_improvement": "Lengthen only the post-switch fragility cooldown component for one named fragile switch pattern.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "exact_failure_mode_being_fixed": "Immediate reversal after low-conviction switch.",
            "why_expected_edge_survives_strict_scoring": "Targets one named failure mode rather than generic cooldown reduction of whipsaw.",
            "primary_expected_metric_improvement": "DD",
            "cooldown_component_name": "post_switch_fragility_cooldown",
            "named_baseline_failure_mode": "low_conviction_switch_then_immediate_reversal",
            "why_current_cooldown_is_wrong_for_that_failure_mode": "It allows too-early follow-up transition after a fragile switch.",
            "exact_cooldown_change": "Increase fragility cooldown by one step only for the named failure mode.",
            "expected_transition_effect": "Lower repeated reversal churn after fragile switches."
        },
        "threshold_tuning_v2": {
            "hypothesis_label": "core_threshold_tuning_v3",
            "hypothesis_text": "Tighten only the confirmation-strength threshold that admits one named weak setup pattern in recent conditions.",
            "rationale": "A single confirmation threshold may be too loose and admit weak setups that fail quickly.",
            "known_baseline_weakness": "Weak confirmation setup admissions in recent regime transitions.",
            "exact_mechanism_of_improvement": "Tighten one named confirmation threshold for one named weak setup pattern.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "exact_failure_mode_being_fixed": "False positive admission from weak confirmation setup.",
            "why_expected_edge_survives_strict_scoring": "Targets one named false-positive channel instead of a generic threshold sweep.",
            "primary_expected_metric_improvement": "since2025",
            "threshold_name": "confirmation_strength_threshold",
            "named_failure_mode": "weak_confirmation_false_positive",
            "why_baseline_threshold_is_wrong": "It is too loose for one named weak setup pattern.",
            "exact_threshold_change": "Raise confirmation threshold by one targeted increment for the named failure mode.",
            "expected_false_positive_or_missed_move_effect": "Reduce false positives with limited missed valid transitions."
        }
    }


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

    vague = set(ideation_policy["anti_generic_guards"]["reject_vague_phrases"])
    lowered = candidate["hypothesis_text"].lower()
    if any(p.lower() in lowered for p in vague):
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
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise IdeationError("choose exactly one of --dry-run or --execute")

    ideation_policy = load_json(POLICY_PATH)
    mutation_policy = load_json(MUTATION_POLICY_PATH)

    selected: list[dict[str, Any]] = []
    for family, payload in templates().items():
        candidate = {
            "hypothesis_id": make_id(payload["hypothesis_label"]),
            "branch": "core",
            "segment_owner": "core_strategy",
            "baseline_reference": "phase66g_production_soft_filters",
            "mutation_family": family,
            **payload
        }
        ok, reason = validate_candidate(candidate, ideation_policy, mutation_policy)
        append_jsonl(OUTPUT_LOG, {
            "ts": now_utc(),
            "family": family,
            "hypothesis_label": candidate["hypothesis_label"],
            "decision": "accepted" if ok else "blocked",
            "reason": reason
        })
        if ok:
            selected.append(candidate)

    limits = ideation_policy["generation_limits"]
    selected = selected[:limits["max_selected_specs_total"]]

    summary_rows = [{
        "hypothesis_id": h["hypothesis_id"],
        "hypothesis_label": h["hypothesis_label"],
        "mutation_family": h["mutation_family"],
        "baseline_reference": h["baseline_reference"],
        "primary_expected_metric_improvement": h["primary_expected_metric_improvement"]
    } for h in selected]

    if args.execute:
        write_json(OUTPUT_JSON, {"hypotheses": selected, "policy_version": ideation_policy["policy_version"]})
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
        print(f"[SAVED] hypotheses={len(selected)}")
        print(f"[SAVED] json={OUTPUT_JSON}")
        print(f"[SAVED] csv={OUTPUT_CSV}")
    else:
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