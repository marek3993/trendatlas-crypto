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

EXPECTED_PARENT_BY_TYPE = {
    "decision": "decisions",
    "snapshot": "manifests",
    "manifest": "manifests",
    "export": "exports",
    "reference": "references",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalFilenamePathContracts(unittest.TestCase):
    def test_all_canonical_json_files_live_under_canonical_folder(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            rel = path.relative_to(ROOT).as_posix()
            if not rel.startswith("canonical/"):
                failures.append(rel)

        self.assertFalse(failures, f"Files outside canonical folder: {failures}")

    def test_parent_folder_matches_artifact_type_contract(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            artifact_type = payload["artifact_type"]
            expected_parent = EXPECTED_PARENT_BY_TYPE.get(artifact_type)
            actual_parent = path.parent.name

            if expected_parent != actual_parent:
                failures.append(
                    f"{path.relative_to(ROOT)} expected parent {expected_parent}, got {actual_parent}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_filename_equals_artifact_name_plus_json(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            expected_name = payload["artifact_name"] + ".json"
            if path.name != expected_name:
                failures.append(
                    f"{path.relative_to(ROOT)} expected filename {expected_name}, got {path.name}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_all_canonical_json_names_use_canonical_prefix(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            if not payload["artifact_name"].startswith("canonical_"):
                failures.append(str(path.relative_to(ROOT)))

        self.assertFalse(failures, f"Missing canonical_ prefix: {failures}")


if __name__ == "__main__":
    unittest.main()