from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "approved_strategy_net_compare"

SOURCE_PATHS = {
    "phase66g_production_soft_filters": (
        ROOT
        / "outputs"
        / "phase66g_production_candidate_live"
        / "phase66g_production_soft_filters_authoritative_net_compare_export.csv"
    ),
    "phase67j_no_neo_main": (
        ROOT
        / "outputs"
        / "phase67j_final_narrow_validation_pack"
        / "phase67j_no_neo_main_authoritative_net_compare_export.csv"
    ),
    "phase68g_66g_1p25x_candidate": (
        ROOT
        / "outputs"
        / "phase68g_portfolio_exposure_leverage_validation"
        / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
    ),
    "phase68i_dynamic_ladder_candidate": (
        ROOT
        / "outputs"
        / "execution"
        / "app_exports"
        / "phase68i_dynamic_ladder_candidate_authoritative_net_compare_export.csv"
    ),
}

REQUIRED_FIELDS = [
    "model",
    "total_return_pct_net",
    "cagr_pct_net",
    "max_drawdown_pct_net",
    "since2023_cagr_pct_net",
    "since2025_cagr_pct_net",
    "total_return_pct_gross",
    "cagr_pct_gross",
    "max_drawdown_pct_gross",
    "since2023_cagr_pct_gross",
    "since2025_cagr_pct_gross",
    "trading_fees_total_pct",
    "funding_total_pct",
    "borrow_cost_total_pct",
    "tradable_slippage_cost_total_pct",
    "switch_count",
    "trade_count",
    "cash_days_pct",
    "btc_days_pct",
]

OPTIONAL_COMPARE_FIELDS = [
    "annual_borrow_cost_pct",
    "tradable_transition_slippage_bps",
    "fee_side_mode",
    "taker_fee_bps",
    "maker_fee_bps",
    "staking_discount_pct",
    "referral_discount_pct",
    "effective_trading_fee_bps",
    "latest_available_date",
]


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def read_single_row(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required compare source: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if len(rows) != 1:
        raise ValueError(f"Expected exactly 1 row in {path}, got {len(rows)}")
    return fieldnames, rows[0]


def normalize_row(row: dict[str, str], source_path: Path) -> dict[str, str]:
    missing = [field for field in REQUIRED_FIELDS if field not in row or str(row.get(field, "")).strip() == ""]
    if missing:
        raise ValueError(f"{source_path} is missing required compare fields: {missing}")

    out = {field: row.get(field, "") for field in REQUIRED_FIELDS}
    for field in OPTIONAL_COMPARE_FIELDS:
        if field in row:
            out[field] = row.get(field, "")
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    compare_path = OUTPUT_DIR / "approved_strategy_authoritative_net_compare.csv"
    manifest_path = OUTPUT_DIR / "approved_strategy_authoritative_net_compare_manifest.json"

    ordered_rows: list[dict[str, str]] = []
    source_manifest: list[dict[str, str]] = []

    for model_name, source_path in SOURCE_PATHS.items():
        fieldnames, row = read_single_row(source_path)
        normalized = normalize_row(row, source_path)
        if normalized["model"] != model_name:
            raise ValueError(
                f"{source_path} has model={normalized['model']}, expected {model_name}"
            )
        ordered_rows.append(normalized)
        source_manifest.append(
            {
                "model": model_name,
                "source_path": str(source_path),
                "source_fields": fieldnames,
            }
        )

    output_fields = list(REQUIRED_FIELDS)
    for field in OPTIONAL_COMPARE_FIELDS:
        if any(field in row for row in ordered_rows):
            output_fields.append(field)

    with compare_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for row in ordered_rows:
            writer.writerow({field: row.get(field, "") for field in output_fields})

    manifest = {
        "artifact_type": "approved_strategy_authoritative_net_compare",
        "generated_at_utc": utc_now_iso(),
        "compare_path": str(compare_path),
        "required_fields": REQUIRED_FIELDS,
        "optional_fields_included": [field for field in OPTIONAL_COMPARE_FIELDS if field in output_fields],
        "source_exports": source_manifest,
        "notes": [
            "Approved-strategy compare assembled only from first-party authoritative exports.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[COMPARE] saved {compare_path}", flush=True)
    print(f"[COMPARE] saved {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
