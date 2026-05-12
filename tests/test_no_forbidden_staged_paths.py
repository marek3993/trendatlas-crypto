import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PREFIXES = (
    "outputs/",
    "data/",
    "outputs/execution/authority/",
)


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


class TestNoForbiddenStagedPaths(unittest.TestCase):
    def test_no_outputs_data_or_authority_paths_are_staged(self):
        staged_files = get_staged_files()
        violations = [
            path
            for path in staged_files
            if path.startswith(FORBIDDEN_PREFIXES)
        ]
        self.assertFalse(
            violations,
            f"Forbidden staged paths detected: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
