"""Transactional 10/6/4 controller with a sealed final test."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import time
import uuid

from .backtest import (
    Bar, DOMAINS, WARMUP, backtest, candidate_id, canonical, cash_backtest,
    read_bars,
)
from .protocol import comparison, stability_decision, validate_protocol

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path("outputs/research_os/dev_only/evolution")


def code_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    digest.update((Path(__file__).parent / "CONTRACT.md").read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def database_path(root, run_id):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", run_id):
        raise ValueError("Invalid run ID")
    root = Path(root).resolve()
    path = root / OUTPUT / run_id / "research.sqlite3"
    # Reject links in every output component, including the SQLite sidecars.
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("Research output links are forbidden")
    if not path.resolve().is_relative_to(root / OUTPUT):
        raise ValueError("Research output escaped its registered root")
    for suffix in ("-journal", "-wal", "-shm"):
        if Path(str(path) + suffix).is_symlink():
            raise ValueError("SQLite sidecar link is forbidden")
    return path


def connect(root, run_id):
    path = database_path(root, run_id)
    if not path.is_file():
        raise ValueError("Unknown research run")
    db = sqlite3.connect(path, timeout=1)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    return db


def metadata(db):
    return json.loads(db.execute("SELECT payload FROM meta WHERE id=1").fetchone()[0])


def save_meta(db, value):
    db.execute("UPDATE meta SET payload=? WHERE id=1", (canonical(value),))


def frozen_check(meta):
    if meta["code_sha256"] != code_hash():
        raise ValueError("Code changed: resume/final test requires the frozen implementation")
    if meta["state"] == "SEALED":
        raise ValueError("Final test already consumed; this run is sealed")


def population(rng):
    result = {}
    while len(result) < 10:
        genes = {key: rng.choice(values) for key, values in DOMAINS.items()}
        result[candidate_id(genes)] = genes
    return result


def validation_folds(meta):
    start = date.fromisoformat(meta["validation_start"])
    end = date.fromisoformat(meta["validation_end"])
    days = (end - start).days + 1
    if days < 180:
        raise ValueError("Validation needs at least two 90-day folds")
    first_end = start + timedelta(days=days // 2 - 1)
    return (
        ("validation_1", start.isoformat(), first_end.isoformat()),
        ("validation_2", (first_end + timedelta(days=1)).isoformat(), end.isoformat()),
    )


def rank_candidates(fold_scores):
    """Prefer the strongest weak period, then mean performance."""
    return sorted(
        fold_scores,
        key=lambda cid: (
            -min(fold_scores[cid]),
            -(sum(fold_scores[cid]) / len(fold_scores[cid])),
            cid,
        ),
    )


def adjacent_children(survivors, genes_by_id, seen, rng):
    """Return four unseen mutations moving exactly one domain step."""
    choices = {}
    for parent in survivors:
        genes = genes_by_id[parent]
        for key, domain in DOMAINS.items():
            index = domain.index(genes[key])
            for next_index in (index - 1, index + 1):
                if 0 <= next_index < len(domain):
                    child = dict(genes)
                    child[key] = domain[next_index]
                    cid = candidate_id(child)
                    if cid not in seen and cid not in choices:
                        choices[cid] = (child, parent)
    ids = sorted(choices)
    if len(ids) < 4:
        raise ValueError("Could not produce four unseen adjacent mutations")
    selected = rng.sample(ids, 4)
    return [(cid, *choices[cid]) for cid in selected]


def initialize(root, run_id, input_path, *, train_start, train_end, validation_end,
               holdout_end, generations=3, seed=20260920, cost_bps=15.0, max_seconds=300,
               evaluation_protocol=None):
    if type(generations) is not int or not 1 <= generations <= 100:
        raise ValueError("Generation budget must be 1..100")
    if not 1 <= max_seconds <= 3600 or not 0 <= cost_bps <= 100:
        raise ValueError("Invalid time or cost budget")
    dates = [date.fromisoformat(s) for s in (train_start, train_end, validation_end, holdout_end)]
    if not dates[0] < dates[1] < dates[2] < dates[3]:
        raise ValueError("Train, validation and final test must be ordered and disjoint")
    if (dates[1] - dates[0]).days < 90 or (dates[3] - dates[2]).days < 90:
        raise ValueError("Training and final-test periods need at least 90 days")
    if (dates[2] - dates[1]).days < 180:
        raise ValueError("Validation needs at least two 90-day folds")
    raw = Path(input_path).read_bytes()
    bars = read_bars(raw)
    day_set = {bar.day for bar in bars}
    if any(day not in day_set for day in (train_start, train_end, validation_end, holdout_end)):
        raise ValueError("Input does not cover all frozen boundaries")
    if sum(bar.day < train_start for bar in bars) < WARMUP:
        raise ValueError("Insufficient training warmup")
    input_digest = hashlib.sha256(raw).hexdigest()
    if evaluation_protocol is not None:
        # Store a detached canonical copy; later changes to the spec cannot alter a run.
        evaluation_protocol = json.loads(canonical(evaluation_protocol))
        validate_protocol(evaluation_protocol, {
            "experiment_id": run_id, "input_sha256": input_digest,
            "train_start": train_start, "train_end": train_end,
            "validation_end": validation_end, "holdout_end": holdout_end,
            "generations": generations, "seed": seed, "cost_bps": cost_bps,
        })
    path = database_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwrite or a duplicate final test.
    with path.open("xb"):
        pass
    meta = {
        "schema_version": 1, "run_id": run_id, "state": "SEARCH",
        "dev_only": True, "non_authoritative": True, "iml_required": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(Path(input_path).resolve()),
        "input_sha256": input_digest, "code_sha256": code_hash(),
        "train_start": train_start, "train_end": train_end,
        "validation_start": (dates[1] + timedelta(days=1)).isoformat(),
        "validation_end": validation_end,
        "holdout_start": (dates[2] + timedelta(days=1)).isoformat(), "holdout_end": holdout_end,
        "generations": generations, "completed_generations": 0, "seed": seed,
        "cost_bps": cost_bps, "max_seconds_per_operation": max_seconds,
        "population_size": 10, "survivors": 6, "mutations": 4,
        "fitness": "rank_worst_then_mean_of_two_validation_fold_cagr_minus_2_absolute_max_drawdown",
        "adapter": "btc_daily_long_cash_trend_momentum_volatility_v1",
        "domains": DOMAINS, "champion": None,
    }
    if evaluation_protocol is not None:
        meta["evaluation_protocol"] = evaluation_protocol
        meta["evaluation_protocol_sha256"] = hashlib.sha256(canonical(evaluation_protocol).encode()).hexdigest()
        meta["final_period_role"] = "retrospective_controls_plus_already_seen_exploration"
    db = connect(root, run_id)
    try:
        with db:
            db.executescript("""
                CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE bars (day TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE candidates (id TEXT PRIMARY KEY, genes TEXT NOT NULL, parent TEXT REFERENCES candidates(id), born INTEGER NOT NULL);
                CREATE TABLE populations (generation INTEGER, slot INTEGER, candidate TEXT REFERENCES candidates(id), PRIMARY KEY(generation,slot), UNIQUE(generation,candidate));
                CREATE TABLE evaluations (candidate TEXT REFERENCES candidates(id), split TEXT, metrics TEXT NOT NULL, PRIMARY KEY(candidate,split));
                CREATE TABLE curves (candidate TEXT REFERENCES candidates(id), split TEXT, day TEXT, equity REAL, weight REAL, PRIMARY KEY(candidate,split,day));
                CREATE TABLE trades (candidate TEXT REFERENCES candidates(id), split TEXT, ordinal INTEGER, payload TEXT, PRIMARY KEY(candidate,split,ordinal));
                CREATE TABLE generations (generation INTEGER PRIMARY KEY, survivors TEXT, mutations TEXT);
                CREATE TABLE final_test (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            """)
            db.execute("INSERT INTO meta VALUES (1,?)", (canonical(meta),))
            db.executemany("INSERT INTO bars VALUES (?,?)", [(bar.day, canonical(asdict(bar))) for bar in bars if bar.day <= holdout_end])
            for slot, (cid, genes) in enumerate(population(random.Random(seed)).items()):
                db.execute("INSERT INTO candidates VALUES (?,?,NULL,0)", (cid, canonical(genes)))
                db.execute("INSERT INTO populations VALUES (0,?,?)", (slot, cid))
    finally:
        db.close()
    return meta


def load_bars(db, end):
    return [Bar(**json.loads(row[0])) for row in db.execute("SELECT payload FROM bars WHERE day<=? ORDER BY day", (end,))]


def store_evaluation(db, cid, split, result):
    db.execute("INSERT INTO evaluations VALUES (?,?,?)", (cid, split, canonical(result["metrics"])))
    db.executemany("INSERT INTO curves VALUES (?,?,?,?,?)", [(cid, split, row["day"], row["equity"], row["weight"]) for row in result["curve"]])
    db.executemany("INSERT INTO trades VALUES (?,?,?,?)", [(cid, split, n, canonical(row)) for n, row in enumerate(result["trades"])])


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("Research operation exceeded its wall-time budget; transaction rolled back")


def evolve(root, run_id):
    db = connect(root, run_id)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            meta = metadata(db)
            frozen_check(meta)
            generation = meta["completed_generations"]
            if generation >= meta["generations"]:
                raise ValueError("Search budget exhausted; only final testing is allowed")
            deadline = time.monotonic() + meta["max_seconds_per_operation"]
            # The selection path cannot access final-test bars.
            bars = load_bars(db, meta["validation_end"])
            rows = db.execute("SELECT c.id,c.genes FROM populations p JOIN candidates c ON c.id=p.candidate WHERE p.generation=? ORDER BY p.slot", (generation,)).fetchall()
            if len(rows) != 10:
                raise ValueError("Population is not exactly ten")
            scores, fold_scores, genes_by_id = {}, {}, {}
            for cid, raw in rows:
                genes = genes_by_id[cid] = json.loads(raw)
                evaluations = (
                    ("train", meta["train_start"], meta["train_end"]),
                    *validation_folds(meta),
                )
                fold_scores[cid] = []
                for split, start, end in evaluations:
                    check_deadline(deadline)
                    cached = db.execute("SELECT metrics FROM evaluations WHERE candidate=? AND split=?", (cid, split)).fetchone()
                    if cached:
                        measured = json.loads(cached[0])
                    else:
                        result = backtest(bars, genes, start, end, meta["cost_bps"])
                        store_evaluation(db, cid, split, result)
                        measured = result["metrics"]
                    if split.startswith("validation_"):
                        fold_scores[cid].append(measured["fitness"])
                scores[cid] = min(fold_scores[cid])
            survivors = rank_candidates(fold_scores)[:6]
            seen = {row[0] for row in db.execute("SELECT id FROM candidates")}
            rng = random.Random(meta["seed"] + generation + 1)
            selected_children = adjacent_children(survivors, genes_by_id, seen, rng)
            mutations = []
            for cid, child, parent in selected_children:
                check_deadline(deadline)
                seen.add(cid)
                mutations.append(cid)
                db.execute("INSERT INTO candidates VALUES (?,?,?,?)", (cid, canonical(child), parent, generation + 1))
            db.executemany("INSERT INTO populations VALUES (?,?,?)", [(generation + 1, n, cid) for n, cid in enumerate(survivors + mutations)])
            db.execute("INSERT INTO generations VALUES (?,?,?)", (generation, canonical(survivors), canonical(mutations)))
            meta["completed_generations"] += 1
            if meta["completed_generations"] == meta["generations"]:
                meta.update(state="FROZEN", champion=survivors[0])
            check_deadline(deadline)
            save_meta(db, meta)
            return {"generation": generation, "survivors": survivors, "mutations": mutations, "scores": scores, "state": meta["state"]}
    finally:
        db.close()


def finalize(root, run_id):
    db = connect(root, run_id)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            meta = metadata(db)
            frozen_check(meta)
            if meta["state"] != "FROZEN" or meta["completed_generations"] != meta["generations"]:
                raise ValueError("Complete the predeclared search budget before final testing")
            deadline = time.monotonic() + meta["max_seconds_per_operation"]
            cid = meta["champion"]
            genes = json.loads(db.execute("SELECT genes FROM candidates WHERE id=?", (cid,)).fetchone()[0])
            bars = load_bars(db, meta["holdout_end"])
            result = backtest(bars, genes, meta["holdout_start"], meta["holdout_end"], meta["cost_bps"])
            store_evaluation(db, cid, "final_test", result)
            baseline_id = "benchmark_buy_hold"
            db.execute("INSERT INTO candidates VALUES (?,?,NULL,-1)", (baseline_id, canonical(genes)))
            baseline = backtest(bars, genes, meta["holdout_start"], meta["holdout_end"], meta["cost_bps"], benchmark=True)
            store_evaluation(db, baseline_id, "final_test", baseline)
            cash_id = "benchmark_cash"
            db.execute("INSERT INTO candidates VALUES (?,?,NULL,-1)", (cash_id, canonical(genes)))
            cash = cash_backtest(bars, meta["holdout_start"], meta["holdout_end"])
            store_evaluation(db, cash_id, "final_test", cash)
            beats_cash_return = result["metrics"]["total_return"] > cash["metrics"]["total_return"]
            beats_cash_risk_adjusted = result["metrics"]["fitness"] > cash["metrics"]["fitness"]
            report = {"champion": cid, "genes": genes, "start": meta["holdout_start"], "end": meta["holdout_end"],
                      "candidate": result["metrics"], "buy_and_hold": baseline["metrics"],
                      "cash": cash["metrics"],
                      "research_decision": {
                          "beats_cash_return": beats_cash_return,
                          "beats_cash_risk_adjusted": beats_cash_risk_adjusted,
                          "status": "PASS" if beats_cash_return and beats_cash_risk_adjusted else "REJECT",
                      },
                      "dev_only": True, "non_authoritative": True, "promotion_allowed": False}
            protocol = meta.get("evaluation_protocol")
            if protocol is not None:
                expected_hash = hashlib.sha256(canonical(protocol).encode()).hexdigest()
                if expected_hash != meta["evaluation_protocol_sha256"]:
                    raise ValueError("Frozen evaluation protocol hash mismatch")
                controls = protocol["control_windows"]
                continuous = {"id": "control_continuous", "start": controls[0]["start"], "end": controls[-1]["end"]}
                comparisons = []
                for window in [*controls, continuous, protocol["exploratory"]]:
                    check_deadline(deadline)
                    # Only prior observations can warm up each forward window.
                    window_bars = [bar for bar in bars if bar.day <= window["end"]]
                    candidate_result = backtest(window_bars, genes, window["start"], window["end"], meta["cost_bps"])
                    btc_result = backtest(window_bars, genes, window["start"], window["end"], meta["cost_bps"], benchmark=True)
                    cash_result = cash_backtest(window_bars, window["start"], window["end"])
                    for result_id, measured in ((cid, candidate_result), (baseline_id, btc_result), (cash_id, cash_result)):
                        store_evaluation(db, result_id, window["id"], measured)
                    comparisons.append({**window, **comparison(candidate_result["metrics"], cash_result["metrics"], btc_result["metrics"])})
                report["mixed_period_decision_diagnostic_only"] = report["research_decision"]
                report["chronological_controls"] = comparisons[:-2]
                report["continuous_controls"] = comparisons[-2]
                report["seen_exploratory"] = comparisons[-1]
                report["research_decision"] = stability_decision(comparisons[:-2], comparisons[-2], comparisons[-1])
                report["final_period_role"] = meta["final_period_role"]
            check_deadline(deadline)
            db.execute("INSERT INTO final_test VALUES (1,?)", (canonical(report),))
            meta["state"] = "SEALED"
            save_meta(db, meta)
            return report
    finally:
        db.close()


def status(root, run_id):
    db = connect(root, run_id)
    try:
        meta = metadata(db)
        final = db.execute("SELECT payload FROM final_test WHERE id=1").fetchone()
        return {"metadata": meta, "final_test": json.loads(final[0]) if final else None,
                "database": str(database_path(root, run_id)),
                "evaluation_count": db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]}
    finally:
        db.close()


def export_report(root, run_id):
    """Readable snapshot, generated only from committed database records."""
    db = connect(root, run_id)
    try:
        db.execute("BEGIN")
        meta = metadata(db)
        final = db.execute("SELECT payload FROM final_test WHERE id=1").fetchone()
        report = {"metadata": meta, "final_test": json.loads(final[0]) if final else None,
                  "generations": [{"generation": g, "survivors": json.loads(s), "mutations": json.loads(m)}
                                  for g, s, m in db.execute("SELECT * FROM generations ORDER BY generation")],
                  "evaluations": [{"candidate": cid, "split": split, **json.loads(measured)}
                                  for cid, split, measured in db.execute("SELECT * FROM evaluations ORDER BY candidate,split")]}
    finally:
        db.close()
    directory = database_path(root, run_id).parent
    temp = directory / ("report-" + uuid.uuid4().hex + ".tmp")
    with temp.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    destination = directory / "report.json"
    os.replace(temp, destination)
    return {"report": str(destination), "state": meta["state"]}
