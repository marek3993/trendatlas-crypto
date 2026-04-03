import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
MANIFEST_PATH = TESTS_DIR / "repo_hygiene_guardrails_manifest.json"


def load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_test_files() -> list[Path]:
    if not MANIFEST_PATH.exists():
        raise RuntimeError(f"Missing manifest: {MANIFEST_PATH}")

    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    test_files = payload.get("test_files")
    if not isinstance(test_files, list) or not test_files:
        raise RuntimeError("repo_hygiene_guardrails_manifest.json must contain non-empty test_files list")

    resolved = []
    for rel_path in test_files:
        if not isinstance(rel_path, str) or not rel_path.strip():
            raise RuntimeError(f"Invalid test file entry in manifest: {rel_path}")
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            raise RuntimeError(f"Manifest references missing test file: {rel_path}")
        resolved.append(abs_path)

    return resolved


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    test_files = load_test_files()

    for index, file_path in enumerate(test_files, start=1):
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