from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"
SCREENSHOTS_DIR = AUTOMATION_ROOT / "screenshots"
VALIDATE_JSON_SCRIPT = AUTOMATION_ROOT / "tools" / "validate_json.py"


def find_single_file(directory: Path, suffix: str) -> Path:
    matches = list(directory.glob(f"*{suffix}"))
    if not matches:
        raise FileNotFoundError(f"No file with suffix '{suffix}' in {directory}")
    if len(matches) > 1:
        raise RuntimeError(f"Expected 1 file with suffix '{suffix}' in {directory}, found {len(matches)}")
    return matches[0]


def run_validation(target_file: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(VALIDATE_JSON_SCRIPT), str(target_file)],
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "").strip()
    if result.stderr:
        output = f"{output}\n{result.stderr.strip()}".strip()
    return result.returncode == 0, output


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python validate_run_bundle.py <run_id>")

    run_id = sys.argv[1].strip()

    run_dir = RUNS_DIR / run_id
    report_dir = REPORTS_DIR / run_id
    screenshot_dir = SCREENSHOTS_DIR / run_id

    if not VALIDATE_JSON_SCRIPT.exists():
        raise FileNotFoundError(f"Missing validator script: {VALIDATE_JSON_SCRIPT}")
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not report_dir.exists():
        raise FileNotFoundError(f"Report directory not found: {report_dir}")
    if not screenshot_dir.exists():
        raise FileNotFoundError(f"Screenshot directory not found: {screenshot_dir}")

    targets = [
        find_single_file(run_dir, ".run_log.json"),
        find_single_file(report_dir, ".report.json"),
        find_single_file(screenshot_dir, ".screenshot_manifest.json"),
    ]

    all_ok = True

    print(f"run_id={run_id}")
    for target in targets:
        ok, output = run_validation(target)
        print("---")
        print(output)
        if not ok:
            all_ok = False

    print("---")
    if all_ok:
        print("OK: run bundle validation passed")
        print("bundle_valid=True")
    else:
        print("FAIL: run bundle validation failed")
        print("bundle_valid=False")
        sys.exit(1)


if __name__ == "__main__":
    main()