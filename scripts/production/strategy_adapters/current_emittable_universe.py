"""Expose current selector instruments without interpreting historical baskets."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable


def derive_current_emittable_universe(*, root: Path, closed_day: str,
                                     strategy_version: str, adapter_path: Path,
                                     overlay_assets: Iterable[str]) -> dict[str, Any]:
    contract_path = root / "source_of_truth/production_asset_universe_contract.json"
    result: dict[str, Any] = {
        "schema_version": 1, "status": "unavailable", "strategy_version": strategy_version,
        "closed_day": closed_day, "assets": [], "source_kind": "current_production_selector",
        "errors": [],
    }
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        declared_adapter = (root / contract["adapter_source"]).resolve()
        declared_adapter.relative_to(root.resolve())
        if adapter_path.resolve() != declared_adapter:
            raise ValueError("Current production adapter does not match the source contract")
        source = (root / contract["selector_source"]).resolve()
        source.relative_to(root.resolve())
        raw = source.read_bytes()
        with source.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError("Current production selector has no successfully loaded candidates")
        assets = set()
        for row in rows:
            asset = str(row.get("asset") or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9._:-]{0,63}", asset):
                raise ValueError("Current production selector contains an invalid instrument")
            if date.fromisoformat(str(row.get("end_date") or "")[:10]) < date.fromisoformat(closed_day):
                raise ValueError("Current production selector candidate data is stale")
            if int(row.get("history_days") or 0) <= 0:
                raise ValueError("Current production selector candidate history is invalid")
            if asset in assets:
                raise ValueError("Current production selector contains duplicate instruments")
            assets.add(asset)
        normalized_overlays = set()
        for asset in overlay_assets:
            normalized = str(asset).strip().upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9._:-]{0,63}", normalized):
                raise ValueError("Production overlay instrument is invalid")
            assets.add(normalized)
            normalized_overlays.add(normalized)
        assets.add("CASH")
        result.update(status="available", assets=sorted(assets), selector_source=str(source.relative_to(root.resolve())).replace("\\", "/"),
                      adapter_source=str(declared_adapter.relative_to(root.resolve())).replace("\\", "/"), overlay_assets=sorted(normalized_overlays),
                      selector_sha256=hashlib.sha256(raw).hexdigest(), adapter_sha256=hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
                      selector_candidate_count=len(rows))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"] = [str(exc)]
    return result
