from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "outputs" / "app_freshness_verification"
REPORT_PATH = REPORT_DIR / "app_freshness_report.json"

BTC_RAW_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
TOP100_DIR = ROOT / "data" / "ohlcv_phase67_top100"
SHORTLIST_PATH = ROOT / "outputs" / "phase67b_top100_forensic_prune_and_rerun" / "phase67b_asset_shortlist.csv"
CANONICAL_APP_EXPORTS_DIR = ROOT / "outputs" / "execution" / "app_exports"
LEGACY_PHASE66G_DIR = ROOT / "outputs" / "phase66g_production_candidate_live"
LEGACY_PHASE67J_DIR = ROOT / "outputs" / "phase67j_final_narrow_validation_pack"

# The freshness step runs before materialization in the daily pipeline, so it
# must prefer the freshest available artifact across the upstream legacy phase
# folders and the canonical app export layer.
PHASE66G_PAPER_PATHS = [
    CANONICAL_APP_EXPORTS_DIR / "phase66g_production_soft_filters_paper.csv",
    LEGACY_PHASE66G_DIR / "phase66g_production_soft_filters_paper.csv",
]
PHASE66G_LIVE_PATHS = [
    CANONICAL_APP_EXPORTS_DIR / "phase66g_live_status.csv",
    LEGACY_PHASE66G_DIR / "phase66g_live_status.csv",
]
PHASE66G_TREND_PATHS = [
    CANONICAL_APP_EXPORTS_DIR / "phase66g_trend_barometer_history.csv",
    LEGACY_PHASE66G_DIR / "phase66g_trend_barometer_history.csv",
]
PHASE67J_PAPER_PATHS = [
    CANONICAL_APP_EXPORTS_DIR / "phase67j_no_neo_main_paper.csv",
    LEGACY_PHASE67J_DIR / "phase67j_no_neo_main_paper.csv",
]
PHASE67J_LIVE_PATHS = [
    CANONICAL_APP_EXPORTS_DIR / "phase67j_live_status.csv",
    LEGACY_PHASE67J_DIR / "phase67j_live_status.csv",
]

MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"


def utc_today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def latest_closed_utc_date() -> datetime.date:
    return (utc_today_start() - timedelta(days=1)).date()


def ensure_file(path: Path, errors: list[str]) -> None:
    if not path.exists() or not path.is_file():
        errors.append(f"missing_file::{path}")


def ensure_any_file(paths: list[Path], label: str, errors: list[str]) -> None:
    if not any(path.exists() and path.is_file() for path in paths):
        errors.append(f"missing_file::{label}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_last_date(path: Path, date_col_candidates: list[str]) -> datetime.date:
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"empty_csv::{path}")

    for candidate in date_col_candidates:
        if candidate in rows[0]:
            raw = str(rows[-1].get(candidate, "")).strip()
            if raw:
                return datetime.strptime(raw, "%Y-%m-%d").date()

    raise ValueError(f"missing_date_column::{path}")


def read_live_status_value(path: Path, field: str) -> str:
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"empty_live_status::{path}")
    return str(rows[0].get(field, "")).strip()


def latest_date_across_paths(paths: list[Path], date_col_candidates: list[str], label: str) -> datetime.date:
    last_error: Exception | None = None
    values: list[datetime.date] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            values.append(read_last_date(path, date_col_candidates))
        except Exception as exc:
            last_error = exc

    if values:
        return max(values)
    if last_error is not None:
        raise last_error
    raise ValueError(f"missing_file::{label}")


def latest_live_status_date_across_paths(paths: list[Path], field: str, label: str) -> datetime.date:
    last_error: Exception | None = None
    values: list[datetime.date] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            values.append(datetime.strptime(read_live_status_value(path, field), "%Y-%m-%d").date())
        except Exception as exc:
            last_error = exc

    if values:
        return max(values)
    if last_error is not None:
        raise last_error
    raise ValueError(f"missing_file::{label}")


def shortlist_assets() -> list[str]:
    if not SHORTLIST_PATH.exists():
        return []

    rows = read_csv_rows(SHORTLIST_PATH)
    assets: list[str] = []
    for row in rows:
        asset = str(row.get("asset", "")).strip().upper()
        if asset:
            assets.append(asset)
    return assets


def write_report(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []

    critical_files = [
        BTC_RAW_PATH,
        MACRO_PATH,
    ]
    for path in critical_files:
        ensure_file(path, errors)
    ensure_any_file(PHASE66G_PAPER_PATHS, "phase66g_paper", errors)
    ensure_any_file(PHASE66G_LIVE_PATHS, "phase66g_live_status", errors)
    ensure_any_file(PHASE66G_TREND_PATHS, "phase66g_trend_history", errors)
    ensure_any_file(PHASE67J_PAPER_PATHS, "phase67j_paper", errors)
    ensure_any_file(PHASE67J_LIVE_PATHS, "phase67j_live_status", errors)

    assets = shortlist_assets()
    top100_asset_dates: dict[str, str] = {}

    for asset in assets:
        asset_path = TOP100_DIR / f"{asset}USDT_1d.csv"
        if not asset_path.exists():
            errors.append(f"missing_top100_asset::{asset_path}")
            continue

        try:
            last_date = read_last_date(asset_path, ["date"])
            top100_asset_dates[asset] = last_date.isoformat()
        except Exception as exc:
            errors.append(str(exc))

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_closed_utc_date": latest_closed_utc_date().isoformat(),
        "status": "fail",
        "checks": {},
        "warnings": warnings,
        "errors": errors,
        "report_path": str(REPORT_PATH),
    }

    if errors:
        write_report(report)
        print(f"[FRESHNESS] FAIL report={REPORT_PATH}", flush=True)
        for err in errors:
            print(f"[FRESHNESS] {err}", flush=True)
        sys.exit(1)

    btc_raw_last = read_last_date(BTC_RAW_PATH, ["date"])
    phase66g_paper_last = latest_date_across_paths(PHASE66G_PAPER_PATHS, ["date"], "phase66g_paper")
    phase67j_paper_last = latest_date_across_paths(PHASE67J_PAPER_PATHS, ["date"], "phase67j_paper")
    phase66g_trend_last = latest_date_across_paths(PHASE66G_TREND_PATHS, ["date"], "phase66g_trend_history")
    macro_last = read_last_date(MACRO_PATH, ["date"])

    phase66g_live_last = latest_live_status_date_across_paths(
        PHASE66G_LIVE_PATHS,
        "latest_available_date",
        "phase66g_live_status",
    )
    phase67j_live_last = latest_live_status_date_across_paths(
        PHASE67J_LIVE_PATHS,
        "latest_available_date",
        "phase67j_live_status",
    )

    target_closed = latest_closed_utc_date()

    if btc_raw_last < target_closed - timedelta(days=1):
        errors.append(
            f"stale_btc_raw::btc_raw_last={btc_raw_last.isoformat()} target_closed={target_closed.isoformat()}"
        )

    if top100_asset_dates:
        min_top100_last = min(datetime.strptime(v, "%Y-%m-%d").date() for v in top100_asset_dates.values())
        max_top100_last = max(datetime.strptime(v, "%Y-%m-%d").date() for v in top100_asset_dates.values())

        if min_top100_last < target_closed - timedelta(days=1):
            errors.append(
                f"stale_top100_raw::min_top100_last={min_top100_last.isoformat()} target_closed={target_closed.isoformat()}"
            )
    else:
        min_top100_last = None
        max_top100_last = None
        warnings.append("top100_shortlist_empty_or_missing")

    if phase66g_live_last != phase66g_paper_last:
        errors.append(
            f"phase66g_live_mismatch::live={phase66g_live_last.isoformat()} paper={phase66g_paper_last.isoformat()}"
        )

    if phase67j_live_last != phase67j_paper_last:
        errors.append(
            f"phase67j_live_mismatch::live={phase67j_live_last.isoformat()} paper={phase67j_paper_last.isoformat()}"
        )

    if phase66g_paper_last != phase67j_paper_last:
        errors.append(
            f"paper_date_mismatch::phase66g={phase66g_paper_last.isoformat()} phase67j={phase67j_paper_last.isoformat()}"
        )

    if phase66g_trend_last != phase66g_paper_last:
        errors.append(
            f"trend_history_mismatch::trend={phase66g_trend_last.isoformat()} paper={phase66g_paper_last.isoformat()}"
        )

    if phase66g_paper_last < btc_raw_last - timedelta(days=1):
        errors.append(
            f"phase66g_too_far_behind_raw::phase66g={phase66g_paper_last.isoformat()} btc_raw={btc_raw_last.isoformat()}"
        )

    if min_top100_last is not None and phase67j_paper_last < min_top100_last - timedelta(days=1):
        errors.append(
            f"phase67j_too_far_behind_top100::phase67j={phase67j_paper_last.isoformat()} top100_min={min_top100_last.isoformat()}"
        )

    report["checks"] = {
        "btc_raw_last_date": btc_raw_last.isoformat(),
        "phase66g_paper_last_date": phase66g_paper_last.isoformat(),
        "phase66g_live_latest_available_date": phase66g_live_last.isoformat(),
        "phase66g_trend_last_date": phase66g_trend_last.isoformat(),
        "phase67j_paper_last_date": phase67j_paper_last.isoformat(),
        "phase67j_live_latest_available_date": phase67j_live_last.isoformat(),
        "macro_last_date": macro_last.isoformat(),
        "top100_assets_checked": assets,
        "top100_asset_last_dates": top100_asset_dates,
        "top100_min_last_date": min_top100_last.isoformat() if min_top100_last else "",
        "top100_max_last_date": max_top100_last.isoformat() if max_top100_last else "",
    }
    report["warnings"] = warnings
    report["errors"] = errors
    report["status"] = "ok" if not errors else "fail"

    write_report(report)

    if errors:
        print(f"[FRESHNESS] FAIL report={REPORT_PATH}", flush=True)
        for err in errors:
            print(f"[FRESHNESS] {err}", flush=True)
        sys.exit(1)

    print("[FRESHNESS] OK", flush=True)
    print(f"[FRESHNESS] report={REPORT_PATH}", flush=True)
    print(f"[FRESHNESS] btc_raw_last_date={btc_raw_last.isoformat()}", flush=True)
    print(f"[FRESHNESS] phase66g_paper_last_date={phase66g_paper_last.isoformat()}", flush=True)
    print(f"[FRESHNESS] phase67j_paper_last_date={phase67j_paper_last.isoformat()}", flush=True)
    print(f"[FRESHNESS] macro_last_date={macro_last.isoformat()}", flush=True)
    if min_top100_last is not None:
        print(f"[FRESHNESS] top100_min_last_date={min_top100_last.isoformat()}", flush=True)


if __name__ == "__main__":
    main()
