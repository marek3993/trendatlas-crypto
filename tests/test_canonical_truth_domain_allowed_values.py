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

ALLOWED_TRUTH_DOMAINS = {
    "strategy",
    "universe",
    "leverage",
    "product",
    "benchmark",
    "artifacts",
    "lineage",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalTruthDomainAllowedValues(unittest.TestCase):
    def test_truth_domain_is_in_allowed_set(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            truth_domain = payload.get("truth_domain")

            if truth_domain not in ALLOWED_TRUTH_DOMAINS:
                failures.append(
                    f"{path.relative_to(ROOT)} invalid truth_domain={truth_domain}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_truth_domain_is_non_empty_string(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            truth_domain = payload.get("truth_domain")

            if not isinstance(truth_domain, str) or not truth_domain.strip():
                failures.append(
                    f"{path.relative_to(ROOT)} truth_domain must be non-empty string"
                )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()