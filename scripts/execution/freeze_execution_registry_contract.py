from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

PATHS_REGISTRY_PATH = ROOT / "source_of_truth" / "paths_registry.json"
CURRENT_ISSUES_PATH = ROOT / "source_of_truth" / "current_issues.md"
SCRIPT_REGISTRY_PATH = ROOT / "canonical" / "script_registry.json"
OUTPUT_REGISTRY_PATH = ROOT / "canonical" / "output_registry.json"

LOG_DIR = ROOT / "outputs" / "execution" / "logs"
LOG_PATH = LOG_DIR / "freeze_execution_registry_contract.log"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def log(msg: str) -> None:
    print(msg)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Invalid JSON in {path}: {e}")
    except Exception as e:
        fail(f"Failed reading {path}: {e}")
    raise RuntimeError("unreachable")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def upsert_dict_key(target: dict[str, Any], key: str, value: Any) -> None:
    target[key] = value


def upsert_script(scripts: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    script_path = entry["script_path"]
    for idx, existing in enumerate(scripts):
        if existing.get("script_path") == script_path:
            scripts[idx] = entry
            return
    scripts.append(entry)


def upsert_output(outputs: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    output_path = entry["output_path"]
    for idx, existing in enumerate(outputs):
        if existing.get("output_path") == output_path:
            outputs[idx] = entry
            return
    outputs.append(entry)


def ensure_artifact(
    artifacts: dict[str, Any],
    key: str,
    canonical: str,
    owner: str,
    artifact_type: str,
    truth_domain: str,
    read_scope: list[str],
    write_mode: str,
    legacy_aliases: list[str] | None = None,
) -> None:
    artifacts[key] = {
        "canonical": canonical,
        "legacy_aliases": legacy_aliases or [],
        "owner": owner,
        "artifact_type": artifact_type,
        "truth_domain": truth_domain,
        "read_scope": read_scope,
        "write_mode": write_mode,
    }


def main() -> None:
    log("[START] freeze_execution_registry_contract")

    paths_registry = read_json(PATHS_REGISTRY_PATH)
    script_registry = read_json(SCRIPT_REGISTRY_PATH)
    output_registry = read_json(OUTPUT_REGISTRY_PATH)

    canonical_roots = paths_registry.setdefault("canonical_roots", {})
    artifact_type_definitions = paths_registry.setdefault("artifact_type_definitions", {})
    artifacts = paths_registry.setdefault("artifacts", {})

    upsert_dict_key(
        canonical_roots,
        "execution_read_only",
        str(ROOT / "outputs" / "execution" / "read_only"),
    )
    upsert_dict_key(
        canonical_roots,
        "execution_live_status",
        str(ROOT / "outputs" / "execution" / "live_status"),
    )
    upsert_dict_key(
        canonical_roots,
        "execution_source_contract",
        str(ROOT / "outputs" / "execution" / "source_contract"),
    )
    upsert_dict_key(
        canonical_roots,
        "execution_intents",
        str(ROOT / "outputs" / "execution" / "intents"),
    )
    upsert_dict_key(
        canonical_roots,
        "execution_dry_run",
        str(ROOT / "outputs" / "execution" / "dry_run"),
    )
    upsert_dict_key(
        canonical_roots,
        "execution_logs",
        str(ROOT / "outputs" / "execution" / "logs"),
    )

    upsert_dict_key(
        artifact_type_definitions,
        "account_snapshot",
        "read_only_exchange_account_snapshot_output",
    )
    upsert_dict_key(
        artifact_type_definitions,
        "execution_intent",
        "normalized_execution_intent_output",
    )
    upsert_dict_key(
        artifact_type_definitions,
        "dry_run_decision",
        "simulated_execution_decision_output",
    )
    upsert_dict_key(
        artifact_type_definitions,
        "execution_log",
        "execution_runtime_log_output",
    )

    ensure_artifact(
        artifacts,
        "execution_read_only_snapshot",
        str(ROOT / "outputs" / "execution" / "read_only" / "hyperliquid_account_snapshot.json"),
        "DATA",
        "account_snapshot",
        "execution",
        ["app", "execution", "automation", "validation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_read_only_snapshot_quality",
        str(ROOT / "outputs" / "execution" / "read_only" / "hyperliquid_account_snapshot_quality.json"),
        "DATA",
        "validation_report",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_read_only_snapshot_manifest",
        str(ROOT / "outputs" / "execution" / "read_only" / "hyperliquid_account_snapshot_manifest.json"),
        "DATA",
        "manifest",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )

    ensure_artifact(
        artifacts,
        "execution_status_json",
        str(ROOT / "outputs" / "execution" / "live_status" / "execution_status.json"),
        "DATA",
        "live_status",
        "execution",
        ["app", "execution", "automation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_status_manifest",
        str(ROOT / "outputs" / "execution" / "live_status" / "execution_status_manifest.json"),
        "DATA",
        "manifest",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )

    ensure_artifact(
        artifacts,
        "execution_source_contract_report",
        str(ROOT / "outputs" / "execution" / "source_contract" / "execution_source_contract_report.json"),
        "DATA",
        "validation_report",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_source_contract_quality",
        str(ROOT / "outputs" / "execution" / "source_contract" / "execution_source_contract_quality.json"),
        "DATA",
        "validation_report",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_source_contract_manifest",
        str(ROOT / "outputs" / "execution" / "source_contract" / "execution_source_contract_manifest.json"),
        "DATA",
        "manifest",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )

    ensure_artifact(
        artifacts,
        "execution_intent_latest",
        str(ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent.json"),
        "DATA",
        "execution_intent",
        "execution",
        ["app", "execution", "automation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_intent_quality",
        str(ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent_quality.json"),
        "DATA",
        "validation_report",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_intent_manifest",
        str(ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent_manifest.json"),
        "DATA",
        "manifest",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )

    ensure_artifact(
        artifacts,
        "execution_dry_run_decision",
        str(ROOT / "outputs" / "execution" / "dry_run" / "latest_dry_run_decision.json"),
        "DATA",
        "dry_run_decision",
        "execution",
        ["app", "execution", "automation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_dry_run_decision_quality",
        str(ROOT / "outputs" / "execution" / "dry_run" / "latest_dry_run_decision_quality.json"),
        "DATA",
        "validation_report",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )
    ensure_artifact(
        artifacts,
        "execution_dry_run_decision_manifest",
        str(ROOT / "outputs" / "execution" / "dry_run" / "latest_dry_run_decision_manifest.json"),
        "DATA",
        "manifest",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )

    ensure_artifact(
        artifacts,
        "execution_action_log",
        str(ROOT / "outputs" / "execution" / "logs" / "execution_action_log.jsonl"),
        "DATA",
        "execution_log",
        "execution",
        ["execution", "automation", "validation"],
        "generated_runtime_output",
    )

    scripts = script_registry.setdefault("scripts", [])
    execution_scripts = [
        {
            "script_path": "scripts/execution/materialize_execution_app_exports.py",
            "layer": "execution_data",
            "status": "active",
            "purpose": "Copies legacy strategy exports to canonical execution app export paths without fabricating data.",
            "primary_outputs": [
                "outputs/execution/app_exports/",
                "outputs/execution/freshness/",
                "outputs/execution/refresh_pipeline/materialize_execution_app_exports_report.json",
                "outputs/execution/refresh_pipeline/materialize_execution_app_exports_quality.json",
                "outputs/execution/refresh_pipeline/materialize_execution_app_exports_manifest.json",
            ],
            "output_type": "execution_export_materialization",
            "decision_relevance": "support_only",
            "writes_source_of_truth": False,
            "notes": "Bridge only. No official truth writes."
        },
        {
            "script_path": "scripts/execution/validate_execution_source_contract.py",
            "layer": "execution_data",
            "status": "active",
            "purpose": "Validates canonical execution input contract presence and basic shape before intent build.",
            "primary_outputs": [
                "outputs/execution/source_contract/execution_source_contract_report.json",
                "outputs/execution/source_contract/execution_source_contract_quality.json",
                "outputs/execution/source_contract/execution_source_contract_manifest.json",
            ],
            "output_type": "validation",
            "decision_relevance": "support_only",
            "writes_source_of_truth": False,
            "notes": "Read-only validator for execution contract."
        },
        {
            "script_path": "scripts/execution/hyperliquid_read_only_snapshot.py",
            "layer": "execution_data",
            "status": "active",
            "purpose": "Fetches Hyperliquid account state in read-only mode and writes snapshot/quality/manifest artifacts.",
            "primary_outputs": [
                "outputs/execution/read_only/hyperliquid_account_snapshot.json",
                "outputs/execution/read_only/hyperliquid_account_snapshot_quality.json",
                "outputs/execution/read_only/hyperliquid_account_snapshot_manifest.json",
            ],
            "output_type": "read_only_snapshot",
            "decision_relevance": "support_only",
            "writes_source_of_truth": False,
            "notes": "No order placement."
        },
        {
            "script_path": "scripts/execution/render_execution_app_status.py",
            "layer": "execution_data",
            "status": "active",
            "purpose": "Renders app-facing execution live status from read-only snapshot artifacts.",
            "primary_outputs": [
                "outputs/execution/live_status/execution_status.json",
                "outputs/execution/live_status/execution_status_manifest.json",
            ],
            "output_type": "live_status",
            "decision_relevance": "support_only",
            "writes_source_of_truth": False,
            "notes": "App read model only."
        },
        {
            "script_path": "scripts/execution/build_execution_intent_from_strategy_exports.py",
            "layer": "execution_data",
            "status": "active",
            "purpose": "Builds deterministic normalized execution intent from canonical strategy exports and freshness report.",
            "primary_outputs": [
                "outputs/execution/intents/latest_execution_intent.json",
                "outputs/execution/intents/latest_execution_intent_quality.json",
                "outputs/execution/intents/latest_execution_intent_manifest.json",
            ],
            "output_type": "execution_intent",
            "decision_relevance": "decision_relevant",
            "writes_source_of_truth": False,
            "notes": "Intent only. No live orders."
        },
        {
            "script_path": "scripts/execution/run_dry_execution_bridge.py",
            "layer": "execution_data",
            "status": "active",
            "purpose": "Combines normalized intent with read-only account snapshot and produces simulated execution decision plus app status.",
            "primary_outputs": [
                "outputs/execution/dry_run/latest_dry_run_decision.json",
                "outputs/execution/dry_run/latest_dry_run_decision_quality.json",
                "outputs/execution/dry_run/latest_dry_run_decision_manifest.json",
                "outputs/execution/live_status/execution_status.json",
                "outputs/execution/logs/execution_action_log.jsonl",
            ],
            "output_type": "dry_run_execution",
            "decision_relevance": "decision_relevant",
            "writes_source_of_truth": False,
            "notes": "Dry-run only. No real orders."
        },
    ]
    for entry in execution_scripts:
        upsert_script(scripts, entry)

    outputs = output_registry.setdefault("outputs", [])
    execution_outputs = [
        {
            "output_path": "outputs/execution/read_only/",
            "generated_by": ["scripts/execution/hyperliquid_read_only_snapshot.py"],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "read_only_snapshot_outputs",
            "decision_relevance": "support_only",
            "official_truth": False,
            "notes": "Hyperliquid read-only account snapshots and validation sidecars."
        },
        {
            "output_path": "outputs/execution/live_status/",
            "generated_by": [
                "scripts/execution/render_execution_app_status.py",
                "scripts/execution/run_dry_execution_bridge.py",
            ],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "execution_live_status_outputs",
            "decision_relevance": "support_only",
            "official_truth": False,
            "notes": "App-facing execution status. Not official truth."
        },
        {
            "output_path": "outputs/execution/source_contract/",
            "generated_by": ["scripts/execution/validate_execution_source_contract.py"],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "execution_contract_validation_outputs",
            "decision_relevance": "support_only",
            "official_truth": False,
            "notes": "Contract validation artifacts for execution pipeline."
        },
        {
            "output_path": "outputs/execution/intents/",
            "generated_by": ["scripts/execution/build_execution_intent_from_strategy_exports.py"],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "normalized_execution_intent_outputs",
            "decision_relevance": "decision_relevant",
            "official_truth": False,
            "notes": "Deterministic intent artifacts derived from canonical strategy exports."
        },
        {
            "output_path": "outputs/execution/dry_run/",
            "generated_by": ["scripts/execution/run_dry_execution_bridge.py"],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "dry_run_execution_outputs",
            "decision_relevance": "decision_relevant",
            "official_truth": False,
            "notes": "Simulated execution decisions only. No real orders."
        },
        {
            "output_path": "outputs/execution/logs/",
            "generated_by": [
                "scripts/execution/hyperliquid_read_only_snapshot.py",
                "scripts/execution/render_execution_app_status.py",
                "scripts/execution/run_dry_execution_bridge.py",
                "scripts/execution/freeze_execution_registry_contract.py",
            ],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "runtime_logs",
            "decision_relevance": "support_only",
            "official_truth": False,
            "notes": "Operational logs only."
        },
    ]
    for entry in execution_outputs:
        upsert_output(outputs, entry)

    current_issues_text = """# Current Issues

## Leverage branch truth-promotion status
- research/raw winner = phase68i_66g_1p50x_static
- best deployment candidate = phase68i_dynamic_ladder_candidate
- official softer fallback = phase68g_66g_1p25x_candidate
- Phase68J simple tail-risk guardrails = rejected
- ordering remains unchanged
- leverage branch is strong enough for truth-promotion workflow
- leverage branch is not approved for direct auto-switch to app/live

## Execution refresh branch status
- Hyperliquid execution branch is frozen at safe read-only + dry-run scope
- automation wrapper layer for execution refresh is functional
- canonical execution chain is:
  1. scripts/execution/materialize_execution_app_exports.py
  2. scripts/execution/validate_execution_source_contract.py
  3. scripts/execution/hyperliquid_read_only_snapshot.py
  4. scripts/execution/render_execution_app_status.py
  5. scripts/execution/build_execution_intent_from_strategy_exports.py
  6. scripts/execution/run_dry_execution_bridge.py
- execution outputs are decision-relevant operational artifacts, not official truth
- automation artifacts for execution refresh are not official truth
- live orders are not enabled yet
- source_of_truth writes are not part of execution refresh runtime
"""
    CURRENT_ISSUES_PATH.write_text(current_issues_text, encoding="utf-8")

    write_json(PATHS_REGISTRY_PATH, paths_registry)
    write_json(SCRIPT_REGISTRY_PATH, script_registry)
    write_json(OUTPUT_REGISTRY_PATH, output_registry)

    log(f"[SAVED] {PATHS_REGISTRY_PATH}")
    log(f"[SAVED] {SCRIPT_REGISTRY_PATH}")
    log(f"[SAVED] {OUTPUT_REGISTRY_PATH}")
    log(f"[SAVED] {CURRENT_ISSUES_PATH}")
    log("[END] freeze_execution_registry_contract success")


if __name__ == "__main__":
    main()