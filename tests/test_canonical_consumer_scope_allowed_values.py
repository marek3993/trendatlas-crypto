import json
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

ALLOWED_CONSUMER_SCOPE_VALUES = {
    "research_only",
    "canonical_only",
    "product_readable",
    "app_readable",
    "audit_only",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalConsumerScopeAllowedValues(unittest.TestCase):
    def test_consumer_scope_contains_only_allowed_values(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            consumer_scope = payload.get("consumer_scope", [])

            if not isinstance(consumer_scope, list):
                failures.append(f"{path.relative_to(ROOT)} consumer_scope must be a list")
                continue

            invalid = [item for item in consumer_scope if item not in ALLOWED_CONSUMER_SCOPE_VALUES]
            if invalid:
                failures.append(
                    f"{path.relative_to(ROOT)} invalid consumer_scope values: {invalid}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_consumer_scope_has_no_duplicates(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            consumer_scope = payload.get("consumer_scope", [])

            if len(consumer_scope) != len(set(consumer_scope)):
                failures.append(f"{path.relative_to(ROOT)} consumer_scope contains duplicates")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()