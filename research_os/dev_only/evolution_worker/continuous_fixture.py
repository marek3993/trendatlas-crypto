"""Two tiny synthetic cycles only; explicit acceptance command, never service run."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import re
import sqlite3
import time

from . import continuous as c, continuous_engine as engine, runtime as w


def run_fixture(release, base, *, phase="all", fixture_id=None):
    if phase not in ("all", "start", "resume"):
        raise ValueError("Unknown synthetic fixture phase")
    if fixture_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", fixture_id):
        raise ValueError("Invalid fixture ID")
    if phase != "all" and fixture_id is None:
        raise ValueError("A fixed fixture ID is required across processes")
    base = w.state_path(base)
    manifest = w.verify_release(release)
    scratch = w.safe_path(base / "fixtures" / (fixture_id or ("continuous_" + str(time.time_ns()))))
    if phase == "resume":
        if not scratch.is_dir():
            raise ValueError("Fixture checkpoint is missing")
    else:
        scratch.mkdir(parents=True, exist_ok=False)
    source = w.safe_path(scratch / "synthetic.csv")
    start = date(2020, 1, 1)
    raw = ("date,open,high,low,close,volume\n" + "".join(
        f"{start + timedelta(days=i)},100,101,99,100,1\n" for i in range(1200))).encode()
    if phase == "resume":
        if source.read_bytes() != raw:
            raise ValueError("Synthetic fixture input changed")
    else:
        w.atomic_bytes(source, raw)
    policy = json.loads(c.POLICY.read_bytes())
    policy["templates"] = [policy["templates"][0], policy["templates"][2]]
    policy.update(generations=1, population=2, survivors=1, mutations=0, fold_days=10)
    digest = w.digest(w.canonical(policy).encode())
    if phase == "resume":
        auth = json.loads((scratch / "continuous" / "authorization.json").read_bytes())
        if auth["release_sha256"] != manifest["release_sha256"] or auth["policy_sha256"] != digest:
            raise ValueError("Fixture release/policy changed between processes")
    else:
        w.atomic_json(scratch / "continuous" / "authorization.json", {"schema_version": 1,
            "release_sha256": manifest["release_sha256"], "source_commit": manifest["source_commit"],
            "policy_sha256": digest, "activated_at": time.time()})
    original_policy = c.policy_from_release
    original_step = engine.step
    original_temp = c.campaign.temperature
    original_disk = c.campaign.disk_guard
    c.policy_from_release = lambda _: (policy, digest)
    c.campaign.temperature = lambda: 50.0
    c.campaign.disk_guard = lambda _: None
    evaluations_before_restart = None
    try:
        if phase != "resume":
            fired = False
            def interrupt_once(folder, spec, guard, progress):
                def checkpoint_then_interrupt():
                    nonlocal fired
                    progress()
                    if not fired:
                        fired = True
                        raise SystemExit("fixture_restart_after_committed_evaluation")
                return original_step(folder, spec, guard, checkpoint_then_interrupt)
            engine.step = interrupt_once
            try:
                c.run(release, scratch, source=source, check_production=False)
            except SystemExit as error:
                if str(error) != "fixture_restart_after_committed_evaluation":
                    raise
            else:
                raise AssertionError("Fixture did not interrupt the committed checkpoint")
        db = sqlite3.connect(scratch / "continuous" / "ledger.sqlite3")
        try:
            first = db.execute("SELECT id FROM cycles").fetchone()[0]
        finally:
            db.close()
        first_root = scratch / "continuous" / "cycles" / first
        evaluations_before_restart = engine.report(first_root)["period_evaluations"]
        if evaluations_before_restart != 1:
            raise AssertionError("Fixture checkpoint did not commit exactly one period")
        if phase == "start":
            return {"mode": "synthetic_fixture_only", "phase": "checkpointed",
                    "fixture_id": fixture_id, "fixture_root": str(scratch),
                    "first_cycle_id": first, "periods_committed": evaluations_before_restart,
                    "orders_sent": False, "production_promotion": False}
        engine.step = original_step
        result = c.run(release, scratch, source=source, check_production=False)
        db = sqlite3.connect(scratch / "continuous" / "ledger.sqlite3")
        try:
            rows = list(db.execute("SELECT id,fingerprint,family_id,state,outcome,selection_reason "
                                   "FROM cycles ORDER BY created_at"))
        finally:
            db.close()
        if (result["state"] != "WAITING_FOR_NEW_DATA" or len(rows) != 2
                or [row[2] for row in rows] != ["trend_momentum", "mean_reversion_entry"]
                or len({row[1] for row in rows}) != 2
                or any(row[3:5] != ("SEALED", engine.REJECT) for row in rows)
                or any(not (scratch / "continuous" / "cycles" / row[0] / "SEALED.json").exists() for row in rows)):
            raise AssertionError("Fixture did not automatically seal and switch distinct cycles")
        if "switch trend_momentum to mean_reversion_entry" not in rows[1][5]:
            raise AssertionError("Reasoned hypothesis transition missing")
        return {"mode": "synthetic_fixture_only", "passed": True,
                "first_family": rows[0][2], "second_family": rows[1][2],
                "first_fingerprint": rows[0][1], "second_fingerprint": rows[1][1],
                "first_periods_before_restart": evaluations_before_restart,
                "first_periods_after_resume": engine.report(first_root)["period_evaluations"],
                "cycles_sealed": 2, "final_state": result["state"],
                "orders_sent": False, "production_promotion": False,
                "fixture_root": str(scratch)}
    finally:
        engine.step = original_step
        c.policy_from_release = original_policy
        c.campaign.temperature = original_temp
        c.campaign.disk_guard = original_disk
