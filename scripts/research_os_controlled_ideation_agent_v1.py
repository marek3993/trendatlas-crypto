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


def reset_templates() -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_label": "core_baseline_relative_edge_gate_v1",
            "mutation_family": "baseline_relative_edge_gate",
            "family_name": "baseline_relative_edge_gate",
            "hypothesis_text": "Promote candidate only when rolling excess edge versus baseline is positive on two horizons; otherwise fallback to baseline.",
            "rationale": "Family fails because it does not create stable excess edge versus baseline, especially in hard subperiods.",
            "known_baseline_weakness": "Family fails to create stable excess edge versus baseline, especially in hard subperiods.",
            "exact_mechanism_of_improvement": "Require positive rolling excess edge versus baseline on short and medium horizons before promotion; otherwise fallback to baseline.",
            "new_state_or_new_classification": "New baseline-relative excess-edge promotion gate.",
            "exact_compare_target": "phase67j_no_neo_main",
            "why_not_parameter_tuning": "Introduces explicit baseline-relative gating logic instead of tuning thresholds or weights.",
            "why_expected_edge_should_survive_strict_scoring": "Directly ties promotion to stable excess edge versus baseline on two horizons.",
            "primary_expected_metric_improvement": "since2025",
            "rolling_excess_edge_reference": "baseline_relative_excess_edge",
            "short_horizon_edge_gate": "short_horizon_excess_edge_must_be_positive",
            "medium_horizon_edge_gate": "medium_horizon_excess_edge_must_be_positive",
            "fallback_to_baseline_rule": "if either horizon fails then fallback_to_baseline"
        },
        {
            "hypothesis_label": "core_breadth_dispersion_corridor_v1",
            "mutation_family": "breadth_dispersion_corridor",
            "family_name": "breadth_dispersion_corridor",
            "hypothesis_text": "Promote candidate only inside a healthy breadth and dispersion corridor; otherwise fallback to baseline.",
            "rationale": "Family quality collapses when market participation is too narrow or too chaotic.",
            "known_baseline_weakness": "Family quality collapses when market participation is too narrow or too chaotic.",
            "exact_mechanism_of_improvement": "Require breadth and dispersion to remain inside a healthy corridor before promotion; otherwise fallback to baseline.",
            "new_state_or_new_classification": "New breadth-dispersion corridor classification gate.",
            "exact_compare_target": "phase67j_no_neo_main",
            "why_not_parameter_tuning": "Introduces a new corridor gate based on market participation quality, not a simple parameter change.",
            "why_expected_edge_should_survive_strict_scoring": "Targets a concrete participation-quality collapse mode with explicit fallback behavior.",
            "primary_expected_metric_improvement": "DD",
            "breadth_measure_name": "market_breadth_participation",
            "dispersion_measure_name": "cross_sectional_dispersion",
            "healthy_corridor_definition": "breadth_not_too_narrow_and_dispersion_not_too_chaotic",
            "fallback_to_baseline_rule": "outside_corridor_fallback_to_baseline"
        },
        {
            "hypothesis_label": "core_downside_asymmetry_veto_v1",
            "mutation_family": "downside_asymmetry_veto",
            "family_name": "downside_asymmetry_veto",
            "hypothesis_text": "Veto promotion when downside beta or downside capture versus reference exceeds cap.",
            "rationale": "Family still participates too much in bad downside states.",
            "known_baseline_weakness": "Family still participates too much in bad downside states.",
            "exact_mechanism_of_improvement": "Block promotion when downside beta or downside capture versus reference breaches a cap.",
            "new_state_or_new_classification": "New downside-asymmetry veto gate.",
            "exact_compare_target": "phase67j_no_neo_main",
            "why_not_parameter_tuning": "Introduces a downside-state veto relationship, not a threshold or weight tuning shell.",
            "why_expected_edge_should_survive_strict_scoring": "Targets explicit downside participation weakness with a hard veto gate.",
            "primary_expected_metric_improvement": "DD",
            "downside_reference_name": "baseline_or_reference_downside_profile",
            "downside_beta_or_capture_measure": "downside_beta_or_capture_vs_reference",
            "downside_cap_rule": "must_not_exceed_downside_cap",
            "promotion_veto_rule": "if_downside_measure_exceeds_cap_then_veto_promotion"
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
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise IdeationError("choose exactly one of --dry-run or --execute")

    ideation_policy = load_json(IDEATION_POLICY_PATH)
    mutation_policy = load_json(MUTATION_POLICY_PATH)

    selected: list[dict[str, Any]] = []
    for payload in reset_templates():
        candidate = {
            "hypothesis_id": make_id(payload["hypothesis_label"]),
            "branch": "core",
            "segment_owner": "core_strategy",
            "baseline_reference": "phase67j_no_neo_main",
            **payload
        }
        ok, reason = validate_candidate(candidate, ideation_policy, mutation_policy)
        append_jsonl(OUTPUT_LOG, {
            "ts": now_utc(),
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
            "wave": "master_reset_batch_v1",
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