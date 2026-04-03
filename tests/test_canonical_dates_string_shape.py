import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_JSON_FILES = [
    ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_universe_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json",
    ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json",
    ROOT / "canonical" / "manifests" / "canonical_product_manifest.json",
    ROOT / "canonical" / "exports" / "canonical_product_export_contract.json",
    ROOT / "canonical" / "references" / "canonical_66g_reference.json",
    ROOT / "canonical" / "references" / "canonical_benchmark_reference.json",
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalDatesStringShape(unittest.TestCase):
    def test_effective_date_has_yyyy_mm_dd_shape(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            value = payload.get("effective_date")

            if not isinstance(value, str) or not DATE_RE.match(value):
                failures.append(f"{path.relative_to(ROOT)} invalid effective_date={value}")

        self.assertFalse(failures, " | ".join(failures))

    def test_generated_at_has_utc_timestamp_shape(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            value = payload.get("generated_at")

            if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
                failures.append(f"{path.relative_to(ROOT)} invalid generated_at={value}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()