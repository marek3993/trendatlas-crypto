import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REGISTRY_PATH = ROOT / "canonical" / "script_registry.json"


class TestScriptRegistryPathsExist(unittest.TestCase):
    def load_registry(self) -> dict:
        with SCRIPT_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_script_paths_exist(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["scripts"]):
            script_path = entry.get("script_path")
            if not isinstance(script_path, str) or not script_path.strip():
                failures.append(f"scripts[{idx}] invalid script_path={script_path}")
                continue

            abs_path = ROOT / script_path
            if not abs_path.exists():
                failures.append(f"scripts[{idx}] missing file: {script_path}")

        self.assertFalse(failures, " | ".join(failures))

    def test_script_paths_are_unique(self):
        payload = self.load_registry()
        paths = [entry.get("script_path") for entry in payload["scripts"]]
        self.assertEqual(len(paths), len(set(paths)), "Duplicate script_path values found")


if __name__ == "__main__":
    unittest.main()