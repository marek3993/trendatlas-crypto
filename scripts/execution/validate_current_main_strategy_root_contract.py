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

    current_truth_model = str(current_strategy_contract["main_strategy_model"])
    canonical_metrics_source_path = str(current_strategy_contract["canonical_metrics_source_path"])
    canonical_paper_source_path = str(current_strategy_contract["canonical_paper_source_path"])
    authority_snapshot_source_path = str(main_strategy_metrics_metadata.get("path") or "").strip()
    homepage_metric_source_path = canonical_metrics_source_path

    print(f"current truth model: {current_truth_model}")
    print(f"canonical metrics source path: {canonical_metrics_source_path}")
    print(f"canonical paper path: {canonical_paper_source_path}")
    print(f"authority snapshot source path: {authority_snapshot_source_path}")
    print(f"homepage metric source path: {homepage_metric_source_path}")

    try:
        resolve_homepage_current_strategy_sources(
            product_snapshot,
            current_strategy_contract,
        )
    except CurrentMainStrategyContractError as exc:
        raise SystemExit(str(exc)) from exc

    if authority_snapshot_source_path != canonical_metrics_source_path:
        raise SystemExit(
            "Authority snapshot source path diverged from canonical current main strategy metrics source path"
        )


if __name__ == "__main__":
    main()
