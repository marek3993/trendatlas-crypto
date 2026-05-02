from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.execution.runtime_path_resolution import (
    format_path_resolution_message,
    resolve_registry_artifact_path,
    resolve_runtime_path,
)
from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    validate_authoritative_dependency_closure,
)


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
AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH = (
    ROOT / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
)
AUTHORITY_LATEST_ATTEMPT_STATUS_PATH = (
    ROOT / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
)
APP_FRESHNESS_REPORT_PATH = ROOT / "outputs" / "execution" / "freshness" / "app_freshness_report.json"


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


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{context} must be an object")
    return value
    raise RuntimeError("unreachable")


def normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        fail(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        fail(f"{context} is not an ISO day: {value}")
    return text
    raise RuntimeError("unreachable")


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


def load_registered_path(
    artifacts: dict[str, Any],
    artifact_key: str,
    *,
    diagnostics: list[dict[str, Any]],
) -> Path:
    entry = artifacts.get(artifact_key)
    if not isinstance(entry, dict):
        fail(f"paths_registry.json missing artifact entry: {artifact_key}")
    canonical_raw = entry.get("canonical")
    if not isinstance(canonical_raw, str) or not canonical_raw.strip():
        fail(f"Artifact {artifact_key} missing canonical path")
    resolved_path, diagnostic = resolve_registry_artifact_path(
        artifact_key,
        entry,
        root=ROOT,
        context=f"registry:{artifact_key}",
    )
    diagnostics.append(diagnostic)
    return resolved_path


def load_app_export_contract() -> dict[str, Any]:
    payload = read_json(EXPORT_CONTRACT_PATH)
    contract = payload.get("app_export_contract") if isinstance(payload, dict) else None
    if not isinstance(contract, dict):
        fail("export_contract.json missing app_export_contract object")
    return contract


def load_model_source_path_strict(
    contract: dict[str, Any],
    *,
    model_key: str,
    field_name: str,
    diagnostics: list[dict[str, Any]],
) -> Path:
    model_sources = contract.get("model_sources")
    if not isinstance(model_sources, dict):
        fail("export_contract.json missing app_export_contract.model_sources")

    source_cfg = model_sources.get(model_key)
    if not isinstance(source_cfg, dict):
        fail(f"export_contract.json missing model_sources entry for {model_key}")

    raw_path = source_cfg.get(field_name)
    if not isinstance(raw_path, str) or not raw_path.strip():
        fail(f"export_contract.json missing {model_key}.{field_name}")
    resolved_path, diagnostic = resolve_runtime_path(
        raw_path,
        root=ROOT,
        context=f"contract:{model_key}.{field_name}",
    )
    diagnostics.append(diagnostic)
    return resolved_path


def write_fail_closed_intent(
    *,
    started_at: str,
    strategy_model: str,
    reference_model: str,
    blocked_reason: str,
    input_paths: list[str],
    source_paths: dict[str, str],
    path_resolution_diagnostics: list[dict[str, Any]],
) -> None:
    intent = {
        "intent_type": "normalized_execution_intent",
        "intent_status": "blocked",
        "generated_at_utc": utc_now_iso(),
        "as_of_source": None,
        "execution_mode": "read_only_intent_only",
        "trading_enabled": False,
        "kill_switch_required": True,
        "strategy_model": strategy_model,
        "reference_model": reference_model,
        "benchmark": "BTC",
        "signal_id": None,
        "target_asset": None,
        "target_side": "long_only_hold_selected_asset_or_cash",
        "target_regime": None,
        "size_mode": "not_computed_yet",
        "target_size_pct": None,
        "target_notional_usd": None,
        "reference_asset": None,
        "staleness_ok": False,
        "stale_signal": True,
        "blocked_reason": blocked_reason,
        "guardrail_flags": {
            "contract_validated": False,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False,
        },
        "source_paths": source_paths,
        "path_resolution_diagnostics": path_resolution_diagnostics,
        "resolved_columns": {},
        "source_samples": {},
        "notes": [
            "Intent generation was blocked fail-closed.",
            blocked_reason,
        ],
    }
    quality = {
        "intent_ok": False,
        "intent_status": "blocked",
        "strategy_model": strategy_model,
        "signal_id_present": False,
        "target_asset_present": False,
        "target_regime_present": False,
        "staleness_ok": False,
        "trading_enabled": False,
        "kill_switch_required": True,
        "leverage_live_truth_allowed": False,
        "blocked_reason": blocked_reason,
    }
    manifest = {
        "artifact_name": "latest_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": input_paths,
        "output_paths": [
            str(INTENT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "blocked",
    }
    INTENT_PATH.write_text(json.dumps(intent, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def fail_closed_intent(
    blocked_reason: str,
    *,
    started_at: str,
    strategy_model: str,
    reference_model: str,
    input_paths: list[str],
    source_paths: dict[str, str],
    path_resolution_diagnostics: list[dict[str, Any]],
) -> None:
    write_fail_closed_intent(
        started_at=started_at,
        strategy_model=strategy_model,
        reference_model=reference_model,
        blocked_reason=blocked_reason,
        input_paths=input_paths,
        source_paths=source_paths,
        path_resolution_diagnostics=path_resolution_diagnostics,
    )
    fail(blocked_reason)


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

    contract = load_app_export_contract()
    current_strategy_contract = load_current_main_strategy_root_contract(root=ROOT)
    path_resolution_diagnostics: list[dict[str, Any]] = []
    strategy_model = str(
        contract.get("main_model_key") or contract.get("main_strategy_model") or ""
    ).strip()
    reference_model = str(
        contract.get("reference_model_key") or contract.get("reference_strategy_model") or ""
    ).strip()
    if not strategy_model:
        fail("export_contract.json missing current main strategy model")
    if not reference_model:
        fail("export_contract.json missing reference strategy model")

    if strategy_model != str(current_strategy_contract["main_strategy_model"]).strip():
        fail(
            "Execution intent blocked: export contract main model diverged from current main strategy contract "
            f"(export_contract={strategy_model} current_strategy_contract={current_strategy_contract['main_strategy_model']})"
        )

    main_paper_path = Path(current_strategy_contract["paper_path"])
    path_resolution_diagnostics.append(
        {
            "context": f"contract:{strategy_model}.paper_path",
            "original_path": str(current_strategy_contract["canonical_paper_source_path"]),
            "resolved_path": str(main_paper_path.resolve()),
            "reason": "resolved_from_current_main_strategy_root_contract",
            "exists": main_paper_path.exists(),
            "selected_source_path": str(main_paper_path.resolve()),
        }
    )
    main_live_status_path = load_model_source_path_strict(
        contract,
        model_key=strategy_model,
        field_name="live_status_path",
        diagnostics=path_resolution_diagnostics,
    )
    reference_paper_path = load_model_source_path_strict(
        contract,
        model_key=reference_model,
        field_name="paper_path",
        diagnostics=path_resolution_diagnostics,
    )
    app_freshness_report_path = APP_FRESHNESS_REPORT_PATH
    path_resolution_diagnostics.append(
        {
            "context": "canonical:app_freshness_report",
            "original_path": str(APP_FRESHNESS_REPORT_PATH),
            "resolved_path": str(APP_FRESHNESS_REPORT_PATH.resolve()),
            "reason": "canonical_execution_freshness_report_path",
            "exists": APP_FRESHNESS_REPORT_PATH.exists(),
            "selected_source_path": str(APP_FRESHNESS_REPORT_PATH.resolve()),
        }
    )

    for diagnostic in path_resolution_diagnostics:
        log(format_path_resolution_message(diagnostic))

    input_paths_for_failure = [
        str(EXPORT_CONTRACT_PATH.resolve()),
        str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
        str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
        str(main_paper_path.resolve()),
        str(main_live_status_path.resolve()),
        str(reference_paper_path.resolve()),
        str(app_freshness_report_path.resolve()),
    ]
    source_paths_for_failure = {
        "strategy_paper": str(main_paper_path.resolve()),
        "strategy_live_status": str(main_live_status_path.resolve()),
        "reference_paper": str(reference_paper_path.resolve()),
        "app_freshness_report": str(app_freshness_report_path.resolve()),
        "authority_latest_successful_snapshot": str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
        "authority_latest_attempt_status": str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
    }

    latest_successful_snapshot = read_json(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH)
    latest_attempt_status = read_json(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH)
    authority_product_snapshot = require_mapping(
        latest_successful_snapshot.get("app_product_snapshot"),
        "latest_successful_snapshot.app_product_snapshot",
    )
    try:
        validate_authoritative_dependency_closure(
            authority_product_snapshot,
            current_strategy_contract,
            root=ROOT,
            context="Execution intent blocked:",
        )
    except Exception as exc:
        fail_closed_intent(
            str(exc),
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )

    authority_target_closed_day = normalize_iso_day_text(
        latest_successful_snapshot.get("target_closed_day_utc"),
        context="latest_successful_snapshot.target_closed_day_utc",
    )
    authority_strategy_closed_day = normalize_iso_day_text(
        authority_product_snapshot.get("strategy_last_closed_day"),
        context="latest_successful_snapshot.app_product_snapshot.strategy_last_closed_day",
    )
    authority_freshness_closed_day = normalize_iso_day_text(
        authority_product_snapshot.get("freshness_target_closed_day"),
        context="latest_successful_snapshot.app_product_snapshot.freshness_target_closed_day",
    )
    attempt_currentness_status = str(latest_attempt_status.get("currentness_status") or "").strip().lower()
    attempt_target_closed_day = normalize_iso_day_text(
        latest_attempt_status.get("target_closed_day_utc"),
        context="latest_attempt_status.target_closed_day_utc",
    )
    attempt_latest_available_closed_day = normalize_iso_day_text(
        latest_attempt_status.get("latest_available_closed_utc_day"),
        context="latest_attempt_status.latest_available_closed_utc_day",
    )
    if attempt_currentness_status != "current":
        fail_closed_intent(
            f"Execution intent blocked: authority currentness is not current (currentness_status={attempt_currentness_status or 'missing'})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )
    if len({authority_target_closed_day, authority_strategy_closed_day, authority_freshness_closed_day, attempt_target_closed_day, attempt_latest_available_closed_day}) != 1:
        fail_closed_intent(
            "Execution intent blocked: authority target day is not aligned across authoritative inputs "
            f"(success_target={authority_target_closed_day} strategy={authority_strategy_closed_day} "
            f"freshness={authority_freshness_closed_day} attempt_target={attempt_target_closed_day} "
            f"attempt_latest_available={attempt_latest_available_closed_day})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )

    paper_header, paper_rows = read_csv_rows(main_paper_path)
    if not paper_rows:
        fail_closed_intent(
            f"Execution intent blocked: no rows found in {main_paper_path}",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )

    live_header, live_rows = read_csv_rows(main_live_status_path)
    if not live_rows:
        fail_closed_intent(
            f"Execution intent blocked: no rows found in {main_live_status_path}",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )

    reference_header, reference_rows = read_csv_rows(reference_paper_path)
    if not reference_rows:
        fail_closed_intent(
            f"Execution intent blocked: no rows found in {reference_paper_path}",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )

    freshness_report = read_json(app_freshness_report_path)
    freshness_report_closed_day = normalize_iso_day_text(
        freshness_report.get("latest_closed_utc_date"),
        context="app_freshness_report.latest_closed_utc_date",
    )
    freshness_report_status = str(freshness_report.get("status") or "").strip().lower()
    freshness_report_errors = freshness_report.get("errors")
    if freshness_report_closed_day != authority_target_closed_day:
        fail_closed_intent(
            "Execution intent blocked: canonical freshness report day diverged from authority day "
            f"(authority_day={authority_target_closed_day} freshness_day={freshness_report_closed_day})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )
    if freshness_report_status not in {"ok", "success", "current"}:
        fail_closed_intent(
            f"Execution intent blocked: canonical freshness report is not green (status={freshness_report_status or 'missing'})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )
    if isinstance(freshness_report_errors, list) and freshness_report_errors:
        fail_closed_intent(
            "Execution intent blocked: canonical freshness report contains errors",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
        )

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
    )
    as_of_source = normalize_iso_day_text(
        as_of_source,
        context="execution intent as_of_source",
    )
    if as_of_source != authority_target_closed_day:
        fail_closed_intent(
            "Execution intent blocked: source day diverged from authority day "
            f"(authority_day={authority_target_closed_day} source_day={as_of_source})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
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

    freshness_ok = True
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
            "app_freshness_report": str(app_freshness_report_path.resolve()),
            "authority_latest_successful_snapshot": str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
            "authority_latest_attempt_status": str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
        },
        "path_resolution_diagnostics": path_resolution_diagnostics,
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
            "Authority day alignment is required across the full canonical dependency closure.",
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
            str(EXPORT_CONTRACT_PATH.resolve()),
            str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
            str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
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
