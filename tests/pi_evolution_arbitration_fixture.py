"""Exercise only random dummy units in the USER manager, never production units."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def ctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], text=True, capture_output=True, check=check)


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("Dummy unit did not reach expected state")


def hold(root, role):
    root = Path(root)
    other = "production" if role == "worker" else "worker"
    if (root / (other + ".active")).exists():
        (root / "OVERLAP").write_text(role)
        raise SystemExit(2)
    marker = root / (role + ".active")
    marker.write_text(str(os.getpid()))
    def stop(*_):
        if role == "worker":
            time.sleep(.3)  # Exercise re-dispatch during a still-running stop operation.
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            time.sleep(.1)
    finally:
        marker.unlink(missing_ok=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "hold":
        return hold(sys.argv[2], sys.argv[3])
    if len(sys.argv) > 1 and sys.argv[1] == "gate":
        unit = sys.argv[2]
        assert unit.startswith("ta-evo-fixture-")
        state = ctl("show", unit, "-p", "ActiveState", "--value").stdout.strip()
        raise SystemExit(0 if state == "inactive" else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "dispatch-gate":
        unit = sys.argv[2]
        assert unit.startswith("ta-evo-fixture-")
        state = ctl("show", unit, "-p", "ActiveState", "--value").stdout.strip()
        jobs = [{"unit": line.split()[1]} for line in
                ctl("list-jobs", "--no-legend", "--no-pager").stdout.splitlines()]
        # Deliberately omit the normal production-state guard to test its admission race.
        raise SystemExit(0 if state in ("inactive", "failed") and
                         not any(j["unit"] == unit for j in jobs) else 1)
    prefix = "ta-evo-fixture-" + uuid.uuid4().hex[:10]
    prod, worker, dispatch = [prefix + "-" + n + ".service" for n in ("production", "worker", "dispatch")]
    unit_dir = Path(os.environ["XDG_RUNTIME_DIR"]) / "systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve())
    created = []
    with tempfile.TemporaryDirectory(prefix="ta-evo-arbitration-") as temp:
        root = Path(temp)
        units = {
            prod: f"[Unit]\nDescription=Dummy production\n[Service]\nType=exec\nExecStart=/usr/bin/python3 {script} hold {root} production\nTimeoutStopSec=2s\n",
            worker: f"[Unit]\nConflicts={prod}\nAfter={prod}\nRefuseManualStart=yes\n[Service]\nType=exec\nExecCondition=/usr/bin/python3 {script} gate {prod}\nExecStart=/usr/bin/python3 {script} hold {root} worker\nKillMode=control-group\nTimeoutStopSec=2s\n",
            dispatch: f"[Unit]\nAfter={prod}\nOnSuccess={worker}\nOnSuccessJobMode=ignore-requirements\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {script} dispatch-gate {worker}\n"}
        try:
            for name, content in units.items():
                content = content.replace("[Unit]\n", "[Unit]\nStartLimitIntervalSec=0\n")
                path = unit_dir / name
                with path.open("x") as handle:
                    handle.write(content)
                created.append(path)
            ctl("daemon-reload")
            assert ctl("start", worker, check=False).returncode != 0
            ctl("start", prod)
            wait_for(lambda: (root / "production.active").exists())
            original_pid = ctl("show", prod, "-p", "MainPID", "--value").stdout
            ctl("start", dispatch)  # Simulates admission racing with already-active production.
            time.sleep(.25)
            assert not (root / "worker.active").exists()
            assert ctl("show", prod, "-p", "MainPID", "--value").stdout == original_pid
            ctl("stop", prod)
            ctl("start", dispatch)
            wait_for(lambda: (root / "worker.active").exists())
            ctl("start", "--no-block", prod)
            wait_for(lambda: ctl("show", worker, "-p", "ActiveState", "--value").stdout.strip() == "deactivating")
            for _ in range(3):
                ctl("start", "--no-block", dispatch)
                time.sleep(.025)
            wait_for(lambda: (root / "production.active").exists())
            assert not (root / "OVERLAP").exists()
            ctl("stop", dispatch, worker, prod)
            ctl("start", dispatch)
            wait_for(lambda: (root / "worker.active").exists())
            ctl("start", prod)
            wait_for(lambda: (root / "production.active").exists())
            assert not (root / "worker.active").exists()
            for _ in range(12):
                ctl("stop", dispatch, prod, worker)
                ctl("start", "--no-block", dispatch)
                ctl("start", prod)
                wait_for(lambda: (root / "production.active").exists())
                assert not (root / "worker.active").exists()
                assert not (root / "OVERLAP").exists()
            ctl("stop", dispatch, prod, worker)
            dispatch_path = unit_dir / dispatch
            dispatch_path.write_text(dispatch_path.read_text().replace(
                "[Service]\n", '[Service]\nExecCondition=/usr/bin/python3 -c "import sys; sys.exit(255)"\n'))
            ctl("daemon-reload")
            assert ctl("start", dispatch, check=False).returncode != 0
            time.sleep(.25)
            assert ctl("show", dispatch, "-p", "Result", "--value").stdout.strip() == "exit-code"
            assert not (root / "worker.active").exists()
            print(json.dumps({"dummy_user_units_only": True, "manual_start_refused": True,
                "production_not_stopped_by_dispatch": True, "worker_preempted_before_production": True,
                "redispatch_during_preemption_no_overlap": True,
                "busy_condition_failed_without_onsuccess": True,
                "admission_races_without_overlap": 12, "real_production_touched": False}))
        except Exception:
            print(ctl("show", prod, worker, dispatch, "-p", "ActiveState", "-p", "SubState", "-p", "Result", check=False).stdout)
            print(subprocess.run(["journalctl", "--user", "-u", prod, "-u", worker, "-u", dispatch,
                                  "-n", "35", "--no-pager"], capture_output=True, text=True).stdout)
            raise
        finally:
            ctl("stop", dispatch, worker, prod, check=False)
            ctl("reset-failed", dispatch, worker, prod, check=False)
            for path in created:
                path.unlink()
            ctl("daemon-reload")


if __name__ == "__main__":
    main()
