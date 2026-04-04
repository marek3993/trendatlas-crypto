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


def redesigned_templates() -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_label": "core_regime_reentry_proof_v1",
            "mutation_family": "regime_reentry_proof",
            "family_name": "regime_reentry_proof",
            "hypothesis_text": "Require a re-entry proof sequence after cash or stress exit before full risk-on reactivation.",
            "rationale": "Baseline can re-enter risk-on too early after weak recovery.",
            "known_baseline_weakness": "Baseline can re-enter risk-on too early after weak recovery.",
            "exact_mechanism_of_improvement": "Require follow-through, persistence and no immediate reversal before full risk-on after exit.",
            "new_state_or_new_classification": "New re-entry proof sequence gate.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_not_parameter_tuning": "Introduces a new re-entry mechanism and sequence gate, not a threshold tweak.",
            "why_expected_edge_should_survive_strict_scoring": "Targets one concrete re-entry failure mode with a discrete proof sequence.",
            "primary_expected_metric_improvement": "Calmar",
            "reentry_proof_sequence_name": "post_exit_reentry_proof_sequence",
            "follow_through_requirement": "require follow-through confirmation after exit",
            "persistence_requirement": "require persistence before full risk-on",
            "immediate_reversal_block_rule": "block full risk-on if immediate reversal appears during proof window"
        },
        {
            "hypothesis_label": "core_leader_fragility_filter_v1",
            "mutation_family": "leader_fragility_filter",
            "family_name": "leader_fragility_filter",
            "hypothesis_text": "Block or reduce risk-on when the selected leader looks strong by level but fails a stability or fragility screen.",
            "rationale": "Selected leader can look strong by level but still be unstable and break quickly.",
            "known_baseline_weakness": "Selected leader looks strong by level but is unstable and breaks quickly.",
            "exact_mechanism_of_improvement": "Add a leader fragility or stability filter before activation or continuation.",
            "new_state_or_new_classification": "New leader stability classification gate.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_not_parameter_tuning": "Introduces a new leader stability concept, not ranking-weight tuning.",
            "why_expected_edge_should_survive_strict_scoring": "Targets selection persistence weakness directly with a new logical gate.",
            "primary_expected_metric_improvement": "since2025",
            "leader_fragility_signal_name": "leader_stability_fragility_filter",
            "stability_definition": "leader must remain stable across short persistence checks before activation or continuation",
            "activation_or_continuation_gate": "unstable leader blocks or reduces risk-on"
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
    for payload in redesigned_templates():
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
            "wave": "redesigned_batch_v1",
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