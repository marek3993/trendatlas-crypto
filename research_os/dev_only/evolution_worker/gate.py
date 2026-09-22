"""Read-only systemd admission check, separate from strategy execution."""
import subprocess
import sys


def properties(unit):
    result = subprocess.run(["/usr/bin/systemctl", "show", unit,
        "-p", "LoadState", "-p", "ActiveState", "-p", "SubState", "-p", "Result",
        "-p", "ExecMainExitTimestampMonotonic", "-p", "UnitFileState", "-p", "MainPID", "-p", "CPUUsageNSec"],
        check=True, capture_output=True, text=True, timeout=5, env={"PATH": "/usr/bin:/bin", "LANG": "C"})
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def allowed(service, timer, jobs):
    return (service.get("LoadState") == "loaded" and service.get("ActiveState") == "inactive"
            and service.get("SubState") == "dead" and service.get("Result") == "success"
            and int(service.get("ExecMainExitTimestampMonotonic", "0")) > 0
            and timer.get("UnitFileState") == "enabled" and timer.get("ActiveState") == "active"
            and not any(j.get("unit") == "mrv1-production.service" for j in jobs))


def main():
    try:
        jobs = subprocess.run(["/usr/bin/systemctl", "list-jobs", "--no-legend", "--no-pager"],
            check=True, capture_output=True, text=True, timeout=5,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"})
        pending_jobs = parse_jobs(jobs.stdout)
        if "--dispatch" in sys.argv:
            worker = properties("trendatlas-evolution-worker.service")
            if not dispatch_allowed(worker, pending_jobs):
                return 1
        return 0 if allowed(properties("mrv1-production.service"), properties("mrv1-production.timer"),
                            pending_jobs) else 1
    except (ValueError, OSError, subprocess.SubprocessError):
        return 1


def dispatch_allowed(worker, jobs):
    # Only this single dispatcher may indirectly start the worker. Never replace
    # a pending worker stop/start job (especially during production preemption).
    return (worker.get("LoadState") == "loaded" and worker.get("ActiveState") in ("inactive", "failed")
            and not any(j.get("unit") in ("mrv1-production.service", "trendatlas-evolution-worker.service")
                        for j in jobs))


def parse_jobs(text):
    jobs = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 4 or not fields[0].isdigit():
            raise ValueError("Unrecognized systemd job listing")
        jobs.append({"unit": fields[1]})
    return jobs


if __name__ == "__main__":
    sys.exit(main())
