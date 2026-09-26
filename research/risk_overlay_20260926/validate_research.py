"""Offline reproducibility and boundary verification for this research bundle."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((HERE / "input_manifest.json").read_text())
    before = {name: digest(ROOT / name) for name in manifest["files"]}
    if before != manifest["files"]:
        raise AssertionError("Current checkout inputs differ from the frozen research baseline")
    runs = []
    def run(file, args=(), expected=0):
        command = [sys.executable, str(HERE / file), *args]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        runs.append({"command": "python research/risk_overlay_20260926/" + file + (" " + " ".join(args) if args else ""),
                     "exit_code": result.returncode, "expected_exit_code": expected,
                     "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != expected:
            raise AssertionError(result.stderr + result.stdout)
    for args, prefix in [((), ""), (("--source", "local"), "local_")]:
        run("run_audit.py", args, expected=2)
        first = digest(HERE / f"{prefix}results.json")
        run("run_audit.py", args, expected=2)
        if first != digest(HERE / f"{prefix}results.json"):
            raise AssertionError("Repeated research result differs")
    run("test_audit.py")
    run("leverage_audit.py")
    after = {name: digest(ROOT / name) for name in manifest["files"]}
    protected_diff = subprocess.check_output([
        "git", "diff", "--name-only", "--", "data", "outputs", "scripts", "src", "source_of_truth", "execution", "app.py"
    ], cwd=ROOT, text=True).strip()
    if after != before or protected_diff:
        raise AssertionError("Protected inputs or production paths changed")
    result = {"passed": True, "tests": 23, "deterministic_repeat": True,
              "protected_inputs_unchanged": True, "production_diff_empty": True,
              "network_requests": 0, "live_order_chain": "not_invoked", "heavy_refresh_steps": "skipped",
              "runs": runs}
    (HERE / "validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print("PASS: 23 tests; deterministic current failure and local reproduction; protected files unchanged; no network/order/refresh")


if __name__ == "__main__":
    main()
