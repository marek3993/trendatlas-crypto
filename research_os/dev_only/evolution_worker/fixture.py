"""Synthetic, explicitly requested integration dry-run; never market history."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import time

from . import runtime


def fixture_job(manifest):
    start = date(2017, 1, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(440)]
    raw = ("date,open,high,low,close,volume\n" + "".join(
        f"{day},100,101,99,100,1000\n" for day in days)).encode()
    study = json.loads(runtime.engine.STUDY_PATH.read_bytes())
    study["experiment_id"] = "fixture_flat_prices_v1"
    study["input_sha256"] = runtime.digest(raw)
    study["folds"] = [{"id": f"fixture_{i}", "start": days[200+i*30], "end": days[229+i*30]} for i in range(8)]
    job = {"schema_version": 1, "job_id": study["experiment_id"], "mode": "fixture",
           "engine": "btc_mean_reversion_v1", "study": study,
           "preregistration_commit": manifest["source_commit"],
           "release_sha256": manifest["release_sha256"], "input_name": "synthetic.csv",
           "input_sha256": runtime.digest(raw)}
    return job, raw


def probe_sandbox(input_path):
    import socket
    hidden = not os.access("/opt/market_regime_v1", os.R_OK)
    secret_denied = all(not os.access(p, os.R_OK) for p in (
        "/etc/default/trendatlas-multi-account", "/etc/credstore.encrypted",
        "/run/credentials/mrv1-production.service"))
    readonly = bool(os.statvfs(input_path).f_flag & os.ST_RDONLY)
    network_denied = False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.close()
    except OSError:
        network_denied = True
    assert os.geteuid() != 0 and 1000 not in os.getgroups()
    assert hidden and secret_denied and readonly and network_denied
    assert os.getpriority(os.PRIO_PROCESS, 0) == 19
    return {"uid": os.geteuid(), "production_hidden": hidden, "secret_paths_denied": secret_denied,
            "input_mount_read_only": readonly, "inet_socket_denied": network_denied, "nice": 19}


def run_fixture(release, state, probe_input=None):
    state = runtime.state_path(state)
    manifest = runtime.verify_release(release)
    sandbox = probe_sandbox(probe_input) if probe_input else None
    job, raw = fixture_job(manifest)
    runtime.atomic_bytes(state / "fixture-input" / "synthetic.csv", raw)
    runtime.atomic_json(state / "queue" / job["job_id"] / "study.json", job)
    start = time.monotonic()
    result = runtime.run_once(release, state, state / "fixture-input", allow_fixture=True)
    root = state / "jobs" / job["job_id"]
    seal_before = (root / "SEALED.json").read_bytes()
    # A second invocation must be idle and must not touch sealed data.
    second = runtime.run_once(release, state, state / "fixture-input", allow_fixture=True)
    assert second["status"] == "IDLE"
    assert seal_before == (root / "SEALED.json").read_bytes()
    report = json.loads((root / "report.json").read_bytes())
    assert report["meta"]["outcome"] == "HISTORICAL_REJECT"
    assert report["meta"]["completed_generations"] == 5
    assert report["evaluated_candidates"] == 26
    return {"fixture_only": True, "new_historical_search": False, "result": result, "sandbox": sandbox,
            "second_invocation": second, "completed_generations": 5, "evaluated_candidates": 26,
            "elapsed_seconds": round(time.monotonic()-start, 3),
            "state_bytes": sum(p.stat().st_size for p in state.rglob("*") if p.is_file()),
            "audit": str(root / "audit.json"), "release_sha256": manifest["release_sha256"]}
