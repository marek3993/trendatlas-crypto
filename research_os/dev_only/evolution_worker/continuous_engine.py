"""Checkpointed, finite evolution of one immutable continuous-research cycle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import time

from research_os.dev_only.evolution.backtest import canonical, read_bars
from . import continuous_family as family

REJECT = "HISTORICAL_REJECT"
QUALIFIED = "HISTORICAL_QUALIFIED_AWAITING_FORWARD"


def connect(root):
    db = sqlite3.connect(Path(root) / "research.sqlite3", timeout=5)
    db.execute("PRAGMA synchronous=FULL")
    return db


def metadata(db):
    return json.loads(db.execute("SELECT payload FROM meta").fetchone()[0])


def save(db, value):
    db.execute("UPDATE meta SET payload=?", (canonical(value),))


def periods(spec):
    folds = spec["selection_folds"]
    return folds + [{"id": "continuous", "start": folds[0]["start"], "end": folds[-1]["end"]}]


def initialize(root, spec):
    raw = (Path(root) / "input.csv").read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["input_sha256"]:
        raise ValueError("Frozen input SHA mismatch")
    if len(read_bars(raw)) < 200 + 5 * 2:
        raise ValueError("Insufficient closed daily bars")
    (Path(root) / "research.sqlite3").touch(exist_ok=False)
    db = connect(root)
    try:
        db.executescript("""
          CREATE TABLE meta(payload TEXT NOT NULL);
          CREATE TABLE candidates(id TEXT PRIMARY KEY, genes TEXT NOT NULL, parent TEXT, born INTEGER);
          CREATE TABLE populations(generation INTEGER, slot INTEGER, candidate TEXT,
            PRIMARY KEY(generation,slot), UNIQUE(generation,candidate));
          CREATE TABLE evaluations(candidate TEXT, period TEXT, payload TEXT,
            PRIMARY KEY(candidate,period));
          CREATE TABLE generations(generation INTEGER PRIMARY KEY, payload TEXT);
        """)
        rng = random.Random(spec["seed"])
        genes = {}
        for _ in range(2000):
            choice = {key: rng.choice(values) for key, values in spec["domains"].items()}
            cid = family.candidate_id(spec["family_id"], choice, spec["domains"])
            genes[cid] = choice
            if len(genes) == spec["population"]:
                break
        if len(genes) != spec["population"]:
            raise ValueError("Population domain cannot supply unique candidates")
        with db:
            db.execute("INSERT INTO meta VALUES(?)", (canonical({"spec": spec, "state": "SEARCH",
                "completed_generations": 0, "leader": None, "outcome": None, "reasons": []}),))
            for slot, (cid, choice) in enumerate(genes.items()):
                db.execute("INSERT INTO candidates VALUES(?,?,NULL,1)", (cid, canonical(choice)))
                db.execute("INSERT INTO populations VALUES(1,?,?)", (slot, cid))
    finally:
        db.close()


def adjacent_children(survivors, genes, seen, spec, generation):
    choices = {}
    for parent in survivors:
        for key, domain in spec["domains"].items():
            index = domain.index(genes[parent][key])
            for next_index in (index - 1, index + 1):
                if 0 <= next_index < len(domain):
                    child = {**genes[parent], key: domain[next_index]}
                    cid = family.candidate_id(spec["family_id"], child, spec["domains"])
                    if cid not in seen and cid not in choices:
                        choices[cid] = (child, parent)
    if len(choices) < spec["mutations"]:
        raise ValueError("Insufficient unseen adjacent mutations")
    rng = random.Random(spec["seed"] + generation)
    return [(cid, *choices[cid]) for cid in rng.sample(sorted(choices), spec["mutations"])]


def rank(scores, disqualified):
    return sorted((cid for cid in scores if cid not in disqualified), key=lambda cid: (
        -min(scores[cid]), -statistics.median(scores[cid]), -statistics.fmean(scores[cid]), cid))


def qualify(results):
    reasons = []
    for period, value in results.items():
        if value["turnover_disqualified"]:
            reasons.append(period + ":turnover")
        if value["entries"] == 0:
            reasons.append(period + ":no_entries")
        if value["total_return"] <= 0 or value["fitness"] <= 0:
            reasons.append(period + ":cash_gate")
    return (REJECT if reasons else QUALIFIED), reasons


def step(root, spec, guard, progress):
    """Each period commits independently; population selection commits atomically."""
    db = connect(root)
    try:
        info = metadata(db)
        if info["spec"] != spec or info["state"] == "SEALED":
            raise ValueError("Frozen spec changed or cycle already SEALED")
        raw = (Path(root) / "input.csv").read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["input_sha256"]:
            raise ValueError("Frozen input changed")
        bars = read_bars(raw)
        genes = {cid: json.loads(raw_genes) for cid, raw_genes in db.execute("SELECT id,genes FROM candidates")}

        def evaluate(cid, period, benchmark=None):
            old = db.execute("SELECT payload FROM evaluations WHERE candidate=? AND period=?",
                             (cid, period["id"])).fetchone()
            if old:
                return json.loads(old[0])["metrics"]
            guard()
            reserve = getattr(guard, "reserve_evaluation", None)
            if reserve is not None:
                reserve()
            choice = genes[cid] if benchmark is None else next(iter(genes.values()))
            visible = [bar for bar in bars if bar.day <= period["end"]]
            started = time.monotonic()
            def bounded():
                if time.monotonic() - started > 300:
                    raise TimeoutError("Single retrospective backtest exceeded 300 active seconds")
            result = family.backtest(visible, spec["family_id"], choice, spec["domains"],
                                     period["start"], period["end"], benchmark=benchmark,
                                     step_guard=bounded)
            bounded()
            guard()
            with db:
                db.execute("INSERT INTO evaluations VALUES(?,?,?)", (cid, period["id"],
                            canonical({"metrics": result["metrics"]})))
            progress()
            guard()
            return result["metrics"]

        if info["state"] == "SEARCH":
            generation = info["completed_generations"] + 1
            if generation > spec["generations"]:
                raise ValueError("Generation budget exhausted")
            population = [cid for (cid,) in db.execute(
                "SELECT candidate FROM populations WHERE generation=? ORDER BY slot", (generation,))]
            if len(population) != spec["population"]:
                raise ValueError("Population contract violated")
            scores, disqualified = {}, {}
            for cid in population:
                results = {p["id"]: evaluate(cid, p) for p in periods(spec)}
                scores[cid] = [results[p["id"]]["fitness"] for p in spec["selection_folds"]]
                breaches = [key for key, value in results.items() if value["turnover_disqualified"]]
                if breaches:
                    disqualified[cid] = breaches
            for benchmark in ("cash", "btc"):
                for period in periods(spec):
                    evaluate(benchmark, period, benchmark)
            ranking = rank(scores, disqualified)
            survivors = ranking[:spec["survivors"]]
            children = (adjacent_children(survivors, genes, set(genes), spec, generation)
                        if len(survivors) == spec["survivors"] and generation < spec["generations"] else [])
            summary = {"generation": generation, "population": population, "ranking": ranking,
                       "scores": scores, "disqualified": disqualified, "survivors": survivors,
                       "mutations": [{"id": cid, "genes": child, "parent": parent}
                                     for cid, child, parent in children]}
            with db:
                for cid, child, parent in children:
                    db.execute("INSERT INTO candidates VALUES(?,?,?,?)", (cid, canonical(child), parent, generation + 1))
                for slot, cid in enumerate(survivors + [c[0] for c in children]):
                    db.execute("INSERT INTO populations VALUES(?,?,?)", (generation + 1, slot, cid))
                db.execute("INSERT INTO generations VALUES(?,?)", (generation, canonical(summary)))
                info.update(completed_generations=generation, leader=ranking[0] if ranking else None)
                if len(survivors) < spec["survivors"]:
                    info.update(state="SEALED", outcome=REJECT, reasons=["fewer_than_six_eligible_survivors"])
                elif generation == spec["generations"]:
                    info.update(state="ASSESSMENT", frozen_candidate={"sha256": ranking[0], "genes": genes[ranking[0]]})
                save(db, info)
            progress()
            return info
        if info["state"] != "ASSESSMENT" or info["completed_generations"] != spec["generations"]:
            raise ValueError("Unexpected cycle lifecycle")
        cid = info["frozen_candidate"]["sha256"]
        assessment = evaluate(cid, spec["assessment"])
        for benchmark in ("cash", "btc"):
            evaluate(benchmark, spec["assessment"], benchmark)
        results = {p["id"]: evaluate(cid, p) for p in periods(spec)}
        results[spec["assessment"]["id"]] = assessment
        outcome, reasons = qualify(results)
        with db:
            info.update(state="SEALED", outcome=outcome, reasons=reasons)
            save(db, info)
        progress()
        return info
    finally:
        db.close()


def report(root):
    # Unsealed DBs are recovered by SQLite under worker.lock before this read.
    path = Path(root) / "research.sqlite3"
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        info = metadata(db)
        comparisons = {}
        for cid in (info.get("leader"), "cash", "btc"):
            if cid:
                comparisons[cid] = {period: json.loads(value)["metrics"] for period, value in db.execute(
                    "SELECT period,payload FROM evaluations WHERE candidate=?", (cid,))}
        return {"meta": info, "generations": [json.loads(value) for (value,) in db.execute(
                    "SELECT payload FROM generations ORDER BY generation")],
                "comparisons": comparisons,
                "evaluated_candidates": db.execute(
                    "SELECT COUNT(DISTINCT candidate) FROM evaluations WHERE candidate NOT IN ('cash','btc')").fetchone()[0],
                "period_evaluations": db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
                "history_role": "seen_development_retrospective", "production_pass": False}
    finally:
        db.close()
