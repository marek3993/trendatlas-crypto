from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.execution.current_strategy_root_contract import (
    CurrentMainStrategyContractError,
    load_current_main_strategy_root_contract,
    resolve_homepage_current_strategy_sources,
    resolve_validated_homepage_top_performance_source_contract,
    validate_homepage_main_chart_source_path,
    validate_homepage_top_card_source_path,
)


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_SNAPSHOT_PATH = ROOT / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"


def read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected top-level object in {path}")
    return payload


def main() -> None:
    current_strategy_contract = load_current_main_strategy_root_contract()
    homepage_top_card_source_contract = resolve_validated_homepage_top_performance_source_contract(
        str(current_strategy_contract["main_strategy_model"]),
        current_strategy_contract,
    )
    authority_snapshot = read_json_required(AUTHORITY_SNAPSHOT_PATH)
    product_snapshot = authority_snapshot.get("app_product_snapshot")
    if not isinstance(product_snapshot, dict):
        raise ValueError(
            "outputs/execution/authority/latest_successful_snapshot.json missing app_product_snapshot"
        )

    source_metadata = product_snapshot.get("source_metadata")
    if not isinstance(source_metadata, dict):
        raise ValueError("authority app_product_snapshot missing source_metadata")
    main_strategy_metrics_metadata = source_metadata.get("main_strategy_metrics")
    if not isinstance(main_strategy_metrics_metadata, dict):
        raise ValueError("authority app_product_snapshot missing source_metadata.main_strategy_metrics")
    chart_source_paths_metadata = source_metadata.get("chart_source_paths")
    if not isinstance(chart_source_paths_metadata, dict):
        raise ValueError("authority app_product_snapshot missing source_metadata.chart_source_paths")
    main_strategy_chart_metadata = chart_source_paths_metadata.get("main_strategy")
    if not isinstance(main_strategy_chart_metadata, dict):
        raise ValueError(
            "authority app_product_snapshot missing source_metadata.chart_source_paths.main_strategy"
        )

    current_truth_model = str(current_strategy_contract["main_strategy_model"])
    authority_snapshot_source_path = str(main_strategy_metrics_metadata.get("path") or "").strip()
    homepage_main_chart_source_path = str(
        (product_snapshot.get("chart_source_paths") or {}).get("main_strategy") or ""
    ).strip()
    authority_snapshot_chart_source_path = str(main_strategy_chart_metadata.get("path") or "").strip()
    canonical_paper_source_path = str(current_strategy_contract["canonical_paper_source_path"])
    homepage_top_card_source_path = str(homepage_top_card_source_contract["metrics_source_path"])

    print(f"truth model: {current_truth_model}")
    print(f"homepage main chart source path: {homepage_main_chart_source_path}")
    print(f"authority snapshot chart source path: {authority_snapshot_chart_source_path}")
    print(f"canonical paper source path: {canonical_paper_source_path}")
    print(f"homepage top-card source path: {homepage_top_card_source_path}")
    print(f"authority main_strategy_metrics source path: {authority_snapshot_source_path}")

    try:
        resolve_homepage_current_strategy_sources(
            product_snapshot,
            current_strategy_contract,
        )
        validate_homepage_top_card_source_path(
            homepage_top_card_source_path,
            current_strategy_contract,
            context="Homepage top-card smoke validation blocked:",
        )
        validate_homepage_top_card_source_path(
            authority_snapshot_source_path,
            current_strategy_contract,
            context="Authority main_strategy_metrics smoke validation blocked:",
        )
        validate_homepage_main_chart_source_path(
            homepage_main_chart_source_path,
            current_strategy_contract,
            context="Homepage main chart smoke validation blocked:",
        )
        validate_homepage_main_chart_source_path(
            authority_snapshot_chart_source_path,
            current_strategy_contract,
            context="Authority homepage chart metadata smoke validation blocked:",
        )
    except CurrentMainStrategyContractError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
