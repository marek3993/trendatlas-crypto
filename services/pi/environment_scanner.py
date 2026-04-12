from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from services.shared.runtime_bootstrap import load_runtime_config as load_runtime_config_shared
from services.shared.artifact_writer import ArtifactWriter
from services.shared.schemas import EnvironmentScan, FamilyRegistry, FamilyStateSnapshot, MarketStateSnapshot, RuntimeConfig, SCHEMA_VERSION, utc_now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    return load_runtime_config_shared(path)


def scan_environment(config: RuntimeConfig, project_root: Path = PROJECT_ROOT) -> EnvironmentScan:
    safe_environment = {key: os.environ.get(key, "") for key in config.scanner_env_keys}
    notes = [
        "dev_only_research_os_scan",
        "no_live_trading_logic",
        "source_of_truth_not_mutated",
    ]
    return EnvironmentScan.collect(
        scanner_id="pi_environment_scanner",
        role=config.role,
        project_root=project_root,
        paths=config.scanner_paths,
        environment=safe_environment,
        notes=notes,
    )


def load_json_artifact(project_root: Path, artifact_config: dict[str, Any]) -> dict[str, Any]:
    raw_path = Path(str(artifact_config["path"]))
    path = raw_path if raw_path.is_absolute() else project_root / raw_path
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object artifact: {path}")
    return {"config": dict(artifact_config), "path": str(path.resolve()), "payload": payload}


def load_research_artifacts(config: RuntimeConfig, project_root: Path = PROJECT_ROOT) -> list[dict[str, Any]]:
    return [load_json_artifact(project_root, artifact_config) for artifact_config in config.research_artifacts]


def _metric(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def extract_family_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = {
        "net_total_return_delta_pct": (
            _metric(payload, "net_total_return", "delta_probe_minus_baseline_pct")
            or _metric(payload, "total_return_net", "delta_probe_minus_baseline_pct")
            or _metric(payload, "net_return_after_costs_delta_pct")
        ),
        "net_cagr_delta_pct": (
            _metric(payload, "net_cagr", "delta_probe_minus_baseline_pct")
            or _metric(payload, "cagr_net", "delta_probe_minus_baseline_pct")
        ),
        "max_drawdown_delta_pct": (
            _metric(payload, "net_max_drawdown", "delta_probe_minus_baseline_pct")
            or _metric(payload, "max_drawdown_net", "delta_probe_minus_baseline_pct")
            or _metric(payload, "max_drawdown", "delta_probe_minus_baseline_pct")
        ),
        "switch_count_delta": (
            payload.get("switch_count_delta")
            or _metric(payload, "switch_count", "delta_probe_minus_baseline")
        ),
        "trade_days_delta": payload.get("trade_days_delta"),
        "trade_count_delta": _metric(payload, "trade_count", "delta_probe_minus_baseline"),
        "turnover_pressure_delta": _metric(payload, "turnover_pressure", "delta_probe_minus_baseline"),
        "net_early_move_capture_total_pct": _metric(payload, "net_early_move_capture", "total_pct"),
        "net_early_move_capture_delta_pct": _metric(payload, "net_early_move_capture", "delta_probe_minus_baseline_pct"),
        "lead_days_avg": _metric(payload, "lead_days_vs_baseline", "avg_lead_days"),
        "lead_days_max": _metric(payload, "lead_days_vs_baseline", "max_lead_days"),
    }
    return {key: value for key, value in metrics.items() if value is not None}


def summarize_artifact(loaded_artifact: dict[str, Any]) -> dict[str, Any]:
    payload = loaded_artifact["payload"]
    artifact_id = str(payload.get("artifact_id") or loaded_artifact["config"].get("artifact_id", "unknown_artifact"))
    return {
        "artifact_id": artifact_id,
        "family_id": str(loaded_artifact["config"].get("family_id", artifact_id)),
        "path": loaded_artifact["path"],
        "artifact_type": str(loaded_artifact["config"].get("artifact_type", payload.get("artifact_type", "summary"))),
        "generated_at_utc": str(payload.get("generated_at_utc", "")),
        "mechanism_id": str(payload.get("mechanism_id", payload.get("follow_up_recommendation", {}).get("mechanism_id", ""))),
        "verdict": str(payload.get("final_verdict") or payload.get("final_diagnostic_verdict") or payload.get("status", "")),
        "status": str(payload.get("status", "")),
        "metrics": extract_family_metrics(payload),
        "governance": {
            "dev_only": bool(payload.get("dev_only", False)),
            "non_authoritative": bool(payload.get("non_authoritative", False)),
            "official_truth": bool(payload.get("official_truth", False)),
            "strategy_advancement": bool(payload.get("strategy_advancement", False)),
            "candidate_selection": bool(payload.get("candidate_selection", False)),
            "official_edge_claim": bool(payload.get("official_edge_claim", False)),
        },
        "input_refs": payload.get("input_refs", {}),
        "raw_keys": sorted(payload.keys()),
    }


def build_market_state_snapshot(config: RuntimeConfig, project_root: Path = PROJECT_ROOT) -> MarketStateSnapshot:
    source_artifacts = [summarize_artifact(artifact) for artifact in load_research_artifacts(config, project_root)]
    profile = next((artifact for artifact in source_artifacts if artifact["artifact_type"] == "profile"), {})
    subset = next((artifact for artifact in source_artifacts if artifact["artifact_id"] == "supportive_vs_caution_subset_layer_v1"), {})
    market_context = {
        "artifact_ids": [artifact["artifact_id"] for artifact in source_artifacts],
        "latest_generated_at_utc": max((artifact["generated_at_utc"] for artifact in source_artifacts if artifact["generated_at_utc"]), default=""),
        "response_shape_profile": {
            "artifact_id": profile.get("artifact_id", ""),
            "path": profile.get("path", ""),
        },
        "subset_layer": {
            "artifact_id": subset.get("artifact_id", ""),
            "path": subset.get("path", ""),
        },
        "verdict_counts": _count_values([artifact["verdict"] for artifact in source_artifacts]),
    }
    return MarketStateSnapshot(
        schema_version=SCHEMA_VERSION,
        snapshot_id="latest_market_state",
        generated_at=utc_now_iso(),
        mode="dev_only_research_os_snapshot",
        dev_only=True,
        non_authoritative=True,
        official_truth=False,
        source_artifact_count=len(source_artifacts),
        source_artifacts=source_artifacts,
        market_context=market_context,
        governance=_safe_governance(),
        notes=["read_only_snapshot_from_allowlisted_dev_only_artifacts"],
    )


def build_family_state_snapshot(
    config: RuntimeConfig,
    family_registry: FamilyRegistry,
    project_root: Path = PROJECT_ROOT,
) -> FamilyStateSnapshot:
    summaries = [summarize_artifact(artifact) for artifact in load_research_artifacts(config, project_root)]
    summaries_by_id = {summary["artifact_id"]: summary for summary in summaries}
    families: list[dict[str, Any]] = []
    for family in family_registry.families:
        attempts = [
            summaries_by_id[artifact_id]
            for artifact_id in family.source_artifact_ids
            if artifact_id in summaries_by_id
        ]
        last_attempt = attempts[-1] if attempts else {}
        families.append(
            {
                "family_id": family.family_id,
                "owner": family.owner,
                "status": family.status,
                "description": family.description,
                "attempt_count": len(attempts),
                "last_verdict": str(last_attempt.get("verdict", "")),
                "last_artifact_id": str(last_attempt.get("artifact_id", "")),
                "last_metrics": dict(last_attempt.get("metrics", {})),
                "lineage": attempts,
                "constraints": family.constraints,
                "safe_next_job_type": "analyze_family_state",
            }
        )
    return FamilyStateSnapshot(
        schema_version=SCHEMA_VERSION,
        snapshot_id="latest_family_state_snapshot",
        generated_at=utc_now_iso(),
        mode="dev_only_family_state_snapshot",
        dev_only=True,
        non_authoritative=True,
        official_truth=False,
        families=families,
        artifact_count=len(summaries),
        notes=["registry_lineage_snapshot_from_allowlisted_non_authoritative_artifacts"],
    )


def _count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        label = value or "unknown"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _safe_governance() -> dict[str, Any]:
    return {
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "source_of_truth_mutation": False,
        "live_trading": False,
        "official_promotion_logic": False,
    }


def write_market_state_snapshot(config: RuntimeConfig, project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    writer = ArtifactWriter(config.runtime_root)
    record = writer.write_json("market_state/latest_market_state.json", build_market_state_snapshot(config, project_root).to_dict())
    return record.to_dict()


def write_family_state_snapshot(
    config: RuntimeConfig,
    family_registry: FamilyRegistry,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    writer = ArtifactWriter(config.runtime_root)
    snapshot = build_family_state_snapshot(config, family_registry, project_root)
    record = writer.write_json(
        "family_state/latest_family_state_snapshot.json",
        snapshot.to_dict(),
    )
    from services.pi.registry_service import RegistryService

    RegistryService(config.registry_path).upsert_family_state_snapshot(snapshot.to_dict())
    return record.to_dict()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pi environment scanner skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--family-registry", default="configs/families/family_registry.template.json")
    parser.add_argument("--write", action="store_true", help="Write scan JSON under artifact_root.")
    parser.add_argument("--write-market-state", action="store_true", help="Write real dev-only market state snapshot.")
    parser.add_argument("--write-family-state", action="store_true", help="Write real dev-only family state snapshot.")
    parser.add_argument("--write-snapshots", action="store_true", help="Write both real dev-only snapshots.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    family_registry = None
    if args.write_family_state or args.write_snapshots:
        from services.pi.planner_service import load_family_registry

        family_registry = load_family_registry(args.family_registry)
    records: list[dict[str, Any]] = []
    scan = scan_environment(config)
    if args.write:
        writer = ArtifactWriter(config.artifact_root)
        record = writer.write_json("environment/latest_environment_scan.json", scan.to_dict())
        records.append(record.to_dict())
    if args.write_market_state or args.write_snapshots:
        records.append(write_market_state_snapshot(config))
    if args.write_family_state or args.write_snapshots:
        if family_registry is None:
            raise RuntimeError("family registry not loaded")
        records.append(write_family_state_snapshot(config, family_registry))
    if records:
        print(json.dumps(records, indent=2, sort_keys=True))
    else:
        print(json.dumps(scan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
