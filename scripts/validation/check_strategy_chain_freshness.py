from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from freshness_lineage import parse_iso_date, read_last_date, read_single_csv_value, write_json
from scripts.execution.runtime_path_resolution import resolve_registry_artifact_path, resolve_runtime_path


REPORT_PATH = ROOT / "outputs" / "validation" / "reports" / "strategy_chain_freshness_report.json"
BTC_RAW_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
PHASE62_MANIFEST_PATH = ROOT / "outputs" / "phase62_btc_overlay" / "phase62_manifest.json"
PHASE63_MANIFEST_PATH = ROOT / "outputs" / "phase63_btc_participation_overlay" / "phase63_manifest.json"
PHASE66G_MANIFEST_PATH = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_manifest.json"
PHASE67J_MANIFEST_PATH = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_manifest.json"
PATHS_REGISTRY_PATH = ROOT / "source_of_truth" / "paths_registry.json"
DEFAULT_PHASE60_PAPER = (
    ROOT
    / "outputs"
    / "phase60_selective_restore_robustness"
    / "phase60_restore_trx_sol_base_paper.csv"
)
PHASE68I_CANONICAL_APP_EXPORT_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_optional_manifest(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def manifest_lineage_value(manifest: dict[str, Any], field: str) -> str | None:
    lineage = manifest.get("freshness_lineage")
    if not isinstance(lineage, dict):
        return None
    value = lineage.get(field)
    text = str(value).strip() if value is not None else ""
    return text or None


def resolve_runtime_candidate(
    candidate_path: Any,
    *,
    context: str,
    diagnostics: list[dict[str, Any]],
) -> Path | None:
    if not candidate_path:
        return None
    resolved_path, diagnostic = resolve_runtime_path(
        Path(str(candidate_path)),
        root=ROOT,
        context=context,
    )
    diagnostics.append(diagnostic)
    return resolved_path


def read_first_existing_last_date(
    *candidate_paths: Any,
    context: str,
    diagnostics: list[dict[str, Any]],
) -> str | None:
    for candidate_path in candidate_paths:
        resolved_path = resolve_runtime_candidate(
            candidate_path,
            context=context,
            diagnostics=diagnostics,
        )
        if resolved_path is None:
            continue
        last_date = read_last_date(resolved_path)
        if last_date:
            return last_date
    return None


def find_saved_model_output(manifest: dict[str, Any], phase_prefix: str, output_dir: Path) -> Path | None:
    top_models = manifest.get("top_saved_models")
    if not isinstance(top_models, list) or not top_models:
        return None

    preferred_model = next(
        (str(model) for model in top_models if str(model).lower().startswith(phase_prefix)),
        None,
    )
    if preferred_model is None:
        preferred_model = str(top_models[0])

    output_path = output_dir / f"{preferred_model}_paper.csv"
    return output_path if output_path.exists() else None


def read_phase60_last_date(
    phase62_manifest: dict[str, Any],
    phase63_manifest: dict[str, Any],
    *,
    diagnostics: list[dict[str, Any]],
) -> str | None:
    artifact_last_date = read_first_existing_last_date(
        phase62_manifest.get("base_file"),
        phase63_manifest.get("base_file"),
        DEFAULT_PHASE60_PAPER,
        context="freshness:phase60.base_file",
        diagnostics=diagnostics,
    )
    if artifact_last_date:
        return artifact_last_date

    for candidate in (
        manifest_lineage_value(phase62_manifest, "source_last_date"),
        manifest_lineage_value(phase63_manifest, "source_last_date"),
    ):
        if candidate:
            return candidate

    return None


def read_phase62_last_date(phase62_manifest: dict[str, Any]) -> str | None:
    output_path = find_saved_model_output(
        manifest=phase62_manifest,
        phase_prefix="phase62",
        output_dir=ROOT / "outputs" / "phase62_btc_overlay",
    )
    artifact_last_date = read_last_date(output_path) if output_path is not None else None
    if artifact_last_date:
        return artifact_last_date

    return manifest_lineage_value(phase62_manifest, "output_last_date")


def read_phase63_last_date(phase63_manifest: dict[str, Any]) -> str | None:
    output_path = find_saved_model_output(
        manifest=phase63_manifest,
        phase_prefix="phase63",
        output_dir=ROOT / "outputs" / "phase63_btc_participation_overlay",
    )
    artifact_last_date = read_last_date(output_path) if output_path is not None else None
    if artifact_last_date:
        return artifact_last_date

    return manifest_lineage_value(phase63_manifest, "output_last_date")


def read_phase66g_last_date(
    phase66g_manifest: dict[str, Any],
    *,
    diagnostics: list[dict[str, Any]],
) -> str | None:
    output_path = phase66g_manifest.get("production_paper_saved")
    resolved_output_path = resolve_runtime_candidate(
        output_path,
        context="freshness:phase66g.production_paper_saved",
        diagnostics=diagnostics,
    )
    artifact_last_date = read_last_date(resolved_output_path) if resolved_output_path else None
    if artifact_last_date:
        return artifact_last_date

    return manifest_lineage_value(phase66g_manifest, "output_last_date")


def read_phase67j_last_date(phase67j_manifest: dict[str, Any]) -> str | None:
    best_model = str(phase67j_manifest.get("best_model") or "").strip()
    if not best_model:
        return manifest_lineage_value(phase67j_manifest, "output_last_date")
    output_path = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / f"{best_model}_paper.csv"
    artifact_last_date = read_last_date(output_path)
    if artifact_last_date:
        return artifact_last_date

    return manifest_lineage_value(phase67j_manifest, "output_last_date")


def determine_first_break(stage_dates: list[tuple[str, str | None]]) -> tuple[str | None, str | None]:
    previous_date = None

    for stage_name, stage_date_text in stage_dates:
        current_date = parse_iso_date(stage_date_text)

        if current_date is None:
            first_missing = previous_date.isoformat() if previous_date is not None else None
            return stage_name, first_missing

        if previous_date is not None and current_date < previous_date:
            return stage_name, (current_date + timedelta(days=1)).isoformat()

        if previous_date is None or current_date >= previous_date:
            previous_date = current_date

    return None, None


def build_report() -> dict[str, Any]:
    phase62_manifest = read_optional_manifest(PHASE62_MANIFEST_PATH)
    phase63_manifest = read_optional_manifest(PHASE63_MANIFEST_PATH)
    phase66g_manifest = read_optional_manifest(PHASE66G_MANIFEST_PATH)
    phase67j_manifest = read_optional_manifest(PHASE67J_MANIFEST_PATH)
    paths_registry = read_json(PATHS_REGISTRY_PATH)
    artifacts = paths_registry.get("artifacts", {})
    path_resolution_diagnostics: list[dict[str, Any]] = []

    if PHASE68I_CANONICAL_APP_EXPORT_PATH.exists():
        canonical_app_export_path = PHASE68I_CANONICAL_APP_EXPORT_PATH
        path_resolution_diagnostics.append(
            {
                "context": "freshness:canonical_app_export",
                "original_path": str(PHASE68I_CANONICAL_APP_EXPORT_PATH),
                "resolved_path": str(PHASE68I_CANONICAL_APP_EXPORT_PATH),
                "reason": "preferred_canonical_app_export_exists",
                "exists": True,
            }
        )
    else:
        canonical_app_export_path, canonical_app_export_diag = resolve_registry_artifact_path(
            "phase67j_winner_paper",
            artifacts["phase67j_winner_paper"],
            root=ROOT,
            context="freshness:canonical_app_export",
        )
        path_resolution_diagnostics.append(canonical_app_export_diag)

    canonical_live_status_path, canonical_live_status_diag = resolve_registry_artifact_path(
        "phase67j_live_status",
        artifacts["phase67j_live_status"],
        root=ROOT,
        context="freshness:canonical_live_status",
    )
    path_resolution_diagnostics.append(canonical_live_status_diag)

    raw_btc_last_date = read_last_date(BTC_RAW_PATH)
    phase60_last_date = read_phase60_last_date(
        phase62_manifest,
        phase63_manifest,
        diagnostics=path_resolution_diagnostics,
    )
    phase62_last_date = read_phase62_last_date(phase62_manifest)
    phase63_last_date = read_phase63_last_date(phase63_manifest)
    phase66g_last_date = read_phase66g_last_date(
        phase66g_manifest,
        diagnostics=path_resolution_diagnostics,
    )
    phase67j_last_date = read_phase67j_last_date(phase67j_manifest)
    canonical_app_export_last_date = read_last_date(canonical_app_export_path)
    canonical_live_status_latest_available_date = read_single_csv_value(
        canonical_live_status_path,
        "latest_available_date",
    )

    first_broken_stage, first_missing_date = determine_first_break(
        [
            ("raw_btc", raw_btc_last_date),
            ("phase60", phase60_last_date),
            ("phase62", phase62_last_date),
            ("phase63", phase63_last_date),
            ("phase66g", phase66g_last_date),
            ("phase67j", phase67j_last_date),
            ("canonical_app_export", canonical_app_export_last_date),
            ("canonical_live_status", canonical_live_status_latest_available_date),
        ]
    )

    return {
        "raw_btc_last_date": raw_btc_last_date,
        "phase60_last_date": phase60_last_date,
        "phase62_last_date": phase62_last_date,
        "phase63_last_date": phase63_last_date,
        "phase66g_last_date": phase66g_last_date,
        "phase67j_last_date": phase67j_last_date,
        "canonical_app_export_last_date": canonical_app_export_last_date,
        "canonical_live_status_latest_available_date": canonical_live_status_latest_available_date,
        "first_broken_stage": first_broken_stage,
        "first_missing_date": first_missing_date,
        "path_resolution_diagnostics": path_resolution_diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    report = build_report()
    write_json(args.report_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if report["first_broken_stage"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
