import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "repo_hygiene_guardrails_manifest.json"


class TestRepoHygieneManifestValid(unittest.TestCase):
    def load_manifest(self) -> dict:
        with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_manifest_exists(self):
        self.assertTrue(MANIFEST_PATH.exists(), str(MANIFEST_PATH.relative_to(ROOT)))

    def test_manifest_has_non_empty_test_files_list(self):
        payload = self.load_manifest()
        test_files = payload.get("test_files")

        self.assertIsInstance(test_files, list)
        self.assertTrue(test_files)

    def test_manifest_test_files_exist(self):
        payload = self.load_manifest()
        failures = []

        for rel_path in payload["test_files"]:
            if not isinstance(rel_path, str) or not rel_path.strip():
                failures.append(f"Invalid manifest entry: {rel_path}")
                continue

            path = ROOT / rel_path
            if not path.exists():
                failures.append(f"Missing test file from manifest: {rel_path}")

        self.assertFalse(failures, " | ".join(failures))

    def test_manifest_has_no_duplicate_test_files(self):
        payload = self.load_manifest()
        test_files = payload["test_files"]

        self.assertEqual(len(test_files), len(set(test_files)))


if __name__ == "__main__":
    unittest.main()