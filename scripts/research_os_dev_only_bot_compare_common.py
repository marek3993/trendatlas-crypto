from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


MANDATORY_DEV_FLAGS = {
    "dev_only": True,
    "non_authoritative": True,
    "official_truth": False,
    "strategy_advancement": False,
}

OUTPUT_ROOT = Path(
    r"C:\Users\benda\Desktop\market_regime_v1\outputs\research_os\dev_only\non_authoritative_bot_compare"
)


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def with_dev_flags(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    return out


def compare_file_paths(compare_id: str) -> Dict[str, Path]:
    return {
        "comparison_json": OUTPUT_ROOT / f"{compare_id}.json",
        "comparison_csv": OUTPUT_ROOT / f"{compare_id}.csv",
        "agreement_watchlist_json": OUTPUT_ROOT / f"{compare_id.replace('_comparison', '')}_agreement_watchlist.json",
        "disagreement_watchlist_json": OUTPUT_ROOT / f"{compare_id.replace('_comparison', '')}_disagreement_watchlist.json",
    }


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
