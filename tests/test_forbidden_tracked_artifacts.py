import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tests" / "forbidden_tracked_artifacts_baseline.txt"

FORBIDDEN_PATTERNS = [
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
]

FORBIDDEN_SUFFIXES = [
    ".pyc",
    ".pyo",
]


def get_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def load_baseline_prefixes() -> list[str]:
    if not BASELINE_PATH.exists():
        return []

    prefixes = []
    for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip().replace("\\", "/")
        if cleaned and not cleaned.startswith("#"):
            prefixes.append(cleaned)
    return prefixes


def is_forbidden_tracked_path(path: str) -> bool:
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in path:
            return True
    for suffix in FORBIDDEN_SUFFIXES:
        if path.endswith(suffix):
            return True
    return False


def is_baselined(path: str, baseline_prefixes: list[str]) -> bool:
    for prefix in baseline_prefixes:
        if path == prefix or path.startswith(prefix):
            return True
    return False


class TestForbiddenTrackedArtifacts(unittest.TestCase):
    def test_baseline_file_exists(self):
        self.assertTrue(
            BASELINE_PATH.exists(),
            f"Missing baseline file: {BASELINE_PATH.relative_to(ROOT)}",
        )

    def test_no_new_forbidden_tracked_artifacts_outside_baseline(self):
        tracked_files = get_tracked_files()
        baseline_prefixes = load_baseline_prefixes()

        violations = [
            path
            for path in tracked_files
            if is_forbidden_tracked_path(path) and not is_baselined(path, baseline_prefixes)
        ]

        preview = violations[:20]
        message = (
            f"Found {len(violations)} new forbidden tracked artifacts outside baseline. "
            f"Preview: {preview}"
        )
        self.assertFalse(violations, message)


if __name__ == "__main__":
    unittest.main()