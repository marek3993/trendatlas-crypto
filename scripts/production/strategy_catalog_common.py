from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import (
    Phase68g66g1p25xCandidateAdapter,
)
from scripts.production.strategy_adapters.phase68g_btc_persistence_10d_early_risk_075_adapter import (
    CANDIDATE_ID as BTC_PERSISTENCE_MODEL,
    DEV_ONLY_CONTRACT_PATH,
    DEV_ONLY_MANIFEST_SEED_PATH,
    DEV_ONLY_OUTPUT_DIR,
    DEV_ONLY_SPEC_PATH,
    Phase68gBtcPersistence10dEarlyRisk075Adapter,
)
from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    CANDIDATE_ID as ETF_FLOW_MODEL,
    Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = ROOT / "outputs" / "api" / "v1" / "strategy_catalog.json"
CATALOG_SCHEMA_VERSION = 1

PHASE68G_MODEL = "phase68g_66g_1p25x_candidate"
PHASE68I_MODEL = "phase68i_dynamic_ladder_candidate"
SUPPORTED_MODELS = (
    PHASE68G_MODEL,
    BTC_PERSISTENCE_MODEL,
    ETF_FLOW_MODEL,
    PHASE68I_MODEL,
)
ALLOWED_CURRENT_ROLES = {
    "official_live_main",
    "official_softer_fallback",
    "secondary_fallback",
    "legacy_fallback_only",
}
PRODUCTION_OUTPUT_PATHS = [
    "outputs/production/current_strategy_snapshot.json",
    "outputs/production/current_strategy_timeseries.csv",
    "outputs/production/current_strategy_diagnostics.json",
    "outputs/production/current_strategy_snapshot.quality.json",
    "outputs/production/current_strategy_snapshot.manifest.json",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def repo_rel(path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    try:
        return candidate.relative_to(ROOT).as_posix()
    except ValueError:
        return str(candidate.resolve()).replace("\\", "/")


def resolve_repo_path(path_text: str) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def _dedupe_paths(paths: list[str | Path]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        normalized = repo_rel(raw_path)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _display_label(display_names: dict[str, Any], model: str, fallback: str) -> str:
    payload = display_names.get(model)
    if isinstance(payload, dict):
        label = str(payload.get("en") or "").strip()
        if label:
            return label
    return fallback


def _current_role_map(project_truth: dict[str, Any]) -> dict[str, str]:
    leverage_truth = project_truth.get("leverage_truth")
    if not isinstance(leverage_truth, dict):
        raise ValueError("project_truth.json missing leverage_truth")
    current_live = str(leverage_truth.get("current_live_truth") or "").strip()
    softer_fallback = str(leverage_truth.get("official_softer_fallback") or "").strip()
    secondary_fallback = str(leverage_truth.get("secondary_fallback") or "").strip()
    if not current_live or not softer_fallback or not secondary_fallback:
        raise ValueError("project_truth.json leverage_truth is missing one or more fallback fields")
    return {
        current_live: "official_live_main",
        softer_fallback: "official_softer_fallback",
        secondary_fallback: "secondary_fallback",
        PHASE68I_MODEL: "legacy_fallback_only",
    }


def _build_phase68g_entry(
    *,
    label: str,
    current_role: str,
    softer_fallback: str,
    legacy_fallback: str,
) -> dict[str, Any]:
    adapter = Phase68g66g1p25xCandidateAdapter()
    source_paths = _dedupe_paths(list(adapter.resolve_source_paths(root=ROOT).values()))
    return {
        "strategy_model": PHASE68G_MODEL,
        "label": label,
        "status": "active_fallback",
        "current_role": current_role,
        "production_adapter_or_build_route": {
            "kind": "production_core_live_adapter",
            "entrypoint": "scripts/production/strategy_adapters/phase68g_66g_1p25x_candidate_adapter.py",
            "build_script": "scripts/production/build_current_strategy_snapshot.py",
            "validation_script": "scripts/production/validate_current_strategy_snapshot.py",
        },
        "required_source_paths": source_paths,
        "expected_production_outputs": list(PRODUCTION_OUTPUT_PATHS),
        "required_evidence_window": {
            "applicable": False,
            "type": "none",
            "requirement": "No extra evidence window beyond the canonical phase68g export chain.",
        },
        "data_requirements": [
            "Canonical phase68g paper and authoritative export must exist under outputs/execution/app_exports/.",
            "phase66g live status, phase66g trend history, and app freshness report must align to the same closed day.",
            "BTC daily OHLCV must exist and match the production closed day.",
        ],
        "authority_publish_required": True,
        "notes": (
            "Secondary fallback baseline route. Production Core can rebuild it directly without mutating "
            "source_of_truth, but live cutover still requires separate Raspberry Pi authority publish."
        ),
        "fallback_relationship": {
            "live_strategy": ETF_FLOW_MODEL,
            "softer_fallback": softer_fallback,
            "secondary_fallback": PHASE68G_MODEL,
            "legacy_fallback": legacy_fallback,
        },
    }


def _build_btc_persistence_entry(
    *,
    label: str,
    current_role: str,
    legacy_fallback: str,
) -> dict[str, Any]:
    baseline_paths = list(Phase68g66g1p25xCandidateAdapter().resolve_source_paths(root=ROOT).values())
    source_paths = _dedupe_paths(
        [
            *baseline_paths,
            DEV_ONLY_CONTRACT_PATH,
            DEV_ONLY_SPEC_PATH,
            DEV_ONLY_MANIFEST_SEED_PATH,
            DEV_ONLY_OUTPUT_DIR / "summary.json",
            DEV_ONLY_OUTPUT_DIR / "quality.json",
            DEV_ONLY_OUTPUT_DIR / "variant_compare.csv",
            ROOT / "scripts" / "dev_only_production_core_btc_candidate_persistence_early_risk_compare.py",
        ]
    )
    return {
        "strategy_model": BTC_PERSISTENCE_MODEL,
        "label": label,
        "status": "active_fallback",
        "current_role": current_role,
        "production_adapter_or_build_route": {
            "kind": "production_core_live_adapter",
            "entrypoint": "scripts/production/strategy_adapters/phase68g_btc_persistence_10d_early_risk_075_adapter.py",
            "build_script": "scripts/production/build_current_strategy_snapshot.py",
            "validation_script": "scripts/production/validate_current_strategy_snapshot.py",
        },
        "required_source_paths": source_paths,
        "expected_production_outputs": list(PRODUCTION_OUTPUT_PATHS),
        "required_evidence_window": {
            "applicable": True,
            "type": "variant_selection_evidence",
            "source_path": (
                "outputs/research_os/dev_only/non_authoritative_production_core_btc_candidate_"
                "persistence_early_risk_compare/summary.json"
            ),
            "requirement": "selected_variant_id must resolve to btc_candidate_persistence_10d_075.",
        },
        "data_requirements": [
            "All canonical phase68g baseline inputs must be present and aligned.",
            "The dev-only BTC persistence summary, quality, and variant compare artifacts must exist.",
            "The BTC persistence compare contract/spec/manifest inputs must remain present for evidence lineage.",
        ],
        "authority_publish_required": True,
        "notes": (
            "Official softer fallback. It remains eligible for Production Core rebuilds, but live cutover "
            "still requires separate Raspberry Pi authority publish."
        ),
        "fallback_relationship": {
            "live_strategy": ETF_FLOW_MODEL,
            "softer_fallback": BTC_PERSISTENCE_MODEL,
            "secondary_fallback": PHASE68G_MODEL,
            "legacy_fallback": legacy_fallback,
        },
    }


def _build_etf_flow_entry(
    *,
    label: str,
    current_role: str,
    softer_fallback: str,
    secondary_fallback: str,
    legacy_fallback: str,
) -> dict[str, Any]:
    adapter = Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter()
    source_paths = _dedupe_paths(list(adapter.resolve_source_paths(root=ROOT).values()))
    return {
        "strategy_model": ETF_FLOW_MODEL,
        "label": label,
        "status": "active",
        "current_role": current_role,
        "production_adapter_or_build_route": {
            "kind": "production_core_live_adapter",
            "entrypoint": "scripts/production/strategy_adapters/phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter.py",
            "build_script": "scripts/production/build_current_strategy_snapshot.py",
            "validation_script": "scripts/production/validate_current_strategy_snapshot.py",
            "materialize_execution_exports_script": "scripts/execution/materialize_execution_app_exports.py",
        },
        "required_source_paths": source_paths,
        "expected_production_outputs": list(PRODUCTION_OUTPUT_PATHS),
        "required_evidence_window": {
            "applicable": True,
            "type": "etf_flow_feature_window",
            "source_path": "outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel/btc_etf_flow_daily_panel.csv",
            "requirement": "The ETF-flow evidence window must run contiguously from the first feature day through the current closed day.",
        },
        "data_requirements": [
            "The ETF-flow research panel and its quality sidecar must be present and current.",
            "The softer fallback BTC persistence lineage and the phase68g canonical baseline lineage must both be present.",
            "project_truth.json and export_contract.json must already point at the ETF-flow Production Core route for current official builds.",
        ],
        "authority_publish_required": True,
        "notes": (
            "Current official live strategy. Dry-run can rebuild Production Core locally, but live cutover "
            "remains incomplete until the Raspberry Pi authority publish succeeds."
        ),
        "fallback_relationship": {
            "live_strategy": ETF_FLOW_MODEL,
            "softer_fallback": softer_fallback,
            "secondary_fallback": secondary_fallback,
            "legacy_fallback": legacy_fallback,
        },
    }


def _build_phase68i_entry(
    *,
    label: str,
    current_role: str,
    export_contract: dict[str, Any],
) -> dict[str, Any]:
    app_export_contract = export_contract.get("app_export_contract")
    if not isinstance(app_export_contract, dict):
        raise ValueError("export_contract.json missing app_export_contract")
    model_sources = app_export_contract.get("model_sources")
    if not isinstance(model_sources, dict):
        raise ValueError("export_contract.json missing app_export_contract.model_sources")
    phase68i_sources = model_sources.get(PHASE68I_MODEL)
    if not isinstance(phase68i_sources, dict):
        raise ValueError("export_contract.json missing phase68i model_sources entry")
    required_source_paths = _dedupe_paths(
        [
            phase68i_sources.get("summary_path", ""),
            phase68i_sources.get("paper_path", ""),
            phase68i_sources.get("live_status_path", ""),
            "scripts/execution/materialize_execution_app_exports.py",
            "scripts/phase68h_dynamic_leverage_ladder_candidate.py",
        ]
    )
    return {
        "strategy_model": PHASE68I_MODEL,
        "label": label,
        "status": "legacy_only",
        "current_role": current_role,
        "production_adapter_or_build_route": {
            "kind": "legacy_fallback_app_export_only",
            "entrypoint": "scripts/execution/materialize_execution_app_exports.py",
            "source_script": "scripts/phase68h_dynamic_leverage_ladder_candidate.py",
            "production_core_support": False,
        },
        "required_source_paths": required_source_paths,
        "expected_production_outputs": [],
        "required_evidence_window": {
            "applicable": False,
            "type": "legacy_app_export_only",
            "requirement": "Legacy fallback only. No Production Core live adapter exists for this model.",
        },
        "data_requirements": [
            "Canonical legacy summary and paper app exports must remain available.",
            "The materializer must preserve the legacy app-export route, but this model has no active Production Core live adapter.",
            "Use only as a historical or last-resort fallback, never as the default live cutover path in v1.",
        ],
        "authority_publish_required": True,
        "notes": (
            "Legacy or historical fallback only. It is cataloged for safety visibility, but v1 does not "
            "treat it as an active Production Core promotion target."
        ),
        "fallback_relationship": {
            "live_strategy": ETF_FLOW_MODEL,
            "softer_fallback": BTC_PERSISTENCE_MODEL,
            "secondary_fallback": PHASE68G_MODEL,
            "legacy_fallback": PHASE68I_MODEL,
        },
    }


def build_strategy_catalog_payload(*, root: Path = ROOT) -> dict[str, Any]:
    del root
    project_truth = read_json_required(ROOT / "source_of_truth" / "project_truth.json")
    export_contract = read_json_required(ROOT / "source_of_truth" / "export_contract.json")
    current_roles = _current_role_map(project_truth)

    app_product_truth = project_truth.get("app_product_truth")
    leverage_truth = project_truth.get("leverage_truth")
    if not isinstance(app_product_truth, dict) or not isinstance(leverage_truth, dict):
        raise ValueError("project_truth.json missing app_product_truth or leverage_truth")

    current_official_strategy_model = str(app_product_truth.get("main_strategy_model") or "").strip()
    official_softer_fallback_model = str(leverage_truth.get("official_softer_fallback") or "").strip()
    secondary_fallback_model = str(leverage_truth.get("secondary_fallback") or "").strip()
    if not current_official_strategy_model or not official_softer_fallback_model or not secondary_fallback_model:
        raise ValueError("project_truth.json is missing one or more live strategy role fields")

    app_export_contract = export_contract.get("app_export_contract")
    if not isinstance(app_export_contract, dict):
        raise ValueError("export_contract.json missing app_export_contract")
    display_names = app_export_contract.get("display_names")
    if not isinstance(display_names, dict):
        display_names = {}

    strategies = [
        _build_phase68g_entry(
            label=_display_label(display_names, PHASE68G_MODEL, "Secondary fallback"),
            current_role=current_roles.get(PHASE68G_MODEL, "secondary_fallback"),
            softer_fallback=official_softer_fallback_model,
            legacy_fallback=PHASE68I_MODEL,
        ),
        _build_btc_persistence_entry(
            label=_display_label(display_names, BTC_PERSISTENCE_MODEL, "Softer fallback"),
            current_role=current_roles.get(BTC_PERSISTENCE_MODEL, "official_softer_fallback"),
            legacy_fallback=PHASE68I_MODEL,
        ),
        _build_etf_flow_entry(
            label=_display_label(display_names, ETF_FLOW_MODEL, "Main strategy"),
            current_role=current_roles.get(ETF_FLOW_MODEL, "official_live_main"),
            softer_fallback=official_softer_fallback_model,
            secondary_fallback=secondary_fallback_model,
            legacy_fallback=PHASE68I_MODEL,
        ),
        _build_phase68i_entry(
            label=_display_label(display_names, PHASE68I_MODEL, "Historical fallback"),
            current_role=current_roles.get(PHASE68I_MODEL, "legacy_fallback_only"),
            export_contract=export_contract,
        ),
    ]

    return {
        "artifact_type": "strategy_catalog",
        "schema_version": CATALOG_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "current_official_strategy_model": current_official_strategy_model,
        "official_softer_fallback_model": official_softer_fallback_model,
        "secondary_fallback_model": secondary_fallback_model,
        "legacy_fallback_model": PHASE68I_MODEL,
        "authority_publish_required_for_live_cutover": True,
        "strategies": strategies,
        "source_paths": {
            "project_truth": "source_of_truth/project_truth.json",
            "export_contract": "source_of_truth/export_contract.json",
        },
    }


def validate_strategy_catalog_payload(
    payload: dict[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []

    if str(payload.get("artifact_type") or "").strip() != "strategy_catalog":
        errors.append("artifact_type must be strategy_catalog")
    if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {CATALOG_SCHEMA_VERSION} (actual={payload.get('schema_version')!r})"
        )

    strategies = payload.get("strategies")
    if not isinstance(strategies, list):
        errors.append("strategies must be a list")
        strategies = []

    seen_models: list[str] = []
    for index, entry in enumerate(strategies):
        context = f"strategies[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{context} must be an object")
            continue

        strategy_model = str(entry.get("strategy_model") or "").strip()
        if not strategy_model:
            errors.append(f"{context}.strategy_model is required")
        seen_models.append(strategy_model)
        if strategy_model and strategy_model not in SUPPORTED_MODELS:
            errors.append(f"{context}.strategy_model is unsupported ({strategy_model})")

        label = str(entry.get("label") or "").strip()
        status = str(entry.get("status") or "").strip()
        current_role = str(entry.get("current_role") or "").strip()
        notes = str(entry.get("notes") or "").strip()
        if not label:
            errors.append(f"{context}.label is required")
        if not status:
            errors.append(f"{context}.status is required")
        if current_role not in ALLOWED_CURRENT_ROLES:
            errors.append(f"{context}.current_role is invalid ({current_role or 'missing'})")
        if not notes:
            errors.append(f"{context}.notes is required")

        route = entry.get("production_adapter_or_build_route")
        if not isinstance(route, dict):
            errors.append(f"{context}.production_adapter_or_build_route must be an object")
        else:
            kind = str(route.get("kind") or "").strip()
            entrypoint = str(route.get("entrypoint") or "").strip()
            if not kind:
                errors.append(f"{context}.production_adapter_or_build_route.kind is required")
            if not entrypoint:
                errors.append(f"{context}.production_adapter_or_build_route.entrypoint is required")
            elif not (root / entrypoint).exists():
                errors.append(
                    f"{context}.production_adapter_or_build_route.entrypoint is missing ({entrypoint})"
                )

        required_source_paths = entry.get("required_source_paths")
        if not isinstance(required_source_paths, list) or not required_source_paths:
            errors.append(f"{context}.required_source_paths must be a non-empty list")
        else:
            for item_index, raw_path in enumerate(required_source_paths):
                path_text = str(raw_path or "").strip()
                if not path_text:
                    errors.append(f"{context}.required_source_paths[{item_index}] is blank")
                    continue
                if not resolve_repo_path(path_text).exists():
                    errors.append(
                        f"{context}.required_source_paths[{item_index}] is missing ({path_text})"
                    )

        expected_outputs = entry.get("expected_production_outputs")
        if not isinstance(expected_outputs, list):
            errors.append(f"{context}.expected_production_outputs must be a list")
        elif current_role != "legacy_fallback_only" and not expected_outputs:
            errors.append(f"{context}.expected_production_outputs must not be empty for active adapters")

        evidence_window = entry.get("required_evidence_window")
        if not isinstance(evidence_window, dict):
            errors.append(f"{context}.required_evidence_window must be an object")
        elif "applicable" not in evidence_window:
            errors.append(f"{context}.required_evidence_window.applicable is required")

        data_requirements = entry.get("data_requirements")
        if not isinstance(data_requirements, list) or not data_requirements:
            errors.append(f"{context}.data_requirements must be a non-empty list")

        if entry.get("authority_publish_required") is not True:
            errors.append(f"{context}.authority_publish_required must be true")

        fallback_relationship = entry.get("fallback_relationship")
        if not isinstance(fallback_relationship, dict):
            errors.append(f"{context}.fallback_relationship must be an object")

    expected_models = sorted(SUPPORTED_MODELS)
    if sorted(model for model in seen_models if model) != expected_models:
        errors.append(
            "strategies must contain exactly the supported models "
            f"(expected={expected_models} actual={sorted(model for model in seen_models if model)})"
        )

    checks = {
        "artifact_type_ok": str(payload.get("artifact_type") or "").strip() == "strategy_catalog",
        "schema_version_ok": payload.get("schema_version") == CATALOG_SCHEMA_VERSION,
        "strategy_count_ok": len(strategies) == len(SUPPORTED_MODELS),
        "supported_models_present": sorted(model for model in seen_models if model) == expected_models,
        "all_required_paths_exist": not any("required_source_paths" in error for error in errors),
        "all_entries_require_authority_publish": not any(
            "authority_publish_required" in error for error in errors
        ),
    }
    return {
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "checks": checks,
    }
