from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "research_os" / "policies" / "research_os_ideation_policy_v1.json"
MUTATION_POLICY_PATH = ROOT / "research_os" / "policies" / "research_os_mutation_space_policy_v1.json"
TRUTH_PACK_PATH = ROOT / "source_of_truth" / "project_truth.json"
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


def blocked_by_phrase(text: str, blocked_phrases: list[str]) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in blocked_phrases)


def hypothesis_templates() -> dict[str, dict[str, str]]:
    return {
        "ranking_weight_tuning": {
            "hypothesis_text": "Retune leadership weights inside the current 66G ranking stack to down-weight weak recent leadership persistence and improve robustness against false leader handoffs.",
            "rationale": "Baseline appears vulnerable to unstable recent leadership ranking persistence; weight redistribution may reduce weak leader admissions without changing asset universe or decision regime.",
            "known_baseline_weakness": "Weak recent leadership persistence can allow fragile leader handoffs.",
            "failure_mode_being_fixed": "False leader promotion after weak ranking persistence.",
            "explicit_mechanism_of_improvement": "Shift ranking emphasis away from unstable short-horizon leadership inputs toward more persistent ranking evidence.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_edge_should_survive_scoring_strictness": "Mechanism targets a known ranking failure mode rather than broad parameter search.",
            "weight_group_name": "leadership_persistence_weights",
            "current_weighting_problem": "Current weighting may overweight unstable recent leadership signals.",
            "proposed_weight_shift": "Decrease unstable short-horizon weight and increase persistent leadership confirmation weight.",
            "expected_effect_on_regime_selection": "Reduce fragile leader handoffs and improve robustness."
        },
        "cooldown_tuning": {
            "hypothesis_text": "Target cooldown discipline around weak post-switch churn so baseline holds fewer fragile follow-up transitions after low-conviction switches.",
            "rationale": "Baseline may overreact after low-conviction switches; a targeted cooldown adjustment could reduce churn without blocking valid regime changes.",
            "known_baseline_weakness": "Weak post-switch churn after low-conviction transitions.",
            "failure_mode_being_fixed": "Low-conviction switch followed by immediate noisy reversal.",
            "explicit_mechanism_of_improvement": "Increase cooldown discipline only around fragile post-switch states to suppress bad follow-up transitions.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_edge_should_survive_scoring_strictness": "Targets a concrete churn failure mode instead of generic cooldown knob turning.",
            "cooldown_component_name": "post_switch_fragility_cooldown",
            "current_failure_mode": "Immediate noisy reversal after fragile switch.",
            "why_current_cooldown_is_wrong": "Current cooldown may be too permissive after fragile transitions.",
            "proposed_cooldown_change": "Increase cooldown only for low-conviction post-switch states.",
            "expected_reduction_in_bad_transitions": "Fewer fragile back-and-forth reversals."
        },
        "threshold_tuning": {
            "hypothesis_text": "Tighten a targeted baseline threshold that currently admits weak confirmation states, aiming to reduce false positives without broadly suppressing valid moves.",
            "rationale": "A specific confirmation threshold may be too loose and allow weak setups that do not survive scoring scrutiny.",
            "known_baseline_weakness": "Loose confirmation threshold can admit weak setups.",
            "failure_mode_being_fixed": "False positive admissions from weak confirmation states.",
            "explicit_mechanism_of_improvement": "Tighten only the targeted confirmation threshold to reject weak setups while preserving valid moves.",
            "exact_compare_target": "phase66g_production_soft_filters",
            "why_edge_should_survive_scoring_strictness": "Targets a precise false-positive failure mode, not a broad threshold sweep.",
            "threshold_name": "confirmation_strength_threshold",
            "current_threshold_failure_mode": "Weak confirmation states pass too often.",
            "why_baseline_threshold_is_too_loose_or_tight": "Baseline threshold appears too loose for weak confirmation states.",
            "proposed_threshold_change": "Slightly tighten confirmation requirement.",
            "expected_effect_on_false_positives_or_missed_moves": "Reduce false positives with limited impact on valid moves."
        }
    }


def build_hypothesis(branch: str, family: str, owner: str, expected_direction: str) -> dict[str, Any]:
    template = hypothesis_templates()[family]
    label = f"{branch}_{family}_v2"
    hypothesis_text = template["hypothesis_text"]

    return {
        "hypothesis_id": make_id(label),
        "branch": branch,
        "segment_owner": owner,
        "hypothesis_label": label,
        "hypothesis_text": hypothesis_text,
        "rationale": template["rationale"],
        "expected_improvement_direction": expected_direction,
        "baseline_reference": "phase66g_production_soft_filters",
        "mutation_family": family,
        "risk_flags": {
            "instability_risk": "medium",
            "complexity_risk": "low",
            "duplicate_risk": "low",
            "saturation_risk": "low"
        },
        "duplicate_suspicion": False,
        "near_duplicate_suspicion": False,
        "branch_saturation_state": "ok",
        "known_baseline_weakness": template["known_baseline_weakness"],
        "failure_mode_being_fixed": template["failure_mode_being_fixed"],
        "explicit_mechanism_of_improvement": template["explicit_mechanism_of_improvement"],
        "exact_compare_target": template["exact_compare_target"],
        "why_edge_should_survive_scoring_strictness": template["why_edge_should_survive_scoring_strictness"],
        **{k: v for k, v in template.items() if k not in {
            "hypothesis_text",
            "rationale",
            "known_baseline_weakness",
            "failure_mode_being_fixed",
            "explicit_mechanism_of_improvement",
            "exact_compare_target",
            "why_edge_should_survive_scoring_strictness"
        }}
    }


def validate_hypothesis(h: dict[str, Any], policy: dict[str, Any], mutation_policy: dict[str, Any]) -> tuple[bool, str]:
    for field in policy["required_fields"]:
        if field not in h or h[field] in (None, "", []):
            return False, f"missing_required_field:{field}"

    if h["hypothesis_text"] == h["hypothesis_label"]:
        return False, "generic_shell:hypothesis_text_equals_label"

    if h["mutation_family"] in mutation_policy["blocked_mutation_families"]:
        return False, "blocked_family"

    blocked_phrases = mutation_policy["hard_guards"]["generic_phrases_blocklist"]
    if blocked_by_phrase(h["hypothesis_text"], blocked_phrases):
        return False, "generic_shell:blocked_phrase"

    return True, "valid"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", default="core")
    parser.add_argument("--max-hypotheses", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise IdeationError("choose exactly one of --dry-run or --execute")

    policy = load_json(POLICY_PATH)
    mutation_policy = load_json(MUTATION_POLICY_PATH)
    truth = load_json(TRUTH_PACK_PATH)

    if args.branch not in policy["allowed_branches"]:
        raise IdeationError(f"unsupported branch: {args.branch}")

    core_families = mutation_policy["allowed_mutation_families"]["core"]
    selected = []
    for item in core_families:
        family = item["mutation_family"]
        owner = policy["default_segment_owner_by_branch"]["core"]
        h = build_hypothesis("core", family, owner, item["expected_improvement_direction"])
        ok, reason = validate_hypothesis(h, policy, mutation_policy)
        append_jsonl(OUTPUT_LOG, {
            "ts": now_utc(),
            "family": family,
            "hypothesis_label": h["hypothesis_label"],
            "decision": "accepted" if ok else "blocked",
            "reason": reason
        })
        if ok:
            selected.append(h)

    selected = selected[:args.max_hypotheses]

    summary_rows = [{
        "hypothesis_id": h["hypothesis_id"],
        "hypothesis_label": h["hypothesis_label"],
        "mutation_family": h["mutation_family"],
        "branch": h["branch"],
        "segment_owner": h["segment_owner"],
        "baseline_reference": h["baseline_reference"],
        "exact_compare_target": h["exact_compare_target"]
    } for h in selected]

    if args.execute:
        write_json(OUTPUT_JSON, {"hypotheses": selected, "policy_version": policy["policy_version"], "baseline_truth": truth.get("official_baselines", {})})
        write_csv(
            OUTPUT_CSV,
            summary_rows,
            [
                "hypothesis_id",
                "hypothesis_label",
                "mutation_family",
                "branch",
                "segment_owner",
                "baseline_reference",
                "exact_compare_target"
            ]
        )
        print(f"[SAVED] hypotheses={len(selected)}")
        print(f"[SAVED] json={OUTPUT_JSON}")
        print(f"[SAVED] csv={OUTPUT_CSV}")
    else:
        print(f"[DRY-RUN] branch={args.branch}")
        print(f"[DRY-RUN] hypotheses={len(selected)}")
        for row in summary_rows:
            print(f"[DRY-RUN] {row['hypothesis_label']} | {row['mutation_family']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)