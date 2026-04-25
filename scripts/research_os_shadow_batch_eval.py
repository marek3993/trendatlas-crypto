from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import research_os_local_shadow_run_verification as verifier


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "trendatlas_shadow_batch_eval_v3"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "shadow_batch_eval_v3_summary.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "shadow_batch_eval_v3_summary.md"
DEFAULT_COMPACT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "shadow_batch_eval_v3_manual_review.csv"
REAL_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "trendatlas_shadow_batch_eval_real_v3"
REAL_OUTPUT_PATH = REAL_OUTPUT_DIR / "shadow_batch_eval_real_v3_summary.json"
REAL_MARKDOWN_PATH = REAL_OUTPUT_DIR / "shadow_batch_eval_real_v3_summary.md"
REAL_COMPACT_SUMMARY_PATH = REAL_OUTPUT_DIR / "shadow_batch_eval_real_v3_manual_review.csv"
REAL_SHADOW_FAMILY_ID = "cost_aware_hysteretic_pilot_to_full"
REAL_SHADOW_CYCLE_LABELS = (
    "first_openai_backed_cycle",
    "first_real_bringup_cycle",
    "openai_enabled_true_rerun",
    "openai_final_enable_rerun",
    "openai_live_path_test",
    "openai_resolution_debug_rerun",
    "openai_runtime_debug_rerun",
    "openai_token_opt_rerun",
    "real_full_pipeline_cycle_smoke",
    "second_openai_backed_cycle",
    "third_openai_backed_cycle",
)
PLANNER_REASONING_FIELDS = frozenset({"mechanism_hypothesis", "selection_rationale"})
PLANNER_DECISION_FIELDS = frozenset(
    {
        "exact_change",
        "source_artifact_id",
        "stop_condition",
        "target_id",
        "target_type",
    }
)
CRITIC_REASONING_FIELDS = frozenset({"policy_alignment_note", "recommended_reason"})
CRITIC_DECISION_FIELDS = frozenset({"recommended_next_action", "recommended_verdict"})


class BatchEvalFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch-evaluate TrendAtlas shadow retrieval comparisons across discovered family/cycle artifacts."
    )
    parser.add_argument("--retrieval-root", default=str(verifier.DEFAULT_RETRIEVAL_ROOT))
    parser.add_argument("--planner-input-root", default=str(verifier.DEFAULT_PLANNER_INPUT_ROOT))
    parser.add_argument("--heavy-validation-root", default=str(verifier.DEFAULT_HEAVY_VALIDATION_ROOT))
    parser.add_argument("--output-path", default="")
    parser.add_argument("--markdown-path", default="")
    parser.add_argument("--compact-summary-path", default="")
    parser.add_argument("--mode-config", default="")
    parser.add_argument("--family-id", action="append", dest="family_ids", default=[])
    parser.add_argument("--cycle-label", action="append", dest="cycle_labels", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--use-real-openai", action="store_true")
    return parser


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def cycle_label_from_planner_input(path: Path) -> str:
    suffix = "_planner_input.json"
    if not path.name.endswith(suffix):
        raise BatchEvalFailure(f"Unexpected planner input name: {path.name}")
    return path.name[: -len(suffix)]


def cycle_label_from_summary(path: Path, family_id: str) -> str | None:
    suffix = f"_{family_id}_submit_heavy_validation_job_summary.json"
    if not path.name.endswith(suffix):
        return None
    return path.name[: -len(suffix)]


def planner_input_supports_family(path: Path, family_id: str) -> bool:
    payload = verifier.read_json(path)
    environment_scan = dict(payload.get("environment_scan", {}))
    snapshot = dict(environment_scan.get("family_state_snapshot", {}))
    families = list(dict(snapshot.get("payload", {})).get("families", []))
    return any(str(dict(item).get("family_id", "")).strip() == family_id for item in families)


def discover_latest_retrieval_packets(root: Path, family_filter: set[str]) -> list[dict[str, Any]]:
    latest_by_family: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("**/*.retrieval_packet.json")):
        if not path.is_file():
            continue
        payload = verifier.read_json(path)
        family_id = str(dict(payload.get("query", {})).get("family_id", "")).strip()
        if not family_id:
            continue
        if family_filter and family_id not in family_filter:
            continue
        current = latest_by_family.get(family_id)
        candidate = {
            "family_id": family_id,
            "path": path.resolve(),
            "payload": payload,
        }
        if current is None:
            latest_by_family[family_id] = candidate
            continue
        current_key = (current["path"].stat().st_mtime, str(current["path"]))
        candidate_key = (candidate["path"].stat().st_mtime, str(candidate["path"]))
        if candidate_key > current_key:
            latest_by_family[family_id] = candidate
    return [latest_by_family[family_id] for family_id in sorted(latest_by_family)]


def discover_cases(
    *,
    retrieval_root: Path,
    planner_input_root: Path,
    heavy_validation_root: Path,
    family_filter: set[str],
    cycle_filter: set[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    packets = discover_latest_retrieval_packets(retrieval_root, family_filter)
    if not packets:
        raise BatchEvalFailure(f"No retrieval packets discovered under {retrieval_root}")

    planner_inputs = sorted(planner_input_root.glob("*_planner_input.json"))
    summary_files = sorted(heavy_validation_root.glob("*_summary.json"))
    cases: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    packet_descriptors: list[dict[str, Any]] = []
    discovery_details: dict[str, Any] = {}

    for packet in packets:
        family_id = str(packet["family_id"])
        packet_payload = dict(packet["payload"])
        family_summary = dict(packet_payload.get("family_summary", {}))
        packet_descriptors.append(
            {
                "family_id": family_id,
                "retrieval_packet_path": str(packet["path"]),
                "retrieval_generated_at_utc": str(packet_payload.get("retrieval_generated_at_utc", "")),
                "resolved_batch_id": str(dict(packet_payload.get("query", {})).get("resolved_batch_id", "")),
                "memory_query_target": str(dict(packet_payload.get("query", {})).get("memory_query_target", "")),
                "latest_cycle_id": str(family_summary.get("latest_cycle_id", "")),
                "latest_memory_id": str(family_summary.get("latest_memory_id", "")),
            }
        )

        planner_by_cycle: dict[str, Path] = {}
        for planner_input in planner_inputs:
            if planner_input_supports_family(planner_input, family_id):
                planner_by_cycle[cycle_label_from_planner_input(planner_input)] = planner_input.resolve()

        summary_by_cycle: dict[str, Path] = {}
        for summary_path in summary_files:
            cycle_label = cycle_label_from_summary(summary_path, family_id)
            if cycle_label:
                summary_by_cycle[cycle_label] = summary_path.resolve()

        common_cycles = sorted(set(planner_by_cycle) & set(summary_by_cycle))
        selected_common_cycles = [cycle_label for cycle_label in common_cycles if not cycle_filter or cycle_label in cycle_filter]
        missing_summary_cycles = sorted(
            cycle_label
            for cycle_label in (set(planner_by_cycle) - set(summary_by_cycle))
            if not cycle_filter or cycle_label in cycle_filter
        )
        missing_planner_cycles = sorted(
            cycle_label
            for cycle_label in (set(summary_by_cycle) - set(planner_by_cycle))
            if not cycle_filter or cycle_label in cycle_filter
        )
        missing_requested_cycles = sorted(cycle_filter - set(common_cycles)) if cycle_filter else []

        discovery_details[family_id] = {
            "planner_cycles": sorted(planner_by_cycle),
            "summary_cycles": sorted(summary_by_cycle),
            "common_cycles": common_cycles,
            "selected_common_cycles": selected_common_cycles,
            "missing_requested_cycles": missing_requested_cycles,
        }

        for cycle_label in missing_summary_cycles:
            skipped.append(
                {
                    "family_id": family_id,
                    "cycle_label": cycle_label,
                    "reason": "missing_heavy_validation_summary",
                    "planner_input_path": str(planner_by_cycle[cycle_label]),
                }
            )
        for cycle_label in missing_planner_cycles:
            skipped.append(
                {
                    "family_id": family_id,
                    "cycle_label": cycle_label,
                    "reason": "missing_planner_input",
                    "heavy_validation_summary_path": str(summary_by_cycle[cycle_label]),
                }
            )
        for cycle_label in missing_requested_cycles:
            skipped.append(
                {
                    "family_id": family_id,
                    "cycle_label": cycle_label,
                    "reason": "missing_requested_cycle_alignment",
                }
            )
        for cycle_label in selected_common_cycles:
            cases.append(
                {
                    "family_id": family_id,
                    "cycle_label": cycle_label,
                    "retrieval_packet_path": str(packet["path"]),
                    "planner_input_path": str(planner_by_cycle[cycle_label]),
                    "heavy_validation_summary_path": str(summary_by_cycle[cycle_label]),
                }
            )

    cases.sort(key=lambda item: (str(item["family_id"]), str(item["cycle_label"])))
    if limit > 0:
        cases = cases[:limit]
    if not cases:
        raise BatchEvalFailure("No cycle-aligned batch-eval cases were discovered")
    return cases, skipped, packet_descriptors, discovery_details


def usage_snapshot(raw_usage: dict[str, Any]) -> dict[str, Any]:
    usage = dict(raw_usage or {})
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def prompt_metrics_snapshot(raw_metrics: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(raw_metrics or {})
    return {
        "json_char_count": int(metrics.get("json_char_count", 0) or 0),
        "utf8_byte_count": int(metrics.get("utf8_byte_count", 0) or 0),
        "estimated_input_tokens_char_div4": int(metrics.get("estimated_input_tokens_char_div4", 0) or 0),
        "payload_sha256": str(metrics.get("payload_sha256", "")),
    }


def authoritative_response_snapshot(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "network_call": str(operation.get("network_call", "")),
        "response_id": str(operation.get("response_id", "")),
        "response_status": str(operation.get("response_status", "")),
        "response_model": str(operation.get("response_model", "")),
        "usage": usage_snapshot(dict(operation.get("usage", {}))),
    }


def summarize_component(
    component_name: str,
    controlled: dict[str, Any],
    authoritative_operation: dict[str, Any],
    passive_retrieval_comparison: dict[str, Any],
    *,
    reasoning_fields: frozenset[str],
    decision_fields: frozenset[str],
) -> dict[str, Any]:
    observations = dict(controlled.get("observations", {}))
    diff = dict(observations.get("diff", {}))
    authoritative = dict(observations.get("authoritative", {}))
    candidate = dict(observations.get("candidate", {}))
    changed_fields = [str(field) for field in list(diff.get("changed_fields", []))]
    changed_reasoning_fields = [field for field in changed_fields if field in reasoning_fields]
    changed_decision_fields = [field for field in changed_fields if field in decision_fields]
    proposal_content_fields_changed = [
        str(field)
        for field in list(diff.get("proposal_content_fields_changed", []))
    ]
    authoritative_usage = usage_snapshot(dict(authoritative.get("usage", {})))
    candidate_usage = usage_snapshot(dict(candidate.get("usage", {})))
    authoritative_prompt_metrics = prompt_metrics_snapshot(dict(controlled.get("authoritative_prompt_metrics", {})))
    candidate_prompt_metrics = prompt_metrics_snapshot(dict(controlled.get("candidate_prompt_metrics", {})))
    retrieval_prompt_observability = dict(controlled.get("retrieval_prompt_observability", {}))
    full_retrieval_prompt_metrics = prompt_metrics_snapshot(
        dict(dict(retrieval_prompt_observability.get("full_retrieval_mode", {})).get("prompt_metrics", {}))
    )
    compact_retrieval_prompt_metrics = prompt_metrics_snapshot(
        dict(dict(retrieval_prompt_observability.get("compact_retrieval_mode", {})).get("prompt_metrics", {}))
    )
    token_delta_impact = dict(retrieval_prompt_observability.get("token_delta_impact", {}))
    reasoning_only_change = bool(changed_fields) and not changed_decision_fields and set(changed_fields).issubset(
        reasoning_fields
    )
    reasoning_changed = bool(changed_reasoning_fields)
    decision_stayed_identical = not changed_decision_fields and not bool(controlled.get("decision_behavior_changed", False))
    return {
        "component": component_name,
        "passive_retrieval_comparison": {
            "comparison_bucket": str(passive_retrieval_comparison.get("comparison_bucket", "")),
            "retrieval_packet_present": bool(passive_retrieval_comparison.get("retrieval_packet_present", False)),
            "retrieval_packet_status": str(passive_retrieval_comparison.get("retrieval_packet_status", "")),
            "latest_memory_id": str(passive_retrieval_comparison.get("latest_memory_id", "")),
            "semantic_sha256": str(passive_retrieval_comparison.get("semantic_sha256", "")),
            "load_error": str(passive_retrieval_comparison.get("load_error", "")),
        },
        "changed_note_fields": changed_fields,
        "changed_reasoning_fields": changed_reasoning_fields,
        "changed_decision_fields": changed_decision_fields,
        "proposal_content_fields_changed": proposal_content_fields_changed,
        "proposal_content_fields_preserved": bool(diff.get("proposal_content_fields_preserved", True)),
        "reasoning_changed": reasoning_changed,
        "reasoning_only_change": reasoning_only_change,
        "decision_stayed_identical": decision_stayed_identical,
        "reasoning_changed_decision_identical": reasoning_changed and decision_stayed_identical,
        "decision_behavior_changed": bool(controlled.get("decision_behavior_changed", False)),
        "fail_closed_preserved": bool(controlled.get("fail_closed_preserved", False)),
        "candidate_status": str(candidate.get("status", "")),
        "candidate_error": str(candidate.get("error", "")),
        "authoritative_prompt_metrics": authoritative_prompt_metrics,
        "candidate_prompt_metrics": candidate_prompt_metrics,
        "candidate_prompt_mode": str(controlled.get("candidate_prompt_mode", "")),
        "retrieval_prompt_observability": {
            "selected_mode": str(retrieval_prompt_observability.get("selected_mode", "")),
            "full_retrieval_prompt_metrics": full_retrieval_prompt_metrics,
            "compact_retrieval_prompt_metrics": compact_retrieval_prompt_metrics,
            "token_delta_impact": {
                "full_vs_authoritative_prompt_estimated_input_tokens_delta": int(
                    dict(token_delta_impact.get("full_vs_authoritative", {})).get(
                        "estimated_input_tokens_char_div4_delta",
                        0,
                    )
                    or 0
                ),
                "compact_vs_authoritative_prompt_estimated_input_tokens_delta": int(
                    dict(token_delta_impact.get("compact_vs_authoritative", {})).get(
                        "estimated_input_tokens_char_div4_delta",
                        0,
                    )
                    or 0
                ),
                "compact_vs_full_prompt_estimated_input_tokens_delta": int(
                    dict(token_delta_impact.get("compact_vs_full", {})).get(
                        "estimated_input_tokens_char_div4_delta",
                        0,
                    )
                    or 0
                ),
                "compact_vs_full_json_char_count_delta": int(
                    dict(token_delta_impact.get("compact_vs_full", {})).get("json_char_count_delta", 0) or 0
                ),
                "compact_vs_full_utf8_byte_count_delta": int(
                    dict(token_delta_impact.get("compact_vs_full", {})).get("utf8_byte_count_delta", 0) or 0
                ),
            },
        },
        "authoritative_prompt_sha256": authoritative_prompt_metrics["payload_sha256"],
        "candidate_prompt_sha256": candidate_prompt_metrics["payload_sha256"],
        "authoritative_response": authoritative_response_snapshot(authoritative_operation),
        "candidate_response": {
            "response_id": str(candidate.get("response_id", "")),
            "response_status": str(candidate.get("response_status", "")),
            "response_model": str(candidate.get("response_model", "")),
            "usage": candidate_usage,
        },
        "prompt_estimated_input_tokens_delta": candidate_prompt_metrics["estimated_input_tokens_char_div4"]
        - authoritative_prompt_metrics["estimated_input_tokens_char_div4"],
        "response_input_tokens_delta": candidate_usage["input_tokens"] - authoritative_usage["input_tokens"],
        "response_output_tokens_delta": candidate_usage["output_tokens"] - authoritative_usage["output_tokens"],
        "response_total_tokens_delta": candidate_usage["total_tokens"] - authoritative_usage["total_tokens"],
    }


def build_case_result(case: dict[str, Any], summary_payload: dict[str, Any]) -> dict[str, Any]:
    planner_summary = dict(summary_payload.get("planner", {}))
    critic_summary = dict(summary_payload.get("critic", {}))
    planner = summarize_component(
        "planner",
        dict(planner_summary.get("controlled_retrieval_comparison", {})),
        dict(planner_summary.get("openai_hook", {})),
        dict(planner_summary.get("passive_retrieval_comparison", {})),
        reasoning_fields=PLANNER_REASONING_FIELDS,
        decision_fields=PLANNER_DECISION_FIELDS,
    )
    critic = summarize_component(
        "critic",
        dict(critic_summary.get("controlled_retrieval_comparison", {})),
        dict(critic_summary.get("openai_review", {})),
        dict(critic_summary.get("passive_retrieval_comparison", {})),
        reasoning_fields=CRITIC_REASONING_FIELDS,
        decision_fields=CRITIC_DECISION_FIELDS,
    )
    retrieval_packet = dict(dict(summary_payload.get("inputs", {})).get("retrieval_packet", {}))
    policy = dict(summary_payload.get("policy", {}))
    return {
        "family_id": str(case["family_id"]),
        "cycle_label": str(case["cycle_label"]),
        "status": str(summary_payload.get("final_status", "")),
        "execution_mode": str(summary_payload.get("execution_mode", verifier.DEFAULT_SHADOW_EXECUTION_MODE)),
        "retrieval_packet_path": str(case["retrieval_packet_path"]),
        "retrieval_latest_memory_id": str(retrieval_packet.get("latest_memory_id", "")),
        "retrieval_semantic_sha256": str(retrieval_packet.get("semantic_sha256", "")),
        "policy": {
            "authoritative_decision_behavior_changed": bool(
                policy.get("authoritative_decision_behavior_changed", False)
            ),
            "fail_closed_preserved": bool(policy.get("fail_closed_preserved", False)),
            "source_of_truth_mutation": bool(policy.get("source_of_truth_mutation", False)),
            "strategy_logic_mutation": bool(policy.get("strategy_logic_mutation", False)),
            "production_changes_required": bool(policy.get("production_changes_required", False)),
            "governor_mutated": bool(policy.get("governor_mutated", False)),
        },
        "planner": planner,
        "critic": critic,
    }


def aggregate_deltas(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "sum": 0, "avg": 0.0, "min": 0, "max": 0}
    return {
        "count": len(values),
        "sum": sum(values),
        "avg": round(sum(values) / len(values), 3),
        "min": min(values),
        "max": max(values),
    }


def build_decision_field_counts(counter: Counter[str], field_names: frozenset[str]) -> dict[str, int]:
    return {field_name: int(counter.get(field_name, 0)) for field_name in sorted(field_names)}


def write_compact_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "family_id",
        "cycle_label",
        "status",
        "fail_closed_preserved",
        "planner_reasoning_fields_changed",
        "planner_decision_fields_changed",
        "planner_reasoning_changed",
        "planner_decision_stayed_identical",
        "planner_reasoning_changed_decision_identical",
        "planner_prompt_input_token_delta",
        "planner_input_token_delta",
        "planner_output_token_delta",
        "planner_total_token_delta",
        "critic_reasoning_fields_changed",
        "critic_decision_fields_changed",
        "critic_reasoning_changed",
        "critic_decision_stayed_identical",
        "critic_reasoning_changed_decision_identical",
        "critic_prompt_input_token_delta",
        "critic_input_token_delta",
        "critic_output_token_delta",
        "critic_total_token_delta",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def build_compact_summary_rows(case_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_result in case_results:
        planner = dict(case_result.get("planner", {}))
        critic = dict(case_result.get("critic", {}))
        policy = dict(case_result.get("policy", {}))
        rows.append(
            {
                "family_id": str(case_result.get("family_id", "")),
                "cycle_label": str(case_result.get("cycle_label", "")),
                "status": str(case_result.get("status", "")),
                "fail_closed_preserved": bool(policy.get("fail_closed_preserved", False)),
                "planner_reasoning_fields_changed": ",".join(planner.get("changed_reasoning_fields", [])),
                "planner_decision_fields_changed": ",".join(planner.get("changed_decision_fields", [])),
                "planner_reasoning_changed": bool(planner.get("reasoning_changed", False)),
                "planner_decision_stayed_identical": bool(planner.get("decision_stayed_identical", False)),
                "planner_reasoning_changed_decision_identical": bool(
                    planner.get("reasoning_changed_decision_identical", False)
                ),
                "planner_prompt_input_token_delta": int(planner.get("prompt_estimated_input_tokens_delta", 0) or 0),
                "planner_input_token_delta": int(planner.get("response_input_tokens_delta", 0) or 0),
                "planner_output_token_delta": int(planner.get("response_output_tokens_delta", 0) or 0),
                "planner_total_token_delta": int(planner.get("response_total_tokens_delta", 0) or 0),
                "critic_reasoning_fields_changed": ",".join(critic.get("changed_reasoning_fields", [])),
                "critic_decision_fields_changed": ",".join(critic.get("changed_decision_fields", [])),
                "critic_reasoning_changed": bool(critic.get("reasoning_changed", False)),
                "critic_decision_stayed_identical": bool(critic.get("decision_stayed_identical", False)),
                "critic_reasoning_changed_decision_identical": bool(
                    critic.get("reasoning_changed_decision_identical", False)
                ),
                "critic_prompt_input_token_delta": int(critic.get("prompt_estimated_input_tokens_delta", 0) or 0),
                "critic_input_token_delta": int(critic.get("response_input_tokens_delta", 0) or 0),
                "critic_output_token_delta": int(critic.get("response_output_tokens_delta", 0) or 0),
                "critic_total_token_delta": int(critic.get("response_total_tokens_delta", 0) or 0),
            }
        )
    return rows


def blocked_reasons_for_real_mode(
    *,
    case_results: list[dict[str, Any]],
    evaluation_errors: list[dict[str, Any]],
    missing_requested_cases: list[dict[str, Any]],
    retrieval_missing_cases: list[dict[str, Any]],
    real_openai_failure_cases: list[dict[str, Any]],
    planner_decision_counts: dict[str, int],
    critic_decision_counts: dict[str, int],
    all_fail_closed: bool,
) -> list[str]:
    reasons: list[str] = []
    if not case_results:
        reasons.append("no_cases_evaluated")
    if evaluation_errors:
        reasons.append("real_openai_call_failed")
    if missing_requested_cases:
        reasons.append("requested_case_set_incomplete")
    if retrieval_missing_cases:
        reasons.append("retrieval_missing")
    if real_openai_failure_cases:
        reasons.append("real_openai_call_failed")
    if sum(planner_decision_counts.values()) + sum(critic_decision_counts.values()) > 0:
        reasons.append("decision_fields_changed")
    if not all_fail_closed:
        reasons.append("fail_closed_not_preserved")
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def build_markdown_report(summary_payload: dict[str, Any]) -> str:
    summary = dict(summary_payload.get("summary", {}))
    blocked_conditions = dict(summary.get("blocked_conditions", {}))
    compact_summary_path = str(dict(summary_payload.get("inputs", {})).get("compact_summary_path", ""))
    lines = [
        "# TrendAtlas Shadow Batch Eval",
        "",
        f"- Evaluated at: `{summary_payload.get('evaluated_at_utc', '')}`",
        f"- Execution mode: `{summary_payload.get('execution_mode', verifier.DEFAULT_SHADOW_EXECUTION_MODE)}`",
        f"- Final status: `{summary_payload.get('final_status', '')}`",
        f"- Cases evaluated: `{summary.get('cases_evaluated', 0)}`",
        f"- Fail-closed preserved across all cases: `{dict(summary_payload.get('policy', {})).get('fail_closed_preserved', False)}`",
        f"- Requested case set complete: `{summary.get('requested_case_set_complete', True)}`",
        f"- Compact manual review artifact: `{compact_summary_path}`",
        "",
        "## Decision Field Counts",
        "",
        f"- Planner: `{json.dumps(summary.get('planner_decision_field_change_counts', {}), sort_keys=True)}`",
        f"- Critic: `{json.dumps(summary.get('critic_decision_field_change_counts', {}), sort_keys=True)}`",
        "",
        "## Blocked Conditions",
        "",
        f"- Blocked reasons: `{', '.join(summary.get('blocked_reasons', [])) or 'none'}`",
        f"- Evaluation errors: `{blocked_conditions.get('evaluation_errors', 0)}`",
        f"- Missing requested cases: `{blocked_conditions.get('missing_requested_cases', 0)}`",
        f"- Retrieval-missing cases: `{blocked_conditions.get('retrieval_missing_cases', 0)}`",
        f"- Real-call failure cases: `{blocked_conditions.get('real_openai_failure_cases', 0)}`",
        "",
        "## Reasoning-Only Diffs",
        "",
        f"- Planner reasoning-only cases: `{summary.get('planner_reasoning_only_change_cases', 0)}`",
        f"- Critic reasoning-only cases: `{summary.get('critic_reasoning_only_change_cases', 0)}`",
        f"- Planner reasoning field diff frequency: `{json.dumps(summary.get('planner_reasoning_field_differences_frequency', {}), sort_keys=True)}`",
        f"- Critic reasoning field diff frequency: `{json.dumps(summary.get('critic_reasoning_field_differences_frequency', {}), sort_keys=True)}`",
        "",
        "## Token Deltas",
        "",
        f"- Planner prompt/input/output deltas: `{json.dumps(dict(summary.get('token_deltas', {})).get('planner', {}), sort_keys=True)}`",
        f"- Critic prompt/input/output deltas: `{json.dumps(dict(summary.get('token_deltas', {})).get('critic', {}), sort_keys=True)}`",
        "",
        "## Reasoning Changed, Decision Identical",
        "",
        f"- Planner cases: `{summary.get('planner_reasoning_changed_decision_identical_cases', 0)}`",
        f"- Critic cases: `{summary.get('critic_reasoning_changed_decision_identical_cases', 0)}`",
        f"- Combined cases: `{summary.get('reasoning_changed_decision_identical_case_count', 0)}`",
        "",
        "## Cases",
        "",
    ]
    for case_result in list(summary_payload.get("cases", [])):
        planner = dict(case_result.get("planner", {}))
        critic = dict(case_result.get("critic", {}))
        lines.extend(
            [
                f"- `{case_result.get('family_id', '')} / {case_result.get('cycle_label', '')}`: "
                f"planner_candidate_status=`{planner.get('candidate_status', '')}`, "
                f"critic_candidate_status=`{critic.get('candidate_status', '')}`, "
                f"planner_reasoning_changed_decision_identical=`{planner.get('reasoning_changed_decision_identical', False)}`, "
                f"critic_reasoning_changed_decision_identical=`{critic.get('reasoning_changed_decision_identical', False)}`, "
                f"planner_output_delta=`{planner.get('response_output_tokens_delta', 0)}`, "
                f"critic_output_delta=`{critic.get('response_output_tokens_delta', 0)}`",
            ]
        )
    if not list(summary_payload.get("cases", [])):
        lines.append("- `none`")
    return "\n".join(lines).rstrip() + "\n"


def build_summary(
    *,
    retrieval_root: Path,
    planner_input_root: Path,
    heavy_validation_root: Path,
    output_path: Path,
    markdown_path: Path,
    compact_summary_path: Path,
    execution_mode: str,
    requested_family_ids: list[str],
    requested_cycle_labels: list[str],
    packets: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    discovery_details: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    planner_changed_field_counter: Counter[str] = Counter()
    critic_changed_field_counter: Counter[str] = Counter()
    planner_reasoning_field_counter: Counter[str] = Counter()
    critic_reasoning_field_counter: Counter[str] = Counter()
    planner_decision_field_counter: Counter[str] = Counter()
    critic_decision_field_counter: Counter[str] = Counter()
    planner_prompt_deltas: list[int] = []
    planner_input_deltas: list[int] = []
    planner_output_deltas: list[int] = []
    planner_total_deltas: list[int] = []
    planner_compact_vs_full_prompt_deltas: list[int] = []
    critic_prompt_deltas: list[int] = []
    critic_input_deltas: list[int] = []
    critic_output_deltas: list[int] = []
    critic_total_deltas: list[int] = []
    critic_compact_vs_full_prompt_deltas: list[int] = []
    planner_decision_field_changes: list[dict[str, Any]] = []
    critic_decision_field_changes: list[dict[str, Any]] = []
    reasoning_changed_decision_identical_cases: list[dict[str, Any]] = []
    retrieval_missing_cases: list[dict[str, Any]] = []
    real_openai_failure_cases: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    evaluation_errors: list[dict[str, Any]] = []

    requested_case_keys = {
        (family_id, cycle_label)
        for family_id in requested_family_ids
        for cycle_label in requested_cycle_labels
    }

    for case in cases:
        try:
            summary_payload = verifier.evaluate_verification_case(
                retrieval_packet_path=str(case["retrieval_packet_path"]),
                planner_input_path=str(case["planner_input_path"]),
                heavy_validation_summary_path=str(case["heavy_validation_summary_path"]),
                execution_mode=execution_mode,
            )
        except Exception as exc:
            evaluation_errors.append(
                {
                    "family_id": str(case["family_id"]),
                    "cycle_label": str(case["cycle_label"]),
                    "error": str(exc),
                }
            )
            continue

        case_result = build_case_result(case, summary_payload)
        case_results.append(case_result)
        planner = dict(case_result["planner"])
        critic = dict(case_result["critic"])

        planner_changed_field_counter.update(planner["changed_note_fields"])
        critic_changed_field_counter.update(critic["changed_note_fields"])
        planner_reasoning_field_counter.update(planner["changed_reasoning_fields"])
        critic_reasoning_field_counter.update(critic["changed_reasoning_fields"])
        planner_decision_field_counter.update(planner["changed_decision_fields"])
        critic_decision_field_counter.update(critic["changed_decision_fields"])
        planner_prompt_deltas.append(int(planner["prompt_estimated_input_tokens_delta"]))
        planner_input_deltas.append(int(planner["response_input_tokens_delta"]))
        planner_output_deltas.append(int(planner["response_output_tokens_delta"]))
        planner_total_deltas.append(int(planner["response_total_tokens_delta"]))
        planner_compact_vs_full_prompt_deltas.append(
            int(
                dict(dict(planner.get("retrieval_prompt_observability", {})).get("token_delta_impact", {})).get(
                    "compact_vs_full_prompt_estimated_input_tokens_delta",
                    0,
                )
            )
        )
        critic_prompt_deltas.append(int(critic["prompt_estimated_input_tokens_delta"]))
        critic_input_deltas.append(int(critic["response_input_tokens_delta"]))
        critic_output_deltas.append(int(critic["response_output_tokens_delta"]))
        critic_total_deltas.append(int(critic["response_total_tokens_delta"]))
        critic_compact_vs_full_prompt_deltas.append(
            int(
                dict(dict(critic.get("retrieval_prompt_observability", {})).get("token_delta_impact", {})).get(
                    "compact_vs_full_prompt_estimated_input_tokens_delta",
                    0,
                )
            )
        )

        if planner["changed_decision_fields"]:
            planner_decision_field_changes.append(
                {
                    "family_id": str(case["family_id"]),
                    "cycle_label": str(case["cycle_label"]),
                    "changed_fields": list(planner["changed_decision_fields"]),
                }
            )
        if critic["changed_decision_fields"]:
            critic_decision_field_changes.append(
                {
                    "family_id": str(case["family_id"]),
                    "cycle_label": str(case["cycle_label"]),
                    "changed_fields": list(critic["changed_decision_fields"]),
                }
            )
        if planner.get("reasoning_changed_decision_identical", False) or critic.get(
            "reasoning_changed_decision_identical", False
        ):
            reasoning_changed_decision_identical_cases.append(
                {
                    "family_id": str(case["family_id"]),
                    "cycle_label": str(case["cycle_label"]),
                    "planner": bool(planner.get("reasoning_changed_decision_identical", False)),
                    "critic": bool(critic.get("reasoning_changed_decision_identical", False)),
                }
            )
        if not bool(dict(planner.get("passive_retrieval_comparison", {})).get("retrieval_packet_present", False)) or not bool(
            dict(critic.get("passive_retrieval_comparison", {})).get("retrieval_packet_present", False)
        ):
            retrieval_missing_cases.append(
                {
                    "family_id": str(case["family_id"]),
                    "cycle_label": str(case["cycle_label"]),
                    "planner_retrieval_packet_status": str(
                        dict(planner.get("passive_retrieval_comparison", {})).get("retrieval_packet_status", "")
                    ),
                    "critic_retrieval_packet_status": str(
                        dict(critic.get("passive_retrieval_comparison", {})).get("retrieval_packet_status", "")
                    ),
                }
            )
        if execution_mode == verifier.REAL_OPENAI_SHADOW_EXECUTION_MODE:
            for component_name, component_summary in (("planner", planner), ("critic", critic)):
                if str(component_summary.get("candidate_status", "")) != "completed":
                    real_openai_failure_cases.append(
                        {
                            "family_id": str(case["family_id"]),
                            "cycle_label": str(case["cycle_label"]),
                            "component": component_name,
                            "candidate_status": str(component_summary.get("candidate_status", "")),
                            "candidate_error": str(component_summary.get("candidate_error", "")),
                        }
                    )

    all_fail_closed = bool(case_results) and all(
        bool(dict(case_result["policy"]).get("fail_closed_preserved", False))
        and bool(dict(case_result["planner"]).get("fail_closed_preserved", False))
        and bool(dict(case_result["critic"]).get("fail_closed_preserved", False))
        for case_result in case_results
    )
    any_policy_mutation = any(
        bool(dict(case_result["policy"]).get("source_of_truth_mutation", False))
        or bool(dict(case_result["policy"]).get("strategy_logic_mutation", False))
        or bool(dict(case_result["policy"]).get("production_changes_required", False))
        or bool(dict(case_result["policy"]).get("governor_mutated", False))
        for case_result in case_results
    )
    planner_decision_counts = build_decision_field_counts(planner_decision_field_counter, PLANNER_DECISION_FIELDS)
    critic_decision_counts = build_decision_field_counts(critic_decision_field_counter, CRITIC_DECISION_FIELDS)
    discovered_case_keys = {(str(case["family_id"]), str(case["cycle_label"])) for case in cases}
    missing_requested_cases = [
        {"family_id": family_id, "cycle_label": cycle_label}
        for family_id, cycle_label in sorted(requested_case_keys - discovered_case_keys)
    ]
    if execution_mode == verifier.REAL_OPENAI_SHADOW_EXECUTION_MODE:
        blocked_reasons = blocked_reasons_for_real_mode(
            case_results=case_results,
            evaluation_errors=evaluation_errors,
            missing_requested_cases=missing_requested_cases,
            retrieval_missing_cases=retrieval_missing_cases,
            real_openai_failure_cases=real_openai_failure_cases,
            planner_decision_counts=planner_decision_counts,
            critic_decision_counts=critic_decision_counts,
            all_fail_closed=all_fail_closed,
        )
        final_status = "working" if not blocked_reasons else "blocked"
    else:
        blocked_reasons = []
        final_status = "working" if case_results and not evaluation_errors and not any_policy_mutation and all_fail_closed else "blocked"
    families_tested = sorted({str(case_result["family_id"]) for case_result in case_results})
    cycles_tested = [
        {
            "family_id": str(case_result["family_id"]),
            "cycle_label": str(case_result["cycle_label"]),
        }
        for case_result in case_results
    ]
    compact_summary_rows = build_compact_summary_rows(case_results)

    return {
        "schema_version": "trendatlas.shadow_batch_eval.v3",
        "evaluated_at_utc": verifier.utc_now_iso(),
        "execution_mode": execution_mode,
        "final_status": final_status,
        "policy": {
            "fail_closed_preserved": all_fail_closed,
            "source_of_truth_mutation": False,
            "strategy_mutation": False,
            "official_promotion_logic_changed": False,
            "governor_mutated": False,
            "authoritative_decision_behavior_changed_cases": len(planner_decision_field_changes)
            + len(critic_decision_field_changes),
        },
        "inputs": {
            "retrieval_root": str(retrieval_root),
            "planner_input_root": str(planner_input_root),
            "heavy_validation_root": str(heavy_validation_root),
            "output_path": str(output_path),
            "markdown_path": str(markdown_path),
            "compact_summary_path": str(compact_summary_path),
            "requested_family_ids": requested_family_ids,
            "requested_cycle_labels": requested_cycle_labels,
            "retrieval_packets_considered": packets,
            "skipped_discovery": skipped,
            "discovery_details": discovery_details,
        },
        "summary": {
            "cases_evaluated": len(case_results),
            "families_tested": families_tested,
            "cycles_tested": cycles_tested,
            "requested_case_set_complete": not missing_requested_cases,
            "planner_changed_fields_frequency": dict(sorted(planner_changed_field_counter.items())),
            "critic_changed_fields_frequency": dict(sorted(critic_changed_field_counter.items())),
            "planner_reasoning_field_differences_frequency": dict(sorted(planner_reasoning_field_counter.items())),
            "critic_reasoning_field_differences_frequency": dict(sorted(critic_reasoning_field_counter.items())),
            "planner_reasoning_only_change_cases": sum(
                1 for case_result in case_results if bool(dict(case_result["planner"]).get("reasoning_only_change", False))
            ),
            "critic_reasoning_only_change_cases": sum(
                1 for case_result in case_results if bool(dict(case_result["critic"]).get("reasoning_only_change", False))
            ),
            "planner_reasoning_changed_decision_identical_cases": sum(
                1
                for case_result in case_results
                if bool(dict(case_result["planner"]).get("reasoning_changed_decision_identical", False))
            ),
            "critic_reasoning_changed_decision_identical_cases": sum(
                1
                for case_result in case_results
                if bool(dict(case_result["critic"]).get("reasoning_changed_decision_identical", False))
            ),
            "reasoning_changed_decision_identical_case_count": len(reasoning_changed_decision_identical_cases),
            "reasoning_changed_decision_identical_cases": reasoning_changed_decision_identical_cases,
            "planner_decision_field_change_counts": planner_decision_counts,
            "critic_decision_field_change_counts": critic_decision_counts,
            "planner_decision_fields_changed_any": any(planner_decision_counts.values()),
            "critic_decision_fields_changed_any": any(critic_decision_counts.values()),
            "planner_decision_field_changes": planner_decision_field_changes,
            "critic_decision_field_changes": critic_decision_field_changes,
            "token_deltas": {
                "planner": {
                    "prompt_estimated_input_tokens_delta": aggregate_deltas(planner_prompt_deltas),
                    "response_input_tokens_delta": aggregate_deltas(planner_input_deltas),
                    "response_output_tokens_delta": aggregate_deltas(planner_output_deltas),
                    "response_total_tokens_delta": aggregate_deltas(planner_total_deltas),
                    "compact_vs_full_prompt_estimated_input_tokens_delta": aggregate_deltas(
                        planner_compact_vs_full_prompt_deltas
                    ),
                },
                "critic": {
                    "prompt_estimated_input_tokens_delta": aggregate_deltas(critic_prompt_deltas),
                    "response_input_tokens_delta": aggregate_deltas(critic_input_deltas),
                    "response_output_tokens_delta": aggregate_deltas(critic_output_deltas),
                    "response_total_tokens_delta": aggregate_deltas(critic_total_deltas),
                    "compact_vs_full_prompt_estimated_input_tokens_delta": aggregate_deltas(
                        critic_compact_vs_full_prompt_deltas
                    ),
                },
            },
            "prompt_input_token_deltas": {
                "planner": {
                    "prompt_estimated_input_tokens_delta": aggregate_deltas(planner_prompt_deltas),
                    "response_input_tokens_delta": aggregate_deltas(planner_input_deltas),
                },
                "critic": {
                    "prompt_estimated_input_tokens_delta": aggregate_deltas(critic_prompt_deltas),
                    "response_input_tokens_delta": aggregate_deltas(critic_input_deltas),
                },
            },
            "blocked_reasons": blocked_reasons,
            "blocked_conditions": {
                "evaluation_errors": len(evaluation_errors),
                "missing_requested_cases": len(missing_requested_cases),
                "retrieval_missing_cases": len(retrieval_missing_cases),
                "real_openai_failure_cases": len(real_openai_failure_cases),
            },
            "missing_requested_cases": missing_requested_cases,
            "retrieval_missing_cases": retrieval_missing_cases,
            "real_openai_failure_cases": real_openai_failure_cases,
            "evaluation_errors": evaluation_errors,
        },
        "compact_summary_rows": compact_summary_rows,
        "cases": case_results,
    }


def run_batch_eval(
    *,
    retrieval_root: Path,
    planner_input_root: Path,
    heavy_validation_root: Path,
    output_path: Path,
    markdown_path: Path,
    compact_summary_path: Path,
    family_ids: list[str],
    cycle_labels: list[str],
    limit: int,
    execution_mode: str,
) -> dict[str, Any]:
    family_filter = {family_id.strip() for family_id in family_ids if family_id.strip()}
    cycle_filter = {cycle_label.strip() for cycle_label in cycle_labels if cycle_label.strip()}
    cases, skipped, packets, discovery_details = discover_cases(
        retrieval_root=retrieval_root,
        planner_input_root=planner_input_root,
        heavy_validation_root=heavy_validation_root,
        family_filter=family_filter,
        cycle_filter=cycle_filter,
        limit=limit,
    )
    requested_family_ids = sorted(family_filter)
    requested_cycle_labels = sorted(cycle_filter)
    summary_payload = build_summary(
        retrieval_root=retrieval_root,
        planner_input_root=planner_input_root,
        heavy_validation_root=heavy_validation_root,
        output_path=output_path,
        markdown_path=markdown_path,
        compact_summary_path=compact_summary_path,
        execution_mode=execution_mode,
        requested_family_ids=requested_family_ids,
        requested_cycle_labels=requested_cycle_labels,
        packets=packets,
        skipped=skipped,
        discovery_details=discovery_details,
        cases=cases,
    )
    verifier.write_json(output_path, summary_payload)
    write_compact_summary(compact_summary_path, list(summary_payload.get("compact_summary_rows", [])))
    verifier.write_text(markdown_path, build_markdown_report(summary_payload))
    return {
        "status": summary_payload["final_status"],
        "execution_mode": execution_mode,
        "output_path": str(output_path),
        "markdown_path": str(markdown_path),
        "compact_summary_path": str(compact_summary_path),
        "cases_evaluated": int(dict(summary_payload["summary"]).get("cases_evaluated", 0)),
        "families_tested": list(dict(summary_payload["summary"]).get("families_tested", [])),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    execution_mode = verifier.resolve_shadow_execution_mode(
        use_real_openai=bool(args.use_real_openai),
        mode_config_path=args.mode_config or None,
    )
    family_ids = list(args.family_ids)
    cycle_labels = list(args.cycle_labels)
    default_output_path = DEFAULT_OUTPUT_PATH
    default_markdown_path = DEFAULT_MARKDOWN_PATH
    default_compact_summary_path = DEFAULT_COMPACT_SUMMARY_PATH
    if execution_mode == verifier.REAL_OPENAI_SHADOW_EXECUTION_MODE:
        family_ids = [REAL_SHADOW_FAMILY_ID]
        cycle_labels = list(REAL_SHADOW_CYCLE_LABELS)
        default_output_path = REAL_OUTPUT_PATH
        default_markdown_path = REAL_MARKDOWN_PATH
        default_compact_summary_path = REAL_COMPACT_SUMMARY_PATH

    result = run_batch_eval(
        retrieval_root=resolve_path(args.retrieval_root),
        planner_input_root=resolve_path(args.planner_input_root),
        heavy_validation_root=resolve_path(args.heavy_validation_root),
        output_path=resolve_path(args.output_path) if args.output_path else default_output_path,
        markdown_path=resolve_path(args.markdown_path) if args.markdown_path else default_markdown_path,
        compact_summary_path=resolve_path(args.compact_summary_path)
        if args.compact_summary_path
        else default_compact_summary_path,
        family_ids=family_ids,
        cycle_labels=cycle_labels,
        limit=int(args.limit or 0),
        execution_mode=execution_mode,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "working" else 1


if __name__ == "__main__":
    raise SystemExit(main())
