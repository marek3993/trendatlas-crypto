"""Checkpointed development loop. Only this process writes the evaluation ledger."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import shutil
import sqlite3
import time

try:
    import fcntl
except ImportError:  # Windows test host; production is Linux.
    fcntl = None
    import msvcrt

from .engine import SPACE, canonical, digest, evaluate_fold, load_market, mutate, synthetic_market, validate_genes
from .compact import POLICY, proposal

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE.parents[1] / "source_of_truth" / "phase2_development_contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text())
FOLDS = CONTRACT["validation_folds"]
STRESSES = ("nominal", "double_cost", "delayed_entry", "neighbors")
MARKET = None


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temp.open("w") as stream:
        stream.write(canonical(body))
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


def connect(root, *, recover=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "research.sqlite", timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL,
      status TEXT NOT NULL, generation INTEGER NOT NULL, created TEXT NOT NULL,
      contract_hash TEXT NOT NULL, input_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL,
      generation INTEGER NOT NULL, family TEXT NOT NULL, genes TEXT NOT NULL,
      parent TEXT, mutation TEXT NOT NULL, seed INTEGER NOT NULL, created TEXT NOT NULL,
      FOREIGN KEY(cycle_id) REFERENCES cycles(id));
    CREATE TABLE IF NOT EXISTS evaluations(key TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
      fold INTEGER NOT NULL, stress TEXT NOT NULL, status TEXT NOT NULL,
      result TEXT, failure TEXT, finished TEXT,
      FOREIGN KEY(candidate_id) REFERENCES candidates(id));
    CREATE TABLE IF NOT EXISTS family_stage(cycle_id TEXT NOT NULL, family TEXT NOT NULL,
      generation INTEGER NOT NULL, state TEXT NOT NULL, request_hash TEXT,
      PRIMARY KEY(cycle_id,family,generation));
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, utc TEXT NOT NULL,
      kind TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit_chain(id INTEGER PRIMARY KEY, utc TEXT NOT NULL,
      kind TEXT NOT NULL, body TEXT NOT NULL, previous_hash TEXT NOT NULL, row_hash TEXT NOT NULL UNIQUE);
    CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_chain
      BEGIN SELECT RAISE(ABORT,'append_only_audit'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_chain
      BEGIN SELECT RAISE(ABORT,'append_only_audit'); END;
    CREATE TRIGGER IF NOT EXISTS completed_evaluation_immutable BEFORE UPDATE ON evaluations
      WHEN OLD.status='COMPLETE' AND (NEW.status!='COMPLETE' OR NEW.result!=OLD.result OR NEW.finished!=OLD.finished)
      BEGIN SELECT RAISE(ABORT,'completed_evaluation_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS evaluation_no_delete BEFORE DELETE ON evaluations
      BEGIN SELECT RAISE(ABORT,'evaluation_no_delete'); END;
    CREATE TRIGGER IF NOT EXISTS candidate_no_update BEFORE UPDATE ON candidates
      BEGIN SELECT RAISE(ABORT,'candidate_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS candidate_no_delete BEFORE DELETE ON candidates
      BEGIN SELECT RAISE(ABORT,'candidate_immutable'); END;
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS evaluations_by_candidate ON evaluations(candidate_id,fold,stress);
    CREATE INDEX IF NOT EXISTS candidates_by_cycle_family ON candidates(cycle_id,family,generation);
    CREATE INDEX IF NOT EXISTS candidates_by_family ON candidates(family);
    CREATE INDEX IF NOT EXISTS evaluations_by_status ON evaluations(status);
    """)
    # A killed evaluator may be retried; a completed key remains unique forever.
    if recover:
        with db:
            db.execute("UPDATE evaluations SET status='PENDING' WHERE status='RUNNING'")
    return db


def event(db, kind, **fields):
    stamp=utc();body=canonical(fields)
    previous=db.execute("SELECT row_hash FROM audit_chain ORDER BY id DESC LIMIT 1").fetchone()
    previous_hash=previous[0] if previous else "GENESIS"
    row_hash=hashlib.sha256(canonical([stamp,kind,body,previous_hash]).encode()).hexdigest()
    db.execute("INSERT INTO events(utc,kind,body) VALUES(?,?,?)", (stamp, kind, body))
    db.execute("INSERT INTO audit_chain(utc,kind,body,previous_hash,row_hash) VALUES(?,?,?,?,?)",
               (stamp,kind,body,previous_hash,row_hash))


def verify_chain(db):
    if db.execute("PRAGMA quick_check").fetchone()[0]!="ok" or db.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("sqlite_integrity")
    previous="GENESIS"
    for stamp,kind,body,stored_previous,row_hash in db.execute("SELECT utc,kind,body,previous_hash,row_hash FROM audit_chain ORDER BY id"):
        expected=hashlib.sha256(canonical([stamp,kind,body,previous]).encode()).hexdigest()
        if stored_previous!=previous or row_hash!=expected:
            raise RuntimeError("audit_chain_integrity")
        previous=row_hash


def fingerprints(market):
    code = hashlib.sha256((HERE / "engine.py").read_bytes()).hexdigest()
    contract = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    return code, contract, market.input_hash


def ensure_cycle(db, code_hash, contract_hash, input_hash):
    current = db.execute("SELECT id,ordinal,status,generation FROM cycles ORDER BY ordinal DESC LIMIT 1").fetchone()
    if current and current[2] == "ACTIVE":
        if db.execute("SELECT contract_hash,input_hash FROM cycles WHERE id=?", (current[0],)).fetchone() != (contract_hash,input_hash):
            raise RuntimeError("cycle_binding_changed")
        stored_code=db.execute("SELECT value FROM meta WHERE key=?",("code:"+current[0],)).fetchone()
        if stored_code and stored_code[0]!=code_hash:
            raise RuntimeError("cycle_code_changed")
        return current[0]
    if current and current[2] == "SPACE_EXHAUSTED":
        previous_contract = db.execute("SELECT contract_hash FROM cycles WHERE id=?",(current[0],)).fetchone()[0]
        if previous_contract == contract_hash:
            return None
    ordinal = current[1]+1 if current else 1
    cycle_id = f"phase2_dev_{datetime.now(timezone.utc):%Y%m%d}_{ordinal:06d}"
    with db:
        db.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?)", (cycle_id,ordinal,"ACTIVE",0,utc(),contract_hash,input_hash))
        db.execute("INSERT INTO meta(key,value) VALUES(?,?)",("code:"+cycle_id,code_hash))
        event(db,"cycle_created",cycle_id=cycle_id,predecessor=current[0] if current else CONTRACT["predecessor"],code_hash=code_hash)
    return cycle_id


def add_candidate(db, cycle_id, generation, genes, parent, mutation, seed):
    validate_genes(genes)
    cid = digest(genes)
    with db:
        cursor = db.execute("INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?,?,?,?,?)",
                   (cid,cycle_id,generation,genes["family"],canonical(genes),parent,mutation,seed,utc()))
        if cursor.rowcount:
            event(db,"candidate_registered",cycle_id=cycle_id,candidate=cid,generation=generation,parent=parent,mutation=mutation)
    return cid


def seed_population(db, cycle_id):
    ordinal = db.execute("SELECT ordinal FROM cycles WHERE id=?",(cycle_id,)).fetchone()[0]
    existing = {r[0] for r in db.execute("SELECT id FROM candidates")}
    for family in SPACE:
        stage = db.execute("SELECT state FROM family_stage WHERE cycle_id=? AND family=? AND generation=0",
                           (cycle_id,family)).fetchone()
        if stage:
            continue
        rows = db.execute("SELECT COUNT(*) FROM candidates WHERE cycle_id=? AND family=? AND generation=0",(cycle_id,family)).fetchone()[0]
        family_total = math.prod(len(v) for v in SPACE[family].values())
        family_seen = db.execute("SELECT COUNT(*) FROM candidates WHERE family=?",(family,)).fetchone()[0]
        desired = min(CONTRACT["initial_population_per_family"], family_total-family_seen+rows)
        rng = random.Random(1701+ordinal*10007+ord(family))
        attempts = 0
        while rows < desired and attempts < 10000:
            attempts += 1
            genes = {"family":family, **{k:rng.choice(v) for k,v in SPACE[family].items()}}
            cid = digest(genes)
            if cid in existing:
                continue
            add_candidate(db,cycle_id,0,genes,None,"initial_predeclared_space",1701+ordinal)
            existing.add(cid); rows += 1
        if rows < desired:
            # Random sampling failure is not scientific exhaustion. Finish with exact unseen enumeration.
            keys = list(SPACE[family])
            for values in itertools.product(*(SPACE[family][k] for k in keys)):
                genes = {"family":family, **dict(zip(keys,values))}
                cid = digest(genes)
                if cid in existing:
                    continue
                add_candidate(db,cycle_id,0,genes,None,"initial_predeclared_space",1701+ordinal)
                existing.add(cid); rows += 1
                if rows >= desired:
                    break
        if rows < CONTRACT["initial_population_per_family"]:
            with db:
                event(db,"family_space_exhausted",cycle_id=cycle_id,family=family,available=rows)
        with db:
            db.execute("INSERT OR IGNORE INTO family_stage VALUES(?,?,0,'EVALUATING',NULL)",(cycle_id,family))


def evaluation_key(cid,fold,stress,code_hash,input_hash):
    return digest({"candidate":cid,"fold":fold,"stress":stress,"code":code_hash,"input":input_hash})


def schedule(db, cycle_id, code_hash, input_hash):
    rows = db.execute("SELECT id FROM candidates WHERE cycle_id=? ORDER BY generation,family,id",(cycle_id,)).fetchall()
    with db:
        for (cid,) in rows:
            for fold in range(len(FOLDS)):
                for stress in STRESSES:
                    key=evaluation_key(cid,fold,stress,code_hash,input_hash)
                    db.execute("INSERT OR IGNORE INTO evaluations(key,candidate_id,fold,stress,status) VALUES(?,?,?,?,'PENDING')",
                               (key,cid,fold,stress))


def _evaluate(task):
    key,genes,fold,stress = task
    start,end = FOLDS[fold]
    try:
        if stress == "neighbors":
            variants = []
            for field, values in SPACE[genes["family"]].items():
                index = values.index(genes[field])
                for adjacent in (index-1,index+1):
                    if 0 <= adjacent < len(values):
                        variants.append(dict(genes,**{field:values[adjacent]}))
            variants = variants[:4]
            metrics = [evaluate_fold(MARKET,variant,start,end) for variant in variants]
            value = {"neighbors":len(metrics),"passing_fraction":sum(x["mdd"]<=CONTRACT["risk_absolute_mdd"] and x["cagr"]>0 for x in metrics)/len(metrics),
                     "worst_cagr":min(x["cagr"] for x in metrics),
                     "variant_hashes":[digest(v) for v in variants]}
        else:
            value = evaluate_fold(MARKET,genes,start,end,cost_mult=2 if stress=="double_cost" else 1,
                                  delay_entries=stress=="delayed_entry")
        return key,"COMPLETE",value,None
    except Exception as exc:
        return key,"FAILED",None,{"type":type(exc).__name__,"reason":str(exc)[:200]}


def run_pending(db, market, workers, limit=24):
    global MARKET
    MARKET = market
    pending = db.execute("""SELECT e.key,c.genes,e.fold,e.stress FROM evaluations e
      JOIN candidates c ON c.id=e.candidate_id WHERE e.status='PENDING'
      ORDER BY c.generation,c.family,e.fold,e.stress,e.key LIMIT ?""",(limit,)).fetchall()
    if not pending:
        return 0
    tasks = [(key,json.loads(genes),fold,stress) for key,genes,fold,stress in pending]
    with db:
        db.executemany("UPDATE evaluations SET status='RUNNING' WHERE key=?",[(t[0],) for t in tasks])
    if workers == 1:
        results = map(_evaluate,tasks)
        for key,status,value,failure in results:
            with db:
                db.execute("UPDATE evaluations SET status=?,result=?,failure=?,finished=? WHERE key=?",
                           (status,canonical(value) if value else None,canonical(failure) if failure else None,utc(),key))
                event(db,"evaluation_finished",key=key,status=status)
    else:
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("fork")) as pool:
            futures = [pool.submit(_evaluate,task) for task in tasks]
            for future in as_completed(futures):
                key,status,value,failure = future.result()
                with db:
                    db.execute("UPDATE evaluations SET status=?,result=?,failure=?,finished=? WHERE key=?",
                               (status,canonical(value) if value else None,canonical(failure) if failure else None,utc(),key))
                    event(db,"evaluation_finished",key=key,status=status)
    return len(tasks)


def candidate_summary(db, cid):
    rows = db.execute("SELECT fold,stress,status,result,failure FROM evaluations WHERE candidate_id=? ORDER BY fold,stress",(cid,)).fetchall()
    expected = len(FOLDS)*len(STRESSES)
    if len(rows)!=expected or any(r[2] in ("PENDING","RUNNING") for r in rows):
        return None
    if any(r[2] != "COMPLETE" for r in rows):
        return {"id":cid,"eligible":False,"reasons":["candidate_evaluation_failed"],"folds":[]}
    values = {(fold,stress):json.loads(body) for fold,stress,_,body,_ in rows}
    nominal = [values[(fold,"nominal")] for fold in range(len(FOLDS))]
    double = [values[(fold,"double_cost")] for fold in range(len(FOLDS))]
    delayed = [values[(fold,"delayed_entry")] for fold in range(len(FOLDS))]
    neighbors = [values[(fold,"neighbors")] for fold in range(len(FOLDS))]
    keys = ("cagr","mdd","sharpe","calmar","asset_concentration","trade_concentration","turnover","cost_drag","no_best_day_cagr","no_top3_trades_cagr")
    mean = {k:sum(x[k] or 0 for x in nominal)/len(nominal) for k in keys}
    mean["double_cost_cagr"] = sum(x["cagr"] for x in double)/len(double)
    mean["delayed_entry_cagr"] = sum(x["cagr"] for x in delayed)/len(delayed)
    mean["worst_fold_return"] = min(x["net_return"] for x in nominal)
    mean["profitable_fold_fraction"] = sum(x["net_return"]>0 for x in nominal)/len(nominal)
    mean["parameter_stability"] = sum(x["passing_fraction"] for x in neighbors)/len(neighbors)
    reasons = []
    if max(x["mdd"] for x in nominal) > CONTRACT["risk_absolute_mdd"]: reasons.append("mdd_above_absolute_cap")
    if any(x["asset_concentration"] is None or x["trade_concentration"] is None for x in nominal): reasons.append("nonpositive_growth_or_missing_concentration")
    if mean["double_cost_cagr"] <= 0: reasons.append("double_cost_loss")
    if mean["delayed_entry_cagr"] <= 0: reasons.append("delayed_entry_loss")
    if mean["no_best_day_cagr"] <= 0: reasons.append("best_day_dependence")
    if mean["no_top3_trades_cagr"] <= 0: reasons.append("top3_episode_dependence")
    if mean["parameter_stability"] < .75: reasons.append("parameter_instability")
    return {"id":cid,"eligible":not reasons,"reasons":reasons,"metrics":mean,
            "folds":[{"start":FOLDS[i][0],"end":FOLDS[i][1],"metrics":nominal[i]} for i in range(len(FOLDS))]}


def pareto(rows):
    feasible = [r for r in rows if r["eligible"]]
    dimensions = (("cagr",1),("calmar",1),("sharpe",1),("mdd",-1),("turnover",-1))
    front = []
    for candidate in feasible:
        if any(other is not candidate and all(sign*other["metrics"][k]>=sign*candidate["metrics"][k] for k,sign in dimensions)
               and any(sign*other["metrics"][k]>sign*candidate["metrics"][k] for k,sign in dimensions)
               for other in feasible):
            continue
        front.append(candidate)
    # When all candidates fail, retain least-bad development parents to learn why.
    return sorted(front or rows,key=lambda r:(not r["eligible"],len(r["reasons"]),
                                              r.get("metrics",{}).get("mdd",1),
                                              -r.get("metrics",{}).get("calmar",-999),r["id"]))


def parents_for_family(db,cycle_id,family,generation):
    ids = [x[0] for x in db.execute("SELECT id FROM candidates WHERE cycle_id=? AND family=? AND generation=? ORDER BY id",
                                  (cycle_id,family,generation))]
    rows = [candidate_summary(db,cid) for cid in ids]
    if not rows or any(r is None for r in rows):
        return None
    front = pareto(rows)
    chosen = front[:2]
    for row in chosen:
        row["genes"] = json.loads(db.execute("SELECT genes FROM candidates WHERE id=?",(row["id"],)).fetchone()[0])
    return chosen


def proposal_payload(db,cycle_id,family,parents):
    return proposal(db,cycle_id,family,parents,SPACE[family])


def strict_json(data):
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise ValueError("duplicate_json_key")
            result[key]=value
        return result
    def bad(_): raise ValueError("nonfinite_json")
    return json.loads(data,object_pairs_hook=pairs,parse_constant=bad)


def accepted_mutations(body,parents,seen,family):
    try:
        parsed = strict_json(body)
        if set(parsed)!={"candidates"} or not isinstance(parsed["candidates"],list):
            raise ValueError("response_shape")
        rows = parsed["candidates"]
    except (ValueError,TypeError,KeyError):
        return []
    allowed = {p["id"] for p in parents}
    accepted = []
    for row in rows[:8]:
        try:
            if not isinstance(row,dict) or set(row)!={"parent","genes","hypothesis"}:
                raise ValueError("proposal_keys")
            genes = validate_genes(row["genes"])
            if genes["family"]!=family or row["parent"] not in allowed:
                raise ValueError("family_or_parent")
            if not isinstance(row["hypothesis"],str) or not 1<=len(row["hypothesis"])<=600:
                raise ValueError("hypothesis")
            cid = digest(genes)
            if cid in seen: raise ValueError("duplicate_candidate")
            seen.add(cid); accepted.append(row)
        except (ValueError,TypeError,KeyError):
            continue
    return accepted


def advance_family(db,root,cycle_id,family):
    stage = db.execute("SELECT state,request_hash FROM family_stage WHERE cycle_id=? AND family=? AND generation=0",
                       (cycle_id,family)).fetchone()
    if not stage or stage[0]=="DONE":
        return False
    if db.execute("SELECT COUNT(*) FROM candidates WHERE cycle_id=? AND family=? AND generation=0",(cycle_id,family)).fetchone()[0]==0:
        with db:
            db.execute("UPDATE family_stage SET state='DONE' WHERE cycle_id=? AND family=? AND generation=0",(cycle_id,family))
        return True
    parents = parents_for_family(db,cycle_id,family,0)
    if parents is None:
        return False
    mailbox = Path(root)/"mailbox"
    # Resume the exact durable request, including a request made by the previous release.
    if stage[1]:
        request = json.loads((mailbox/"requests"/(stage[1]+".json")).read_text())["payload"]
    else:
        request = proposal_payload(db,cycle_id,family,parents)
    request_hash = digest(request)
    request_path = mailbox/"requests"/(request_hash+".json")
    response_path = mailbox/"responses"/(request_hash+".json")
    if not request_path.exists():
        atomic(request_path,{"hash":request_hash,"payload":request,"utc":utc()})
    with db:
        db.execute("UPDATE family_stage SET state='AWAITING_BROKER',request_hash=? WHERE cycle_id=? AND family=? AND generation=0",
                   (request_hash,cycle_id,family))
    if not response_path.exists():
        return False
    response = json.loads(response_path.read_text())
    if response.get("hash")!=request_hash:
        raise RuntimeError("broker_response_binding")
    seen = {x[0] for x in db.execute("SELECT id FROM candidates")}
    accepted = accepted_mutations(response.get("content") or "",parents,seen,family)
    ordinal = db.execute("SELECT ordinal FROM cycles WHERE id=?",(cycle_id,)).fetchone()[0]
    existing_children = db.execute("SELECT COUNT(*) FROM candidates WHERE cycle_id=? AND family=? AND generation=1",
                                   (cycle_id,family)).fetchone()[0]
    remaining_slots = max(0, CONTRACT["mutations_per_family"]-existing_children)
    for position,row in enumerate(accepted[:remaining_slots]):
        add_candidate(db,cycle_id,1,row["genes"],row["parent"],"deepseek:"+row["hypothesis"],ordinal*1000+position)
    created = len(accepted[:remaining_slots])
    for position in range(existing_children+created,CONTRACT["mutations_per_family"]):
        parent = parents[position%len(parents)]
        child,reason = mutate(parent["genes"],ordinal*10000+ord(family)*100+position,seen)
        if child is None: break
        seen.add(digest(child))
        add_candidate(db,cycle_id,1,child,parent["id"],reason,ordinal*10000+position)
    with db:
        db.execute("UPDATE family_stage SET state='DONE' WHERE cycle_id=? AND family=? AND generation=0",(cycle_id,family))
        db.execute("INSERT OR IGNORE INTO family_stage VALUES(?,?,1,'EVALUATING',NULL)",(cycle_id,family))
        db.execute("UPDATE cycles SET generation=1 WHERE id=?",(cycle_id,))
        event(db,"generation_created",cycle_id=cycle_id,family=family,broker_state=response.get("state"),
              request_hash=request_hash,wire_hash=response.get("wire_hash"),
              accepted_mutations=created,rejected_or_missing_slots=CONTRACT["mutations_per_family"]-created)
    return True


def maybe_complete(db,cycle_id):
    if db.execute("SELECT COUNT(*) FROM family_stage WHERE cycle_id=? AND generation=0 AND state='DONE'",(cycle_id,)).fetchone()[0] != len(SPACE):
        return False
    outstanding = db.execute("""SELECT COUNT(*) FROM evaluations e JOIN candidates c ON c.id=e.candidate_id
       WHERE c.cycle_id=? AND e.status IN ('PENDING','RUNNING')""",(cycle_id,)).fetchone()[0]
    if outstanding:
        return False
    candidate_count = db.execute("SELECT COUNT(*) FROM candidates WHERE cycle_id=?",(cycle_id,)).fetchone()[0]
    state = "SPACE_EXHAUSTED" if candidate_count == 0 else "SEALED_DEVELOPMENT"
    with db:
        db.execute("UPDATE cycles SET status=?,generation=1 WHERE id=?",(state,cycle_id))
        event(db,"cycle_completed",cycle_id=cycle_id,successor="automatic_next_dispatch" if state=="SEALED_DEVELOPMENT" else "await_new_predeclared_space")
    return True


def status(db):
    cycle = db.execute("SELECT id,status,generation,created FROM cycles ORDER BY ordinal DESC LIMIT 1").fetchone()
    counts = db.execute("SELECT status,COUNT(*) FROM evaluations GROUP BY status").fetchall()
    latest = db.execute("SELECT MAX(finished) FROM evaluations WHERE status='COMPLETE'").fetchone()[0]
    return {"active_evolution": bool(cycle and cycle[1]=="ACTIVE"),"cycle":cycle,"evaluation_counts":dict(counts),
            "last_progress_utc":latest,"outer_oos":"LOCKED","forward_2027":"SEALED"}


def run(root,input_dir,*,synthetic=False,workers=2,seconds=1500,steps=None):
    root = Path(root);root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free < POLICY["disk_reserve_bytes"]:
        raise RuntimeError("research_disk_reserve_below_2GiB")
    if (root/"research.sqlite").exists() and (root/"research.sqlite").stat().st_size > POLICY["ledger_max_bytes"]:
        raise RuntimeError("research_ledger_size_limit")
    lock = (root/"runner.lock").open("a+")
    if fcntl:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    else:
        lock.seek(0);lock.write("0");lock.flush();lock.seek(0)
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    db = connect(root,recover=True)
    try:
        verify_chain(db)
        market = synthetic_market() if synthetic else load_market(Path(input_dir),CONTRACT["development_end"])
        code_hash,contract_hash,input_hash = fingerprints(market)
        deadline = time.monotonic()+seconds
        count = 0
        while time.monotonic()<deadline and (steps is None or count<steps):
            count += 1
            cycle_id = ensure_cycle(db,code_hash,contract_hash,input_hash)
            if cycle_id is None:
                break
            seed_population(db,cycle_id)
            schedule(db,cycle_id,code_hash,input_hash)
            for family in SPACE:
                advance_family(db,root,cycle_id,family)
            schedule(db,cycle_id,code_hash,input_hash)
            n = run_pending(db,market,workers)
            completed = maybe_complete(db,cycle_id)
            atomic(root/"status.json",status(db))
            if n==0 and not completed:
                break
        return status(db)
    finally:
        db.close()
        if fcntl: fcntl.flock(lock,fcntl.LOCK_UN)
        else:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        lock.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["run","status","check"])
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--inputs",type=Path)
    parser.add_argument("--synthetic",action="store_true")
    parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--seconds",type=int,default=1500)
    parser.add_argument("--steps",type=int)
    args=parser.parse_args()
    if args.workers not in (1,2): raise ValueError("two_worker_limit")
    if args.command=="run":
        print(canonical(run(args.root,args.inputs,synthetic=args.synthetic,workers=args.workers,seconds=args.seconds,steps=args.steps)))
    else:
        db=connect(args.root)
        try:
            if args.command=="check":
                verify_chain(db)
                print("sqlite_and_audit_chain_ok")
            print(canonical(status(db)))
        finally:db.close()


if __name__=="__main__": main()
