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

REQUIRED_TOP_LEVEL_KEYS = {
    "artifact_name",
    "artifact_type",
    "truth_domain",
    "truth_status",
    "generated_at",
    "effective_date",
    "producer_script",
    "source_run_id",
    "upstream_artifacts",
    "supersedes",
    "consumer_scope",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalRequiredTopLevelKeys(unittest.TestCase):
    def test_all_required_top_level_keys_exist(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(payload.keys()))
            if missing:
                failures.append(f"{path.relative_to(ROOT)} missing keys: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_no_required_top_level_keys_are_null_except_source_run_id(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            for key in REQUIRED_TOP_LEVEL_KEYS:
                if key == "source_run_id":
                    continue
                if payload.get(key) is None:
                    failures.append(f"{path.relative_to(ROOT)} has null key: {key}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()