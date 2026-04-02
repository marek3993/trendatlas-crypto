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

REQUIRED_SCOPE_VALUES = {"canonical_only", "audit_only"}
ALLOWED_ARTIFACT_TYPES = {"decision", "snapshot", "manifest", "export", "reference"}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalJsonSchemaShape(unittest.TestCase):
    def test_all_canonical_json_files_are_objects(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            if not isinstance(payload, dict):
                failures.append(f"{path.relative_to(ROOT)} root JSON must be an object")

        self.assertFalse(failures, " | ".join(failures))

    def test_consumer_scope_is_non_empty_string_list(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            consumer_scope = payload.get("consumer_scope")

            if not isinstance(consumer_scope, list) or not consumer_scope:
                failures.append(f"{path.relative_to(ROOT)} consumer_scope must be a non-empty list")
                continue

            if not all(isinstance(item, str) and item.strip() for item in consumer_scope):
                failures.append(f"{path.relative_to(ROOT)} consumer_scope must contain only non-empty strings")

        self.assertFalse(failures, " | ".join(failures))

    def test_upstream_artifacts_is_string_list(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            upstream = payload.get("upstream_artifacts")

            if not isinstance(upstream, list):
                failures.append(f"{path.relative_to(ROOT)} upstream_artifacts must be a list")
                continue

            if not all(isinstance(item, str) and item.strip() for item in upstream):
                failures.append(f"{path.relative_to(ROOT)} upstream_artifacts must contain only non-empty strings")

        self.assertFalse(failures, " | ".join(failures))

    def test_supersedes_is_string_list(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            supersedes = payload.get("supersedes")

            if not isinstance(supersedes, list):
                failures.append(f"{path.relative_to(ROOT)} supersedes must be a list")
                continue

            if not all(isinstance(item, str) and item.strip() for item in supersedes):
                failures.append(f"{path.relative_to(ROOT)} supersedes must contain only non-empty strings")

        self.assertFalse(failures, " | ".join(failures))

    def test_artifact_type_matches_expected_folder(self):
        failures = []

        folder_by_type = {
            "decision": "decisions",
            "manifest": "manifests",
            "snapshot": "manifests",
            "export": "exports",
            "reference": "references",
        }

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            artifact_type = payload.get("artifact_type")

            if artifact_type not in ALLOWED_ARTIFACT_TYPES:
                failures.append(f"{path.relative_to(ROOT)} invalid artifact_type={artifact_type}")
                continue

            expected_folder = folder_by_type[artifact_type]
            actual_folder = path.parent.name

            if actual_folder != expected_folder:
                failures.append(
                    f"{path.relative_to(ROOT)} folder mismatch: artifact_type={artifact_type}, expected folder={expected_folder}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_every_canonical_json_has_minimum_scope_markers(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            consumer_scope = set(payload.get("consumer_scope", []))

            missing = sorted(REQUIRED_SCOPE_VALUES - consumer_scope)
            if missing:
                failures.append(f"{path.relative_to(ROOT)} missing consumer_scope values: {missing}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()