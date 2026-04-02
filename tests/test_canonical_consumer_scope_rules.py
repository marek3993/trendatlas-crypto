import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STRATEGY_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json"
UNIVERSE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_universe_decision.json"
LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"
STRATEGY_SNAPSHOT_PATH = ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json"
PRODUCT_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_product_manifest.json"
PRODUCT_EXPORT_CONTRACT_PATH = ROOT / "canonical" / "exports" / "canonical_product_export_contract.json"
REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"

OFFICIAL_ARTIFACTS = [
    STRATEGY_DECISION_PATH,
    UNIVERSE_DECISION_PATH,
    LEVERAGE_DECISION_PATH,
    STRATEGY_SNAPSHOT_PATH,
    PRODUCT_MANIFEST_PATH,
    PRODUCT_EXPORT_CONTRACT_PATH,
]

REFERENCE_ARTIFACTS = [
    REF_66G_PATH,
    BENCHMARK_REF_PATH,
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalConsumerScopeRules(unittest.TestCase):
    def test_official_artifacts_are_product_and_app_readable(self):
        failures = []

        for path in OFFICIAL_ARTIFACTS:
            payload = load_json(path)
            consumer_scope = set(payload["consumer_scope"])

            if payload["truth_status"] != "official":
                failures.append(f"{path.relative_to(ROOT)} truth_status must be official")
                continue

            required = {"canonical_only", "product_readable", "app_readable", "audit_only"}
            missing = sorted(required - consumer_scope)
            if missing:
                failures.append(f"{path.relative_to(ROOT)} missing required scope values: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_reference_artifacts_remain_reference_but_still_readable(self):
        failures = []

        for path in REFERENCE_ARTIFACTS:
            payload = load_json(path)
            consumer_scope = set(payload["consumer_scope"])

            if payload["truth_status"] != "reference":
                failures.append(f"{path.relative_to(ROOT)} truth_status must be reference")
                continue

            required = {"canonical_only", "product_readable", "app_readable", "audit_only"}
            missing = sorted(required - consumer_scope)
            if missing:
                failures.append(f"{path.relative_to(ROOT)} missing required scope values: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_product_export_contract_allowed_sources_are_canonical_only(self):
        payload = load_json(PRODUCT_EXPORT_CONTRACT_PATH)
        allowed_sources = payload["export_contract"]["allowed_sources"]

        self.assertTrue(any("canonical decisions" in item.lower() for item in allowed_sources))
        self.assertTrue(any("canonical manifests" in item.lower() for item in allowed_sources))
        self.assertTrue(any("canonical references" in item.lower() for item in allowed_sources))

    def test_product_export_contract_forbidden_sources_block_historical_direct_reads(self):
        payload = load_json(PRODUCT_EXPORT_CONTRACT_PATH)
        forbidden_sources = payload["export_contract"]["forbidden_sources"]

        self.assertTrue(any("historical compare" in item.lower() for item in forbidden_sources))
        self.assertTrue(any("historical summary" in item.lower() for item in forbidden_sources))
        self.assertTrue(any("raw research outputs" in item.lower() for item in forbidden_sources))
        self.assertTrue(any("paper-only" in item.lower() for item in forbidden_sources))


if __name__ == "__main__":
    unittest.main()