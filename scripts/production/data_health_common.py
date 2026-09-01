from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "production"
REPORT_PATH = DEFAULT_OUTPUT_DIR / "data_health_report.json"
QUALITY_PATH = DEFAULT_OUTPUT_DIR / "data_health_report.quality.json"
MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "data_health_report.manifest.json"

REPORT_ARTIFACT_TYPE = "data_health_report"
QUALITY_ARTIFACT_TYPE = "data_health_report_quality"
MANIFEST_ARTIFACT_TYPE = "data_health_report_manifest"
SCHEMA_VERSION = 1

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_STALE = "stale"
STATUS_INVALID_SCHEMA = "invalid_schema"
STATUS_UNAVAILABLE = "unavailable"
STATUS_FAILED = "failed"
STATUS_WARNING = "warning"

CRITICALITY_PRODUCTION = "production_critical"
CRITICALITY_EXECUTION = "execution_critical"
CRITICALITY_APP = "app_critical"
CRITICALITY_RESEARCH = "research_only"
CRITICALITY_INFO = "informational"

ACTION_ALLOW = "allow"
ACTION_WARN_ONLY = "warn_only"
ACTION_BLOCK_RESEARCH = "block_research_probe"
ACTION_BLOCK_APP = "block_app"
ACTION_BLOCK_EXECUTION = "block_execution"

STATUS_VALUES = {
    STATUS_OK,
    STATUS_MISSING,
    STATUS_STALE,
    STATUS_INVALID_SCHEMA,
    STATUS_UNAVAILABLE,
    STATUS_FAILED,
    STATUS_WARNING,
}
CRITICALITY_VALUES = {
    CRITICALITY_PRODUCTION,
    CRITICALITY_EXECUTION,
    CRITICALITY_APP,
    CRITICALITY_RESEARCH,
    CRITICALITY_INFO,
}
ACTION_VALUES = {
    ACTION_ALLOW,
    ACTION_WARN_ONLY,
    ACTION_BLOCK_RESEARCH,
    ACTION_BLOCK_APP,
    ACTION_BLOCK_EXECUTION,
}

RESEARCH_WARNING_RULE_SOURCE_IDS = {
    "research_btc_etf_flow_daily_panel_csv",
    "research_btc_etf_flow_daily_panel_quality",
    "research_btc_derivatives_daily_panel_csv",
    "research_btc_derivatives_daily_panel_quality",
}
ETF_FLOW_LIVE_STRATEGY_VERSION = "phase68g_etf_flow_impulse_early_risk_cooldown_15"
ETF_FLOW_DYNAMIC_SOURCE_IDS = {
    "research_btc_etf_flow_daily_panel_csv",
    "research_btc_etf_flow_daily_panel_quality",
}
CANONICAL_EXECUTION_SOURCE_IDS = frozenset(
    {
        "execution_latest_execution_intent",
        "execution_latest_real_order_gate_decision",
    }
)
CANONICAL_ACCOUNT_SNAPSHOT_PATH = (
    "outputs/execution/read_only/hyperliquid_account_snapshot.json"
)


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    source_type: str
    path: str
    kind: str
    criticality: str
    action_on_failure: str
    label_sk: str
    label_en: str
    required_keys: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    expected_mode: str | None = None
    max_allowed_lag_days: int | None = None
    env_name: str | None = None


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        source_id="production_current_strategy_snapshot",
        source_type="production_snapshot_json",
        path="outputs/production/current_strategy_snapshot.json",
        kind="json",
        criticality=CRITICALITY_PRODUCTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="produkčný snapshot stratégie",
        label_en="production strategy snapshot",
        required_keys=(
            "artifact_type",
            "strategy_id",
            "strategy_version",
            "closed_day",
            "validation",
            "execution_intent",
        ),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="production_current_strategy_timeseries",
        source_type="production_timeseries_csv",
        path="outputs/production/current_strategy_timeseries.csv",
        kind="csv",
        criticality=CRITICALITY_PRODUCTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="produkčný timeseries stratégie",
        label_en="production strategy timeseries",
        required_columns=("date", "strategy_id", "strategy_version", "authorized_equity", "source_validated"),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="production_current_strategy_diagnostics",
        source_type="production_diagnostics_json",
        path="outputs/production/current_strategy_diagnostics.json",
        kind="json",
        criticality=CRITICALITY_PRODUCTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="produkčné diagnostiky stratégie",
        label_en="production strategy diagnostics",
        required_keys=(
            "artifact_type",
            "strategy_id",
            "strategy_version",
            "closed_day",
            "current_data_health_summary",
            "validation",
        ),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="production_current_strategy_snapshot_quality",
        source_type="production_quality_json",
        path="outputs/production/current_strategy_snapshot.quality.json",
        kind="json",
        criticality=CRITICALITY_PRODUCTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="produkčný quality report snapshotu",
        label_en="production snapshot quality report",
        required_keys=("artifact_type", "status", "error_count", "warning_count", "checks", "validated_paths"),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="data_ohlcv_btcusdt_1d",
        source_type="ohlcv_csv",
        path="data/ohlcv/BTCUSDT_1d.csv",
        kind="csv",
        criticality=CRITICALITY_PRODUCTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="BTC denné OHLCV dáta",
        label_en="BTC daily OHLCV data",
        required_columns=("date", "open", "high", "low", "close", "volume"),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="execution_authority_latest_successful_snapshot",
        source_type="authority_snapshot_json",
        path="outputs/execution/authority/latest_successful_snapshot.json",
        kind="json",
        criticality=CRITICALITY_APP,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="posledný úspešný autoritatívny snapshot",
        label_en="latest successful authority snapshot",
        required_keys=(
            "artifact_type",
            "target_closed_day_utc",
            "latest_authoritative_attempt_status",
            "currentness_status",
            "generated_at_utc",
            "app_product_snapshot",
            "app_runtime_snapshot",
        ),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="execution_authority_latest_attempt_status",
        source_type="authority_status_json",
        path="outputs/execution/authority/latest_attempt_status.json",
        kind="json",
        criticality=CRITICALITY_EXECUTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="stav posledného autoritatívneho pokusu",
        label_en="latest authority attempt status",
        required_keys=(
            "artifact_type",
            "target_closed_day_utc",
            "latest_authoritative_attempt_status",
            "currentness_status",
            "generated_at_utc",
            "app_runtime_snapshot",
        ),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="execution_latest_execution_intent",
        source_type="execution_intent_json",
        path="outputs/execution/intents/latest_execution_intent.json",
        kind="json",
        criticality=CRITICALITY_EXECUTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="najnovší execution intent",
        label_en="latest execution intent",
        required_keys=(
            "generated_at_utc",
            "as_of_source",
            "strategy_model",
            "signal_id",
            "target_asset",
            "stale_signal",
            "guardrail_flags",
            "source_fingerprints",
        ),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="execution_latest_real_order_gate_decision",
        source_type="real_order_gate_json",
        path="outputs/execution/live_gate/latest_real_order_gate_decision.json",
        kind="json",
        criticality=CRITICALITY_EXECUTION,
        action_on_failure=ACTION_BLOCK_EXECUTION,
        label_sk="najnovšie real-order gate rozhodnutie",
        label_en="latest real-order gate decision",
        required_keys=(
            "generated_at_utc",
            "signal_id",
            "target_asset",
            "status",
            "checks",
            "production_signal_context",
            "source_fingerprints",
        ),
        expected_mode="latest_closed_utc_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="research_btc_etf_flow_daily_panel_csv",
        source_type="research_panel_csv",
        path="outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel/btc_etf_flow_daily_panel.csv",
        kind="csv",
        criticality=CRITICALITY_RESEARCH,
        action_on_failure=ACTION_BLOCK_RESEARCH,
        label_sk="ETF-flow research panel",
        label_en="ETF flow research panel",
        required_columns=("date", "us_trading_session_date", "aggregate_net_flow_usd", "daily_causal_ready", "probe_input_ready_flag"),
        expected_mode="active_strategy_closed_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="research_btc_etf_flow_daily_panel_quality",
        source_type="research_quality_json",
        path="outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel/btc_etf_flow_daily_panel.quality.json",
        kind="json",
        criticality=CRITICALITY_RESEARCH,
        action_on_failure=ACTION_BLOCK_RESEARCH,
        label_sk="ETF-flow research quality report",
        label_en="ETF flow research quality report",
        required_keys=("artifact_type", "status", "panel_end_causal_btc_utc_day", "ready_for_dev_only_probe", "verdict"),
        expected_mode="active_strategy_closed_day",
        max_allowed_lag_days=0,
    ),
    SourceSpec(
        source_id="research_btc_derivatives_daily_panel_csv",
        source_type="research_panel_csv",
        path="outputs/research_os/dev_only/non_authoritative_btc_derivatives_daily_panel/btc_derivatives_daily_panel.csv",
        kind="csv",
        criticality=CRITICALITY_RESEARCH,
        action_on_failure=ACTION_BLOCK_RESEARCH,
        label_sk="BTC derivatives research panel",
        label_en="BTC derivatives research panel",
        required_columns=("date", "funding_rate_daily", "basis_daily", "premium_daily", "open_interest_daily", "daily_causal_ready", "probe_input_ready_flag"),
        expected_mode="btc_last_day",
        max_allowed_lag_days=3,
    ),
    SourceSpec(
        source_id="research_btc_derivatives_daily_panel_quality",
        source_type="research_quality_json",
        path="outputs/research_os/dev_only/non_authoritative_btc_derivatives_daily_panel/btc_derivatives_daily_panel.quality.json",
        kind="json",
        criticality=CRITICALITY_RESEARCH,
        action_on_failure=ACTION_BLOCK_RESEARCH,
        label_sk="BTC derivatives research quality report",
        label_en="BTC derivatives research quality report",
        required_keys=("artifact_type", "status", "panel_end_date", "ready_for_dev_only_probe", "verdict"),
        expected_mode="btc_last_day",
        max_allowed_lag_days=3,
    ),
    SourceSpec(
        source_id="env_mrv1_btc_etf_flow_primary_provider",
        source_type="environment_variable",
        path="env:MRV1_BTC_ETF_FLOW_PRIMARY_PROVIDER",
        kind="env",
        criticality=CRITICALITY_INFO,
        action_on_failure=ACTION_WARN_ONLY,
        label_sk="env MRV1_BTC_ETF_FLOW_PRIMARY_PROVIDER",
        label_en="env MRV1_BTC_ETF_FLOW_PRIMARY_PROVIDER",
        env_name="MRV1_BTC_ETF_FLOW_PRIMARY_PROVIDER",
    ),
    SourceSpec(
        source_id="env_mrv1_coinglass_api_key",
        source_type="environment_variable",
        path="env:MRV1_COINGLASS_API_KEY",
        kind="env",
        criticality=CRITICALITY_INFO,
        action_on_failure=ACTION_WARN_ONLY,
        label_sk="env MRV1_COINGLASS_API_KEY",
        label_en="env MRV1_COINGLASS_API_KEY",
        env_name="MRV1_COINGLASS_API_KEY",
    ),
    SourceSpec(
        source_id="env_mrv1_sosovalue_api_key",
        source_type="environment_variable",
        path="env:MRV1_SOSOVALUE_API_KEY",
        kind="env",
        criticality=CRITICALITY_INFO,
        action_on_failure=ACTION_WARN_ONLY,
        label_sk="env MRV1_SOSOVALUE_API_KEY",
        label_en="env MRV1_SOSOVALUE_API_KEY",
        env_name="MRV1_SOSOVALUE_API_KEY",
    ),
)

SOURCE_INDEX = {spec.source_id: spec for spec in SOURCE_SPECS}


def _load_current_main_strategy_model(root: Path) -> str | None:
    project_truth_path = root / "source_of_truth" / "project_truth.json"
    export_contract_path = root / "source_of_truth" / "export_contract.json"
    try:
        project_truth = json.loads(project_truth_path.read_text(encoding="utf-8"))
        export_contract = json.loads(export_contract_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(project_truth, dict) or not isinstance(export_contract, dict):
        return None
    app_product_truth = project_truth.get("app_product_truth")
    app_export_contract = export_contract.get("app_export_contract")
    if not isinstance(app_product_truth, dict) or not isinstance(app_export_contract, dict):
        return None
    project_model = str(app_product_truth.get("main_strategy_model") or "").strip()
    export_model = str(app_export_contract.get("main_strategy_model") or "").strip()
    if project_model and export_model and project_model != export_model:
        return None
    return project_model or export_model or None


def _load_active_strategy_closed_day(root: Path) -> str | None:
    snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return parse_iso_day(payload.get("closed_day"))


def _load_effective_etf_panel_last_day(root: Path) -> str | None:
    snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("strategy_version") or "").strip() != ETF_FLOW_LIVE_STRATEGY_VERSION:
        return None
    materialization = nested_get(payload, "source_inputs", "etf_panel_materialization")
    if not isinstance(materialization, dict):
        return None

    materialized_closed_day = parse_iso_day(materialization.get("materialized_closed_day"))
    actual_latest_causal_day = parse_iso_day(
        materialization.get("actual_latest_causal_available_day")
    )
    actual_latest_source_day = parse_iso_day(
        materialization.get("actual_latest_source_session_day")
    )
    carry_forward_reason = str(materialization.get("carry_forward_reason") or "").strip()
    synthetic_source_rows_added = materialization.get("synthetic_source_rows_added")
    d_plus_1_source_contract_ok = materialization.get("d_plus_1_source_contract_ok")
    if not materialized_closed_day or not actual_latest_causal_day or not actual_latest_source_day:
        return None
    if carry_forward_reason != "no_intermediate_us_trading_sessions":
        return None
    if synthetic_source_rows_added != 0:
        return None
    if d_plus_1_source_contract_ok is not True:
        return None
    if iso_day_to_date(actual_latest_source_day) is None or iso_day_to_date(actual_latest_causal_day) is None:
        return None
    materialized_date = iso_day_to_date(materialized_closed_day)
    actual_causal_date = iso_day_to_date(actual_latest_causal_day)
    if materialized_date is None or actual_causal_date is None:
        return None
    if actual_causal_date > materialized_date:
        return None
    return materialized_closed_day


def _load_effective_btc_benchmark_last_day(root: Path) -> str | None:
    snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    source_inputs = payload.get("source_inputs")
    if not isinstance(source_inputs, dict):
        return None
    benchmark_source_mode = str(
        source_inputs.get("benchmark_source_mode")
        or nested_get(source_inputs, "files", "benchmark_ohlcv", "source_mode")
        or ""
    ).strip()
    if benchmark_source_mode != "durable_baseline_embedded_btc_close":
        return None
    candidate_values = (
        nested_get(source_inputs, "files", "benchmark_ohlcv", "last_date"),
        nested_get(source_inputs, "files", "benchmark_ohlcv", "materialized_closed_day"),
        nested_get(source_inputs, "files", "benchmark_ohlcv", "raw_source_closed_day"),
        nested_get(source_inputs, "durable_benchmark_close", "last_date"),
        nested_get(source_inputs, "durable_benchmark_close", "materialized_closed_day"),
        nested_get(source_inputs, "benchmark_materialization", "materialized_closed_day"),
    )
    for value in candidate_values:
        normalized = parse_iso_day(value)
        if normalized:
            return normalized
    return None


def resolve_effective_source_spec(spec: SourceSpec, *, context: dict[str, Any]) -> SourceSpec:
    main_strategy_model = str(context.get("main_strategy_model") or "").strip()
    if (
        main_strategy_model == ETF_FLOW_LIVE_STRATEGY_VERSION
        and spec.source_id in ETF_FLOW_DYNAMIC_SOURCE_IDS
    ):
        return replace(
            spec,
            criticality=CRITICALITY_PRODUCTION,
            action_on_failure=ACTION_BLOCK_EXECUTION,
        )
    return spec


def utc_now(reference_now: datetime | None = None) -> datetime:
    if reference_now is not None:
        if reference_now.tzinfo is None:
            return reference_now.replace(tzinfo=timezone.utc)
        return reference_now.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def utc_now_iso(reference_now: datetime | None = None) -> str:
    return utc_now(reference_now).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest_closed_utc_day(reference_now: datetime | None = None) -> str:
    current = utc_now(reference_now).date()
    return (current - timedelta(days=1)).isoformat()


def parse_reference_now(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_path.replace(path)


def parse_iso_day(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def iso_day_to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def format_file_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_path(path_value: str, *, root: Path) -> Path:
    raw = str(path_value).strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def parse_key_value_pairs(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Override must use source_id=value format: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Override source_id is empty: {item}")
        overrides[key] = value
    return overrides


def load_csv_meta(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            row_count = 0
            first_row: dict[str, Any] | None = None
            last_row: dict[str, Any] | None = None
            for row in reader:
                row_count += 1
                normalized_row = {str(key).strip(): value for key, value in row.items()}
                if first_row is None:
                    first_row = normalized_row
                last_row = normalized_row
    except Exception as exc:
        return None, str(exc)
    return {
        "columns": columns,
        "row_count": row_count,
        "first_row": first_row,
        "last_row": last_row,
    }, None


def companion_quality_path_for(source_id: str, *, root: Path, path_overrides: dict[str, str]) -> Path | None:
    mapping = {
        "research_btc_etf_flow_daily_panel_csv": "research_btc_etf_flow_daily_panel_quality",
        "research_btc_derivatives_daily_panel_csv": "research_btc_derivatives_daily_panel_quality",
    }
    quality_source_id = mapping.get(source_id)
    if not quality_source_id:
        return None
    quality_spec = SOURCE_INDEX[quality_source_id]
    override_path = path_overrides.get(quality_source_id, quality_spec.path)
    return normalize_path(override_path, root=root)


def resolve_actual_last_date_for_json(source_id: str, payload: dict[str, Any], *, root: Path, path_overrides: dict[str, str]) -> str | None:
    if source_id in {
        "production_current_strategy_snapshot",
        "production_current_strategy_diagnostics",
        "execution_authority_latest_successful_snapshot",
        "execution_authority_latest_attempt_status",
    }:
        return parse_iso_day(payload.get("closed_day") or payload.get("target_closed_day_utc"))
    if source_id == "production_current_strategy_snapshot_quality":
        snapshot_spec = SOURCE_INDEX["production_current_strategy_snapshot"]
        snapshot_path = normalize_path(path_overrides.get(snapshot_spec.source_id, snapshot_spec.path), root=root)
        if snapshot_path.exists():
            try:
                snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except Exception:
                return None
            if isinstance(snapshot_payload, dict):
                return parse_iso_day(snapshot_payload.get("closed_day"))
        return None
    if source_id == "execution_latest_execution_intent":
        return parse_iso_day(payload.get("as_of_source"))
    if source_id == "execution_latest_real_order_gate_decision":
        return parse_iso_day(nested_get(payload, "production_signal_context", "closed_day"))
    if source_id == "research_btc_etf_flow_daily_panel_quality":
        effective_etf_panel_last_day = _load_effective_etf_panel_last_day(root)
        if effective_etf_panel_last_day:
            return effective_etf_panel_last_day
        return parse_iso_day(payload.get("panel_end_causal_btc_utc_day"))
    if source_id == "research_btc_derivatives_daily_panel_quality":
        return parse_iso_day(payload.get("panel_end_date"))
    return None


def resolve_actual_last_date_for_csv(source_id: str, meta: dict[str, Any], *, root: Path) -> str | None:
    last_row = meta.get("last_row") or {}
    if source_id == "data_ohlcv_btcusdt_1d":
        effective_last_day = _load_effective_btc_benchmark_last_day(root)
        if effective_last_day:
            return effective_last_day
    if source_id == "research_btc_etf_flow_daily_panel_csv":
        effective_etf_panel_last_day = _load_effective_etf_panel_last_day(root)
        if effective_etf_panel_last_day:
            return effective_etf_panel_last_day
    if source_id in {
        "production_current_strategy_timeseries",
        "data_ohlcv_btcusdt_1d",
        "research_btc_etf_flow_daily_panel_csv",
        "research_btc_derivatives_daily_panel_csv",
    }:
        return parse_iso_day(last_row.get("date"))
    return None


def resolve_expected_last_date(spec: SourceSpec, context: dict[str, Any]) -> str | None:
    if spec.expected_mode == "latest_closed_utc_day":
        return context["latest_closed_utc_day"]
    if spec.expected_mode == "btc_last_day":
        return context.get("btc_last_day")
    if spec.expected_mode == "btc_last_day_plus_one":
        btc_last_day = iso_day_to_date(context.get("btc_last_day"))
        if btc_last_day is None:
            return None
        return (btc_last_day + timedelta(days=1)).isoformat()
    if spec.expected_mode == "active_strategy_closed_day":
        return context.get("active_strategy_closed_day") or context["latest_closed_utc_day"]
    return None


def derive_quality_status(payload: dict[str, Any]) -> str | None:
    status = str(payload.get("status") or "").strip().lower()
    return status or None


def derive_action(spec: SourceSpec, status: str) -> str:
    if status == STATUS_OK:
        return ACTION_ALLOW
    return spec.action_on_failure


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_effective_json_source(
    source_id: str,
    *,
    root: Path,
    path_overrides: dict[str, str],
) -> tuple[dict[str, Any] | None, Path]:
    spec = SOURCE_INDEX[source_id]
    path = normalize_path(path_overrides.get(source_id, spec.path), root=root)
    if not path.exists() or not path.is_file():
        return None, path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, path
    return (payload if isinstance(payload, dict) else None), path


def values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    try:
        return abs(float(expected) - float(actual)) <= 1e-9
    except (TypeError, ValueError):
        return str(expected or "").strip() == str(actual or "").strip()


def canonical_execution_alignment_errors(
    source_id: str,
    payload: dict[str, Any],
    *,
    root: Path,
    path_overrides: dict[str, str],
) -> list[str]:
    production_payload, production_path = load_effective_json_source(
        "production_current_strategy_snapshot",
        root=root,
        path_overrides=path_overrides,
    )
    if production_payload is None:
        return ["Production Core snapshot is unavailable for execution alignment."]
    production_intent = production_payload.get("execution_intent")
    if not isinstance(production_intent, dict):
        return ["Production Core execution_intent is unavailable for execution alignment."]

    expected_intent_fields = {
        "as_of_source": production_payload.get("closed_day"),
        "strategy_model": production_payload.get("strategy_version"),
        "signal_id": production_intent.get("signal_id"),
        "target_asset": production_intent.get("target_asset"),
        "target_size_pct": production_intent.get("target_exposure"),
        "stale_signal": production_intent.get("stale_signal"),
        "allow_live_order_candidate": production_intent.get(
            "allow_live_order_candidate"
        ),
    }
    errors: list[str] = []

    if source_id == "execution_latest_execution_intent":
        for field_name, expected_value in expected_intent_fields.items():
            if not values_match(expected_value, payload.get(field_name)):
                errors.append(
                    f"intent.{field_name} diverges from Production Core "
                    f"(expected={expected_value!r} actual={payload.get(field_name)!r})"
                )
        fingerprints = payload.get("source_fingerprints")
        fingerprints = fingerprints if isinstance(fingerprints, dict) else {}
        expected_hash = sha256_file(production_path)
        if fingerprints.get("production_snapshot_sha256") != expected_hash:
            errors.append("intent Production Core fingerprint does not match the canonical snapshot")
        return errors

    intent_payload, intent_path = load_effective_json_source(
        "execution_latest_execution_intent",
        root=root,
        path_overrides=path_overrides,
    )
    if intent_payload is None:
        return ["Canonical execution intent is unavailable for gate alignment."]

    direct_gate_fields = {
        "signal_id": expected_intent_fields["signal_id"],
        "target_asset": expected_intent_fields["target_asset"],
    }
    for field_name, expected_value in direct_gate_fields.items():
        if not values_match(expected_value, payload.get(field_name)):
            errors.append(
                f"gate.{field_name} diverges from Production Core "
                f"(expected={expected_value!r} actual={payload.get(field_name)!r})"
            )

    production_context = payload.get("production_signal_context")
    production_context = production_context if isinstance(production_context, dict) else {}
    expected_context_fields = {
        "strategy_version": production_payload.get("strategy_version"),
        "closed_day": production_payload.get("closed_day"),
        "signal_id": production_intent.get("signal_id"),
        "target_asset": production_intent.get("target_asset"),
        "target_exposure": production_intent.get("target_exposure"),
        "allow_live_order_candidate": production_intent.get(
            "allow_live_order_candidate"
        ),
    }
    for field_name, expected_value in expected_context_fields.items():
        if not values_match(expected_value, production_context.get(field_name)):
            errors.append(
                f"gate.production_signal_context.{field_name} diverges from Production Core"
            )

    checks = payload.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    required_alignment_checks = (
        "intent_day_matches_production_snapshot",
        "intent_signal_matches_production_snapshot",
        "intent_target_asset_matches_production_snapshot",
        "intent_target_exposure_matches_production_snapshot",
        "intent_stale_signal_matches_production_snapshot",
        "intent_strategy_model_matches_production_snapshot",
        "intent_allow_live_order_candidate_matches_snapshot",
    )
    for check_name in required_alignment_checks:
        if checks.get(check_name) is not True:
            errors.append(f"gate alignment check {check_name}=false_or_missing")

    source_paths = payload.get("source_paths")
    source_paths = source_paths if isinstance(source_paths, dict) else {}
    gate_intent_path = normalize_path(str(source_paths.get("intent_path") or ""), root=root)
    account_snapshot_path = normalize_path(CANONICAL_ACCOUNT_SNAPSHOT_PATH, root=root)
    gate_account_path = normalize_path(
        str(source_paths.get("account_snapshot_path") or ""), root=root
    )
    if gate_intent_path != intent_path.resolve():
        errors.append("gate intent source path is not the canonical execution intent")
    if gate_account_path != account_snapshot_path.resolve():
        errors.append("gate account source path is not the canonical read-only snapshot")

    fingerprints = payload.get("source_fingerprints")
    fingerprints = fingerprints if isinstance(fingerprints, dict) else {}
    expected_fingerprints = {
        "intent_sha256": sha256_file(intent_path),
        "production_snapshot_sha256": sha256_file(production_path),
        "account_snapshot_sha256": sha256_file(account_snapshot_path),
    }
    for field_name, expected_value in expected_fingerprints.items():
        if not expected_value or fingerprints.get(field_name) != expected_value:
            errors.append(f"gate {field_name} does not match its canonical source")
    return errors


def build_failure_reason_for_lag(expected_last_date: str, actual_last_date: str, max_allowed_lag_days: int, lag_days: int) -> str:
    return (
        "Stale source: expected_last_date="
        f"{expected_last_date} actual_last_date={actual_last_date} "
        f"max_allowed_lag_days={max_allowed_lag_days} lag_days={lag_days}"
    )


def apply_special_rules(
    *,
    spec: SourceSpec,
    payload: dict[str, Any] | None,
    source: dict[str, Any],
    root: Path,
    path_overrides: dict[str, str],
) -> tuple[str | None, str | None]:
    if payload is None:
        return None, None

    quality_status = source.get("quality_status")
    source_id = spec.source_id

    if source_id in {
        "production_current_strategy_snapshot",
        "production_current_strategy_diagnostics",
    }:
        validation_status = str(nested_get(payload, "validation", "status") or "").strip().lower()
        if validation_status != "passed":
            return STATUS_FAILED, f"Validation status is {validation_status or 'missing'}."

    if source_id == "production_current_strategy_snapshot_quality":
        if quality_status != "passed":
            return STATUS_FAILED, f"Quality status is {quality_status or 'missing'}."

    if source_id in {
        "execution_authority_latest_successful_snapshot",
        "execution_authority_latest_attempt_status",
    }:
        attempt_status = str(payload.get("latest_authoritative_attempt_status") or "").strip().lower()
        currentness_status = str(payload.get("currentness_status") or "").strip().lower()
        if attempt_status == "failed":
            return STATUS_FAILED, f"latest_authoritative_attempt_status={attempt_status}."
        if source_id == "execution_authority_latest_attempt_status" and attempt_status == "in_progress":
            intent_payload, _ = load_effective_json_source(
                "execution_latest_execution_intent",
                root=root,
                path_overrides=path_overrides,
            )
            guardrails = (
                intent_payload.get("guardrail_flags", {})
                if isinstance(intent_payload, dict)
                and isinstance(intent_payload.get("guardrail_flags"), dict)
                else {}
            )
            attempt_run_id = str(payload.get("run_id") or "").strip()
            intent_run_id = str(guardrails.get("same_run_authority_run_id") or "").strip()
            attempt_day = str(payload.get("target_closed_day_utc") or "").strip()
            intent_day = str(guardrails.get("same_run_authority_target_closed_day") or "").strip()
            if not bool(guardrails.get("same_run_authority_allowed")):
                return STATUS_FAILED, "In-progress authority is not bound to canonical intent same-run guardrails."
            if not attempt_run_id or attempt_run_id != intent_run_id:
                return STATUS_FAILED, "In-progress authority run_id diverges from canonical intent."
            if not attempt_day or attempt_day != intent_day:
                return STATUS_FAILED, "In-progress authority target day diverges from canonical intent."
            return STATUS_OK, None
        if currentness_status and currentness_status != "current":
            return STATUS_WARNING, f"currentness_status={currentness_status}."

    if source_id == "execution_latest_execution_intent":
        intent_status = str(payload.get("intent_status") or "").strip().lower()
        if intent_status == "blocked":
            blocked_reason = str(payload.get("blocked_reason") or "").strip()
            return STATUS_FAILED, blocked_reason or "Intent is blocked fail-closed."
        if bool(payload.get("stale_signal", False)):
            return STATUS_STALE, "Intent artifact reports stale_signal=true."
        if not bool(nested_get(payload, "guardrail_flags", "production_snapshot_validated")):
            return STATUS_FAILED, "Intent guardrail production_snapshot_validated=false."
        alignment_errors = canonical_execution_alignment_errors(
            source_id,
            payload,
            root=root,
            path_overrides=path_overrides,
        )
        if alignment_errors:
            return STATUS_FAILED, " | ".join(alignment_errors)

    if source_id == "execution_latest_real_order_gate_decision":
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        if not bool(checks.get("production_snapshot_validation_passed", True)):
            return STATUS_FAILED, "Gate check production_snapshot_validation_passed=false."
        if not bool(checks.get("intent_day_matches_production_snapshot", True)):
            return STATUS_FAILED, "Gate check intent_day_matches_production_snapshot=false."
        if not bool(checks.get("intent_signal_matches_production_snapshot", True)):
            return STATUS_FAILED, "Gate check intent_signal_matches_production_snapshot=false."
        if bool(checks.get("production_snapshot_stale_signal", False)):
            return STATUS_FAILED, "Gate check production_snapshot_stale_signal=true."
        alignment_errors = canonical_execution_alignment_errors(
            source_id,
            payload,
            root=root,
            path_overrides=path_overrides,
        )
        if alignment_errors:
            return STATUS_FAILED, " | ".join(alignment_errors)

    if source_id in {
        "research_btc_etf_flow_daily_panel_quality",
        "research_btc_derivatives_daily_panel_quality",
    }:
        ready = payload.get("ready_for_dev_only_probe")
        verdict = str(payload.get("verdict") or "").strip()
        if quality_status != "passed":
            return STATUS_FAILED, f"Quality status is {quality_status or 'missing'}."
        if ready is False:
            return STATUS_WARNING, f"Research verdict is {verdict or 'NOT_AVAILABLE'}."

    return None, None


def apply_research_csv_companion_rule(
    *,
    spec: SourceSpec,
    source: dict[str, Any],
    root: Path,
    path_overrides: dict[str, str],
) -> tuple[str | None, str | None]:
    if spec.source_id not in {
        "research_btc_etf_flow_daily_panel_csv",
        "research_btc_derivatives_daily_panel_csv",
    }:
        return None, None
    companion_path = companion_quality_path_for(spec.source_id, root=root, path_overrides=path_overrides)
    if companion_path is None or not companion_path.exists():
        return None, None
    try:
        companion_payload = json.loads(companion_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    if not isinstance(companion_payload, dict):
        return None, None
    ready = companion_payload.get("ready_for_dev_only_probe")
    verdict = str(companion_payload.get("verdict") or "").strip()
    if ready is False:
        return STATUS_WARNING, f"Research verdict is {verdict or 'NOT_AVAILABLE'}."
    return None, None


def build_user_messages(
    *,
    spec: SourceSpec,
    status: str,
    action: str,
    failure_reason: str | None,
    expected_last_date: str | None,
    actual_last_date: str | None,
) -> tuple[str, str]:
    expected_vs_actual = ""
    if expected_last_date or actual_last_date:
        expected_vs_actual = f" Očakávaný dátum {expected_last_date or 'n/a'}, skutočný {actual_last_date or 'n/a'}."
    expected_vs_actual_en = ""
    if expected_last_date or actual_last_date:
        expected_vs_actual_en = f" Expected date {expected_last_date or 'n/a'}, actual {actual_last_date or 'n/a'}."

    if status == STATUS_OK:
        return (
            f"Zdroj {spec.label_sk} je v poriadku.",
            f"Source {spec.label_en} is healthy.",
        )

    if spec.criticality == CRITICALITY_RESEARCH:
        return (
            f"Výskumný zdroj {spec.label_sk} je nedostupný alebo blokovaný. Produkcia tým nie je ovplyvnená, ale príslušný research probe je zablokovaný.{expected_vs_actual}",
            f"Research source {spec.label_en} is unavailable or blocked. Production is unaffected, but the related research probe is blocked.{expected_vs_actual_en}",
        )

    if spec.criticality == CRITICALITY_INFO:
        return (
            f"Pomocný zdroj {spec.label_sk} nie je dostupný. Produkcia tým nie je ovplyvnená.",
            f"Auxiliary source {spec.label_en} is unavailable. Production is unaffected.",
        )

    if action in {ACTION_BLOCK_EXECUTION, ACTION_BLOCK_APP}:
        return (
            f"Kritický zdroj {spec.label_sk} zlyhal. Aplikácia a execution ostávajú fail-closed.{expected_vs_actual}",
            f"Critical source {spec.label_en} failed. The app and execution remain fail-closed.{expected_vs_actual_en}",
        )

    detail = f" Dôvod: {failure_reason}" if failure_reason else ""
    detail_en = f" Reason: {failure_reason}" if failure_reason else ""
    return (
        f"Zdroj {spec.label_sk} vyžaduje pozornosť.{detail}{expected_vs_actual}",
        f"Source {spec.label_en} needs attention.{detail_en}{expected_vs_actual_en}",
    )


def evaluate_source(
    *,
    spec: SourceSpec,
    root: Path,
    reference_now: datetime | None,
    context: dict[str, Any],
    path_overrides: dict[str, str],
    env_overrides: dict[str, str],
) -> dict[str, Any]:
    path_text = path_overrides.get(spec.source_id, spec.path)
    source: dict[str, Any] = {
        "source_id": spec.source_id,
        "source_type": spec.source_type,
        "path": path_text,
        "exists": False,
        "status": STATUS_OK,
        "criticality": spec.criticality,
        "expected_last_date": resolve_expected_last_date(spec, context),
        "actual_last_date": None,
        "max_allowed_lag_days": spec.max_allowed_lag_days,
        "last_modified_utc": None,
        "row_count": None,
        "quality_status": None,
        "failure_reason": None,
        "user_message_sk": "",
        "user_message_en": "",
        "action": ACTION_ALLOW,
    }

    if spec.kind == "env":
        env_name = spec.env_name or path_text.removeprefix("env:")
        env_value = env_overrides.get(spec.source_id)
        if env_value is None and spec.source_id not in env_overrides:
            env_value = os.environ.get(env_name, "")
        exists = bool(str(env_value or "").strip())
        source["exists"] = exists
        source["last_modified_utc"] = None
        if not exists:
            source["status"] = STATUS_UNAVAILABLE
            source["failure_reason"] = f"Missing environment variable {env_name}."
        else:
            source["quality_status"] = "present"
        source["action"] = derive_action(spec, source["status"])
        source["user_message_sk"], source["user_message_en"] = build_user_messages(
            spec=spec,
            status=source["status"],
            action=source["action"],
            failure_reason=source["failure_reason"],
            expected_last_date=source["expected_last_date"],
            actual_last_date=source["actual_last_date"],
        )
        return source

    resolved_path = normalize_path(path_text, root=root)
    source["path"] = str(resolved_path)
    source["exists"] = resolved_path.exists()
    source["last_modified_utc"] = format_file_mtime(resolved_path)

    if not resolved_path.exists():
        source["status"] = STATUS_MISSING
        source["failure_reason"] = f"Missing required path {resolved_path}"
    else:
        payload: dict[str, Any] | None = None
        csv_meta: dict[str, Any] | None = None
        if spec.kind == "json":
            try:
                loaded = json.loads(resolved_path.read_text(encoding="utf-8"))
            except Exception as exc:
                source["status"] = STATUS_INVALID_SCHEMA
                source["failure_reason"] = f"JSON parse failed: {exc}"
            else:
                if not isinstance(loaded, dict):
                    source["status"] = STATUS_INVALID_SCHEMA
                    source["failure_reason"] = "Top-level JSON payload is not an object."
                else:
                    payload = loaded
                    missing_keys = [key for key in spec.required_keys if key not in payload]
                    if (
                        spec.source_id == "execution_authority_latest_attempt_status"
                        and str(payload.get("latest_authoritative_attempt_status") or "").strip().lower()
                        == "in_progress"
                    ):
                        missing_keys = [key for key in missing_keys if key != "app_runtime_snapshot"]
                    if missing_keys:
                        source["status"] = STATUS_INVALID_SCHEMA
                        source["failure_reason"] = "Missing required JSON keys: " + ", ".join(missing_keys)
                    else:
                        source["actual_last_date"] = resolve_actual_last_date_for_json(
                            spec.source_id,
                            payload,
                            root=root,
                            path_overrides=path_overrides,
                        )
                        source["quality_status"] = derive_quality_status(payload)
        elif spec.kind == "csv":
            csv_meta, csv_error = load_csv_meta(resolved_path)
            if csv_error:
                source["status"] = STATUS_INVALID_SCHEMA
                source["failure_reason"] = f"CSV read failed: {csv_error}"
            elif not csv_meta:
                source["status"] = STATUS_INVALID_SCHEMA
                source["failure_reason"] = "CSV metadata could not be derived."
            else:
                source["row_count"] = int(csv_meta.get("row_count") or 0)
                columns = set(csv_meta.get("columns") or [])
                missing_columns = [column for column in spec.required_columns if column not in columns]
                if source["row_count"] <= 0:
                    source["status"] = STATUS_INVALID_SCHEMA
                    source["failure_reason"] = "CSV has no data rows."
                elif missing_columns:
                    source["status"] = STATUS_INVALID_SCHEMA
                    source["failure_reason"] = "Missing required CSV columns: " + ", ".join(missing_columns)
                else:
                    source["actual_last_date"] = resolve_actual_last_date_for_csv(
                        spec.source_id,
                        csv_meta,
                        root=root,
                    )

        if source["status"] == STATUS_OK and source["expected_last_date"] and source["actual_last_date"] and spec.max_allowed_lag_days is not None:
            expected_day = iso_day_to_date(source["expected_last_date"])
            actual_day = iso_day_to_date(source["actual_last_date"])
            if expected_day is None or actual_day is None:
                source["status"] = STATUS_INVALID_SCHEMA
                source["failure_reason"] = "Could not normalize expected/actual last date."
            else:
                lag_days = (expected_day - actual_day).days
                if lag_days > spec.max_allowed_lag_days:
                    source["status"] = STATUS_STALE
                    source["failure_reason"] = build_failure_reason_for_lag(
                        source["expected_last_date"],
                        source["actual_last_date"],
                        spec.max_allowed_lag_days,
                        lag_days,
                    )

        if source["status"] == STATUS_OK and source["expected_last_date"] and source["actual_last_date"] is None:
            source["status"] = STATUS_INVALID_SCHEMA
            source["failure_reason"] = "Expected an actual_last_date but none could be extracted."

        special_status, special_reason = apply_special_rules(
            spec=spec,
            payload=payload,
            source=source,
            root=root,
            path_overrides=path_overrides,
        )
        if special_status in {STATUS_FAILED, STATUS_INVALID_SCHEMA, STATUS_UNAVAILABLE, STATUS_MISSING}:
            source["status"] = special_status
            source["failure_reason"] = special_reason
        elif source["status"] == STATUS_OK and special_status is not None:
            source["status"] = special_status
            source["failure_reason"] = special_reason

        if spec.kind == "csv":
            special_status, special_reason = apply_research_csv_companion_rule(
                spec=spec,
                source=source,
                root=root,
                path_overrides=path_overrides,
            )
            if source["status"] == STATUS_OK and special_status is not None:
                source["status"] = special_status
                source["failure_reason"] = special_reason

    source["action"] = derive_action(spec, source["status"])
    source["user_message_sk"], source["user_message_en"] = build_user_messages(
        spec=spec,
        status=source["status"],
        action=source["action"],
        failure_reason=source["failure_reason"],
        expected_last_date=source["expected_last_date"],
        actual_last_date=source["actual_last_date"],
    )
    return source


def build_context(
    *,
    root: Path,
    reference_now: datetime | None,
    path_overrides: dict[str, str],
) -> dict[str, Any]:
    btc_spec = SOURCE_INDEX["data_ohlcv_btcusdt_1d"]
    btc_path = normalize_path(path_overrides.get(btc_spec.source_id, btc_spec.path), root=root)
    btc_last_day: str | None = None
    if btc_path.exists():
        btc_meta, _btc_error = load_csv_meta(btc_path)
        if btc_meta:
            btc_last_day = resolve_actual_last_date_for_csv(
                btc_spec.source_id,
                btc_meta,
                root=root,
            )
    return {
        "latest_closed_utc_day": latest_closed_utc_day(reference_now),
        "btc_last_day": btc_last_day,
        "active_strategy_closed_day": _load_active_strategy_closed_day(root),
        "main_strategy_model": _load_current_main_strategy_model(root),
    }


def summarize_sources(sources: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in sorted(STATUS_VALUES)}
    action_counts = {action: 0 for action in sorted(ACTION_VALUES)}
    for source in sources:
        status_counts[source["status"]] = status_counts.get(source["status"], 0) + 1
        action_counts[source["action"]] = action_counts.get(source["action"], 0) + 1

    app_blocking_source_ids = [
        source["source_id"]
        for source in sources
        if source["status"] != STATUS_OK
        and source["criticality"] in {CRITICALITY_PRODUCTION, CRITICALITY_APP}
    ]
    execution_blocking_source_ids = [
        source["source_id"]
        for source in sources
        if source["status"] != STATUS_OK
        and source["action"] == ACTION_BLOCK_EXECUTION
    ]
    research_blocked_source_ids = [
        source["source_id"]
        for source in sources
        if source["status"] != STATUS_OK
        and source["action"] == ACTION_BLOCK_RESEARCH
    ]
    warning_source_ids = [
        source["source_id"]
        for source in sources
        if source["status"] in {STATUS_WARNING, STATUS_UNAVAILABLE}
        or (source["status"] != STATUS_OK and source["criticality"] == CRITICALITY_INFO)
    ]

    block_app = bool(app_blocking_source_ids)
    block_execution = bool(execution_blocking_source_ids)
    overall_status = STATUS_OK
    if block_app or block_execution:
        overall_status = STATUS_FAILED
    elif research_blocked_source_ids or warning_source_ids:
        overall_status = STATUS_WARNING

    if block_app or block_execution:
        app_status = "blocked"
        execution_status = "blocked"
    else:
        app_status = "ok"
        execution_status = "ok"

    research_status = "warning" if research_blocked_source_ids else "ok"

    messages_sk = [source["user_message_sk"] for source in sources if source["status"] != STATUS_OK]
    messages_en = [source["user_message_en"] for source in sources if source["status"] != STATUS_OK]
    return {
        "overall_status": overall_status,
        "app_status": app_status,
        "execution_status": execution_status,
        "research_status": research_status,
        "block_app": block_app,
        "block_execution": block_execution,
        "status_counts": status_counts,
        "action_counts": action_counts,
        "app_blocking_source_ids": app_blocking_source_ids,
        "execution_blocking_source_ids": execution_blocking_source_ids,
        "research_blocked_source_ids": research_blocked_source_ids,
        "warning_source_ids": warning_source_ids,
        "user_messages_sk": messages_sk,
        "user_messages_en": messages_en,
    }


def build_report_bundle(
    *,
    root: Path = ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    reference_now: datetime | None = None,
    path_overrides: dict[str, str] | None = None,
    env_overrides: dict[str, str] | None = None,
    write_outputs: bool = True,
) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_output_dir = output_dir.resolve()
    path_override_map = dict(path_overrides or {})
    env_override_map = dict(env_overrides or {})
    forbidden_execution_overrides = sorted(
        CANONICAL_EXECUTION_SOURCE_IDS.intersection(path_override_map)
    )
    if forbidden_execution_overrides:
        raise ValueError(
            "Data health execution sources must use canonical paths; forbidden path overrides: "
            + ", ".join(forbidden_execution_overrides)
        )

    context = build_context(
        root=resolved_root,
        reference_now=reference_now,
        path_overrides=path_override_map,
    )
    sources = [
        evaluate_source(
            spec=resolve_effective_source_spec(spec, context=context),
            root=resolved_root,
            reference_now=reference_now,
            context=context,
            path_overrides=path_override_map,
            env_overrides=env_override_map,
        )
        for spec in SOURCE_SPECS
    ]
    summary = summarize_sources(sources)
    generated_at_utc = utc_now_iso(reference_now)

    report = {
        "artifact_type": REPORT_ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "reference_closed_day_utc": context["latest_closed_utc_day"],
        "overall_status": summary["overall_status"],
        "summary": summary,
        "sources": sources,
    }

    quality_errors: list[str] = []
    source_ids = [source["source_id"] for source in sources]
    if len(source_ids) != len(set(source_ids)):
        quality_errors.append("Duplicate source_id detected in data health report.")
    invalid_status_ids = [source["source_id"] for source in sources if source["status"] not in STATUS_VALUES]
    if invalid_status_ids:
        quality_errors.append("Invalid source statuses: " + ", ".join(invalid_status_ids))
    invalid_action_ids = [source["source_id"] for source in sources if source["action"] not in ACTION_VALUES]
    if invalid_action_ids:
        quality_errors.append("Invalid source actions: " + ", ".join(invalid_action_ids))

    quality = {
        "artifact_type": QUALITY_ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "status": "passed" if not quality_errors else "failed",
        "error_count": len(quality_errors),
        "warning_count": 0,
        "errors": quality_errors,
        "warnings": [],
        "checks": {
            "source_id_unique": len(source_ids) == len(set(source_ids)),
            "valid_status_enum": not invalid_status_ids,
            "valid_action_enum": not invalid_action_ids,
            "production_and_execution_fail_closed": bool(summary["block_execution"]) if summary["overall_status"] != STATUS_OK else True,
        },
        "validated_paths": {
            "report_path": str((resolved_output_dir / REPORT_PATH.name).resolve()),
        },
    }

    manifest = {
        "artifact_type": MANIFEST_ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "script_path": str(Path(__file__).resolve()),
        "root_path": str(resolved_root),
        "output_paths": {
            "report_path": str((resolved_output_dir / REPORT_PATH.name).resolve()),
            "quality_path": str((resolved_output_dir / QUALITY_PATH.name).resolve()),
            "manifest_path": str((resolved_output_dir / MANIFEST_PATH.name).resolve()),
        },
        "source_ids": source_ids,
        "reference_closed_day_utc": context["latest_closed_utc_day"],
        "context": context,
        "path_overrides": path_override_map,
        "env_override_source_ids": sorted(env_override_map.keys()),
    }

    if write_outputs:
        atomic_write_json(resolved_output_dir / REPORT_PATH.name, report)
        atomic_write_json(resolved_output_dir / QUALITY_PATH.name, quality)
        atomic_write_json(resolved_output_dir / MANIFEST_PATH.name, manifest)

    return {
        "report": report,
        "quality": quality,
        "manifest": manifest,
    }


def load_report_bundle(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    report = json.loads((output_dir / REPORT_PATH.name).read_text(encoding="utf-8"))
    quality = json.loads((output_dir / QUALITY_PATH.name).read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / MANIFEST_PATH.name).read_text(encoding="utf-8"))
    return {
        "report": report,
        "quality": quality,
        "manifest": manifest,
    }


def execution_blocking_sources(
    report: dict[str, Any],
    *,
    exclude_source_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = exclude_source_ids or set()
    sources = report.get("sources") if isinstance(report.get("sources"), list) else []
    return [
        source
        for source in sources
        if isinstance(source, dict)
        and source.get("source_id") not in excluded
        and source.get("status") != STATUS_OK
        and source.get("action") == ACTION_BLOCK_EXECUTION
    ]


def app_blocking_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    sources = report.get("sources") if isinstance(report.get("sources"), list) else []
    return [
        source
        for source in sources
        if isinstance(source, dict)
        and source.get("status") != STATUS_OK
        and source.get("criticality") in {CRITICALITY_PRODUCTION, CRITICALITY_APP}
    ]


def research_warning_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    sources = report.get("sources") if isinstance(report.get("sources"), list) else []
    return [
        source
        for source in sources
        if isinstance(source, dict)
        and source.get("status") != STATUS_OK
        and (
            source.get("criticality") == CRITICALITY_RESEARCH
            or source.get("source_id") in RESEARCH_WARNING_RULE_SOURCE_IDS
        )
    ]


def informational_warning_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    sources = report.get("sources") if isinstance(report.get("sources"), list) else []
    return [
        source
        for source in sources
        if isinstance(source, dict)
        and source.get("status") != STATUS_OK
        and source.get("criticality") == CRITICALITY_INFO
    ]


def _unique_sources_by_id(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_sources: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "").strip()
        if not source_id or source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        unique_sources.append(source)
    return unique_sources


def homepage_data_health_view(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}

    app_blocking = app_blocking_sources(report)
    excluded_source_ids = {
        str(source.get("source_id") or "").strip()
        for source in app_blocking
        if isinstance(source, dict)
    }
    execution_blocking = execution_blocking_sources(
        report,
        exclude_source_ids=excluded_source_ids,
    )
    critical_sources = _unique_sources_by_id([*app_blocking, *execution_blocking])
    research_sources = research_warning_sources(report)
    informational_sources = informational_warning_sources(report)

    block_app = summary.get("block_app") is True or bool(app_blocking)
    block_execution = summary.get("block_execution") is True or bool(critical_sources)
    show_primary_alert = block_app or block_execution or bool(critical_sources)

    return {
        "block_app": block_app,
        "block_execution": block_execution,
        "show_primary_alert": show_primary_alert,
        "show_ok_status": not show_primary_alert,
        "show_secondary_note": (not show_primary_alert)
        and bool(research_sources or informational_sources),
        "critical_sources": critical_sources,
        "research_sources": research_sources,
        "informational_sources": informational_sources,
        "critical_source_ids": [
            str(source.get("source_id") or "").strip()
            for source in critical_sources
            if isinstance(source, dict)
        ],
        "research_source_ids": [
            str(source.get("source_id") or "").strip()
            for source in research_sources
            if isinstance(source, dict)
        ],
        "informational_source_ids": [
            str(source.get("source_id") or "").strip()
            for source in informational_sources
            if isinstance(source, dict)
        ],
    }
