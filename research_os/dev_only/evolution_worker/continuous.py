"""Autonomous succession of distinct, finite, SHA-pinned research cycles only."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import stat
import time

from research_os.dev_only.evolution.backtest import read_bars
from . import continuous_engine as engine, continuous_family as family, runtime as w
from . import campaign

POLICY = Path(__file__).with_name("continuous_policy.json")
SOURCE = Path("/opt/trendatlas-research/input/BTCUSDT_1d.csv")
STATE_NAME = "continuous"
POLICY_IDS = ("trend_momentum_base_v1", "trend_momentum_low_turnover_v1",
              "mean_reversion_entry_v1", "trend_momentum_pullback_protected_v1",
              "regime_ensemble_v1")
POLICY_FAMILIES = ("trend_momentum", "trend_low_turnover", "mean_reversion_entry",
                   "trend_momentum_protected", "regime_ensemble")
EVALUATION_RESERVATION_SECONDS = 300


def state_root(base):
    return w.state_path(base) / STATE_NAME


def policy_from_release(release):
    path = w.safe_path(Path(release) / POLICY.relative_to(Path(__file__).parents[3]))
    raw = path.read_bytes()
    value = json.loads(raw)
    if (value.get("schema_version") != 1 or value.get("mode") != "continuous_evolution_v1"
            or (value.get("generations"), value.get("population"), value.get("survivors"),
                value.get("mutations"), value.get("selection_fold_count"), value.get("fold_days"),
                value.get("warmup_days"), value.get("min_new_closed_days"),
                value.get("cost_bps_one_way"), value.get("max_annualized_turnover"),
                value.get("exposure_ceiling")) != (5, 10, 6, 4, 4, 180, 200, 30, 15, 24, 0.75)
            or tuple(t.get("id") for t in value.get("templates", [])) != POLICY_IDS
            or tuple(t.get("family_id") for t in value["templates"]) != POLICY_FAMILIES
            or any(not isinstance(t.get("domains"), dict) or t.get("seed", 0) <= 0
                   or any(not isinstance(v, list) or len(v) < 2 for v in t["domains"].values())
                   for t in value["templates"])):
        raise w.Blocked("Continuous policy contract changed")
    return value, hashlib.sha256(raw).hexdigest()


def authorization(base, manifest, release):
    root = state_root(base)
    auth = json.loads(w.safe_path(root / "authorization.json").read_bytes())
    policy, digest = policy_from_release(release)
    if (set(auth) != {"schema_version", "release_sha256", "source_commit", "policy_sha256", "activated_at"}
            or auth["schema_version"] != 1 or auth["release_sha256"] != manifest["release_sha256"]
            or auth["source_commit"] != manifest["source_commit"] or auth["policy_sha256"] != digest):
        raise w.Blocked("Continuous authorization/release changed")
    return auth, policy


def activate(base, manifest, release):
    """Root-only local enablement; no input or cycle is fabricated here."""
    root = state_root(base)
    if (root / "authorization.json").exists():
        raise w.Blocked("Continuous authorization already exists")
    policy, digest = policy_from_release(release)
    if policy["history_role"] != "seen_development_retrospective":
        raise w.Blocked("Historical status changed")
    auth = {"schema_version": 1, "release_sha256": manifest["release_sha256"],
            "source_commit": manifest["source_commit"], "policy_sha256": digest,
            "activated_at": time.time()}
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        import pwd
        account = pwd.getpwnam("trendatlas-research")
        os.chown(root, 0, account.pw_gid)
        root.chmod(0o1770)
    w.atomic_json(root / "authorization.json", auth)
    if os.name == "posix":
        os.chown(root / "authorization.json", 0, account.pw_gid)
    (root / "authorization.json").chmod(0o440)
    return {"mode": policy["mode"], "state": "ACTIVATED", "next_step": "automatic dispatcher admission"}


def ledger(root):
    path = w.safe_path(root / "ledger.sqlite3")
    for suffix in ("-journal", "-wal", "-shm"):
        w.safe_path(Path(str(path) + suffix))
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS inputs(sha TEXT PRIMARY KEY, last_day TEXT, seen_at REAL);
      CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE,
        input_sha TEXT, template_id TEXT, family_id TEXT, spec TEXT,
        state TEXT NOT NULL, outcome TEXT, reject_reasons TEXT, selection_reason TEXT,
        active_seconds REAL NOT NULL DEFAULT 0, created_at REAL);
    """)
    return db


def source_info(source):
    source = w.safe_path(source)
    if source.stat().st_size > 5 * w.MIB:
        raise w.Blocked("Read-only historical input exceeds 5 MiB")
    raw = source.read_bytes()
    bars = read_bars(raw, today=utc_today())
    if len(bars) > 10000 or len(bars) < 1100:
        raise w.Blocked("Input bar count outside frozen bounds")
    if date.fromisoformat(bars[-1].day) >= utc_today():
        raise w.Blocked("Only closed UTC daily bars may enter research")
    return raw, hashlib.sha256(raw).hexdigest(), bars


def utc_today():
    return datetime.now(timezone.utc).date()


def require_append_only_input(root, previous_sha, new_bars):
    frozen = w.safe_path(root / "inputs" / (previous_sha + ".csv")).read_bytes()
    old_bars = read_bars(frozen)
    if len(new_bars) <= len(old_bars) or new_bars[:len(old_bars)] != old_bars:
        raise w.Blocked("Read-only source rewrote or truncated frozen history")


def folds_for(bars, policy):
    size = policy["fold_days"]
    count = policy["selection_fold_count"] + 1
    if len(bars) < policy["warmup_days"] + count * size:
        raise w.Blocked("Insufficient chronological folds")
    selected = bars[-count * size:]
    folds = [{"id": "selection_" + str(index + 1), "start": selected[index * size].day,
              "end": selected[(index + 1) * size - 1].day} for index in range(count - 1)]
    assessment = {"id": "assessment", "start": selected[(count - 1) * size].day,
                  "end": selected[-1].day}
    if any(date.fromisoformat(b.day).toordinal() + 1 != date.fromisoformat(a.day).toordinal()
           for b, a in zip(selected, selected[1:])):
        raise w.Blocked("Chronological folds contain a missing day")
    return folds, assessment


def cycle_spec(template, input_sha, bars, policy, auth):
    folds, assessment = folds_for(bars, policy)
    value = {"schema_version": 1, "mode": policy["mode"], "template_id": template["id"],
             "family_id": template["family_id"], "domains": template["domains"], "seed": template["seed"],
             "input_sha256": input_sha, "input_last_closed_day": bars[-1].day,
             "release_sha256": auth["release_sha256"], "source_commit": auth["source_commit"],
             "policy_sha256": auth["policy_sha256"],
             "selection_folds": folds, "assessment": assessment,
             "generations": policy["generations"], "population": policy["population"],
             "survivors": policy["survivors"], "mutations": policy["mutations"],
             "cost_bps_one_way": policy["cost_bps_one_way"],
             "max_annualized_turnover": policy["max_annualized_turnover"],
             "cycle_elapsed_seconds": policy["cycle_elapsed_seconds"],
             "cycle_disk_bytes": policy["cycle_disk_bytes"],
             "history_role": policy["history_role"], "allowed_outcomes": policy["allowed_outcomes"]}
    fingerprint = w.digest(w.canonical(value).encode())
    return {**value, "cycle_id": "cycle_" + fingerprint[:20], "fingerprint": fingerprint}


def reject_category(reasons, report=None):
    if any("turnover" in reason for reason in reasons):
        return "turnover"
    if report and reasons == ["fewer_than_six_eligible_survivors"]:
        if any(g["disqualified"] for g in report["generations"]):
            return "turnover"
    if any("no_entries" in reason for reason in reasons):
        return "no_entries"
    if any("cash_gate" in reason for reason in reasons):
        return "cash_gate"
    return "insufficient_eligible" if reasons else "none"


def choose_template(policy, used, last_category):
    preferred = {"turnover": "trend_momentum_low_turnover_v1",
                 "cash_gate": "regime_ensemble_v1", "no_entries": "mean_reversion_entry_v1"}
    order = [preferred.get(last_category)] + list(POLICY_IDS)
    by_id = {template["id"]: template for template in policy["templates"]}
    return next((by_id[key] for key in order if key in by_id and key not in used), None)


def prior_reject_analysis(base):
    """Read the ten prior SEALED outcomes without reopening their databases writable."""
    result = {"prior_campaign": "btc_walk_forward_campaign_v3_20260922",
              "prior_rejects_expected": 10, "verified_sealed_rejects": 0,
              "negative_assessments": 0, "cash_tie_assessments": 0,
              "turnover_failures": 0, "no_entry_failures": 0,
              "evidence": "not_yet_verified"}
    try:
        auth = json.loads(w.safe_path(Path(base) / "campaign.json").read_bytes())
        studies = auth["definition"]["studies"]
        if len(studies) != 10:
            return result
        for study in studies:
            folder = w.safe_path(Path(base) / "jobs" / study["experiment_id"])
            seal = json.loads(w.safe_path(folder / "SEALED.json").read_bytes())
            if seal["outcome"] != engine.REJECT or w.sha(folder / "report.json") != seal["files"]["report.json"]:
                return result
            report = json.loads((folder / "report.json").read_bytes())
            if report["meta"]["outcome"] != engine.REJECT:
                return result
            result["verified_sealed_rejects"] += 1
            reasons = report["meta"].get("reasons", [])
            result["turnover_failures"] += any("turnover" in reason for reason in reasons)
            result["no_entry_failures"] += any("no_entries" in reason for reason in reasons)
            leader = report["meta"].get("leader")
            assessment = report["comparisons"].get(leader, {}).get("walk_forward_assessment", {})
            value = assessment.get("total_return")
            if value is not None:
                result["negative_assessments"] += value < -1e-12
                result["cash_tie_assessments"] += abs(value) <= 1e-12
        result["evidence"] = "verified_prior_sealed_reports"
    except (OSError, ValueError, KeyError, TypeError):
        result["evidence"] = "prior_reports_unavailable_or_incomplete"
    return result


def _ram_kib():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def replace_status(path, value):
    path = w.safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = w.safe_path(path.with_name(path.name + ".pending"))
    with temporary.open("wb") as handle:
        handle.write((w.canonical(value) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    w.sync_dir(path.parent)


def publish(root, state, *, cycle=None, last_reject_reason=None, next_change=None, reason=None, **extra):
    path = w.safe_path(root / "status.json")
    previous = json.loads(path.read_bytes()) if path.exists() else {}
    value = {"mode": "continuous_evolution_v1", "state": state,
             "campaign_id": ("input_" + cycle["input_sha256"][:16]) if cycle else previous.get("campaign_id"),
             "cycle_id": cycle["cycle_id"] if cycle else previous.get("cycle_id"),
             "template_id": cycle["template_id"] if cycle else previous.get("template_id"),
             "family_id": cycle["family_id"] if cycle else previous.get("family_id"),
             "generation": previous.get("generation", 0) if cycle is None else 0,
             "evaluated_candidates": previous.get("evaluated_candidates", 0) if cycle is None else 0,
             "candidate_count": previous.get("candidate_count", 0) if cycle is None else 0,
             "last_reject_reason": last_reject_reason if last_reject_reason is not None else previous.get("last_reject_reason"),
             "next_change": next_change if next_change is not None else previous.get("next_change"),
             "reason": reason, "updated_at": time.time(), "pid": os.getpid(),
             "cpu_seconds_current_activation": time.process_time(), "ram_kib": _ram_kib(),
             "active_seconds_current_cycle": previous.get("active_seconds_current_cycle", 0),
             "orders_sent": False, "production_promotion": False, "ai_api_used": False}
    if "legacy_reject_analysis" in previous:
        value["legacy_reject_analysis"] = previous["legacy_reject_analysis"]
    try:
        value["temperature_c"] = campaign.temperature()
    except (OSError, ValueError):
        value["temperature_c"] = None
    if cycle and (root / "cycles" / cycle["cycle_id"] / "research.sqlite3").exists():
        report = engine.report(root / "cycles" / cycle["cycle_id"])
        value.update(generation=report["meta"]["completed_generations"],
                     evaluated_candidates=report["evaluated_candidates"],
                     candidate_count=len(report["generations"][-1]["population"]) if report["generations"] else cycle["population"],
                     period_evaluations=report["period_evaluations"])
    value.update(extra)
    replace_status(path, value)
    return value


def read_status(base, *, inspect_system=False):
    root = state_root(base)
    path = w.safe_path(root / "status.json")
    error_path = w.safe_path(root / "error.json")
    value = (json.loads(path.read_bytes()) if path.exists() else
             {"mode": "continuous_evolution_v1",
              "state": "WAITING_FOR_DISPATCH" if (root / "authorization.json").exists() else "NOT_ACTIVATED"})
    if inspect_system:
        from . import gate
        try:
            service = gate.properties("trendatlas-evolution-worker.service")
            value["systemd_state"] = service.get("ActiveState")
            value["pid"] = int(service.get("MainPID", "0"))
            value["systemd_cpu_seconds"] = int(service.get("CPUUsageNSec", "0")) / 1e9
            if value.get("state") == "RUNNING" and service.get("ActiveState") != "active":
                value.update(state="PREEMPTED", reason="worker_inactive_resume_on_dispatch")
            value["temperature_c"] = campaign.temperature()
        except (OSError, ValueError):
            value["system_probe"] = "unavailable"
    if error_path.exists():
        try:
            value.update(state="ERROR", reason=json.loads(error_path.read_bytes())["reason"],
                         next_change="operator review")
        except (OSError, ValueError, KeyError):
            value.update(state="ERROR", reason="controller_error_latch_unreadable",
                         next_change="operator review")
    return value


def ready(base, manifest, release, source=SOURCE):
    root = state_root(base)
    if not (root / "authorization.json").exists():
        return False
    if (root / "error.json").exists():
        return False
    _, policy = authorization(base, manifest, release)
    path = root / "ledger.sqlite3"
    if not path.exists() or Path(str(path) + "-journal").exists():
        return True
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            if db.execute("SELECT 1 FROM cycles WHERE state='ERROR' LIMIT 1").fetchone():
                return False
            if db.execute("SELECT 1 FROM cycles WHERE state='RUNNING' LIMIT 1").fetchone():
                return True
            latest = db.execute("SELECT sha,last_day FROM inputs ORDER BY seen_at DESC LIMIT 1").fetchone()
            if not latest:
                return True
            count = db.execute("SELECT COUNT(*) FROM cycles WHERE input_sha=?", (latest[0],)).fetchone()[0]
            if count < len(policy["templates"]):
                return True
            raw, sha, bars = source_info(source)
            if sha == latest[0]:
                return False
            require_append_only_input(root, latest[0], bars)
            return (date.fromisoformat(bars[-1].day) - date.fromisoformat(latest[1])).days >= policy["min_new_closed_days"]
        finally:
            db.close()
    except (sqlite3.Error, OSError, ValueError):
        # Admit one worker so it can report an actual integrity/input error.
        return True


def guard(base, root, cycle=None, active_before=0, active_start=None):
    from . import gate
    if gate.main() != 0:
        raise w.Paused("production_priority")
    campaign.disk_guard(base)
    if cycle is not None:
        if active_start is None or active_before + time.monotonic() - active_start > cycle["cycle_elapsed_seconds"]:
            raise w.Blocked("Cycle active-time budget exhausted")
        folder = w.safe_path(root / "cycles" / cycle["cycle_id"])
        if folder.exists() and sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) >= cycle["cycle_disk_bytes"]:
            raise w.Paused("Cycle disk budget")
    latch = w.safe_path(root / "thermal.json")
    old = json.loads(latch.read_bytes()).get("paused", False) if latch.exists() else False
    try:
        temp = campaign.temperature()
    except (OSError, ValueError):
        raise w.Paused("thermal_sensor_unavailable")
    paused = temp >= 68 if old else temp > 75
    if not latch.exists() or old != paused:
        replace_status(latch, {"paused": paused, "temperature_c": temp})
    if paused:
        raise w.Paused("thermal_hysteresis_wait_below_68C")


def prepare(root, cycle):
    destination = w.safe_path(root / "cycles" / cycle["cycle_id"])
    if destination.exists():
        if (json.loads((destination / "accepted.json").read_bytes()) != cycle
                or w.sha(destination / "input.csv") != cycle["input_sha256"]):
            raise w.Blocked("Accepted cycle or input changed")
        if (destination / "SEALED.json").exists():
            seal(destination, cycle)
        else:
            with engine.connect(destination) as db:
                if engine.metadata(db)["spec"] != cycle:
                    raise w.Blocked("Checkpointed cycle spec changed")
        return destination
    staging = w.safe_path(root / "staging" / cycle["cycle_id"])
    if staging.exists():
        for path in staging.rglob("*"):
            w.safe_path(path)
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    raw = w.safe_path(root / "inputs" / (cycle["input_sha256"] + ".csv")).read_bytes()
    w.atomic_json(staging / "accepted.json", cycle)
    w.atomic_bytes(staging / "input.csv", raw)
    engine.initialize(staging, cycle)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, destination)
    w.sync_dir(destination.parent)
    return destination


def seal(folder, cycle, *, active_seconds=None):
    target = w.safe_path(folder / "SEALED.json")
    if target.exists():
        result = json.loads(target.read_bytes())
        for name, digest in result["files"].items():
            if w.sha(w.safe_path(folder / name)) != digest:
                raise w.Blocked("SEALED cycle changed")
        return result["outcome"]
    result = engine.report(folder)
    if result["meta"]["state"] != "SEALED":
        raise w.Blocked("Cannot seal incomplete cycle")
    charge_path = w.safe_path(folder / "final-charge.json")
    if charge_path.exists():
        charge = json.loads(charge_path.read_bytes())
        if charge.get("cycle_id") != cycle["cycle_id"] or not isinstance(charge.get("active_seconds"), (int, float)):
            raise w.Blocked("Frozen final active-time charge changed")
        active_seconds = charge["active_seconds"]
    else:
        if active_seconds is None:
            raise w.Blocked("Cycle active-time charge must precede SEALED audit")
        w.atomic_json(charge_path, {"cycle_id": cycle["cycle_id"], "active_seconds": active_seconds})
    result["active_seconds"] = active_seconds
    w.atomic_json(folder / "report.json", result)
    w.atomic_json(folder / "audit.json", {"cycle_id": cycle["cycle_id"],
        "fingerprint": cycle["fingerprint"], "family_id": cycle["family_id"],
        "release_sha256": cycle["release_sha256"], "input_sha256": cycle["input_sha256"],
        "outcome": result["meta"]["outcome"], "rejection_reasons": result["meta"]["reasons"],
        "active_seconds": active_seconds, "active_budget_seconds": cycle["cycle_elapsed_seconds"],
        "history_role": cycle["history_role"], "orders_sent": False,
        "production_writes": False, "ai_api_used": False})
    names = ["accepted.json", "input.csv", "research.sqlite3", "final-charge.json", "report.json", "audit.json"]
    if result["meta"]["outcome"] == engine.QUALIFIED:
        w.atomic_json(folder / "paper-monitor-proposal.json", {"candidate": result["meta"]["frozen_candidate"],
            "status": "REVIEW_REQUIRED_NOT_INSTALLED", "orders_allowed": False,
            "production_writes": False, "forward_start": "after_candidate_freeze"})
        names.append("paper-monitor-proposal.json")
    w.atomic_json(target, {"outcome": result["meta"]["outcome"],
                           "files": {name: w.sha(folder / name) for name in names}})
    for name in names + ["SEALED.json"]:
        (folder / name).chmod(stat.S_IRUSR | stat.S_IRGRP)
    return result["meta"]["outcome"]


def verify_sealed_rows(root, db):
    for (raw_spec, expected) in db.execute("SELECT spec,outcome FROM cycles WHERE state='SEALED'"):
        spec = json.loads(raw_spec)
        folder = w.safe_path(root / "cycles" / spec["cycle_id"])
        if (not (folder / "SEALED.json").exists()
                or json.loads(w.safe_path(folder / "accepted.json").read_bytes()) != spec
                or w.sha(folder / "input.csv") != spec["input_sha256"]
                or seal(folder, spec) != expected):
            raise w.Blocked("Previously SEALED cycle integrity changed")


def checkpoint_active(db, cycle, before, started, *, reservation_floor=0):
    if cycle is None or started is None:
        return before
    consumed = max(before + max(0, time.monotonic() - started), reservation_floor)
    with db:
        db.execute("UPDATE cycles SET active_seconds=? WHERE id=? AND state='RUNNING'",
                   (consumed, cycle["cycle_id"]))
    return consumed


def run(release, base, source=SOURCE, *, check_production=True):
    if set(os.environ) - w.ALLOWED_ENV:
        raise w.Blocked("Worker requires empty allowlisted environment")
    base = w.state_path(base)
    manifest = w.verify_release(release)
    auth, policy = authorization(base, manifest, release)
    root = state_root(base)
    with w.worker_lock(base):
        db = None
        current = None
        active_before = 0.0
        active_start = None
        active_reservation = 0.0
        previous_handler = signal.getsignal(signal.SIGTERM)
        def preempt(*_):
            raise w.Paused("production_preemption")
        signal.signal(signal.SIGTERM, preempt)
        try:
            if (root / "error.json").exists():
                return read_status(base)
            db = ledger(root)
            verify_sealed_rows(root, db)
            while True:
                if check_production:
                    guard(base, root)
                row = db.execute("SELECT spec,created_at FROM cycles WHERE state='ERROR' LIMIT 1").fetchone()
                if row:
                    return publish(root, "ERROR", reason="Prior cycle requires review")
                row = db.execute("SELECT spec,created_at,active_seconds FROM cycles WHERE state='RUNNING' ORDER BY created_at LIMIT 1").fetchone()
                if row:
                    current, created_at, active_before = json.loads(row[0]), row[1], row[2]
                    active_start = time.monotonic()
                    active_reservation = 0.0
                    raw = w.safe_path(root / "inputs" / (current["input_sha256"] + ".csv")).read_bytes()
                    if w.digest(raw) != current["input_sha256"]:
                        raise w.Blocked("Frozen input snapshot changed")
                else:
                    source_raw, input_sha, bars = source_info(source)
                    latest = db.execute("SELECT sha,last_day FROM inputs ORDER BY seen_at DESC LIMIT 1").fetchone()
                    if latest and latest[0] != input_sha:
                        require_append_only_input(root, latest[0], bars)
                        span = (date.fromisoformat(bars[-1].day) - date.fromisoformat(latest[1])).days
                        if span < policy["min_new_closed_days"]:
                            input_sha = latest[0]
                            source_raw = w.safe_path(root / "inputs" / (input_sha + ".csv")).read_bytes()
                            bars = read_bars(source_raw)
                    elif latest and latest[0] == input_sha:
                        source_raw = w.safe_path(root / "inputs" / (input_sha + ".csv")).read_bytes()
                    if not latest or latest[0] != input_sha:
                        w.atomic_bytes(root / "inputs" / (input_sha + ".csv"), source_raw)
                        with db:
                            db.execute("INSERT INTO inputs VALUES(?,?,?)", (input_sha, bars[-1].day, time.time()))
                    attempts = list(db.execute("SELECT template_id,outcome,reject_reasons FROM cycles WHERE input_sha=? ORDER BY created_at", (input_sha,)))
                    used = {r[0] for r in attempts}
                    last_reasons = json.loads(attempts[-1][2]) if attempts and attempts[-1][2] else []
                    category = ("qualified" if attempts and attempts[-1][1] == engine.QUALIFIED else
                                reject_category(last_reasons))
                    template = choose_template(policy, used, category)
                    if template is None:
                        return publish(root, "WAITING_FOR_NEW_DATA", current_input_sha256=input_sha,
                            reason="all_distinct_hypotheses_exhausted",
                            next_change="Wait for at least 30 additional closed UTC BTC daily bars")
                    current = cycle_spec(template, input_sha, bars, policy, auth)
                    prior_family = db.execute("SELECT family_id FROM cycles WHERE input_sha=? ORDER BY created_at DESC LIMIT 1", (input_sha,)).fetchone()
                    legacy = prior_reject_analysis(base) if not prior_family and not latest else None
                    if not prior_family and not latest:
                        detail = (str(legacy["negative_assessments"]) + " negative and " +
                                  str(legacy["cash_tie_assessments"]) + " cash-tie assessments verified; "
                                  if legacy and legacy["evidence"] == "verified_prior_sealed_reports" else
                                  "individual prior reports unavailable; ")
                        change = ("Prior bounded mean-reversion campaign rejected 10/10 studies; " +
                                  detail + "switch hypothesis to trend/momentum")
                    elif not prior_family:
                        change = "New append-only closed input; restart fixed hypothesis list with trend/momentum"
                    else:
                        change = ("After " + category + " result, switch " + prior_family[0] + " to " +
                                  template["family_id"] + " / " + template["id"])
                    created_at = time.time()
                    with db:
                        db.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (current["cycle_id"], current["fingerprint"], input_sha,
                             template["id"], template["family_id"], w.canonical(current),
                             "RUNNING", None, None, change, 0.0, created_at))
                    active_before = 0.0
                    active_start = time.monotonic()
                    active_reservation = 0.0
                    publish(root, "RUNNING", cycle=current, last_reject_reason=category if attempts else None,
                            next_change=change, reason="cycle_admitted",
                            **({"legacy_reject_analysis": legacy} if legacy else {}))
                folder = prepare(root, current)
                def protected_guard():
                    if check_production:
                        guard(base, root, current, active_before, active_start)
                def reserve_evaluation():
                    nonlocal active_reservation
                    charge = active_before + max(0, time.monotonic() - active_start) + EVALUATION_RESERVATION_SECONDS
                    if charge > current["cycle_elapsed_seconds"]:
                        raise w.Blocked("Insufficient active-time budget for one bounded evaluation")
                    with db:
                        db.execute("UPDATE cycles SET active_seconds=? WHERE id=? AND state='RUNNING'",
                                   (charge, current["cycle_id"]))
                    active_reservation = charge
                protected_guard.reserve_evaluation = reserve_evaluation
                def progress():
                    nonlocal active_reservation
                    active_reservation = 0.0
                    consumed = checkpoint_active(db, current, active_before, active_start)
                    publish(root, "RUNNING", cycle=current, reason="evaluating_frozen_cycle",
                            active_seconds_current_cycle=consumed)
                if engine.report(folder)["meta"]["state"] != "SEALED":
                    progress()
                while engine.report(folder)["meta"]["state"] != "SEALED":
                    protected_guard()
                    engine.step(folder, current, protected_guard, progress)
                report = engine.report(folder)
                if (folder / "SEALED.json").exists():
                    consumed = json.loads((folder / "audit.json").read_bytes())["active_seconds"]
                    outcome = seal(folder, current)
                elif (folder / "final-charge.json").exists():
                    consumed = json.loads((folder / "final-charge.json").read_bytes())["active_seconds"]
                    outcome = seal(folder, current)
                else:
                    consumed = checkpoint_active(db, current, active_before, active_start,
                                                 reservation_floor=active_reservation)
                    outcome = seal(folder, current, active_seconds=consumed)
                reasons = report["meta"].get("reasons", [])
                category = reject_category(reasons, report) if outcome == engine.REJECT else "qualified"
                with db:
                    db.execute("UPDATE cycles SET state='SEALED',outcome=?,reject_reasons=?,active_seconds=? "
                               "WHERE id=? AND state='RUNNING'",
                               (outcome, w.canonical(reasons), consumed, current["cycle_id"]))
                publish(root, "RUNNING", cycle=current, last_reject_reason=category,
                        reason="cycle_sealed_automatically_advancing", last_outcome=outcome,
                        active_seconds_current_cycle=consumed)
                current = None
                active_start = None
                active_reservation = 0.0
        except w.Paused as exc:
            if current and db is not None:
                consumed = checkpoint_active(db, current, active_before, active_start,
                                             reservation_floor=active_reservation)
            else:
                consumed = None
            state = "PREEMPTED" if "production" in str(exc) else "PAUSED_RESOURCE"
            return publish(root, state, cycle=current, reason=str(exc),
                           next_change="resume same immutable cycle on next dispatcher admission",
                           **({"active_seconds_current_cycle": consumed} if consumed is not None else {}))
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)
            w.atomic_json(root / "error.json", {"reason": reason, "at": time.time(),
                         "cycle_id": current["cycle_id"] if current else None})
            if current and db is not None:
                checkpoint_active(db, current, active_before, active_start,
                                  reservation_floor=active_reservation)
                with db:
                    db.execute("UPDATE cycles SET state='ERROR',reject_reasons=? WHERE id=? AND state='RUNNING'",
                               (w.canonical([reason]), current["cycle_id"]))
            return publish(root, "ERROR", cycle=current, reason=reason, next_change="operator review")
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            if db is not None:
                db.close()
