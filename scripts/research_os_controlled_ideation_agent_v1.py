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
PROJECT_TRUTH_JSON = ROOT / "source_of_truth" / "project_truth.json"
OUTPUT_DIR = ROOT / "outputs" / "research_os_ideation_v1"
OUTPUT_JSON = OUTPUT_DIR / "ideation_hypotheses.json"
OUTPUT_CSV = OUTPUT_DIR / "ideation_summary.csv"
OUTPUT_LOG = OUTPUT_DIR / "ideation_decision_log.jsonl"

ACTIVE_STRATEGY_LINE_ID = "phase68i_dynamic_ladder_autonomous_line"


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


def assert_active_line_allowed() -> None:
    truth = load_json(PROJECT_TRUTH_JSON)
    active_line = truth.get("ai_lab_runtime", {}).get("active_strategy_line_id")
    if active_line != ACTIVE_STRATEGY_LINE_ID:
        raise IdeationError(f"unexpected active strategy line: {active_line}")

    line = truth.get("ai_lab_strategy_lines", {}).get(ACTIVE_STRATEGY_LINE_ID, {})
    if line.get("autonomous_ideation_allowed") is not True:
        raise IdeationError(f"active strategy line not allowed for ideation: {ACTIVE_STRATEGY_LINE_ID}")


def human_seeded_templates() -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_label": "phase68i_ladder_reentry_stability_gate_v1",
            "mutation_family": "ladder_reentry_stability_gate",
            "family_name": "ladder_reentry_stability_gate",
            "hypothesis_text": "After temporary ladder reduction, require stable continuation proof before restoring higher ladder exposure.",
            "rationale": "Dynamic ladder can re-expand too early after a weak bounce.",
            "known_baseline_weakness": "Dynamic ladder can re-expand too early after a weak bounce.",
            "exact_mechanism_of_improvement": "Require a stability proof sequence before re-entry to higher ladder states after temporary reduction.",
            "new_state_or_new_classification": "New ladder re-entry stability gate.",
            "exact_compare_target": "phase68i_dynamic_ladder_candidate",
            "why_not_parameter_tuning": "Introduces a new ladder re-entry gate instead of changing thresholds or weights.",
            "why_expected_edge_should_survive_strict_scoring": "Targets a specific deployment-profile weakness around premature re-expansion after weak recovery.",
            "primary_expected_metric_improvement": "DD",
            "reentry_trigger_name": "ladder_reentry_after_reduction",
            "stability_proof_requirement": "require stable continuation before higher step restoration",
            "premature_reentry_block_rule": "block higher step restoration on weak bounce"
        },
        {
            "hypothesis_label": "phase68i_ladder_step_fragility_filter_v1",
            "mutation_family": "ladder_step_fragility_filter",
            "family_name": "ladder_step_fragility_filter",
            "hypothesis_text": "Before each higher ladder step, require a fragility check so that fragile continuation blocks the next step-up.",
            "rationale": "Ladder step-up progression can be too aggressive when trend continuation is fragile.",
            "known_baseline_weakness": "Ladder step-up progression can be too aggressive when continuation is fragile.",
            "exact_mechanism_of_improvement": "Add a step fragility filter before each upward ladder move and hold at the lower step when fragile.",
            "new_state_or_new_classification": "New ladder step fragility gate.",
            "exact_compare_target": "phase68i_dynamic_ladder_candidate",
            "why_not_parameter_tuning": "Introduces a new ladder step fragility decision layer, not generic threshold tuning.",
            "why_expected_edge_should_survive_strict_scoring": "Targets deployment-profile step escalation quality directly instead of chasing raw CAGR.",
            "primary_expected_metric_improvement": "Calmar",
            "step_fragility_signal_name": "ladder_step_fragility_signal",
            "step_up_gate_rule": "require non-fragile continuation before higher step",
            "fragile_state_hold_rule": "hold current lower step when fragility detected"
        },
        {
            "hypothesis_label": "phase68i_ladder_downside_capture_cap_v1",
            "mutation_family": "ladder_downside_capture_cap",
            "family_name": "ladder_downside_capture_cap",
            "hypothesis_text": "If downside capture versus the baseline exceeds a cap, freeze further ladder increases and reduce exposure.",
            "rationale": "Dynamic ladder may still absorb too much downside participation in bad intervals.",
            "known_baseline_weakness": "Dynamic ladder may still absorb too much downside participation in bad intervals.",
            "exact_mechanism_of_improvement": "Apply a downside capture cap relative to the baseline and step down or freeze when breached.",
            "new_state_or_new_classification": "New downside capture veto state for ladder progression.",
            "exact_compare_target": "phase68i_dynamic_ladder_candidate",
            "why_not_parameter_tuning": "Introduces a new downside control relationship versus the baseline, not a simple ladder threshold tweak.",
            "why_expected_edge_should_survive_strict_scoring": "Targets downside robustness explicitly, which matches the deployment objective of the line.",
            "primary_expected_metric_improvement": "DD",
            "downside_capture_reference": "phase68i_dynamic_ladder_candidate",
            "downside_cap_rule": "must not exceed downside capture cap versus baseline",
            "step_down_or_freeze_rule": "freeze higher steps and reduce exposure when cap is breached"
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

    assert_active_line_allowed()

    ideation_policy = load_json(IDEATION_POLICY_PATH)
    mutation_policy = load_json(MUTATION_POLICY_PATH)

    selected: list[dict[str, Any]] = []
    for payload in human_seeded_templates():
        candidate = {
            "hypothesis_id": make_id(payload["hypothesis_label"]),
            "branch": "core",
            "segment_owner": "core_strategy",
            "baseline_reference": "phase68i_dynamic_ladder_candidate",
            **payload
        }
        ok, reason = validate_candidate(candidate, ideation_policy, mutation_policy)
        append_jsonl(OUTPUT_LOG, {
            "ts": now_utc(),
            "strategy_line_id": ACTIVE_STRATEGY_LINE_ID,
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
            "strategy_line_id": ACTIVE_STRATEGY_LINE_ID,
            "wave": "human_seeded_first_batch_v1",
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
