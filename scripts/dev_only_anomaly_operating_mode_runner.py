from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from research_os_dev_only_anomaly_operating_common import (
    FAMILY_IDS,
    FAMILY_PROBE_SCRIPTS,
    INTERACTIONS_CSV_PATH,
    INTERACTIONS_HISTORY_JSON_PATH,
    INTERACTIONS_JSON_PATH,
    INTERACTION_STABILITY_JSON_PATH,
    OPERATING_MANIFEST_JSON_PATH,
    OPERATING_HISTORY_MANIFEST_JSON_PATH,
    RANKING_CSV_PATH,
    RANKING_HISTORY_JSON_PATH,
    RANKING_JSON_PATH,
    RANKING_STABILITY_JSON_PATH,
    ROOT,
)
from research_os_dev_only_feature_output_common import feature_file_paths, save_json, with_dev_flags


SUMMARY_SCRIPT_PATH = ROOT / "scripts" / "dev_only_feature_family_summary.py"
PROFILE_SCRIPT_PATH = ROOT / "scripts" / "dev_only_feature_profile_runner.py"
INTERACTIONS_SCRIPT_PATH = ROOT / "scripts" / "dev_only_anomaly_cross_family_interactions.py"
RANKING_SCRIPT_PATH = ROOT / "scripts" / "dev_only_anomaly_ranking_heuristics.py"
HISTORY_SCRIPT_PATH = ROOT / "scripts" / "dev_only_anomaly_history_manager.py"


def run_step(command: List[str]) -> None:
    subprocess.run(command, check=True, cwd=str(ROOT))


def build_cycle_identity() -> tuple[str, str]:
    current_dt = datetime.now(timezone.utc)
    cycle_id = current_dt.strftime("%Y%m%dT%H%M%S%fZ")
    generated_at_utc = current_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return cycle_id, generated_at_utc


def build_output_refs() -> Dict[str, Any]:
    family_outputs = {}
    for family_id in FAMILY_IDS:
        paths = feature_file_paths(family_id)
        family_outputs[family_id] = {
            "features_csv": str(paths["features_csv"]),
            "manifest_json": str(paths["manifest_json"]),
            "quality_json": str(paths["quality_json"]),
            "profile_json": str(paths["profile_json"]),
        }
    return {
        "family_outputs": family_outputs,
        "family_summary_json": str(ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_features" / "anomaly_feature_family_summary.json"),
        "family_summary_csv": str(ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_features" / "anomaly_feature_family_summary.csv"),
        "cross_family_interactions_json": str(INTERACTIONS_JSON_PATH),
        "cross_family_interactions_csv": str(INTERACTIONS_CSV_PATH),
        "cross_family_interactions_history_json": str(INTERACTIONS_HISTORY_JSON_PATH),
        "cross_family_interaction_stability_json": str(INTERACTION_STABILITY_JSON_PATH),
        "ranking_heuristics_json": str(RANKING_JSON_PATH),
        "ranking_heuristics_csv": str(RANKING_CSV_PATH),
        "ranking_history_json": str(RANKING_HISTORY_JSON_PATH),
        "ranking_stability_json": str(RANKING_STABILITY_JSON_PATH),
        "operating_history_manifest_json": str(OPERATING_HISTORY_MANIFEST_JSON_PATH),
    }


def main() -> None:
    cycle_id, cycle_generated_at_utc = build_cycle_identity()
    probe_steps = []
    for family_id in FAMILY_IDS:
        script_path = FAMILY_PROBE_SCRIPTS[family_id]
        run_step([sys.executable, str(script_path)])
        probe_steps.append({"family_id": family_id, "script_path": str(script_path), "status": "rerun_complete"})

    profile_steps = []
    for family_id in FAMILY_IDS:
        run_step([sys.executable, str(PROFILE_SCRIPT_PATH), "--family", family_id])
        profile_steps.append({"family_id": family_id, "script_path": str(PROFILE_SCRIPT_PATH), "status": "rerun_complete"})

    run_step([sys.executable, str(SUMMARY_SCRIPT_PATH)])
    run_step([sys.executable, str(INTERACTIONS_SCRIPT_PATH)])
    run_step([sys.executable, str(RANKING_SCRIPT_PATH)])
    run_step([sys.executable, str(HISTORY_SCRIPT_PATH), "--cycle-id", cycle_id, "--cycle-generated-at-utc", cycle_generated_at_utc])

    payload = with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_operating_mode_cycle_manifest",
            "artifact_id": "anomaly_operating_mode_cycle_manifest",
            "generated_at_utc": cycle_generated_at_utc,
            "cycle_id": cycle_id,
            "cycle_status": "completed",
            "probe_steps": probe_steps,
            "profile_steps": profile_steps,
            "summary_step": {"script_path": str(SUMMARY_SCRIPT_PATH), "status": "rerun_complete"},
            "cross_family_interaction_step": {
                "script_path": str(INTERACTIONS_SCRIPT_PATH),
                "status": "rerun_complete",
            },
            "ranking_heuristics_step": {
                "script_path": str(RANKING_SCRIPT_PATH),
                "status": "rerun_complete",
            },
            "history_step": {
                "script_path": str(HISTORY_SCRIPT_PATH),
                "status": "rerun_complete",
            },
            "output_refs": build_output_refs(),
        }
    )
    save_json(OPERATING_MANIFEST_JSON_PATH, payload)

    print("dev-only anomaly operating mode cycle completed")
    print(OPERATING_MANIFEST_JSON_PATH)


if __name__ == "__main__":
    main()
