from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
APP_EXPORTS_DIR = OUTPUTS_DIR / "app_exports"
FRESHNESS_DIR = OUTPUTS_DIR / "freshness"
LOGS_DIR = OUTPUTS_DIR / "logs"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"
PROJECT_TRUTH_PATH = SOURCE_OF_TRUTH_DIR / "project_truth.json"

REPORT_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_report.json"
MANIFEST_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_manifest.json"
QUALITY_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_quality.json"
LOG_PATH = LOGS_DIR / "materialize_execution_app_exports.log"

REQUIRED_ARTIFACT_KEYS = [
    "phase67j_winner_paper",
    "phase67j_live_status",
    "phase66g_core_paper",
    "phase66g_live_status",
    "app_freshness_report",
]

REQUIRED_APP_LIVE_MODE_FIELDS = [
    "live_truth_mode",
    "execution_profile",
    "leverage_mode",
    "deployment_candidate_label",
    "fallback_profile_label",
    "approval_gate_status",
]

PHASE68I_SUMMARY_OUTPUT_PATH = APP_EXPORTS_DIR / "phase68i_dynamic_ladder_candidate_summary.csv"
PHASE68I_PAPER_INPUT_PATH = APP_EXPORTS_DIR / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68H_SUMMARY_INPUT_PATH = ROOT / "outputs" / "phase68h_dynamic_leverage_ladder_candidate" / "phase68h_dynamic_leverage_ladder_summary.csv"
PHASE68H_DYNAMIC_PAPER_INPUT_PATH = ROOT / "outputs" / "phase68h_dynamic_leverage_ladder_candidate" / "papers" / "phase68h_dynamic_ladder_candidate_paper.csv"


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


def ensure_dirs() -> None:
    APP_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FRESHNESS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "refresh_pipeline").mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def find_existing_source(artifact_entry: dict[str, Any]) -> Path | None:
    legacy_aliases = artifact_entry.get("legacy_aliases", [])
    if not isinstance(legacy_aliases, list):
        return None

    for raw_path in legacy_aliases:
        try:
            candidate = Path(raw_path)
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def read_single_csv_row(path: Path) -> dict[str, str]:
    header, rows = read_csv_rows(path)
    if not header:
        fail(f"CSV has no header: {path}")
    if not rows:
        fail(f"CSV has no data rows: {path}")
    return rows[0]


def phase66g_live_status_refresh_tuple(path: Path) -> tuple[str, str]:
    row = read_single_csv_row(path)
    return (
        str(row.get("latest_available_date", "")).strip(),
        str(row.get("trend_calc_date", "")).strip(),
    )


def should_refresh_phase66g_live_status(source_path: Path, canonical_path: Path) -> bool:
    if not canonical_path.exists() or not canonical_path.is_file():
        return True

    source_tuple = phase66g_live_status_refresh_tuple(source_path)
    canonical_tuple = phase66g_live_status_refresh_tuple(canonical_path)
    return source_tuple > canonical_tuple


def safe_stat(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def load_app_live_mode_contract() -> dict[str, str]:
    truth = read_json(PROJECT_TRUTH_PATH)
    contract_root = truth.get("app_live_mode_contract")
    if not isinstance(contract_root, dict):
        fail("source_of_truth/project_truth.json missing app_live_mode_contract")

    current_contract = contract_root.get("current")
    if not isinstance(current_contract, dict):
        fail("source_of_truth/project_truth.json missing app_live_mode_contract.current")

    normalized: dict[str, str] = {}
    for field in REQUIRED_APP_LIVE_MODE_FIELDS:
        value = str(current_contract.get(field, "")).strip()
        if not value:
            fail(f"app_live_mode_contract.current missing required field: {field}")
        normalized[field] = value
    return normalized


def copy_plain_artifact(source_path: Path, canonical_path: Path) -> dict[str, Any]:
    shutil.copy2(source_path, canonical_path)
    return {
        "status": "copied_from_legacy_alias",
        "source_path": str(source_path),
        "source_info": safe_stat(source_path),
        "canonical_info": safe_stat(canonical_path),
    }


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


def parse_iso_date_required(raw: str | None, context: str) -> str:
    text = str(raw or "").strip()
    if not text:
        fail(f"Missing required ISO date in {context}")
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        fail(f"Invalid ISO date in {context}: {text}")
    raise RuntimeError("unreachable")


def newer_phase66g_live_status_available(
    source_path: Path,
    canonical_path: Path,
) -> dict[str, str] | None:
    _, source_rows = read_csv_rows(source_path)
    _, canonical_rows = read_csv_rows(canonical_path)

    if len(source_rows) != 1:
        fail(f"Expected exactly 1 row in phase66g live status source, got {len(source_rows)}")
    if len(canonical_rows) != 1:
        fail(f"Expected exactly 1 row in phase66g live status canonical, got {len(canonical_rows)}")

    source_date = parse_iso_date_required(
        source_rows[0].get("latest_available_date"),
        f"{source_path} latest_available_date",
    )
    canonical_date = parse_iso_date_required(
        canonical_rows[0].get("latest_available_date"),
        f"{canonical_path} latest_available_date",
    )

    if source_date <= canonical_date:
        return None

    return {
        "source_latest_available_date": source_date,
        "canonical_latest_available_date": canonical_date,
    }


def parse_float_required(row: dict[str, str], key: str) -> float:
    raw = str(row.get(key, "")).strip()
    if raw == "":
        fail(f"Missing required numeric field '{key}' in summary source row")
    try:
        return float(raw)
    except Exception:
        fail(f"Invalid numeric field '{key}' in summary source row: {raw}")
    raise RuntimeError("unreachable")


def parse_float_maybe(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        return None


def annualized_sharpe_from_daily_returns(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    var = sum((x - mean_ret) ** 2 for x in daily_returns) / (len(daily_returns) - 1)
    if var <= 0:
        return None
    std = var ** 0.5
    if std == 0:
        return None
    return (mean_ret / std) * (365 ** 0.5)


def annualized_sortino_from_daily_returns(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    downside = [x for x in daily_returns if x < 0]
    if len(downside) < 2:
        return None
    downside_mean = sum(downside) / len(downside)
    downside_var = sum((x - downside_mean) ** 2 for x in downside) / (len(downside) - 1)
    if downside_var <= 0:
        return None
    downside_std = downside_var ** 0.5
    if downside_std == 0:
        return None
    return (mean_ret / downside_std) * (365 ** 0.5)


def format_float(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{decimals}f}"


def build_phase68i_summary_export() -> dict[str, Any]:
    summary_header, summary_rows = read_csv_rows(PHASE68H_SUMMARY_INPUT_PATH)
    if not summary_rows:
        fail(f"No rows found in {PHASE68H_SUMMARY_INPUT_PATH}")

    target_row = None
    for row in summary_rows:
        if str(row.get("model", "")).strip() == "phase68h_dynamic_ladder_candidate":
            target_row = row
            break

    if target_row is None:
        fail("Could not find phase68h_dynamic_ladder_candidate row in phase68h summary source")

    if not PHASE68H_DYNAMIC_PAPER_INPUT_PATH.exists():
        fail(f"Missing required phase68h dynamic paper: {PHASE68H_DYNAMIC_PAPER_INPUT_PATH}")

    try:
        shutil.copy2(PHASE68H_DYNAMIC_PAPER_INPUT_PATH, PHASE68I_PAPER_INPUT_PATH)
    except Exception as e:
        fail(f"Failed refreshing phase68i canonical paper from phase68h producer output: {e}")

    paper_header, paper_rows = read_csv_rows(PHASE68I_PAPER_INPUT_PATH)
    if not paper_rows:
        fail(f"No rows found in {PHASE68I_PAPER_INPUT_PATH}")

    if "date" not in paper_header and "ts" not in paper_header:
        fail("phase68i paper export missing date/ts column")

    if "equity_curve" not in paper_header and "equity" not in paper_header:
        fail("phase68i paper export missing equity-compatible column")

    if "realistic_ret" not in paper_header:
        fail("phase68i paper export missing realistic_ret required for sharpe/sortino")
    if "portfolio_held_asset" not in paper_header:
        fail("phase68i paper export missing portfolio_held_asset required for switch/cash/btc metrics")

    returns: list[float] = []
    held_assets: list[str] = []
    for row in paper_rows:
        ret = parse_float_maybe(row.get("realistic_ret"))
        if ret is None:
            fail("phase68i paper export contains empty/invalid realistic_ret")
        returns.append(ret)
        held_assets.append(str(row.get("portfolio_held_asset", "")).strip().upper())

    sharpe = annualized_sharpe_from_daily_returns(returns)
    sortino = annualized_sortino_from_daily_returns(returns)
    if sharpe is None:
        fail("Could not compute sharpe reliably from realistic_ret")
    if sortino is None:
        fail("Could not compute sortino reliably from realistic_ret")

    switch_count = 0
    prev_asset = None
    for asset in held_assets:
        if prev_asset is None:
            prev_asset = asset
            continue
        if asset != prev_asset:
            switch_count += 1
        prev_asset = asset

    total_days = len(held_assets)
    if total_days == 0:
        fail("No held asset rows found in phase68i paper export")

    cash_days = sum(1 for asset in held_assets if asset in {"CASH", "BASELINE_RISK"})
    btc_days = sum(1 for asset in held_assets if asset == "BTC")

    cash_days_pct = (cash_days / total_days) * 100.0
    btc_days_pct = (btc_days / total_days) * 100.0

    output_header = [
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
    ]

    output_row = {
        "model": "phase68i_dynamic_ladder_candidate",
        "cagr_pct": str(parse_float_required(target_row, "cagr_pct")),
        "max_drawdown_pct": str(parse_float_required(target_row, "max_drawdown_pct")),
        "since2023_cagr_pct": str(parse_float_required(target_row, "since2023_cagr_pct")),
        "since2025_cagr_pct": str(parse_float_required(target_row, "since2025_cagr_pct")),
        "sharpe": format_float(sharpe, 4),
        "sortino": format_float(sortino, 4),
        "switch_count": str(switch_count),
        "cash_days_pct": format_float(cash_days_pct, 4),
        "btc_days_pct": format_float(btc_days_pct, 4),
    }

    try:
        with PHASE68I_SUMMARY_OUTPUT_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_header)
            writer.writeheader()
            writer.writerow(output_row)
    except Exception as e:
        fail(f"Failed writing phase68i summary export {PHASE68I_SUMMARY_OUTPUT_PATH}: {e}")

    return {
        "status": "phase68i_summary_export_written",
        "summary_source_path": str(PHASE68H_SUMMARY_INPUT_PATH),
        "paper_source_path": str(PHASE68I_PAPER_INPUT_PATH),
        "paper_refresh_source_path": str(PHASE68H_DYNAMIC_PAPER_INPUT_PATH),
        "output_path": str(PHASE68I_SUMMARY_OUTPUT_PATH),
        "output_info": safe_stat(PHASE68I_SUMMARY_OUTPUT_PATH),
        "computed_fields": [
            "sharpe",
            "sortino",
            "switch_count",
            "cash_days_pct",
            "btc_days_pct",
        ],
        "copied_fields_from_summary_source": [
            "cagr_pct",
            "max_drawdown_pct",
            "since2023_cagr_pct",
            "since2025_cagr_pct",
        ],
    }


def materialize_phase67j_live_status_with_contract(
    source_path: Path,
    canonical_path: Path,
    app_live_mode_contract: dict[str, str],
) -> dict[str, Any]:
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            source_header = reader.fieldnames or []
            rows = list(reader)
    except Exception as e:
        fail(f"Failed reading source CSV {source_path}: {e}")

    if len(rows) != 1:
        fail(f"Expected exactly 1 row in phase67j live status source, got {len(rows)}")

    row = dict(rows[0])
    output_header = list(source_header)
    for field in REQUIRED_APP_LIVE_MODE_FIELDS:
        if field not in output_header:
            output_header.append(field)
        row[field] = app_live_mode_contract[field]

    try:
        with canonical_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_header)
            writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        fail(f"Failed writing canonical CSV {canonical_path}: {e}")

    return {
        "status": "materialized_with_app_live_mode_contract",
        "source_path": str(source_path),
        "source_info": safe_stat(source_path),
        "canonical_info": safe_stat(canonical_path),
        "added_fields": REQUIRED_APP_LIVE_MODE_FIELDS,
    }


def main() -> None:
    ensure_dirs()
    started_at = utc_now_iso()
    log("[START] materialize_execution_app_exports")

    registry = read_json(PATHS_REGISTRY_PATH)
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, dict):
        fail("paths_registry.json missing top-level 'artifacts' object")

    app_live_mode_contract = load_app_live_mode_contract()

    report_rows: list[dict[str, Any]] = []
    missing_registry_keys: list[str] = []
    missing_legacy_sources: list[str] = []
    copied_count = 0
    transformed_count = 0
    already_present_count = 0

    for artifact_key in REQUIRED_ARTIFACT_KEYS:
        entry = artifacts.get(artifact_key)
        if not isinstance(entry, dict):
            missing_registry_keys.append(artifact_key)
            continue

        canonical_raw = entry.get("canonical")
        if not isinstance(canonical_raw, str) or not canonical_raw.strip():
            missing_registry_keys.append(artifact_key)
            continue

        canonical_path = Path(canonical_raw)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)

        row: dict[str, Any] = {
            "artifact_key": artifact_key,
            "canonical_path": str(canonical_path),
            "artifact_type": entry.get("artifact_type"),
            "owner": entry.get("owner"),
            "truth_domain": entry.get("truth_domain"),
        }

        source_path = find_existing_source(entry)
        if source_path is None and not canonical_path.exists():
            missing_legacy_sources.append(artifact_key)
            row["status"] = "missing_legacy_source"
            row["legacy_aliases"] = entry.get("legacy_aliases", [])
            report_rows.append(row)
            log(f"[MISS] no existing legacy alias for: {artifact_key}")
            continue

        if artifact_key == "phase67j_live_status":
            if source_path is None:
                fail("phase67j_live_status requires legacy source for deterministic rematerialization")
            transform_result = materialize_phase67j_live_status_with_contract(
                source_path=source_path,
                canonical_path=canonical_path,
                app_live_mode_contract=app_live_mode_contract,
            )
            transformed_count += 1
            row.update(transform_result)
            report_rows.append(row)
            log(f"[MATERIALIZED] {artifact_key}")
            log(f"              source={source_path}")
            log(f"              target={canonical_path}")
            continue

        if (
            artifact_key == "phase66g_live_status"
            and source_path is not None
            and canonical_path.exists()
            and canonical_path.is_file()
        ):
            refresh_metadata = newer_phase66g_live_status_available(
                source_path=source_path,
                canonical_path=canonical_path,
            )
            if refresh_metadata is not None:
                copy_result = copy_plain_artifact(source_path, canonical_path)
                copied_count += 1
                row.update(copy_result)
                row["status"] = "refreshed_from_newer_legacy_alias"
                row.update(refresh_metadata)
                report_rows.append(row)
                log(f"[REFRESHED] {artifact_key}")
                log(f"            source={source_path}")
                log(f"            target={canonical_path}")
                continue

        if artifact_key == "phase66g_live_status":
            if source_path is None:
                fail("phase66g_live_status requires legacy source for freshness-aware rematerialization")
            if should_refresh_phase66g_live_status(source_path, canonical_path):
                copy_result = copy_plain_artifact(source_path, canonical_path)
                copied_count += 1
                row.update(copy_result)
                row["status"] = "refreshed_from_newer_upstream"
                row["refresh_reason"] = "upstream_phase66g_live_status_is_newer_than_canonical"
                report_rows.append(row)
                log(f"[REFRESHED] {artifact_key}")
                log(f"           source={source_path}")
                log(f"           target={canonical_path}")
            else:
                already_present_count += 1
                row["status"] = "already_present"
                row["canonical_info"] = safe_stat(canonical_path)
                row["refresh_reason"] = "canonical_phase66g_live_status_is_not_older_than_upstream"
                report_rows.append(row)
                log(f"[OK] already present: {artifact_key} -> {canonical_path}")
            continue

        if canonical_path.exists() and canonical_path.is_file():
            already_present_count += 1
            row["status"] = "already_present"
            row["canonical_info"] = safe_stat(canonical_path)
            report_rows.append(row)
            log(f"[OK] already present: {artifact_key} -> {canonical_path}")
            continue

        if source_path is None:
            fail(f"Missing source path for required artifact: {artifact_key}")

        copy_result = copy_plain_artifact(source_path, canonical_path)
        copied_count += 1
        row.update(copy_result)
        report_rows.append(row)
        log(f"[COPIED] {artifact_key}")
        log(f"         source={source_path}")
        log(f"         target={canonical_path}")

    phase68i_summary_result = build_phase68i_summary_export()
    report_rows.append({
        "artifact_key": "phase68i_dynamic_ladder_candidate_summary",
        **phase68i_summary_result,
    })
    transformed_count += 1
    log(f"[MATERIALIZED] phase68i_dynamic_ladder_candidate_summary")
    log(f"              target={PHASE68I_SUMMARY_OUTPUT_PATH}")

    hard_required = [
        "phase67j_winner_paper",
        "phase67j_live_status",
    ]

    hard_required_missing = [
        key for key in hard_required
        if key in missing_registry_keys or key in missing_legacy_sources
    ]

    report = {
        "report_type": "materialize_execution_app_exports_report",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "paths_registry_path": str(PATHS_REGISTRY_PATH.resolve()),
        "project_truth_path": str(PROJECT_TRUTH_PATH.resolve()),
        "required_artifact_keys": REQUIRED_ARTIFACT_KEYS,
        "required_app_live_mode_fields": REQUIRED_APP_LIVE_MODE_FIELDS,
        "hard_required_for_execution": hard_required,
        "missing_registry_keys": missing_registry_keys,
        "missing_legacy_sources": missing_legacy_sources,
        "hard_required_missing": hard_required_missing,
        "copied_count": copied_count,
        "transformed_count": transformed_count,
        "already_present_count": already_present_count,
        "rows": report_rows,
        "status": "success" if not hard_required_missing else "partial_failure",
        "notes": [
            "This script never fabricates strategy data.",
            "phase67j_live_status is rematerialized deterministically with official app_live_mode_contract.current fields from source_of_truth/project_truth.json.",
            "phase68i dynamic ladder summary export is built from phase68h summary source plus phase68i app paper-derived metrics.",
            "Other artifacts are copied from existing legacy aliases only."
        ],
    }

    quality = {
        "materializer_ok": True,
        "missing_registry_key_count": len(missing_registry_keys),
        "missing_legacy_source_count": len(missing_legacy_sources),
        "hard_required_missing_count": len(hard_required_missing),
        "copied_count": copied_count,
        "transformed_count": transformed_count,
        "already_present_count": already_present_count,
        "contract_ready_after_materialization": len(hard_required_missing) == 0,
        "app_live_mode_fields_written": True,
        "phase68i_summary_written": PHASE68I_SUMMARY_OUTPUT_PATH.exists(),
    }

    manifest = {
        "artifact_name": "materialize_execution_app_exports",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(PATHS_REGISTRY_PATH.resolve()),
            str(PROJECT_TRUTH_PATH.resolve()),
            str(PHASE68H_SUMMARY_INPUT_PATH.resolve()),
            str(PHASE68I_PAPER_INPUT_PATH.resolve()),
        ],
        "output_paths": [
            str(REPORT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
            str(PHASE68I_SUMMARY_OUTPUT_PATH.resolve()),
        ],
        "status": report["status"],
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {REPORT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] materialize_execution_app_exports status={report['status']}")


if __name__ == "__main__":
    main()

