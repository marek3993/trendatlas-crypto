from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

PATHS_REGISTRY_PATH = ROOT / "source_of_truth" / "paths_registry.json"
OUTPUT_REGISTRY_PATH = ROOT / "canonical" / "output_registry.json"

PHASE68I_PAPER_PATH = str(ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv")
PHASE68I_SUMMARY_PATH = str(ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv")

LOG_DIR = ROOT / "outputs" / "execution" / "logs"
LOG_PATH = LOG_DIR / "register_phase68i_app_exports.log"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def ensure_file_exists(path_str: str) -> None:
    path = Path(path_str)
    if not path.exists():
        fail(f"Missing required artifact file: {path}")


def upsert_artifact(artifacts: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
    artifacts[key] = entry


def upsert_output(outputs: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    output_path = entry["output_path"]
    for idx, existing in enumerate(outputs):
        if existing.get("output_path") == output_path:
            outputs[idx] = entry
            return
    outputs.append(entry)


def main() -> None:
    log("[START] register_phase68i_app_exports")

    ensure_file_exists(PHASE68I_PAPER_PATH)
    ensure_file_exists(PHASE68I_SUMMARY_PATH)

    paths_registry = read_json(PATHS_REGISTRY_PATH)
    output_registry = read_json(OUTPUT_REGISTRY_PATH)

    artifacts = paths_registry.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        fail("paths_registry.json missing top-level 'artifacts' object")

    upsert_artifact(
        artifacts,
        "phase68i_dynamic_ladder_candidate_paper",
        {
            "canonical": PHASE68I_PAPER_PATH,
            "legacy_aliases": [],
            "owner": "DATA",
            "artifact_type": "paper",
            "truth_domain": "product",
            "read_scope": ["app", "product", "validation"],
            "write_mode": "future_write_through_candidate",
        },
    )

    upsert_artifact(
        artifacts,
        "phase68i_dynamic_ladder_candidate_summary",
        {
            "canonical": PHASE68I_SUMMARY_PATH,
            "legacy_aliases": [],
            "owner": "DATA",
            "artifact_type": "summary",
            "truth_domain": "product",
            "read_scope": ["app", "product", "validation"],
            "write_mode": "future_write_through_candidate",
            "field_contract": {
                "required_fields": [
                    "model",
                    "cagr_pct",
                    "max_drawdown_pct",
                    "since2023_cagr_pct",
                    "since2025_cagr_pct",
                    "sharpe",
                    "sortino",
                    "switch_count",
                    "cash_days_pct",
                    "btc_days_pct",
                ],
                "app_must_not_infer": True,
            },
        },
    )

    outputs = output_registry.setdefault("outputs", [])
    if not isinstance(outputs, list):
        fail("canonical/output_registry.json missing top-level 'outputs' list")

    upsert_output(
        outputs,
        {
            "output_path": "outputs/execution/app_exports/phase68i_dynamic_ladder_candidate_paper.csv",
            "generated_by": [
                "scripts/phase68h_dynamic_leverage_ladder_candidate.py"
            ],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "app_curve_export",
            "decision_relevance": "support_only",
            "official_truth": False,
            "notes": "Approved deployment candidate curve for APP rendering. Canonical app export artifact."
        },
    )

    upsert_output(
        outputs,
        {
            "output_path": "outputs/execution/app_exports/phase68i_dynamic_ladder_candidate_summary.csv",
            "generated_by": [
                "scripts/execution/materialize_execution_app_exports.py"
            ],
            "layer": "execution_data",
            "status": "active",
            "output_kind": "app_summary_export",
            "decision_relevance": "support_only",
            "official_truth": False,
            "notes": "Approved deployment candidate product metrics for APP summary_path. APP must not infer these metrics."
        },
    )

    write_json(PATHS_REGISTRY_PATH, paths_registry)
    write_json(OUTPUT_REGISTRY_PATH, output_registry)

    log(f"[SAVED] {PATHS_REGISTRY_PATH}")
    log(f"[SAVED] {OUTPUT_REGISTRY_PATH}")
    log("[END] register_phase68i_app_exports success")


if __name__ == "__main__":
    main()