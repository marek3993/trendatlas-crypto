"""Release entry point: verify bytes BEFORE importing any research code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def verified_root():
    root = Path(__file__).absolute().parents[3]
    manifest = json.loads((root / "manifest.json").read_bytes())
    for name, expected in manifest["files"].items():
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError("Untrusted release")
    sys.path.insert(0, str(root))
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "ready", "fixture", "enqueue"))
    parser.add_argument("--state", default="/var/lib/trendatlas-research")
    parser.add_argument("--job-file")
    parser.add_argument("--probe-input", help="Fixture-only read-only mount inspection")
    args = parser.parse_args()
    release = verified_root()
    from research_os.dev_only.evolution_worker import runtime
    manifest = runtime.verify_release(release)
    if args.command in ("run", "ready") and args.state != "/var/lib/trendatlas-research":
        raise ValueError("Installed worker has a fixed research state path")
    if args.command == "ready":
        return 0 if runtime.pending(args.state) else 1
    if args.command == "enqueue":
        if os.geteuid() != 0:
            raise ValueError("Only the local operator/root can enqueue a preregistered job")
        job = json.loads(Path(args.job_file).read_bytes())
        runtime.validate_job(job, manifest)
        if job["mode"] != "research":
            raise ValueError("Fixture jobs use the dedicated fixture command")
        state = runtime.state_path(args.state)
        path = runtime.safe_path(state / "queue" / job["job_id"] / "study.json")
        if path.exists():
            raise ValueError("Duplicate queue job")
        # Operator invokes under the same lock; service only has read access to queue.
        state.mkdir(parents=True, exist_ok=True)
        with runtime.worker_lock(state):
            runtime.atomic_json(path, job)
        print(json.dumps({"queued": job["job_id"]}))
        return 0
    if args.command == "fixture":
        from research_os.dev_only.evolution_worker.fixture import run_fixture
        result = run_fixture(release, args.state, probe_input=args.probe_input)
    else:
        result = runtime.run_once(release, args.state, Path("/opt/trendatlas-research/input"))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # No environment/config dump, job content or secret values in errors.
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
