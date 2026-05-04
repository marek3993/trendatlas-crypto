from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
PROJECT_TRUTH_PATH = SOURCE_OF_TRUTH_DIR / "project_truth.json"
EXPORT_CONTRACT_PATH = SOURCE_OF_TRUTH_DIR / "export_contract.json"
DEFAULT_ALLOWED_CANONICAL_ROOT = "outputs/execution/app_exports"
# Homepage top cards are a current live/main strategy surface. Even though the
# canonical filename contains "net_compare_export", homepage top cards must read
# the same canonical metrics artifact as current_main_strategy_root_contract and
# must never switch to a separate compare/ranking-only artifact.
HOMEPAGE_TOP_PERFORMANCE_SOURCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "phase68g_66g_1p25x_candidate": {
        "source_family": "canonical_phase68g_authoritative_net_compare_top_cards",
        "semantic_role": "current_live_main_strategy_top_cards",
        "metrics_source_path": (
            "outputs/execution/app_exports/"
            "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
        ),
        "metric_aliases": {
            "cagr_pct": "cagr_pct",
            "since2023_cagr_pct": "since2023_cagr_pct",
            "since2025_cagr_pct": "since2025_cagr_pct",
        },
    },
}
HOMEPAGE_OPERATIONAL_METRIC_CONTRACTS: dict[str, dict[str, Any]] = {
    "phase68g_66g_1p25x_candidate": {
        "semantic_role": "current_live_main_strategy_operational_metrics",
        "expected_switch_count": 9,
        "expected_cash_days_pct": 85.17,
        "cash_days_tolerance_pct": 0.25,
        "expected_btc_days_pct": 0.0,
        "btc_days_tolerance_pct": 0.01,
    },
}


class CurrentMainStrategyContractError(ValueError):
    """Raised when the current main strategy root contract is missing or diverged."""


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise CurrentMainStrategyContractError(f"Missing required JSON file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CurrentMainStrategyContractError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CurrentMainStrategyContractError(f"Expected top-level object in {path}")
    return payload


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CurrentMainStrategyContractError(f"{context} must be an object")
    return value


def _require_text(value: Any, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurrentMainStrategyContractError(f"{context} is missing")
    return text


def _require_float(value: Any, context: str) -> float:
    if value is None:
        raise CurrentMainStrategyContractError(f"{context} is missing")
    text = str(value).strip()
    if not text:
        raise CurrentMainStrategyContractError(f"{context} is missing")
    try:
        numeric = float(text)
    except ValueError as exc:
        raise CurrentMainStrategyContractError(f"{context} must be numeric (actual={text})") from exc
    if not math.isfinite(numeric):
        raise CurrentMainStrategyContractError(
            f"{context} must be a finite numeric value (actual={text})"
        )
    return numeric


def _normalize_app_path_text(path_text: str) -> str:
    normalized = str(path_text).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _resolve_path(raw_path: Any, *, context: str, root: Path) -> Path:
    text = _require_text(raw_path, context)
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _path_for_app(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _ensure_within_root(path: Path, *, allowed_root: Path, context: str) -> None:
    try:
        path.resolve().relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise CurrentMainStrategyContractError(
            f"{context} must stay within {allowed_root.resolve()} (actual={path.resolve()})"
        ) from exc


def serialize_current_main_strategy_root_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": int(contract["contract_version"]),
        "source_family": str(contract["source_family"]),
        "main_strategy_model": str(contract["main_strategy_model"]),
        "canonical_metrics_source_path": str(contract["canonical_metrics_source_path"]),
        "canonical_paper_source_path": str(contract["canonical_paper_source_path"]),
        "allowed_canonical_root": str(contract["allowed_canonical_root"]),
        "forbidden_source_roots": [str(item) for item in contract["forbidden_source_roots"]],
    }


def load_current_main_strategy_root_contract(
    *,
    root: Path | None = None,
    require_files: bool = True,
) -> dict[str, Any]:
    repo_root = (root or ROOT).resolve()
    truth = _read_json_required(repo_root / "source_of_truth" / "project_truth.json")
    export_contract = _read_json_required(repo_root / "source_of_truth" / "export_contract.json")

    app_product_truth = _require_mapping(
        truth.get("app_product_truth"),
        "source_of_truth/project_truth.json app_product_truth",
    )
    truth_main_strategy_model = _require_text(
        app_product_truth.get("main_strategy_model"),
        "source_of_truth/project_truth.json app_product_truth.main_strategy_model",
    )

    app_export_contract = _require_mapping(
        export_contract.get("app_export_contract"),
        "source_of_truth/export_contract.json app_export_contract",
    )
    export_main_strategy_model = _require_text(
        app_export_contract.get("main_strategy_model"),
        "source_of_truth/export_contract.json app_export_contract.main_strategy_model",
    )
    if export_main_strategy_model != truth_main_strategy_model:
        raise CurrentMainStrategyContractError(
            "Current main strategy truth diverged between source_of_truth/project_truth.json and "
            "source_of_truth/export_contract.json "
            f"(project_truth={truth_main_strategy_model} export_contract={export_main_strategy_model})"
        )

    model_sources = _require_mapping(
        app_export_contract.get("model_sources"),
        "source_of_truth/export_contract.json app_export_contract.model_sources",
    )
    main_source_entry = _require_mapping(
        model_sources.get(truth_main_strategy_model),
        "source_of_truth/export_contract.json "
        f"app_export_contract.model_sources.{truth_main_strategy_model}",
    )

    root_contract = _require_mapping(
        app_export_contract.get("current_main_strategy_root_contract"),
        "source_of_truth/export_contract.json app_export_contract.current_main_strategy_root_contract",
    )
    contract_version = int(root_contract.get("contract_version") or 0)
    if contract_version < 1:
        raise CurrentMainStrategyContractError(
            "source_of_truth/export_contract.json app_export_contract.current_main_strategy_root_contract.contract_version "
            "must be >= 1"
        )

    contract_main_strategy_model = _require_text(
        root_contract.get("main_strategy_model"),
        "source_of_truth/export_contract.json app_export_contract.current_main_strategy_root_contract.main_strategy_model",
    )
    if contract_main_strategy_model != truth_main_strategy_model:
        raise CurrentMainStrategyContractError(
            "Current main strategy root contract model diverged from source of truth "
            f"(truth={truth_main_strategy_model} root_contract={contract_main_strategy_model})"
        )

    contract_metrics_path_text = _normalize_app_path_text(
        _require_text(
            root_contract.get("canonical_metrics_source_path"),
            "source_of_truth/export_contract.json "
            "app_export_contract.current_main_strategy_root_contract.canonical_metrics_source_path",
        )
    )
    contract_paper_path_text = _normalize_app_path_text(
        _require_text(
            root_contract.get("canonical_paper_source_path"),
            "source_of_truth/export_contract.json "
            "app_export_contract.current_main_strategy_root_contract.canonical_paper_source_path",
        )
    )
    source_entry_metrics_path_text = _normalize_app_path_text(
        _require_text(
            main_source_entry.get("summary_path"),
            "source_of_truth/export_contract.json "
            f"app_export_contract.model_sources.{truth_main_strategy_model}.summary_path",
        )
    )
    source_entry_paper_path_text = _normalize_app_path_text(
        _require_text(
            main_source_entry.get("paper_path"),
            "source_of_truth/export_contract.json "
            f"app_export_contract.model_sources.{truth_main_strategy_model}.paper_path",
        )
    )
    if contract_metrics_path_text != source_entry_metrics_path_text:
        raise CurrentMainStrategyContractError(
            "Current main strategy root contract metrics path diverged from model_sources "
            f"(root_contract={contract_metrics_path_text} model_sources={source_entry_metrics_path_text})"
        )
    if contract_paper_path_text != source_entry_paper_path_text:
        raise CurrentMainStrategyContractError(
            "Current main strategy root contract paper path diverged from model_sources "
            f"(root_contract={contract_paper_path_text} model_sources={source_entry_paper_path_text})"
        )

    source_family = _require_text(
        root_contract.get("source_family"),
        "source_of_truth/export_contract.json app_export_contract.current_main_strategy_root_contract.source_family",
    )
    allowed_canonical_root = _normalize_app_path_text(
        _require_text(
            root_contract.get("allowed_canonical_root"),
            "source_of_truth/export_contract.json "
            "app_export_contract.current_main_strategy_root_contract.allowed_canonical_root",
        )
    )
    forbidden_source_roots = root_contract.get("forbidden_source_roots")
    if not isinstance(forbidden_source_roots, list) or not forbidden_source_roots:
        raise CurrentMainStrategyContractError(
            "source_of_truth/export_contract.json app_export_contract.current_main_strategy_root_contract."
            "forbidden_source_roots must be a non-empty list"
        )
    normalized_forbidden_source_roots = [
        _normalize_app_path_text(_require_text(item, "forbidden_source_roots[]"))
        for item in forbidden_source_roots
    ]

    resolved_metrics_path = _resolve_path(
        contract_metrics_path_text,
        context="current main strategy metrics source path",
        root=repo_root,
    )
    resolved_paper_path = _resolve_path(
        contract_paper_path_text,
        context="current main strategy paper source path",
        root=repo_root,
    )
    allowed_root_path = _resolve_path(
        allowed_canonical_root,
        context="current main strategy allowed canonical root",
        root=repo_root,
    )
    _ensure_within_root(
        resolved_metrics_path,
        allowed_root=allowed_root_path,
        context="Current main strategy metrics source path",
    )
    _ensure_within_root(
        resolved_paper_path,
        allowed_root=allowed_root_path,
        context="Current main strategy paper source path",
    )
    if require_files and (not resolved_metrics_path.exists() or not resolved_metrics_path.is_file()):
        raise CurrentMainStrategyContractError(
            f"Current main strategy metrics source path is missing: {resolved_metrics_path}"
        )
    if require_files and (not resolved_paper_path.exists() or not resolved_paper_path.is_file()):
        raise CurrentMainStrategyContractError(
            f"Current main strategy paper source path is missing: {resolved_paper_path}"
        )

    return {
        "contract_version": contract_version,
        "source_family": source_family,
        "main_strategy_model": truth_main_strategy_model,
        "canonical_metrics_source_path": _path_for_app(resolved_metrics_path, root=repo_root),
        "canonical_paper_source_path": _path_for_app(resolved_paper_path, root=repo_root),
        "allowed_canonical_root": allowed_canonical_root or DEFAULT_ALLOWED_CANONICAL_ROOT,
        "forbidden_source_roots": normalized_forbidden_source_roots,
        "metrics_path": resolved_metrics_path,
        "paper_path": resolved_paper_path,
    }


def validate_product_snapshot_current_strategy_contract(
    product_snapshot: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    context: str,
) -> None:
    expected_contract_payload = serialize_current_main_strategy_root_contract(contract)
    actual_contract_payload = product_snapshot.get("current_main_strategy_root_contract")
    if actual_contract_payload is not None:
        actual_contract_payload = _require_mapping(
            actual_contract_payload,
            f"{context} product_snapshot.current_main_strategy_root_contract",
        )
        if actual_contract_payload != expected_contract_payload:
            raise CurrentMainStrategyContractError(
                f"{context} product_snapshot.current_main_strategy_root_contract diverged from source_of_truth/export_contract.json"
            )

    expected_model = str(contract["main_strategy_model"])
    expected_metrics_path = str(contract["canonical_metrics_source_path"])
    expected_paper_path = str(contract["canonical_paper_source_path"])

    actual_model = _require_text(
        product_snapshot.get("main_strategy_model"),
        f"{context} product_snapshot.main_strategy_model",
    )
    if actual_model != expected_model:
        raise CurrentMainStrategyContractError(
            f"{context} product_snapshot.main_strategy_model diverged "
            f"(expected={expected_model} actual={actual_model})"
        )

    main_strategy_metrics = _require_mapping(
        product_snapshot.get("main_strategy_metrics"),
        f"{context} product_snapshot.main_strategy_metrics",
    )
    metrics_model = _require_text(
        main_strategy_metrics.get("model"),
        f"{context} product_snapshot.main_strategy_metrics.model",
    )
    if metrics_model != expected_model:
        raise CurrentMainStrategyContractError(
            f"{context} product_snapshot.main_strategy_metrics.model diverged "
            f"(expected={expected_model} actual={metrics_model})"
        )
    validate_homepage_operational_metrics_contract(
        main_strategy_metrics,
        main_strategy_model=expected_model,
        context=f"{context} product_snapshot.main_strategy_metrics",
    )

    top_performance_metrics_payload = product_snapshot.get("main_strategy_top_performance_metrics")
    if top_performance_metrics_payload is not None:
        top_performance_metrics = _require_mapping(
            top_performance_metrics_payload,
            f"{context} product_snapshot.main_strategy_top_performance_metrics",
        )
        top_performance_model = str(top_performance_metrics.get("model") or "").strip()
        if top_performance_model and top_performance_model != expected_model:
            raise CurrentMainStrategyContractError(
                f"{context} product_snapshot.main_strategy_top_performance_metrics.model diverged "
                f"(expected={expected_model} actual={top_performance_model})"
            )

    chart_source_paths = _require_mapping(
        product_snapshot.get("chart_source_paths"),
        f"{context} product_snapshot.chart_source_paths",
    )
    validate_homepage_main_chart_source_path(
        chart_source_paths.get("main_strategy"),
        contract,
        context=f"{context} product_snapshot.chart_source_paths.main_strategy",
    )

    source_metadata = _require_mapping(
        product_snapshot.get("source_metadata"),
        f"{context} product_snapshot.source_metadata",
    )
    metrics_metadata = _require_mapping(
        source_metadata.get("main_strategy_metrics"),
        f"{context} product_snapshot.source_metadata.main_strategy_metrics",
    )
    actual_metrics_path = _require_text(
        metrics_metadata.get("path"),
        f"{context} product_snapshot.source_metadata.main_strategy_metrics.path",
    )
    if _normalize_app_path_text(actual_metrics_path) != expected_metrics_path:
        raise CurrentMainStrategyContractError(
            f"{context} product_snapshot.source_metadata.main_strategy_metrics.path diverged "
            f"(expected={expected_metrics_path} actual={actual_metrics_path})"
        )

    top_performance_metadata_payload = source_metadata.get("main_strategy_top_performance_metrics")
    if top_performance_metadata_payload is not None:
        top_performance_metadata = _require_mapping(
            top_performance_metadata_payload,
            f"{context} product_snapshot.source_metadata.main_strategy_top_performance_metrics",
        )
        validate_homepage_top_card_source_path(
            top_performance_metadata.get("path"),
            contract,
            context=f"{context} product_snapshot.source_metadata.main_strategy_top_performance_metrics.path",
        )

    for field_name in ("strategy_last_closed_day", "live_public_state"):
        field_metadata = _require_mapping(
            source_metadata.get(field_name),
            f"{context} product_snapshot.source_metadata.{field_name}",
        )
        validate_homepage_main_chart_source_path(
            field_metadata.get("path"),
            contract,
            context=f"{context} product_snapshot.source_metadata.{field_name}.path",
        )

    chart_source_metadata = _require_mapping(
        source_metadata.get("chart_source_paths"),
        f"{context} product_snapshot.source_metadata.chart_source_paths",
    )
    chart_main_source_metadata = _require_mapping(
        chart_source_metadata.get("main_strategy"),
        f"{context} product_snapshot.source_metadata.chart_source_paths.main_strategy",
    )
    validate_homepage_main_chart_source_path(
        chart_main_source_metadata.get("path"),
        contract,
        context=f"{context} product_snapshot.source_metadata.chart_source_paths.main_strategy.path",
    )


def validate_homepage_main_chart_source_path(
    source_path: Any,
    contract: Mapping[str, Any],
    *,
    context: str,
) -> str:
    actual_source_path = _normalize_app_path_text(
        _require_text(source_path, f"{context} homepage main-chart source path")
    )
    expected_source_path = _normalize_app_path_text(str(contract["canonical_paper_source_path"]))
    if actual_source_path != expected_source_path:
        raise CurrentMainStrategyContractError(
            f"{context} homepage main chart must use "
            "current_main_strategy_root_contract.canonical_paper_source_path and must not "
            "switch to a stale/native/non-canonical paper artifact "
            f"(expected={expected_source_path} actual={actual_source_path})"
    )
    return actual_source_path


def _read_csv_rows_required(path: Path, *, context: str) -> list[dict[str, str]]:
    if not path.exists() or not path.is_file():
        raise CurrentMainStrategyContractError(f"{context} is missing: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
    except Exception as exc:
        raise CurrentMainStrategyContractError(f"{context} is unreadable: {path} ({exc})") from exc
    if not rows:
        raise CurrentMainStrategyContractError(f"{context} has no rows: {path}")
    return rows


def _normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = _require_text(value, context)
    normalized = text.replace("\\", "/").strip()
    if "T" in normalized:
        normalized = normalized.split("T", 1)[0]
    if len(normalized) != 10:
        raise CurrentMainStrategyContractError(f"{context} is not an ISO day: {text}")
    return normalized


def validate_homepage_operational_metrics_contract(
    metrics: Mapping[str, Any],
    *,
    main_strategy_model: str,
    context: str,
) -> None:
    contract = HOMEPAGE_OPERATIONAL_METRIC_CONTRACTS.get(str(main_strategy_model or "").strip())
    if contract is None:
        return

    actual_switch_count = int(round(_require_float(metrics.get("switch_count"), f"{context}.switch_count")))
    expected_switch_count = int(contract["expected_switch_count"])
    if actual_switch_count != expected_switch_count:
        raise CurrentMainStrategyContractError(
            f"{context}.switch_count diverged from {main_strategy_model} operational metric contract "
            f"(expected={expected_switch_count} actual={actual_switch_count})"
        )

    actual_cash_days_pct = _require_float(metrics.get("cash_days_pct"), f"{context}.cash_days_pct")
    expected_cash_days_pct = float(contract["expected_cash_days_pct"])
    cash_days_tolerance_pct = float(contract["cash_days_tolerance_pct"])
    if abs(actual_cash_days_pct - expected_cash_days_pct) > cash_days_tolerance_pct:
        raise CurrentMainStrategyContractError(
            f"{context}.cash_days_pct diverged from {main_strategy_model} operational metric contract "
            f"(expected={expected_cash_days_pct} +/- {cash_days_tolerance_pct} actual={actual_cash_days_pct})"
        )

    actual_btc_days_pct = _require_float(metrics.get("btc_days_pct"), f"{context}.btc_days_pct")
    expected_btc_days_pct = float(contract["expected_btc_days_pct"])
    btc_days_tolerance_pct = float(contract["btc_days_tolerance_pct"])
    if abs(actual_btc_days_pct - expected_btc_days_pct) > btc_days_tolerance_pct:
        raise CurrentMainStrategyContractError(
            f"{context}.btc_days_pct diverged from {main_strategy_model} operational metric contract "
            f"(expected={expected_btc_days_pct} +/- {btc_days_tolerance_pct} actual={actual_btc_days_pct})"
        )


def validate_current_main_strategy_source_files_against_snapshot(
    product_snapshot: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    context: str,
) -> dict[str, str]:
    validate_product_snapshot_current_strategy_contract(
        product_snapshot,
        contract,
        context=context,
    )

    expected_model = _require_text(
        product_snapshot.get("main_strategy_model"),
        f"{context} product_snapshot.main_strategy_model",
    )
    expected_closed_day = _normalize_iso_day_text(
        product_snapshot.get("strategy_last_closed_day"),
        context=f"{context} product_snapshot.strategy_last_closed_day",
    )

    metrics_path = Path(contract["metrics_path"])
    paper_path = Path(contract["paper_path"])

    metrics_rows = _read_csv_rows_required(
        metrics_path,
        context=f"{context} canonical main strategy metrics export",
    )
    metrics_row = metrics_rows[-1]
    metrics_model = _require_text(
        metrics_row.get("model"),
        f"{context} canonical main strategy metrics export model",
    )
    if metrics_model != expected_model:
        raise CurrentMainStrategyContractError(
            f"{context} canonical main strategy metrics export model diverged "
            f"(expected={expected_model} actual={metrics_model})"
        )

    metrics_latest_available_day = _normalize_iso_day_text(
        metrics_row.get("latest_available_date"),
        context=f"{context} canonical main strategy metrics export latest_available_date",
    )
    if metrics_latest_available_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical main strategy metrics export is stale versus authority snapshot "
            f"(expected={expected_closed_day} actual={metrics_latest_available_day} path={metrics_path})"
        )

    paper_rows = _read_csv_rows_required(
        paper_path,
        context=f"{context} canonical main strategy paper",
    )
    paper_last_row = paper_rows[-1]
    paper_last_day = _normalize_iso_day_text(
        paper_last_row.get("date"),
        context=f"{context} canonical main strategy paper last_row.date",
    )
    if paper_last_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical main strategy paper is stale versus authority snapshot "
            f"(expected={expected_closed_day} actual={paper_last_day} path={paper_path})"
        )

    return {
        "main_strategy_model": expected_model,
        "expected_closed_day": expected_closed_day,
        "metrics_latest_available_day": metrics_latest_available_day,
        "paper_last_day": paper_last_day,
    }


def _resolve_source_metadata_path(
    source_metadata: Mapping[str, Any],
    *,
    key: str,
    context: str,
    root: Path,
) -> Path:
    metadata = _require_mapping(
        source_metadata.get(key),
        f"{context} product_snapshot.source_metadata.{key}",
    )
    return _resolve_path(
        metadata.get("path"),
        context=f"{context} product_snapshot.source_metadata.{key}.path",
        root=root,
    )


def _resolve_nested_source_metadata_path(
    source_metadata: Mapping[str, Any],
    *,
    parent_key: str,
    child_key: str,
    context: str,
    root: Path,
) -> Path:
    parent_metadata = _require_mapping(
        source_metadata.get(parent_key),
        f"{context} product_snapshot.source_metadata.{parent_key}",
    )
    child_metadata = _require_mapping(
        parent_metadata.get(child_key),
        f"{context} product_snapshot.source_metadata.{parent_key}.{child_key}",
    )
    return _resolve_path(
        child_metadata.get("path"),
        context=f"{context} product_snapshot.source_metadata.{parent_key}.{child_key}.path",
        root=root,
    )


def _normalize_row_day(
    row: Mapping[str, Any],
    candidates: list[str],
    *,
    context: str,
) -> str:
    for candidate in candidates:
        value = row.get(candidate)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        return _normalize_iso_day_text(text, context=f"{context}.{candidate}")
    raise CurrentMainStrategyContractError(
        f"{context} is missing all supported day fields: {', '.join(candidates)}"
    )


def _load_export_contract_model_source_path(
    model_key: str,
    field_name: str,
    *,
    root: Path,
    context: str,
) -> Path:
    export_contract = _read_json_required(root / "source_of_truth" / "export_contract.json")
    app_export_contract = _require_mapping(
        export_contract.get("app_export_contract"),
        f"{context} source_of_truth/export_contract.json app_export_contract",
    )
    model_sources = _require_mapping(
        app_export_contract.get("model_sources"),
        f"{context} source_of_truth/export_contract.json app_export_contract.model_sources",
    )
    model_source = _require_mapping(
        model_sources.get(model_key),
        f"{context} source_of_truth/export_contract.json app_export_contract.model_sources.{model_key}",
    )
    return _resolve_path(
        model_source.get(field_name),
        context=(
            f"{context} source_of_truth/export_contract.json "
            f"app_export_contract.model_sources.{model_key}.{field_name}"
        ),
        root=root,
    )


def validate_authoritative_dependency_closure(
    product_snapshot: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    root: Path | None = None,
    context: str,
) -> dict[str, Any]:
    repo_root = (root or ROOT).resolve()
    current_strategy_validation = validate_current_main_strategy_source_files_against_snapshot(
        product_snapshot,
        contract,
        context=context,
    )

    source_metadata = _require_mapping(
        product_snapshot.get("source_metadata"),
        f"{context} product_snapshot.source_metadata",
    )
    chart_source_paths = _require_mapping(
        product_snapshot.get("chart_source_paths"),
        f"{context} product_snapshot.chart_source_paths",
    )

    expected_closed_day = current_strategy_validation["expected_closed_day"]
    freshness_target_closed_day = _normalize_iso_day_text(
        product_snapshot.get("freshness_target_closed_day"),
        context=f"{context} product_snapshot.freshness_target_closed_day",
    )
    if freshness_target_closed_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} product_snapshot.freshness_target_closed_day diverged "
            f"(expected={expected_closed_day} actual={freshness_target_closed_day})"
        )

    reference_strategy_model = _require_text(
        product_snapshot.get("reference_strategy_model"),
        f"{context} product_snapshot.reference_strategy_model",
    )
    reference_paper_path = _resolve_path(
        chart_source_paths.get("reference_strategy"),
        context=f"{context} product_snapshot.chart_source_paths.reference_strategy",
        root=repo_root,
    )
    reference_paper_metadata_path = _resolve_nested_source_metadata_path(
        source_metadata,
        parent_key="chart_source_paths",
        child_key="reference_strategy",
        context=context,
        root=repo_root,
    )
    if reference_paper_metadata_path.resolve() != reference_paper_path.resolve():
        raise CurrentMainStrategyContractError(
            f"{context} product_snapshot.source_metadata.chart_source_paths.reference_strategy.path diverged "
            f"(expected={reference_paper_path.resolve()} actual={reference_paper_metadata_path.resolve()})"
        )
    reference_paper_last_row = _read_csv_rows_required(
        reference_paper_path,
        context=f"{context} canonical reference strategy paper",
    )[-1]
    reference_paper_last_day = _normalize_row_day(
        reference_paper_last_row,
        ["date"],
        context=f"{context} canonical reference strategy paper last_row",
    )
    if reference_paper_last_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical reference strategy paper is stale versus authority snapshot "
            f"(expected={expected_closed_day} actual={reference_paper_last_day} path={reference_paper_path})"
        )

    reference_live_status_path = _load_export_contract_model_source_path(
        reference_strategy_model,
        "live_status_path",
        root=repo_root,
        context=context,
    )
    reference_live_status_last_row = _read_csv_rows_required(
        reference_live_status_path,
        context=f"{context} canonical reference live status",
    )[-1]
    reference_live_status_model = _require_text(
        reference_live_status_last_row.get("model"),
        f"{context} canonical reference live status model",
    )
    if reference_live_status_model != reference_strategy_model:
        raise CurrentMainStrategyContractError(
            f"{context} canonical reference live status model diverged "
            f"(expected={reference_strategy_model} actual={reference_live_status_model})"
        )
    reference_live_status_day = _normalize_row_day(
        reference_live_status_last_row,
        ["latest_available_date", "date"],
        context=f"{context} canonical reference live status last_row",
    )
    if reference_live_status_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical reference live status is stale versus authority snapshot "
            f"(expected={expected_closed_day} actual={reference_live_status_day} path={reference_live_status_path})"
        )

    phase66g_live_status_path = _resolve_source_metadata_path(
        source_metadata,
        key="trend_barometer_summary",
        context=context,
        root=repo_root,
    )
    phase66g_live_status_last_row = _read_csv_rows_required(
        phase66g_live_status_path,
        context=f"{context} canonical phase66g live status",
    )[-1]
    phase66g_live_status_day = _normalize_row_day(
        phase66g_live_status_last_row,
        ["latest_available_date", "trend_calc_date", "date"],
        context=f"{context} canonical phase66g live status last_row",
    )
    if phase66g_live_status_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical phase66g live status is stale versus authority snapshot "
            f"(expected={expected_closed_day} actual={phase66g_live_status_day} path={phase66g_live_status_path})"
        )
    phase66g_trend_calc_day = _normalize_row_day(
        phase66g_live_status_last_row,
        ["trend_calc_date", "latest_available_date", "date"],
        context=f"{context} canonical phase66g live status trend calc",
    )
    if phase66g_trend_calc_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical phase66g trend calculation day diverged "
            f"(expected={expected_closed_day} actual={phase66g_trend_calc_day} path={phase66g_live_status_path})"
        )

    trend_history_path = _resolve_path(
        product_snapshot.get("trend_history_source_path"),
        context=f"{context} product_snapshot.trend_history_source_path",
        root=repo_root,
    )
    trend_history_metadata_path = _resolve_source_metadata_path(
        source_metadata,
        key="trend_history_source_path",
        context=context,
        root=repo_root,
    )
    if trend_history_metadata_path.resolve() != trend_history_path.resolve():
        raise CurrentMainStrategyContractError(
            f"{context} product_snapshot.source_metadata.trend_history_source_path.path diverged "
            f"(expected={trend_history_path.resolve()} actual={trend_history_metadata_path.resolve()})"
        )
    trend_history_last_row = _read_csv_rows_required(
        trend_history_path,
        context=f"{context} canonical phase66g trend history",
    )[-1]
    trend_history_last_day = _normalize_row_day(
        trend_history_last_row,
        ["trend_calc_date", "date", "latest_available_date"],
        context=f"{context} canonical phase66g trend history last_row",
    )
    if trend_history_last_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical phase66g trend history is stale versus authority snapshot "
            f"(expected={expected_closed_day} actual={trend_history_last_day} path={trend_history_path})"
        )

    freshness_report_path = _resolve_source_metadata_path(
        source_metadata,
        key="freshness",
        context=context,
        root=repo_root,
    )
    freshness_target_metadata_path = _resolve_source_metadata_path(
        source_metadata,
        key="freshness_target_closed_day",
        context=context,
        root=repo_root,
    )
    if freshness_target_metadata_path.resolve() != freshness_report_path.resolve():
        raise CurrentMainStrategyContractError(
            f"{context} freshness metadata paths diverged "
            f"(freshness={freshness_report_path.resolve()} freshness_target_closed_day={freshness_target_metadata_path.resolve()})"
        )
    freshness_payload = _read_json_required(freshness_report_path)
    freshness_report_day = _normalize_iso_day_text(
        freshness_payload.get("latest_closed_utc_date"),
        context=f"{context} canonical freshness report latest_closed_utc_date",
    )
    if freshness_report_day != expected_closed_day:
        raise CurrentMainStrategyContractError(
            f"{context} canonical freshness report diverged from authority snapshot "
            f"(expected={expected_closed_day} actual={freshness_report_day} path={freshness_report_path})"
        )
    freshness_status = str(freshness_payload.get("status") or "").strip().lower()
    if freshness_status not in {"ok", "success", "current"}:
        raise CurrentMainStrategyContractError(
            f"{context} canonical freshness report is not green "
            f"(status={freshness_status or 'missing'} path={freshness_report_path})"
        )
    freshness_errors = freshness_payload.get("errors")
    if isinstance(freshness_errors, list) and freshness_errors:
        raise CurrentMainStrategyContractError(
            f"{context} canonical freshness report contains errors "
            f"(path={freshness_report_path})"
        )

    return {
        **current_strategy_validation,
        "reference_strategy_model": reference_strategy_model,
        "reference_paper_path": reference_paper_path,
        "reference_paper_last_day": reference_paper_last_day,
        "reference_live_status_path": reference_live_status_path,
        "reference_live_status_day": reference_live_status_day,
        "phase66g_live_status_path": phase66g_live_status_path,
        "phase66g_live_status_day": phase66g_live_status_day,
        "phase66g_trend_history_path": trend_history_path,
        "phase66g_trend_history_day": trend_history_last_day,
        "freshness_report_path": freshness_report_path,
        "freshness_report_day": freshness_report_day,
    }


def resolve_homepage_current_strategy_sources(
    product_snapshot: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    validate_product_snapshot_current_strategy_contract(
        product_snapshot,
        contract,
        context="Homepage load blocked:",
    )
    paper_source_path = validate_homepage_main_chart_source_path(
        (
            _require_mapping(
                product_snapshot.get("chart_source_paths"),
                "Homepage load blocked: product_snapshot.chart_source_paths",
            )
        ).get("main_strategy"),
        contract,
        context="Homepage load blocked:",
    )
    return {
        "source_family": str(contract["source_family"]),
        "main_strategy_model": str(contract["main_strategy_model"]),
        "metrics_source_path": str(contract["canonical_metrics_source_path"]),
        "paper_source_path": paper_source_path,
        "metrics_path": Path(contract["metrics_path"]),
        "paper_path": Path(contract["paper_path"]),
    }


def resolve_homepage_top_performance_source_contract(
    main_strategy_model: str,
    *,
    root: Path | None = None,
    require_file: bool = True,
) -> dict[str, Any] | None:
    repo_root = (root or ROOT).resolve()
    source_contract = HOMEPAGE_TOP_PERFORMANCE_SOURCE_CONTRACTS.get(main_strategy_model)
    if source_contract is None:
        return None

    source_family = _require_text(
        source_contract.get("source_family"),
        f"homepage top performance source contract {main_strategy_model}.source_family",
    )
    semantic_role = _require_text(
        source_contract.get("semantic_role"),
        f"homepage top performance source contract {main_strategy_model}.semantic_role",
    )
    metrics_source_path_text = _normalize_app_path_text(
        _require_text(
            source_contract.get("metrics_source_path"),
            f"homepage top performance source contract {main_strategy_model}.metrics_source_path",
        )
    )
    metric_aliases_raw = source_contract.get("metric_aliases")
    if not isinstance(metric_aliases_raw, dict) or not metric_aliases_raw:
        raise CurrentMainStrategyContractError(
            f"homepage top performance source contract {main_strategy_model}.metric_aliases must be a non-empty object"
        )
    metric_aliases = {
        _require_text(display_field, "homepage top performance metric alias display field"): _require_text(
            source_field,
            f"homepage top performance source contract {main_strategy_model}.metric_aliases.{display_field}",
        )
        for display_field, source_field in metric_aliases_raw.items()
    }

    resolved_metrics_path = _resolve_path(
        metrics_source_path_text,
        context=f"homepage top performance metrics source path for {main_strategy_model}",
        root=repo_root,
    )
    if require_file and (not resolved_metrics_path.exists() or not resolved_metrics_path.is_file()):
        raise CurrentMainStrategyContractError(
            f"Homepage top performance metrics source path is missing for {main_strategy_model}: {resolved_metrics_path}"
        )

    return {
        "main_strategy_model": main_strategy_model,
        "source_family": source_family,
        "semantic_role": semantic_role,
        "metrics_source_path": _path_for_app(resolved_metrics_path, root=repo_root),
        "metric_aliases": metric_aliases,
        "metrics_path": resolved_metrics_path,
    }


def validate_homepage_top_card_source_path(
    source_path: Any,
    contract: Mapping[str, Any],
    *,
    context: str,
) -> str:
    actual_source_path = _normalize_app_path_text(
        _require_text(source_path, f"{context} homepage top-card source path")
    )
    expected_source_path = _normalize_app_path_text(str(contract["canonical_metrics_source_path"]))
    if actual_source_path != expected_source_path:
        raise CurrentMainStrategyContractError(
            f"{context} homepage top-card metrics must use "
            "current_main_strategy_root_contract.canonical_metrics_source_path and must not "
            "use a separate compare/ranking artifact "
            f"(expected={expected_source_path} actual={actual_source_path})"
        )
    return actual_source_path


def resolve_validated_homepage_top_performance_source_contract(
    main_strategy_model: str,
    contract: Mapping[str, Any],
    *,
    root: Path | None = None,
    require_file: bool = True,
) -> dict[str, Any]:
    expected_model = _require_text(
        contract.get("main_strategy_model"),
        "current main strategy root contract.main_strategy_model",
    )
    source_contract = resolve_homepage_top_performance_source_contract(
        main_strategy_model,
        root=root,
        require_file=require_file,
    )
    if source_contract is None:
        raise CurrentMainStrategyContractError(
            "Homepage top-card source contract is missing for the current live/main strategy "
            f"model {expected_model}"
        )

    actual_model = _require_text(
        source_contract.get("main_strategy_model"),
        f"homepage top performance source contract {main_strategy_model}.main_strategy_model",
    )
    if actual_model != expected_model:
        raise CurrentMainStrategyContractError(
            "Homepage top-card source contract model diverged from the current live/main "
            f"strategy truth (expected={expected_model} actual={actual_model})"
        )

    validate_homepage_top_card_source_path(
        source_contract.get("metrics_source_path"),
        contract,
        context="Homepage top-card source contract blocked:",
    )
    return source_contract
