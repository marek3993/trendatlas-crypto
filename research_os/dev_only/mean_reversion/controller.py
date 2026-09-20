"""Preregistered retrospective study; local SQLite only, no production interfaces."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import statistics
import time

from .backtest import Bar, DOMAINS, STUDY_PATH, backtest, candidate_id, canonical, read_bars

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path("outputs/research_os/dev_only/mean_reversion")
PREREGISTRATION_COMMIT = "16d15998e62778d1fce02dbf8824ddcfa5e9a6eb"
REJECT = "HISTORICAL_REJECT"
QUALIFIED = "HISTORICAL_QUALIFIED_AWAITING_FORWARD"


def code_hash():
    paths = list(Path(__file__).parent.glob("*.py"))
    paths += [STUDY_PATH, STUDY_PATH.with_name("CONTRACT.md"),
              Path(__file__).parents[1] / "evolution" / "backtest.py"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def load_study():
    return json.loads(STUDY_PATH.read_text(encoding="utf-8"))


def validate_study(study, bars):
    fixed = {"domains": DOMAINS, "seed": 20260920, "generations": 5,
             "population": 10, "survivors": 6, "mutations": 4,
             "cost_bps_one_way": 15, "max_annualized_turnover": 24.0,
             "warmup_days": 200, "max_seconds_per_generation": 300,
             "data_role": "development_retrospective_only", "iml_required": False,
             "production_promotion_allowed": False, "output_root": OUTPUT.as_posix(),
             "allowed_outcomes": [REJECT, QUALIFIED]}
    if any(study.get(k) != v for k, v in fixed.items()):
        raise ValueError("Study violates the preregistered contract")
    folds = study["folds"]
    if len(folds) != 8 or len({f["id"] for f in folds}) != 8:
        raise ValueError("Eight distinct chronological folds required")
    days = {b.day for b in bars}
    previous_end = None
    for fold in folds:
        start, end = (date.fromisoformat(fold[k]) for k in ("start", "end"))
        if start >= end or (previous_end and start != previous_end + timedelta(days=1)):
            raise ValueError("Folds must be chronological, contiguous and disjoint")
        if start.isoformat() not in days or end.isoformat() not in days:
            raise ValueError("Fold boundaries missing from input")
        if sum(b.day < fold["start"] for b in bars) < 200:
            raise ValueError("Insufficient warmup")
        if fold["id"] in ("continuous", "cash", "btc"):
            raise ValueError("Reserved period name")
        previous_end = end


def database_path(root, run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ValueError("Invalid run ID")
    root = Path(root).resolve()
    path = root / OUTPUT / run_id / "research.sqlite3"
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Output links and junctions are forbidden")
    if not path.resolve().is_relative_to(root / OUTPUT):
        raise ValueError("Output escaped research root")
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.is_symlink() or sidecar.is_junction():
            raise ValueError("SQLite sidecar links are forbidden")
        if sidecar.exists() and sidecar.stat().st_nlink > 1:
            raise ValueError("Hard-linked SQLite sidecars are forbidden")
    if path.exists() and path.stat().st_nlink > 1:
        raise ValueError("Hard-linked databases are forbidden")
    return path


def connect(root, run_id):
    path = database_path(root, run_id)
    if not path.is_file():
        raise ValueError("Unknown experiment")
    db = sqlite3.connect(path, timeout=1)
    db.execute("PRAGMA synchronous=FULL")
    return db


def metadata(db):
    return json.loads(db.execute("SELECT payload FROM meta").fetchone()[0])


def initial_population(rng):
    result = {}
    while len(result) < 10:
        genes = {key: rng.choice(values) for key, values in DOMAINS.items()}
        result[candidate_id(genes)] = genes
    return result


def adjacent_children(survivors, genes_by_id, seen, rng):
    choices = {}
    for parent in survivors:
        genes = genes_by_id[parent]
        for key, domain in DOMAINS.items():
            index = domain.index(genes[key])
            for next_index in (index - 1, index + 1):
                if 0 <= next_index < len(domain):
                    child = {**genes, key: domain[next_index]}
                    cid = candidate_id(child)
                    if cid not in seen and cid not in choices:
                        choices[cid] = (child, parent)
    if len(choices) < 4:
        raise ValueError("Four unseen adjacent mutations unavailable")
    return [(cid, *choices[cid]) for cid in rng.sample(sorted(choices), 4)]


def rank_candidates(scores, disqualified=()):
    return sorted((cid for cid in scores if cid not in disqualified), key=lambda cid: (
        -min(scores[cid]), -statistics.median(scores[cid]),
        -statistics.fmean(scores[cid]), cid))


def periods(study):
    return study["folds"] + [{"id": "continuous", "start": study["folds"][0]["start"],
                              "end": study["folds"][-1]["end"]}]


def initialize(root, run_id, input_path):
    study = load_study()
    if run_id != study["experiment_id"]:
        raise ValueError("Run ID must match the frozen preregistration")
    raw = Path(input_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != study["input_sha256"]:
        raise ValueError("Historical input changed")
    bars = read_bars(raw)
    validate_study(study, bars)
    path = database_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    meta = {"study": study, "study_sha256": hashlib.sha256(canonical(study).encode()).hexdigest(),
            "preregistration_commit": PREREGISTRATION_COMMIT, "code_sha256": code_hash(),
            "input_sha256": study["input_sha256"], "input_path": str(Path(input_path).resolve()),
            "state": "SEARCH", "completed_generations": 0, "outcome": None}
    db = connect(root, run_id)
    try:
        db.executescript("""
            CREATE TABLE meta(payload TEXT NOT NULL);
            CREATE TABLE bars(day TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE candidates(id TEXT PRIMARY KEY, genes TEXT NOT NULL, parent TEXT, born INTEGER);
            CREATE TABLE populations(generation INTEGER, slot INTEGER, candidate TEXT,
                PRIMARY KEY(generation, slot), UNIQUE(generation, candidate));
            CREATE TABLE evaluations(candidate TEXT, period TEXT, payload TEXT NOT NULL,
                PRIMARY KEY(candidate, period));
            CREATE TABLE generations(generation INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        """)
        with db:
            db.execute("INSERT INTO meta VALUES(?)", (canonical(meta),))
            db.executemany("INSERT INTO bars VALUES(?,?)", [(b.day, canonical(asdict(b))) for b in bars])
            population = initial_population(random.Random(study["seed"]))
            for slot, (cid, genes) in enumerate(population.items()):
                db.execute("INSERT INTO candidates VALUES(?,?,NULL,1)", (cid, canonical(genes)))
                db.execute("INSERT INTO populations VALUES(1,?,?)", (slot, cid))
    finally:
        db.close()
    return meta


def qualification(results):
    failures = []
    for period, metrics in results.items():
        if metrics["turnover_disqualified"]:
            failures.append(period + ":turnover")
        if metrics["total_return"] <= 0 or metrics["fitness"] <= 0:
            failures.append(period + ":cash_gate")
    return (REJECT if failures else QUALIFIED), failures


def step(root, run_id):
    db = connect(root, run_id)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            meta = metadata(db)
            if meta["state"] == "SEALED":
                raise ValueError("Experiment sealed; no additional generations")
            if meta["code_sha256"] != code_hash() or meta["study"] != load_study():
                raise ValueError("Frozen code or preregistration changed")
            study = meta["study"]
            generation = meta["completed_generations"] + 1
            if generation > 5:
                raise ValueError("Fixed generation budget exhausted")
            started = time.monotonic()
            bars = [Bar(**json.loads(r[0])) for r in db.execute("SELECT payload FROM bars ORDER BY day")]
            genes_by_id = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id,genes FROM candidates")}
            current = [r[0] for r in db.execute(
                "SELECT candidate FROM populations WHERE generation=? ORDER BY slot", (generation,))]
            if len(current) != 10:
                raise ValueError("Population contract violated")

            def evaluate(cid, genes, period, benchmark=None):
                row = db.execute("SELECT payload FROM evaluations WHERE candidate=? AND period=?",
                                 (cid, period["id"])).fetchone()
                if row:
                    return json.loads(row[0])["metrics"]
                result = backtest(bars, genes, period["start"], period["end"], benchmark=benchmark)
                if time.monotonic() - started > study["max_seconds_per_generation"]:
                    raise TimeoutError("Generation time budget exceeded; transaction rolled back")
                db.execute("INSERT INTO evaluations VALUES(?,?,?)", (cid, period["id"], canonical(result)))
                return result["metrics"]

            all_results, scores, disqualified = {}, {}, {}
            for cid in current:
                results = {p["id"]: evaluate(cid, genes_by_id[cid], p) for p in periods(study)}
                all_results[cid] = results
                scores[cid] = [results[p["id"]]["fitness"] for p in study["folds"]]
                breaches = [p for p, m in results.items() if m["turnover_disqualified"]]
                if breaches:
                    disqualified[cid] = breaches
            for benchmark in ("cash", "btc"):
                for period in periods(study):
                    evaluate(benchmark, genes_by_id[current[0]], period, benchmark)
            ranking = rank_candidates(scores, disqualified)
            survivors = ranking[:6]
            children = []
            if len(survivors) == 6:
                children = adjacent_children(survivors, genes_by_id, set(genes_by_id),
                                             random.Random(study["seed"] + generation))
                for cid, genes, parent in children:
                    db.execute("INSERT INTO candidates VALUES(?,?,?,?)",
                               (cid, canonical(genes), parent, generation + 1))
                for slot, cid in enumerate(survivors + [c[0] for c in children]):
                    db.execute("INSERT INTO populations VALUES(?,?,?)", (generation + 1, slot, cid))
            summary = {"generation": generation, "population": current, "ranking": ranking,
                       "scores": scores, "disqualified": disqualified, "survivors": survivors,
                       "mutations": [{"id": c[0], "genes": c[1], "parent": c[2]} for c in children]}
            db.execute("INSERT INTO generations VALUES(?,?)", (generation, canonical(summary)))
            meta["completed_generations"] = generation
            if len(survivors) < 6 or generation == 5:
                meta["state"] = "SEALED"
                meta["leader"] = ranking[0] if ranking else None
                if len(survivors) < 6:
                    meta.update(outcome=REJECT, reasons=["fewer_than_six_eligible_survivors"])
                else:
                    meta["outcome"], meta["reasons"] = qualification(all_results[ranking[0]])
                if meta["outcome"] == QUALIFIED:
                    meta["frozen_candidate"] = {"sha256": ranking[0], "genes": genes_by_id[ranking[0]]}
            db.execute("UPDATE meta SET payload=?", (canonical(meta),))
        return {"generation": summary, "meta": meta}
    finally:
        db.close()


def report(root, run_id):
    # Opening read-only prevents a report from changing a SEALED experiment.
    path = database_path(root, run_id)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        meta = metadata(db)
        summaries = [json.loads(r[0]) for r in db.execute("SELECT payload FROM generations ORDER BY generation")]
        leader = meta.get("leader")
        comparisons = {}
        for cid in (leader, "cash", "btc"):
            if cid:
                comparisons[cid] = {r[0]: json.loads(r[1])["metrics"] for r in db.execute(
                    "SELECT period,payload FROM evaluations WHERE candidate=? ORDER BY period", (cid,))}
        return {"meta": meta, "generations": summaries, "comparisons": comparisons,
                "candidate_count": db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
                "evaluated_candidates": db.execute(
                    "SELECT COUNT(DISTINCT candidate) FROM evaluations WHERE candidate NOT IN ('cash','btc')").fetchone()[0]}
    finally:
        db.close()


def export_report(root, run_id):
    result = report(root, run_id)
    if result["meta"]["state"] != "SEALED":
        raise ValueError("Only a sealed report can be exported")
    path = database_path(root, run_id).with_name("report.json")
    # Exclusive creation refuses existing files, symlinks and report overwrite.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return path
