from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from dev_only_feature_profile_runner import FAMILY_CONFIG
from research_os_dev_only_feature_output_common import OUTPUT_ROOT, feature_file_paths
from research_os_dev_only_feature_profile_common import compute_anomaly_scores, load_feature_frame


ROOT = Path(__file__).resolve().parents[1]
FAMILY_IDS = list(FAMILY_CONFIG.keys())
FAMILY_PROBE_SCRIPTS = {
    "pre_move_structure_quality_stack": ROOT / "scripts" / "dev_only_feature_probe_pre_move_structure.py",
    "participation_breadth_confirmation_stack": ROOT / "scripts" / "dev_only_feature_probe_participation_breadth.py",
    "cross_asset_decoupling_stack": ROOT / "scripts" / "dev_only_feature_probe_cross_asset_decoupling.py",
    "liquidity_stress_anomaly_stack": ROOT / "scripts" / "dev_only_feature_probe_liquidity_stress.py",
    "event_context_flags_stack": ROOT / "scripts" / "dev_only_feature_probe_event_context_flags.py",
}
FAMILY_SUMMARY_JSON_PATH = OUTPUT_ROOT / "anomaly_feature_family_summary.json"
FAMILY_SUMMARY_CSV_PATH = OUTPUT_ROOT / "anomaly_feature_family_summary.csv"
INTERACTIONS_JSON_PATH = OUTPUT_ROOT / "anomaly_cross_family_interactions.json"
INTERACTIONS_CSV_PATH = OUTPUT_ROOT / "anomaly_cross_family_interactions.csv"
RANKING_JSON_PATH = OUTPUT_ROOT / "anomaly_ranking_heuristics.json"
RANKING_CSV_PATH = OUTPUT_ROOT / "anomaly_ranking_heuristics.csv"
OPERATING_MANIFEST_JSON_PATH = OUTPUT_ROOT / "anomaly_operating_mode_cycle_manifest.json"
HISTORY_ROOT = OUTPUT_ROOT / "history"
INTERACTIONS_HISTORY_JSON_PATH = OUTPUT_ROOT / "anomaly_cross_family_interactions_history.json"
INTERACTION_STABILITY_JSON_PATH = OUTPUT_ROOT / "anomaly_cross_family_interaction_stability.json"
RANKING_HISTORY_JSON_PATH = OUTPUT_ROOT / "anomaly_ranking_history.json"
RANKING_STABILITY_JSON_PATH = OUTPUT_ROOT / "anomaly_ranking_stability.json"
OPERATING_HISTORY_MANIFEST_JSON_PATH = OUTPUT_ROOT / "anomaly_operating_history_manifest.json"
INTERESTING_QUANTILE = 0.90


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile_payload(family_id: str) -> Dict[str, Any]:
    paths = feature_file_paths(family_id)
    return load_json(paths["profile_json"])


def load_quality_payload(family_id: str) -> Dict[str, Any]:
    paths = feature_file_paths(family_id)
    return load_json(paths["quality_json"])


def normalize_family_frame(family_id: str) -> pd.DataFrame:
    config = FAMILY_CONFIG[family_id]
    coverage_column = config["coverage_column"]
    numeric_columns = config["numeric_columns"]
    paths = feature_file_paths(family_id)
    frame = load_feature_frame(paths["features_csv"]).copy()
    frame["entity"] = frame[coverage_column].fillna("").astype(str).str.strip()
    frame["family_id"] = family_id
    frame["family_anomaly_score"] = compute_anomaly_scores(frame, numeric_columns).fillna(0.0)
    threshold = float(frame["family_anomaly_score"].quantile(INTERESTING_QUANTILE)) if len(frame) else 0.0
    if math.isnan(threshold):
        threshold = 0.0
    frame = frame.sort_values(["family_anomaly_score", "date", "entity"], ascending=[False, True, True], kind="mergesort")
    frame["family_rank"] = range(1, len(frame) + 1)
    frame["interesting_threshold"] = threshold
    frame["interesting_flag"] = (frame["family_anomaly_score"] >= threshold) & (frame["family_anomaly_score"] > 0.0)
    return frame[
        [
            "date",
            "entity",
            "family_id",
            "family_anomaly_score",
            "interesting_threshold",
            "interesting_flag",
            "family_rank",
        ]
    ].copy()


def load_all_family_frames() -> pd.DataFrame:
    frames = [normalize_family_frame(family_id) for family_id in FAMILY_IDS]
    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "entity",
                "family_id",
                "family_anomaly_score",
                "interesting_threshold",
                "interesting_flag",
                "family_rank",
            ]
        )
    merged = pd.concat(frames, ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    return merged


def build_guardrail_lookup() -> Dict[str, List[str]]:
    lookup: Dict[str, List[str]] = {}
    for family_id in FAMILY_IDS:
        profile = load_profile_payload(family_id)
        guardrails = profile.get("profile_guardrails", {})
        triggered = sorted(
            name
            for name, payload in guardrails.items()
            if isinstance(payload, dict) and str(payload.get("status", "")).strip().lower() == "guardrail_triggered"
        )
        lookup[family_id] = triggered
    return lookup


def build_interesting_rows_only() -> pd.DataFrame:
    frame = load_all_family_frames()
    return frame[frame["interesting_flag"]].copy()


def build_cluster_note(active_families: List[str]) -> str:
    family_set = set(active_families)
    if len(family_set) <= 1:
        return "single-family anomaly concentration"
    if len(family_set) >= 4:
        return "broad multi-family anomaly interaction"
    if {
        "participation_breadth_confirmation_stack",
        "cross_asset_decoupling_stack",
    }.issubset(family_set):
        return "breadth and decoupling moved together"
    if {
        "liquidity_stress_anomaly_stack",
        "event_context_flags_stack",
    }.issubset(family_set):
        return "liquidity stress aligned with context flags"
    if {
        "pre_move_structure_quality_stack",
        "cross_asset_decoupling_stack",
    }.issubset(family_set):
        return "pre-move shape aligned with decoupling behavior"
    return "compact multi-family anomaly cluster"
