import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"

TEST_MODULES = [
    "tests.test_canonical_reference_separation",
    "tests.test_canonical_product_export_contract",
]


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()

    for module_name in TEST_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n[OK] Canonical guardrails passed.")
        return 0

    print("\n[FAIL] Canonical guardrails failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())