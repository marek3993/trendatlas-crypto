"""Finite local queue, immutable accepted jobs, crash-safe engine adapter."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat

from research_os.dev_only.mean_reversion import controller as engine
from research_os.dev_only.mean_reversion.backtest import canonical, read_bars

MIB = 1024 ** 2
FREE_FLOOR = 1024 * MIB
HEADROOM = 64 * MIB
STATE_BUDGET = 512 * MIB
DENIED_IDS = {"btc_pilot_20260920", "btc_cash_stability_v2_20260920",
              "btc_short_mean_reversion_v1_20260920"}
ALLOWED_ENV = {"PATH", "LANG", "LC_CTYPE", "HOME"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


class Blocked(ValueError):
    """Unsafe or changed job; do not alter its preregistration."""


class Paused(RuntimeError):
    """Temporary resource shortage; retry unchanged when resources recover."""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def safe_path(path):
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if part in (".", ".."):
            raise Blocked("Path traversal")
        current /= part
        if current.is_symlink() or current.is_junction():
            raise Blocked("Linked path component")
        if current.is_file() and current.stat().st_nlink != 1:
            raise Blocked("Hard-linked file")
    return path


def state_path(path):
    path = safe_path(path)
    lowered = path.as_posix().lower()
    if any(x in lowered for x in ("market_regime_v1", "home_automation", "/outputs/production",
                                 "/outputs/execution", "/etc/", "/run/credentials")):
        raise Blocked("Production/secret paths are forbidden")
    return path


def sync_dir(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_bytes(path, content):
    """Publish once; a retry must match byte for byte. Caller holds worker lock."""
    path = safe_path(path)
    if path.exists():
        if path.read_bytes() != content:
            raise Blocked("Immutable artifact mismatch: " + path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe_path(path.with_name(path.name + ".pending"))
    with temporary.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    sync_dir(path.parent)


def atomic_json(path, value):
    atomic_bytes(path, (canonical(value) + "\n").encode())


@contextmanager
def worker_lock(state):
    path = safe_path(state / "worker.lock")
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def check_disk(state):
    used = 0
    for path in state.rglob("*"):
        safe_path(path)
        if path.is_file():
            used += path.stat().st_size
    if used > STATE_BUDGET or shutil.disk_usage(state).free < FREE_FLOOR + HEADROOM:
        raise Paused("Disk reserve/state budget: leave job paused")


def verify_release(release):
    release = safe_path(release)
    manifest = json.loads(safe_path(release / "manifest.json").read_bytes())
    files = manifest["files"]
    identity = {"source_commit": manifest["source_commit"], "files": files}
    if digest(canonical(identity).encode()) != manifest["release_sha256"]:
        raise Blocked("Release manifest hash mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]):
        raise Blocked("Release must name a commit")
    for name, expected in files.items():
        p = safe_path(release / name)
        if not p.is_relative_to(release) or sha(p) != expected:
            raise Blocked("Release file hash mismatch")
    actual = {p.relative_to(release).as_posix() for p in release.rglob("*") if p.is_file()}
    if actual != set(files) | {"manifest.json"}:
        raise Blocked("Unregistered files in release")
    return manifest


def study_fingerprint(study):
    # Renaming a SEALED/duplicate study is not a fresh preregistration.
    return digest(canonical({k: v for k, v in study.items() if k != "experiment_id"}).encode())


def validate_job(job, manifest):
    fields = {"schema_version", "job_id", "mode", "engine", "study", "preregistration_commit",
              "release_sha256", "input_name", "input_sha256"}
    if set(job) != fields or job["schema_version"] != 1 or not NAME.fullmatch(job["job_id"]):
        raise Blocked("Malformed queue record")
    if job["engine"] != "btc_mean_reversion_v1" or job["mode"] not in ("research", "fixture"):
        raise Blocked("Unapproved engine/mode")
    if job["release_sha256"] != manifest["release_sha256"]:
        raise Blocked("Job pins a different release")
    if not re.fullmatch(r"[0-9a-f]{40}", job["preregistration_commit"]):
        raise Blocked("Preregistration commit required")
    study = job["study"]
    if study["experiment_id"] != job["job_id"] or study["input_sha256"] != job["input_sha256"]:
        raise Blocked("Study/job binding mismatch")
    expected_input = "BTCUSDT_1d.csv" if job["mode"] == "research" else "synthetic.csv"
    if job["input_name"] != expected_input or not re.fullmatch(r"[0-9a-f]{64}", job["input_sha256"]):
        raise Blocked("Only registered input basenames are allowed")
    if job["mode"] == "research" and (job["job_id"] in DENIED_IDS or
            study_fingerprint(study) == study_fingerprint(json.loads(engine.STUDY_PATH.read_bytes()))):
        raise Blocked("Old SEALED study cannot be searched again")
    # The engine's fixed semantics are not queue-configurable strings.
    template = json.loads(engine.STUDY_PATH.read_bytes())
    mutable_before_admission = {"experiment_id", "input_sha256", "folds", "base_commit"}
    if set(study) != set(template) or any(study[k] != template[k] for k in template if k not in mutable_before_admission):
        raise Blocked("Study changes the registered engine contract")


def ledger(state):
    path = safe_path(state / "queue.sqlite3")
    for suffix in ("-journal", "-wal", "-shm"):
        safe_path(Path(str(path) + suffix))
    db = sqlite3.connect(path, timeout=1)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, job_sha TEXT UNIQUE, "
               "study_sha TEXT UNIQUE, state TEXT NOT NULL, outcome TEXT, reason TEXT)")
    return db


@contextmanager
def study_adapter(study):
    # Only detached study injection; the frozen controller/math files are untouched.
    original = engine.load_study
    engine.load_study = lambda: json.loads(canonical(study))
    try:
        yield
    finally:
        engine.load_study = original


def read_engine_meta(job_root, job_id):
    path = engine.database_path(job_root, job_id)
    # An interrupted unsealed transaction may require SQLite hot-journal recovery.
    db = (sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
          if (job_root / "SEALED.json").exists() else engine.connect(job_root, job_id))
    try:
        return engine.metadata(db)
    finally:
        db.close()


def prepare_job(state, job, input_root):
    root = safe_path(state / "jobs" / job["job_id"])
    accepted = (canonical(job) + "\n").encode()
    if root.exists():
        if safe_path(root / "accepted.json").read_bytes() != accepted:
            raise Blocked("Accepted job changed")
        if sha(safe_path(root / "input.csv")) != job["input_sha256"]:
            raise Blocked("Frozen input changed")
        meta = read_engine_meta(root, job["job_id"])
        if meta["study"] != job["study"] or meta["code_sha256"] != engine.code_hash():
            raise Blocked("Engine study/code changed")
        return root
    source = safe_path(input_root / job["input_name"])
    if source.stat().st_size > 5 * MIB:
        raise Blocked("Input exceeds 5 MiB")
    raw = source.read_bytes()
    if digest(raw) != job["input_sha256"]:
        raise Blocked("Preregistered input SHA256 mismatch")
    bars = read_bars(raw)
    if len(bars) > 10000:
        raise Blocked("Input exceeds 10000 bars")
    engine.validate_study(job["study"], bars)
    staging = safe_path(state / "staging" / job["job_id"])
    if staging.exists():
        # Only our uncommitted initialization directory, never a live/SEALED job.
        for p in staging.rglob("*"):
            safe_path(p)
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    atomic_bytes(staging / "accepted.json", accepted)
    atomic_bytes(staging / "input.csv", raw)
    engine.initialize(staging, job["job_id"], staging / "input.csv")
    db = engine.connect(staging, job["job_id"])
    try:
        with db:
            meta = engine.metadata(db)
            meta["input_path"] = str(root / "input.csv")
            meta["preregistration_commit"] = job["preregistration_commit"]
            db.execute("UPDATE meta SET payload=?", (canonical(meta),))
    finally:
        db.close()
    root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, root)
    sync_dir(root.parent)
    return root


def finalize(root, job, manifest):
    dbpath = engine.database_path(root, job["job_id"])
    seal_path = safe_path(root / "SEALED.json")
    if seal_path.exists():
        seal = json.loads(seal_path.read_bytes())
        for name, expected in seal["files"].items():
            p = safe_path(root / name)
            if not p.is_relative_to(root) or sha(p) != expected:
                raise Blocked("SEALED artifact changed")
        return seal["outcome"]
    report = engine.report(root, job["job_id"])
    meta = report["meta"]
    if meta["state"] != "SEALED" or meta["outcome"] not in (engine.REJECT, engine.QUALIFIED):
        raise Blocked("Cannot finalize incomplete job")
    atomic_json(root / "report.json", report)
    names = ["accepted.json", "input.csv", "report.json", dbpath.relative_to(root).as_posix()]
    if meta["outcome"] == engine.QUALIFIED:
        atomic_json(root / "paper-monitor-proposal.json", {
            "status": "REVIEW_REQUIRED_NOT_INSTALLED", "candidate": meta["frozen_candidate"],
            "mode": "read_only_paper", "orders_allowed": False, "production_writes": False,
            "imports_forbidden": ["execution", "exchange"],
            "installation": "requires_separate_review_and_approval", "schedule": "after_successful_production_low_priority"})
        names.append("paper-monitor-proposal.json")
    atomic_json(root / "audit.json", {"job_id": job["job_id"], "outcome": meta["outcome"],
        "mode": job["mode"], "release_sha256": manifest["release_sha256"],
        "source_commit": manifest["source_commit"], "preregistration_commit": job["preregistration_commit"],
        "input_sha256": job["input_sha256"], "engine_code_sha256": meta["code_sha256"],
        "completed_generations": meta["completed_generations"], "production_writes": False,
        "orders_sent": False, "network_used": False, "ai_api_used": False})
    names.append("audit.json")
    seal = {"outcome": meta["outcome"], "files": {n: sha(root / n) for n in names}}
    atomic_json(seal_path, seal)
    # Logical immutable plus read-only permissions; worker never reopens engine DB writable.
    for name in names + ["SEALED.json"]:
        (root / name).chmod(stat.S_IRUSR | stat.S_IRGRP)
    return meta["outcome"]


def pending(state):
    """Read-only queue check for the dispatcher; no job creation."""
    state = state_path(state)
    paths = sorted((state / "queue").glob("*/study.json"))
    path = safe_path(state / "queue.sqlite3")
    known = {}
    if path.exists():
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            known = dict(db.execute("SELECT id,state FROM jobs"))
        finally:
            db.close()
    return "RUNNING" in known.values() or any(
        known.get(p.parent.name) not in ("SEALED", "BLOCKED") for p in paths)


def run_once(release, state, input_root, *, allow_fixture=False):
    if set(os.environ) - ALLOWED_ENV:
        raise Blocked("Worker requires an empty allowlisted environment")
    state = state_path(state)
    state.mkdir(parents=True, exist_ok=True)
    manifest = verify_release(release)
    with worker_lock(state):
        check_disk(state)
        db = ledger(state)
        try:
            # Resume accepted jobs even if the operator temporarily removes queue files.
            candidates = {p.parent.name: p for p in (state / "queue").glob("*/study.json")}
            for job_id, status in db.execute("SELECT id,state FROM jobs"):
                if status == "RUNNING" and job_id not in candidates:
                    candidates[job_id] = state / "jobs" / job_id / "accepted.json"
            for job_id, path in sorted(candidates.items()):
                if not NAME.fullmatch(job_id):
                    raise Blocked("Invalid queue directory name")
                safe_path(path)
                row = db.execute("SELECT job_sha,state FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row and row[1] == "BLOCKED":
                    continue
                if path.stat().st_size > 128 * 1024:
                    raise Blocked("Queue record exceeds 128 KiB")
                job = json.loads(path.read_bytes())
                validate_job(job, manifest)
                if job["job_id"] != job_id or (job["mode"] == "fixture" and not allow_fixture):
                    raise Blocked("Queue ID/fixture admission mismatch")
                job_sha = digest(canonical(job).encode())
                if row and row[0] != job_sha:
                    raise Blocked("Queue changed after admission")
                if row and row[1] == "SEALED":
                    finalize(state / "jobs" / job_id, job, manifest)
                    continue
                if row is None:
                    with db:
                        db.execute("INSERT INTO jobs VALUES(?,?,?,'RUNNING',NULL,NULL)",
                                   (job_id, job_sha, study_fingerprint(job["study"])))
                with study_adapter(job["study"]):
                    root = prepare_job(state, job, Path(input_root))
                    while read_engine_meta(root, job_id)["state"] != "SEALED":
                        check_disk(state)
                        engine.step(root, job_id)
                    outcome = finalize(root, job, manifest)
                with db:
                    db.execute("UPDATE jobs SET state='SEALED',outcome=? WHERE id=?", (outcome, job_id))
                return {"status": "SEALED", "job_id": job_id, "outcome": outcome}
            return {"status": "IDLE"}
        except (Blocked, ValueError, TimeoutError, sqlite3.IntegrityError) as exc:
            if "job_id" in locals() and NAME.fullmatch(job_id):
                with db:
                    db.execute("INSERT OR IGNORE INTO jobs(id,state,reason) VALUES(?,'BLOCKED',?)",
                               (job_id, type(exc).__name__ + ": " + str(exc)))
                    db.execute("UPDATE jobs SET state='BLOCKED',reason=? WHERE id=? AND state != 'SEALED'",
                               (type(exc).__name__ + ": " + str(exc), job_id))
            raise
        finally:
            db.close()
