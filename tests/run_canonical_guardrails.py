import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
PATTERN = "test_canonical_*.py"


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = loader.discover(
        start_dir=str(TESTS_DIR),
        pattern=PATTERN,
        top_level_dir=str(ROOT),
    )

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n[OK] Canonical guardrails passed.")
        return 0

    print("\n[FAIL] Canonical guardrails failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())