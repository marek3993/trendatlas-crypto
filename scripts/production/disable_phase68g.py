"""Operator-only shutdown of the old scheduler and its kill switch; sends no order.

Can also be piped to `ssh ... sudo python3 - --repo-root ... --apply`.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=45, check=False)


def disable(repo_root: Path, *, apply: bool = False, systemctl=_systemctl) -> dict:
    root = repo_root.resolve(strict=True)
    path = root / "execution/config/execution_mode.json"
    original = path.read_bytes()
    mode = json.loads(original.decode("utf-8-sig"))
    if not isinstance(mode, dict) or not {"kill_switch", "trading_enabled"} <= set(mode):
        raise ValueError("Unexpected execution_mode schema; no state changed")
    report = {"action": "DISABLE_PHASE68G", "applied": False, "orders_sent": 0,
              "account_state": "NOT_QUERIED", "position_closed": False,
              "repo_root": str(root), "configuration": str(path),
              "new_flags": {"kill_switch": True, "trading_enabled": False, "dry_run_enabled": True}}
    if not apply:
        return report
    start = systemctl("show", "mrv1-production.service", "--property=ExecStart", "--value")
    if start.returncode or not any(str(p) in start.stdout for p in (repo_root, root)):
        raise ValueError("Installed ExecStart does not match supplied production root; no state changed")
    # First stop new scheduled activations. Never invoke the production service.
    for args in (("stop", "mrv1-production.timer"), ("disable", "mrv1-production.timer"), ("stop", "mrv1-production.service")):
        result = systemctl(*args)
        if result.returncode:
            raise RuntimeError("Scheduler shutdown incomplete; inspect protected systemd logs")
    metadata = path.stat()
    mode.update(report["new_flags"])
    backup = path.with_name("execution_mode.pre_clean_shutdown.json")
    if not backup.exists():
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(original)
            out.flush()
            os.fsync(out.fileno())
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".clean-kill-")
    try:
        os.fchmod(fd, stat.S_IMODE(metadata.st_mode))
        if os.geteuid() == 0:
            os.fchown(fd, metadata.st_uid, metadata.st_gid)
        with os.fdopen(fd, "w") as out:
            json.dump(mode, out, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if Path(temp).exists():
            Path(temp).unlink()
    readback = json.loads(path.read_text())
    timer = systemctl("is-active", "mrv1-production.timer")
    service = systemctl("is-active", "mrv1-production.service")
    enabled = systemctl("is-enabled", "mrv1-production.timer")
    verified = (readback.get("kill_switch") is True and readback.get("trading_enabled") is False
                and timer.stdout.strip() == "inactive" and service.stdout.strip() in {"inactive", "failed"}
                and enabled.stdout.strip() in {"disabled", "masked"})
    report.update({"applied": True, "verified_disabled": verified, "kill_switch": readback.get("kill_switch"),
                   "timer_active": timer.stdout.strip(), "service_active": service.stdout.strip(),
                   "timer_enabled": enabled.stdout.strip(), "backup": str(backup),
                   "inflight_exchange_outcome": "NOT_INFERRED_REQUIRES_READ_ONLY_ACCOUNT_RECONCILIATION"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        report = disable(args.repo_root, apply=args.apply)
        print(json.dumps(report, indent=2))
        return 0 if not args.apply or report.get("verified_disabled") else 2
    except Exception as exc:
        print(json.dumps({"action": "DISABLE_PHASE68G", "status": "NOT_CONFIRMED", "reason": str(exc), "orders_sent": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
