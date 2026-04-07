from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
INTENTS_DIR = OUTPUTS_DIR / "intents"
LOGS_DIR = OUTPUTS_DIR / "logs"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"
EXPORT_CONTRACT_PATH = SOURCE_OF_TRUTH_DIR / "export_contract.json"

INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
QUALITY_PATH = INTENTS_DIR / "latest_execution_intent_quality.json"
MANIFEST_PATH = INTENTS_DIR / "latest_execution_intent_manifest.json"
LOG_PATH = LOGS_DIR / "build_execution_intent_from_strategy_exports.log"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def log(msg: str) -> None:
    print(msg)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
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


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        fail(f"Missing required CSV: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = list(reader)
            return header, rows
    except Exception as e:
        fail(f"Failed reading CSV {path}: {e}")
    raise RuntimeError("unreachable")


def resolve_repo_path(raw_path: str | Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        return ROOT / candidate
    if candidate.exists():
        return candidate

    root_name = ROOT.name.lower()
    lowered_parts = [part.lower() for part in candidate.parts]
    if root_name in lowered_parts:
        root_index = lowered_parts.index(root_name)
        suffix_parts = candidate.parts[root_index + 1 :]
        if suffix_parts:
            return ROOT.joinpath(*suffix_parts)
    return candidate


def normalize_key(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def find_column(header: list[str], candidates: list[str]) -> str | None:
    normalized_map = {normalize_key(col): col for col in header}
    for candidate in candidates:
        found = normalized_map.get(normalize_key(candidate))
        if found:
            return found
    return None


def first_nonempty(row: dict[str, str], columns: list[str]) -> str | None:
    for col in columns:
        value = str(row.get(col, "")).strip()
        if value:
            return value
    return None


def load_registered_path(artifacts: dict[str, Any], artifact_key: str) -> Path:
    entry = artifacts.get(artifact_key)
    if not isinstance(entry, dict):
        fail(f"paths_registry.json missing artifact entry: {artifact_key}")
    canonical_raw = entry.get("canonical")
    if not isinstance(canonical_raw, str) or not canonical_raw.strip():
        fail(f"Artifact {artifact_key} missing canonical path")
    return resolve_repo_path(canonical_raw)


def load_app_export_contract() -> dict[str, Any]:
    payload = read_json(EXPORT_CONTRACT_PATH)
    contract = payload.get("app_export_contract") if isinstance(payload, dict) else None
    if not isinstance(contract, dict):
        fail("export_contract.json missing app_export_contract object")
    return contract


def load_model_source_path(
    contract: dict[str, Any],
    *,
    model_key: str,
    field_name: str,
    fallback_path: Path,
) -> Path:
    model_sources = contract.get("model_sources")
    if not isinstance(model_sources, dict):
        return fallback_path

    source_cfg = model_sources.get(model_key)
    if not isinstance(source_cfg, dict):
        return fallback_path

    raw_path = source_cfg.get(field_name)
    if not isinstance(raw_path, str) or not raw_path.strip():
        return fallback_path
    return resolve_repo_path(raw_path)


def derive_target_asset(
    live_last: dict[str, str],
    paper_last: dict[str, str],
    status_asset_col: str | None,
    status_execution_state_col: str | None,
    paper_asset_col: str | None,
    paper_position_col: str | None,
) -> str:
    live_asset = first_nonempty(live_last, [status_asset_col] if status_asset_col else [])
    live_state = first_nonempty(
        live_last,
        [status_execution_state_col] if status_execution_state_col else []
    )
    paper_asset = first_nonempty(paper_last, [paper_asset_col] if paper_asset_col else [])
    paper_position = first_nonempty(
        paper_last,
        [paper_position_col] if paper_position_col else []
    )

    if live_asset:
        return live_asset
    if live_state:
        return live_state
    if paper_asset:
        return paper_asset
    if paper_position:
        return paper_position

    fail("Could not determine target asset/state from current strategy exports.")
    raise RuntimeError("unreachable")


def main() -> None:
    INTENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] build_execution_intent_from_strategy_exports")

    registry = read_json(PATHS_REGISTRY_PATH)
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, dict):
        fail("paths_registry.json missing top-level 'artifacts' object")

    contract = load_app_export_contract()
    strategy_model = str(
        contract.get("main_model_key") or contract.get("main_strategy_model") or "phase67j_no_neo_main"
    ).strip() or "phase67j_no_neo_main"
    reference_model = str(
        contract.get("reference_model_key") or contract.get("reference_strategy_model") or "phase66g_production_soft_filters"
    ).strip() or "phase66g_production_soft_filters"

    main_paper_path = load_model_source_path(
        contract,
        model_key=strategy_model,
        field_name="paper_path",
        fallback_path=load_registered_path(artifacts, "phase67j_winner_paper"),
    )
    main_live_status_path = load_model_source_path(
        contract,
        model_key=strategy_model,
        field_name="live_status_path",
        fallback_path=load_registered_path(artifacts, "phase67j_live_status"),
    )
    reference_paper_path = load_model_source_path(
        contract,
        model_key=reference_model,
        field_name="paper_path",
        fallback_path=load_registered_path(artifacts, "phase66g_core_paper"),
    )
    app_freshness_report_path = load_registered_path(artifacts, "app_freshness_report")

    paper_header, paper_rows = read_csv_rows(main_paper_path)
    if not paper_rows:
        fail(f"No rows found in {main_paper_path}")

    live_header, live_rows = read_csv_rows(main_live_status_path)
    if not live_rows:
        fail(f"No rows found in {main_live_status_path}")

    reference_header, reference_rows = read_csv_rows(reference_paper_path)
    if not reference_rows:
        fail(f"No rows found in {reference_paper_path}")

    freshness_report = read_json(app_freshness_report_path)

    paper_last = paper_rows[-1]
    live_last = live_rows[-1]
    reference_last = reference_rows[-1]

    paper_date_col = find_column(
        paper_header,
        ["date", "timestamp", "day", "trade_date", "bar_date"],
    )
    paper_asset_col = find_column(
        paper_header,
        [
            "selected_asset",
            "held_asset",
            "asset",
            "symbol",
            "ticker",
            "chosen_asset",
            "weekly_authorized_asset",
        ],
    )
    paper_regime_col = find_column(
        paper_header,
        ["regime", "state", "selected_regime", "market_regime", "executed_regime"],
    )
    paper_position_col = find_column(
        paper_header,
        ["position", "held_position", "executed_position", "state_position"],
    )

    status_date_col = find_column(
        live_header,
        ["date", "timestamp", "day", "trade_date", "bar_date", "latest_available_date"],
    )
    status_asset_col = find_column(
        live_header,
        [
            "selected_asset",
            "held_asset",
            "asset",
            "symbol",
            "ticker",
            "held_asset_public",
            "current_asset",
        ],
    )
    status_regime_col = find_column(
        live_header,
        ["regime", "state", "selected_regime", "market_regime", "held_state_label"],
    )
    status_execution_state_col = find_column(
        live_header,
        ["execution_state", "executed_position", "position", "held_position"],
    )

    reference_asset_col = find_column(
        reference_header,
        [
            "selected_asset",
            "held_asset",
            "asset",
            "symbol",
            "ticker",
            "chosen_asset",
            "weekly_authorized_asset",
        ],
    )
    reference_position_col = find_column(
        reference_header,
        ["position", "held_position", "executed_position", "state_position"],
    )

    as_of_source = (
        first_nonempty(live_last, [status_date_col] if status_date_col else [])
        or first_nonempty(paper_last, [paper_date_col] if paper_date_col else [])
        or utc_now_iso()
    )

    target_asset = derive_target_asset(
        live_last=live_last,
        paper_last=paper_last,
        status_asset_col=status_asset_col,
        status_execution_state_col=status_execution_state_col,
        paper_asset_col=paper_asset_col,
        paper_position_col=paper_position_col,
    )

    target_regime = (
        first_nonempty(live_last, [status_regime_col] if status_regime_col else [])
        or first_nonempty(paper_last, [paper_regime_col] if paper_regime_col else [])
        or first_nonempty(live_last, [status_execution_state_col] if status_execution_state_col else [])
        or first_nonempty(paper_last, [paper_position_col] if paper_position_col else [])
    )

    reference_asset = (
        first_nonempty(reference_last, [reference_asset_col] if reference_asset_col else [])
        or first_nonempty(reference_last, [reference_position_col] if reference_position_col else [])
    )

    freshness_ok = bool(freshness_report.get("freshness_ok", True))
    signal_id = f"{strategy_model}::{str(as_of_source).strip()}::{target_asset}"

    intent = {
        "intent_type": "normalized_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "as_of_source": as_of_source,
        "execution_mode": "read_only_intent_only",
        "trading_enabled": False,
        "kill_switch_required": True,
        "strategy_model": strategy_model,
        "reference_model": reference_model,
        "benchmark": "BTC",
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_side": "long_only_hold_selected_asset_or_cash",
        "target_regime": target_regime,
        "size_mode": "not_computed_yet",
        "target_size_pct": None,
        "target_notional_usd": None,
        "reference_asset": reference_asset,
        "staleness_ok": freshness_ok,
        "stale_signal": not freshness_ok,
        "guardrail_flags": {
            "contract_validated": True,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False
        },
        "source_paths": {
            "strategy_paper": str(main_paper_path.resolve()),
            "strategy_live_status": str(main_live_status_path.resolve()),
            "reference_paper": str(reference_paper_path.resolve()),
            "app_freshness_report": str(app_freshness_report_path.resolve())
        },
        "resolved_columns": {
            "paper_date_col": paper_date_col,
            "paper_asset_col": paper_asset_col,
            "paper_regime_col": paper_regime_col,
            "paper_position_col": paper_position_col,
            "status_date_col": status_date_col,
            "status_asset_col": status_asset_col,
            "status_regime_col": status_regime_col,
            "status_execution_state_col": status_execution_state_col,
            "reference_asset_col": reference_asset_col,
            "reference_position_col": reference_position_col
        },
        "source_samples": {
            "strategy_last_paper_row": paper_last,
            "strategy_last_live_status_row": live_last,
            "reference_last_paper_row": reference_last
        },
        "notes": [
            "Deterministic intent from official execution app exports.",
            "Uses the current strategy contract from source_of_truth/export_contract.json.",
            "Supports current canonical export schema with chosen_asset / held_asset_public / execution_state.",
            "No order sizing logic yet.",
            "No live order execution allowed."
        ]
    }

    quality = {
        "intent_ok": True,
        "strategy_model": intent["strategy_model"],
        "signal_id_present": bool(intent["signal_id"]),
        "target_asset_present": bool(intent["target_asset"]),
        "target_regime_present": bool(intent["target_regime"]),
        "staleness_ok": bool(intent["staleness_ok"]),
        "trading_enabled": bool(intent["trading_enabled"]),
        "kill_switch_required": bool(intent["kill_switch_required"]),
        "leverage_live_truth_allowed": False
    }

    manifest = {
        "artifact_name": "latest_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(PATHS_REGISTRY_PATH.resolve()),
            str(EXPORT_CONTRACT_PATH.resolve()),
            str(main_paper_path.resolve()),
            str(main_live_status_path.resolve()),
            str(reference_paper_path.resolve()),
            str(app_freshness_report_path.resolve())
        ],
        "output_paths": [
            str(INTENT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve())
        ],
        "status": "success"
    }

    INTENT_PATH.write_text(json.dumps(intent, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {INTENT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] build_execution_intent_from_strategy_exports success target_asset={target_asset}")


if __name__ == "__main__":
    main()
