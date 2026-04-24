from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "mvp" / "artifacts"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "imlayer_exports"
SCHEMA_VERSION = "trendatlas.imlayer.decision_episode.v1"
MANIFEST_SCHEMA_VERSION = "trendatlas.imlayer.export_manifest.v1"
PROJECT_NAME = "trendatlas-crypto"
SOURCE_SYSTEM = "trendatlas-research-os"
REQUIRED_KEY_FIELDS = (
    "cycle_id",
    "family_id",
    "proposal_id",
    "request_id",
    "result_id",
    "verdict_id",
    "state_id",
)


class ExportSkip(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def compact_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def stringify_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def require_non_empty_string(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExportSkip(f"{label} must be a non-empty string")
    return value.strip()


def summarize_expected_impact(expected_impact: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for key, value in expected_impact.items():
        if not isinstance(value, dict):
            continue
        summary[key] = {
            "direction": value.get("direction"),
            "target": value.get("target"),
            "basis": value.get("basis", {}),
        }
    return summary


def stage_ref_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(record["path"]).resolve()
    return {
        "artifact_id": record.get("artifact_id"),
        "path": str(path),
        "relative_path": relative_path(path),
        "sha256": record.get("sha256") or sha256_file(path),
        "format": record.get("format"),
        "row_count": record.get("row_count"),
        "metadata": record.get("metadata"),
    }


def stage_ref_from_path(path: Path, artifact_id: Optional[str] = None) -> Dict[str, Any]:
    resolved = path.resolve()
    return {
        "artifact_id": artifact_id,
        "path": str(resolved),
        "relative_path": relative_path(resolved),
        "sha256": sha256_file(resolved),
        "format": resolved.suffix.lstrip(".") or None,
        "row_count": None,
        "metadata": None,
    }


def find_one(records: List[Dict[str, Any]], predicate, description: str) -> Dict[str, Any]:
    matches = [record for record in records if predicate(record)]
    if len(matches) != 1:
        raise ExportSkip(f"expected exactly one {description}, found {len(matches)}")
    return matches[0]


def require_value(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ExportSkip(f"{label} expected {expected!r}, got {actual!r}")


def build_export_policy() -> Dict[str, Any]:
    return {
        "mode": "dev_only_export_preparation",
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "fail_closed_export": True,
        "partial_episode_export_allowed": False,
        "live_integration": False,
    }


def require_governance_flags(
    cycle_summary: Dict[str, Any],
    proposal: Dict[str, Any],
    heavy_summary: Dict[str, Any],
    critic: Dict[str, Any],
    governor: Dict[str, Any],
) -> Dict[str, Any]:
    expected = {
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "official_promotion_logic": False,
        "source_of_truth_mutation": False,
    }
    for key, value in expected.items():
        require_value(f"cycle_summary.{key}", cycle_summary.get(key), value)
        require_value(f"proposal.{key}", proposal.get(key), value)
        require_value(f"heavy_summary.{key}", heavy_summary.get(key), value)
        require_value(f"critic.{key}", critic.get(key), value)
        require_value(f"governor.{key}", governor.get(key), value)

    nested = governor.get("governance", {})
    if not isinstance(nested, dict):
        raise ExportSkip("governor.governance must be an object")

    require_value("governor.governance.dev_only", nested.get("dev_only"), True)
    require_value("governor.governance.non_authoritative", nested.get("non_authoritative"), True)
    require_value("governor.governance.official_truth", nested.get("official_truth"), False)
    require_value("governor.governance.live_trading", nested.get("live_trading"), False)
    require_value(
        "governor.governance.planner_blocked_without_override",
        nested.get("planner_blocked_without_override"),
        True,
    )
    require_value("governor.strategy_advancement", governor.get("strategy_advancement", False), False)

    return {
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "official_promotion_logic": False,
        "source_of_truth_mutation": False,
        "strategy_advancement": False,
        "planner_blocked_without_override": True,
        "fail_closed": True,
        "official_truth_source": "false_by_contract",
    }


def build_compact_packet(
    proposal: Dict[str, Any],
    heavy_summary: Dict[str, Any],
    critic: Dict[str, Any],
    governor: Dict[str, Any],
) -> Dict[str, str]:
    mutation_target = proposal["proposal"]["mutation_target"]

    planner_packet = (
        f"proposal {proposal['proposal']['proposal_id']} target {mutation_target.get('target_id')} "
        f"type {mutation_target.get('target_type')} scope {mutation_target.get('scope')}"
    )

    heavy_packet = (
        f"{heavy_summary.get('status')} via {heavy_summary.get('adapter_id')} "
        f"request {heavy_summary.get('request_id')}"
    )

    critic_packet = (
        f"{critic.get('verdict')} next {critic.get('next_action')} dd "
        f"{stringify_metric(critic.get('key_metrics', {}).get('dd'))} switch "
        f"{stringify_metric(critic.get('key_metrics', {}).get('switch_count_delta'))} trade_days "
        f"{stringify_metric(critic.get('key_metrics', {}).get('trade_days_delta'))}"
    )

    governor_packet = (
        f"{governor.get('lifecycle_state')} planning_eligible {governor.get('planning_eligible')} "
        f"planner_blocked_without_override {governor.get('governance', {}).get('planner_blocked_without_override')}"
    )

    return {
        "planner": planner_packet,
        "heavy_validation": heavy_packet,
        "critic": critic_packet,
        "governor": governor_packet,
    }


def build_retrieval_text(
    cycle_id: str,
    family_id: str,
    proposal: Dict[str, Any],
    heavy_summary: Dict[str, Any],
    critic: Dict[str, Any],
    governor: Dict[str, Any],
) -> str:
    mutation_target = proposal["proposal"]["mutation_target"]
    target_id = mutation_target.get("target_id") or "unknown_target"
    target_type = mutation_target.get("target_type") or "unknown_target_type"
    exact_change = compact_text(mutation_target.get("exact_change"), limit=220) or "change summary unavailable"
    verdict_reason = compact_text(critic.get("verdict_reason"), limit=220) or "reason unavailable"
    breaches = critic.get("evidence", {}).get("guardrail_breaches", [])
    breach_text = ", ".join(str(item) for item in breaches) if breaches else "none"

    text = (
        f"TrendAtlas decision episode {cycle_id} family {family_id}. Dev only, non authoritative, official truth false, "
        f"live trading false. Planner proposed {target_id} as {target_type}: {exact_change} "
        f"Heavy validation status {heavy_summary.get('status')} via {heavy_summary.get('adapter_id')}. "
        f"Critic verdict {critic.get('verdict')} because {verdict_reason}. "
        f"Guardrail breaches: {breach_text}. Governor set lifecycle {governor.get('lifecycle_state')} "
        f"with planning eligible {governor.get('planning_eligible')}."
    ).strip()

    if not text:
        raise ExportSkip(f"retrieval_text resolved empty for {cycle_id}/{family_id}")
    return text


def find_family_snapshot(planner_job: Dict[str, Any], family_id: str) -> Dict[str, Any]:
    families = planner_job.get("payload", {}).get("family_state_snapshot", {}).get("families", [])
    for family_snapshot in families:
        if family_snapshot.get("family_id") == family_id:
            return family_snapshot
    raise ExportSkip(f"missing family snapshot for {family_id}")


def find_one_json_record(
    records: List[Dict[str, Any]],
    suffix: str,
    description: str,
    payload_predicate,
) -> Dict[str, Any]:
    matches = []
    for record in records:
        if not str(record.get("path", "")).endswith(suffix):
            continue
        payload = read_json(Path(record["path"]))
        if not payload_predicate(payload):
            continue
        matches.append(record)

    if len(matches) != 1:
        raise ExportSkip(f"expected exactly one {description}, found {len(matches)}")
    return matches[0]


def validate_episode_contract(episode: Dict[str, Any]) -> None:
    errors: List[str] = []

    if episode.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    retrieval_text = episode.get("retrieval_text")
    if not isinstance(retrieval_text, str) or not retrieval_text.strip():
        errors.append("retrieval_text must be a non-empty string")

    governance = episode.get("governance")
    if not isinstance(governance, dict):
        errors.append("governance must be an object")

    export_policy = episode.get("export_policy")
    if not isinstance(export_policy, dict):
        errors.append("export_policy must be an object")
    else:
        expected_export_policy = build_export_policy()
        for key, expected in expected_export_policy.items():
            if export_policy.get(key) != expected:
                errors.append(f"export_policy.{key} must be {expected!r}")

    keys = episode.get("keys")
    if not isinstance(keys, dict):
        errors.append("keys must be an object")
    else:
        for key in REQUIRED_KEY_FIELDS:
            value = keys.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"keys.{key} must be a non-empty string")

    if errors:
        raise ExportSkip("; ".join(errors))


def build_episode_batch(cycle_summary_path: Path) -> List[Dict[str, Any]]:
    cycle_summary = read_json(cycle_summary_path)
    produced_artifacts = cycle_summary.get("produced_artifacts", [])
    cycle_id = require_non_empty_string("cycle_summary.cycle_id", cycle_summary.get("cycle_id"))

    planner_output_record = find_one(
        produced_artifacts,
        lambda record: str(record.get("path", "")).endswith("_planner_output.json"),
        "planner output artifact",
    )
    planner_output = read_json(Path(planner_output_record["path"]))

    episodes = []
    for planner_job in planner_output.get("jobs", []):
        if planner_job.get("job_type") != "propose_next_mutation":
            continue

        family_id = require_non_empty_string("planner_job.family_id", planner_job.get("family_id"))
        job_id = require_non_empty_string("planner_job.job_id", planner_job.get("job_id"))

        proposal_record = find_one(
            produced_artifacts,
            lambda record: str(record.get("path", "")).endswith("_mutation_proposal.json")
            and record.get("metadata", {}).get("job_id") == job_id,
            f"mutation proposal artifact for {job_id}",
        )
        proposal = read_json(Path(proposal_record["path"]))
        proposal_id = require_non_empty_string("proposal.proposal_id", proposal.get("proposal", {}).get("proposal_id"))

        heavy_request_record = find_one_json_record(
            produced_artifacts,
            "_heavy_validation_request.json",
            f"heavy validation request artifact for {family_id}",
            lambda payload: payload.get("heavy_validation_request", {}).get("proposal_id") == proposal_id
            or payload.get("source_mutation_proposal", {}).get("proposal_id") == proposal_id,
        )
        heavy_request = read_json(Path(heavy_request_record["path"]))
        heavy_request_id = require_non_empty_string(
            "heavy_validation_request.request_id",
            heavy_request.get("heavy_validation_request", {}).get("request_id"),
        )

        heavy_summary_record = find_one(
            produced_artifacts,
            lambda record: str(record.get("path", "")).endswith("_summary.json")
            and record.get("metadata", {}).get("request_id") == heavy_request_id,
            f"heavy validation summary artifact for {family_id}",
        )
        heavy_summary = read_json(Path(heavy_summary_record["path"]))

        heavy_compare_record = find_one(
            produced_artifacts,
            lambda record: str(record.get("path", "")).endswith("_compare.csv")
            and record.get("metadata", {}).get("request_id") == heavy_request_id,
            f"heavy validation compare artifact for {family_id}",
        )

        heavy_cost_record = find_one(
            produced_artifacts,
            lambda record: str(record.get("path", "")).endswith("_cost_metrics.csv")
            and record.get("metadata", {}).get("request_id") == heavy_request_id,
            f"heavy validation cost metrics artifact for {family_id}",
        )

        critic_record = find_one(
            produced_artifacts,
            lambda record: str(record.get("path", "")).endswith("_critic_family_verdict.json")
            and record.get("metadata", {}).get("request_id") == heavy_request_id,
            f"critic verdict artifact for {family_id}",
        )
        critic = read_json(Path(critic_record["path"]))

        governor_record = find_one(
            produced_artifacts,
            lambda record: str(record.get("path", "")).endswith("_governor_state.json")
            and record.get("metadata", {}).get("family_id") == family_id,
            f"governor state artifact for {family_id}",
        )
        governor = read_json(Path(governor_record["path"]))

        require_value(f"proposal.family_id[{family_id}]", proposal.get("family_id"), family_id)
        require_value(f"heavy_request.family_id[{family_id}]", heavy_request.get("family_id"), family_id)
        require_value(f"heavy_summary.family_id[{family_id}]", heavy_summary.get("family_id"), family_id)
        require_value(f"critic.family_id[{family_id}]", critic.get("family_id"), family_id)
        require_value(f"governor.family_id[{family_id}]", governor.get("family_id"), family_id)
        require_value(
            f"heavy_request.proposal_id[{family_id}]",
            heavy_request.get("heavy_validation_request", {}).get("proposal_id"),
            proposal_id,
        )
        require_value(f"heavy_summary.proposal_id[{family_id}]", heavy_summary.get("proposal_id"), proposal_id)
        require_value(f"critic.proposal_id[{family_id}]", critic.get("proposal_id"), proposal_id)
        require_value(f"heavy_summary.request_id[{family_id}]", heavy_summary.get("request_id"), heavy_request_id)
        require_value(f"critic.request_id[{family_id}]", critic.get("request_id"), heavy_request_id)
        require_value(f"governor.verdict_id[{family_id}]", governor.get("verdict_id"), critic.get("verdict_id"))

        governance = require_governance_flags(cycle_summary, proposal, heavy_summary, critic, governor)
        family_snapshot = find_family_snapshot(planner_job, family_id)
        memory_id = f"trendatlas.crypto.decision_episode.{cycle_id}.{family_id}"

        episode = {
            "schema_version": SCHEMA_VERSION,
            "memory_unit": "decision_episode",
            "memory_id": memory_id,
            "episode_id": memory_id,
            "project": PROJECT_NAME,
            "source_system": SOURCE_SYSTEM,
            "export_generated_at": utc_now_iso(),
            "export_policy": build_export_policy(),
            "governance": governance,
            "keys": {
                "cycle_id": cycle_id,
                "family_id": family_id,
                "proposal_id": proposal_id,
                "request_id": heavy_request_id,
                "result_id": require_non_empty_string("critic.result_id", critic.get("result_id")),
                "verdict_id": require_non_empty_string("critic.verdict_id", critic.get("verdict_id")),
                "state_id": require_non_empty_string("governor.state_id", governor.get("state_id")),
            },
            "episode_timestamps": {
                "cycle_started_at": cycle_summary.get("started_at"),
                "cycle_completed_at": cycle_summary.get("completed_at"),
                "planner_created_at": planner_job.get("created_at"),
                "proposal_generated_at": proposal.get("generated_at"),
                "heavy_validation_started_at": heavy_summary.get("started_at"),
                "heavy_validation_finished_at": heavy_summary.get("finished_at"),
                "critic_generated_at": critic.get("generated_at"),
                "governor_updated_at": governor.get("last_updated_at"),
            },
            "planner_proposal": {
                "job_id": job_id,
                "proposal_id": proposal_id,
                "description": planner_job.get("payload", {}).get("description"),
                "family_last_artifact_id": family_snapshot.get("last_artifact_id"),
                "family_last_verdict": family_snapshot.get("last_verdict"),
                "family_last_metrics": family_snapshot.get("last_metrics", {}),
                "lineage_artifact_ids": proposal.get("proposal", {}).get("lineage_refs", {}).get(
                    "family_attempt_artifact_ids", []
                ),
                "mechanism_hypothesis": proposal.get("proposal", {}).get("mechanism_hypothesis"),
                "mutation_target": proposal.get("proposal", {}).get("mutation_target", {}),
                "expected_impact": summarize_expected_impact(proposal.get("proposal", {}).get("expected_impact", {})),
                "stop_condition": proposal.get("proposal", {}).get("stop_condition"),
                "validation_status": proposal.get("validation", {}).get("status"),
            },
            "heavy_validation_verdict": {
                "job_id": heavy_summary.get("job_id"),
                "request_id": heavy_summary.get("request_id"),
                "proposal_id": heavy_summary.get("proposal_id"),
                "status": heavy_summary.get("status"),
                "adapter_id": heavy_summary.get("adapter_id"),
                "mutation_target": heavy_summary.get("mutation_target", {}),
                "expected_impact": summarize_expected_impact(heavy_summary.get("expected_impact", {})),
                "stop_condition": heavy_summary.get("stop_condition"),
                "notes": heavy_summary.get("notes", []),
            },
            "critic_verdict": {
                "job_id": critic.get("job_id"),
                "verdict_id": critic.get("verdict_id"),
                "verdict": critic.get("verdict"),
                "verdict_reason": critic.get("verdict_reason"),
                "next_action": critic.get("next_action"),
                "guardrail_breaches": critic.get("evidence", {}).get("guardrail_breaches", []),
                "key_metrics": critic.get("key_metrics", {}),
                "net_first_rules": critic.get("evidence", {}).get("net_first_rules", {}),
            },
            "governor_decision": {
                "job_id": governor.get("job_id"),
                "state_id": governor.get("state_id"),
                "lifecycle_state": governor.get("lifecycle_state"),
                "planning_eligible": governor.get("planning_eligible"),
                "last_next_action": governor.get("last_next_action"),
                "last_verdict": governor.get("last_verdict"),
                "attempt_count": governor.get("attempt_count"),
                "confirmatory_count": governor.get("confirmatory_count"),
                "planner_blocked_without_override": governor.get("governance", {}).get(
                    "planner_blocked_without_override"
                ),
            },
            "artifact_refs": {
                "cycle_summary": stage_ref_from_path(
                    cycle_summary_path,
                    artifact_id=f"cycle_outputs__{cycle_id}_cycle_summary_json",
                ),
                "planner_output": stage_ref_from_record(planner_output_record),
                "mutation_proposal": stage_ref_from_record(proposal_record),
                "heavy_validation_request": stage_ref_from_record(heavy_request_record),
                "heavy_validation_summary": stage_ref_from_record(heavy_summary_record),
                "heavy_validation_compare": stage_ref_from_record(heavy_compare_record),
                "heavy_validation_cost_metrics": stage_ref_from_record(heavy_cost_record),
                "critic_verdict": stage_ref_from_record(critic_record),
                "governor_state": stage_ref_from_record(governor_record),
            },
        }
        episode["compact_packet"] = build_compact_packet(proposal, heavy_summary, critic, governor)
        episode["retrieval_text"] = build_retrieval_text(cycle_id, family_id, proposal, heavy_summary, critic, governor)
        validate_episode_contract(episode)
        episodes.append(episode)

    return episodes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare TrendAtlas dev-only imLayer decision episode exports.")
    parser.add_argument(
        "--source-root",
        default=str(SOURCE_ROOT),
        help="Research OS MVP artifacts root containing cycle_outputs.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Destination root for export batches.",
    )
    parser.add_argument(
        "--export-batch-id",
        default=None,
        help="Optional explicit export batch id. Defaults to UTC timestamp.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_root = Path(args.source_root).resolve()
    cycle_outputs_root = source_root / "cycle_outputs"
    if not cycle_outputs_root.exists():
        raise SystemExit(f"Missing cycle outputs directory: {cycle_outputs_root}")

    export_batch_id = args.export_batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_root).resolve()
    batch_root = output_root / export_batch_id
    episodes_root = batch_root / "episodes"
    episodes_root.mkdir(parents=True, exist_ok=False)

    exported_paths: List[str] = []
    skipped: List[Dict[str, str]] = []
    cycle_summaries = sorted(cycle_outputs_root.glob("*_cycle_summary.json"))

    for cycle_summary_path in cycle_summaries:
        try:
            for episode in build_episode_batch(cycle_summary_path):
                episode_path = episodes_root / f"{episode['memory_id']}.json"
                write_json(episode_path, episode)
                exported_paths.append(episode_path.relative_to(batch_root).as_posix())
        except ExportSkip as exc:
            skipped.append(
                {
                    "cycle_summary_path": str(cycle_summary_path.resolve()),
                    "reason": str(exc),
                }
            )

    if not exported_paths:
        raise SystemExit("No complete decision episodes were exported.")

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "project": PROJECT_NAME,
        "source_system": SOURCE_SYSTEM,
        "export_batch_id": export_batch_id,
        "generated_at": utc_now_iso(),
        "source_root": str(source_root),
        "cycle_outputs_root": str(cycle_outputs_root),
        "output_root": str(batch_root),
        "policy": {
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "live_trading": False,
            "fail_closed_export": True,
            "partial_episode_export_allowed": False,
            "live_integration": False,
        },
        "cycle_summary_count": len(cycle_summaries),
        "episode_export_count": len(exported_paths),
        "skipped_count": len(skipped),
        "episode_paths": exported_paths,
        "skipped": skipped,
    }
    write_json(batch_root / "manifest.json", manifest)

    print(f"export_batch_id={export_batch_id}")
    print(f"output_root={batch_root}")
    print(f"episode_export_count={len(exported_paths)}")
    print(f"skipped_count={len(skipped)}")
    print(f"sample_episode={exported_paths[0]}")


if __name__ == "__main__":
    main()