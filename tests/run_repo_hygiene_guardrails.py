import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"

TEST_FILES = [
    TESTS_DIR / "test_source_of_truth_presence.py",
    TESTS_DIR / "test_forbidden_tracked_artifacts.py",
    TESTS_DIR / "test_canonical_lineage_minimum.py",
    TESTS_DIR / "test_canonical_truth_consistency.py",
    TESTS_DIR / "test_canonical_reference_separation.py",
    TESTS_DIR / "test_canonical_product_export_contract.py",
    TESTS_DIR / "test_canonical_json_schema_shape.py",
    TESTS_DIR / "test_canonical_consumer_scope_rules.py",
    TESTS_DIR / "test_canonical_decision_vs_reference_boundaries.py",
    TESTS_DIR / "test_canonical_upstream_paths_exist.py",
    TESTS_DIR / "test_canonical_filename_path_contracts.py",
    TESTS_DIR / "test_canonical_required_top_level_keys.py",
    TESTS_DIR / "test_canonical_reference_truth_flags.py",
    TESTS_DIR / "test_canonical_decision_ids_present.py",
    TESTS_DIR / "test_canonical_manifest_indexes_shape.py",
    TESTS_DIR / "test_canonical_truth_domain_allowed_values.py",
    TESTS_DIR / "test_canonical_artifact_type_allowed_values.py",
    TESTS_DIR / "test_canonical_truth_status_allowed_values.py",
    TESTS_DIR / "test_canonical_consumer_scope_allowed_values.py",
]


def load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()

    for index, file_path in enumerate(TEST_FILES, start=1):
        module = load_module_from_path(f"repo_hygiene_guardrail_module_{index}", file_path)
        suite.addTests(loader.loadTestsFromModule(module))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n[OK] Repo hygiene guardrails passed.")
        return 0

    print("\n[FAIL] Repo hygiene guardrails failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())