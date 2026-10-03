"""Bounded JSON broker with durable reservations, content cache and provider usage."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request

from .compact import POLICY, wire_payload
from .engine import canonical, digest
from .runtime import CONTRACT, atomic, utc

SYSTEM = ("Return only JSON. The top-level object must have exactly one key: candidates. "
          "Never add type, json_object or metadata keys. candidates is a list of four objects, "
          "each with exactly parent, genes, hypothesis. "
          "Use exact supplied family schema and enum values. Prefer unseen_options, or propose a novel valid "
          "combination. Improve weak validation folds, drawdown, costs and concentration. Do not repeat parents. "
          "No code or data changes. Outer OOS and forward 2027 are unavailable.")


def api_key():
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if directory:
        path = Path(directory) / "deepseek-key"
        if path.is_file():
            return path.read_text().strip()
    return os.environ.get("DEEPSEEK_API_KEY")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect_forbidden")


def billing(usage):
    hit = int(usage.get("prompt_cache_hit_tokens", 0))
    miss = int(usage.get("prompt_cache_miss_tokens", max(0, int(usage.get("prompt_tokens", 0)) - hit)))
    output = int(usage.get("completion_tokens", 0))
    known = "prompt_tokens" in usage and "completion_tokens" in usage
    return {"input_cache_hit_tokens": hit, "input_cache_miss_tokens": miss, "output_tokens": output,
            "total_tokens": int(usage.get("total_tokens", hit + miss + output)),
            "usd_upper_estimate": (hit * .006 + miss * .30 + output * 1.20) / 1e6 if known else None,
            "billing_known": known, "provider_usage": usage,
            "tariff": "documented_peak_upper_estimate_20260927",
            "tariff_source": "https://api-docs.deepseek.com/quick_start/pricing/"}


def wire_body(payload):
    return {"model": "deepseek-flash", "thinking": {"type": "disabled"},
            "max_tokens": POLICY["output_token_ceiling"], "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": canonical(wire_payload(payload))}]}


def call_deepseek(payload, key):
    request = urllib.request.Request("https://api.deepseek.com/chat/completions",
        data=canonical(wire_body(payload)).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=45) as response:
        raw = response.read(250000)
    reply = json.loads(raw)
    bill = billing(reply.get("usage", {}))
    bill.update(provider_request_id=reply.get("id"), finish_reason=reply["choices"][0].get("finish_reason"))
    return reply["choices"][0]["message"]["content"], bill, reply.get("model")


@contextmanager
def broker_lock(root):
    path = Path(root) / "broker.lock"
    with path.open("a+") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0); lock.write("0"); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def index_responses(root):
    """Import immutable legacy evidence once. Never reread its growing ledgers per tick."""
    db = sqlite3.connect(root / "broker.sqlite")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS responses(hash TEXT PRIMARY KEY,cycle TEXT,calls INTEGER,tokens INTEGER,dollars REAL,unknown INTEGER);
    CREATE TABLE IF NOT EXISTS cache(wire_hash TEXT PRIMARY KEY,response_hash TEXT NOT NULL);
    """)
    indexed = {r[0] for r in db.execute("SELECT hash FROM responses")}
    for path in (root / "responses").glob("*.json"):
        if path.stem in indexed:
            continue
        row = json.loads(path.read_text())
        cycle = row.get("cycle_id")
        if not cycle:
            cycle = json.loads((root / "requests" / path.name).read_text())["payload"]["cycle_id"]
        u = row.get("usage") or {}
        with db:
            db.execute("INSERT OR IGNORE INTO responses VALUES(?,?,?,?,?,?)",
                       (path.stem, cycle, u.get("api_call", 0), u.get("total_tokens", 0),
                        u.get("usd_upper_estimate") or 0, int(bool(u.get("uncertain")))))
            if row.get("state") == "COMPLETE" and row.get("wire_hash"):
                db.execute("INSERT OR IGNORE INTO cache VALUES(?,?)", (row["wire_hash"], path.stem))
    return db


def _broker_once(root, transport):
    responses = root / "responses"; responses.mkdir(parents=True, exist_ok=True)
    inflight = root / "inflight"; inflight.mkdir(parents=True, exist_ok=True)
    attempts_dir = root / "attempts"; attempts_dir.mkdir(parents=True, exist_ok=True)
    db = index_responses(root)
    try:
        for request_path in sorted((root / "requests").glob("*.json")):
            key_hash = request_path.stem
            result_path = responses / request_path.name
            if result_path.exists():
                continue
            request = json.loads(request_path.read_text())
            payload = request["payload"]
            if request["hash"] != key_hash or digest(payload) != key_hash or payload.get("scope") != POLICY["scope"]:
                raise ValueError("request_binding_or_scope")
            cycle = payload["cycle_id"]
            body = wire_body(payload)
            wire_hash = digest(body)
            base = {"hash": key_hash, "wire_hash": wire_hash, "cycle_id": cycle}
            def save(**fields):
                atomic(result_path, {**base, **fields, "utc": utc()})
                return True
            reservation = inflight / request_path.name
            if reservation.exists():
                return save(state="FALLBACK", content=None, error="uncertain_prior_call_no_retry",
                            usage={"api_call": 1, "uncertain": True, "billing_known": False,
                                   "total_tokens": None, "usd_upper_estimate": None})
            cached = db.execute("SELECT response_hash FROM cache WHERE wire_hash=?", (wire_hash,)).fetchone()
            if cached:
                row = json.loads((responses / (cached[0] + ".json")).read_text())
                return save(state="COMPLETE", content=row["content"], error=None, model=row.get("model"),
                            cache_source=cached[0], usage={"api_call": 0, "total_tokens": 0,
                            "usd_upper_estimate": 0, "billing_known": True})
            calls, tokens, dollars, unknown = db.execute(
                "SELECT COALESCE(SUM(calls),0),COALESCE(SUM(tokens),0),COALESCE(SUM(dollars),0),COALESCE(SUM(unknown),0) FROM responses WHERE cycle=?",
                (cycle,)).fetchone()
            bound = len(canonical(body).encode())
            reserved_tokens = bound + POLICY["output_token_ceiling"]
            reserved_usd = (bound * .30 + POLICY["output_token_ceiling"] * 1.20) / 1e6
            reason = None
            if bound > POLICY["input_token_ceiling"]:
                reason = "input_token_ceiling"
            elif (calls >= CONTRACT["api_calls_per_cycle_max"] or
                  tokens + reserved_tokens > CONTRACT["api_tokens_per_cycle_max"] or
                  dollars + reserved_usd > CONTRACT["api_usd_per_cycle_max"] or unknown):
                reason = "cycle_api_budget"
            secret = api_key()
            if not secret:
                reason = "missing_api_key"
            if reason:
                return save(state="FALLBACK", content=None, error=reason,
                            input_token_upper_bound=bound, usage={"api_call": 0, "total_tokens": 0,
                            "usd_upper_estimate": 0, "billing_known": True})
            atomic(reservation, {**base, "utc": utc(), "reserved_call": 1,
                                "reserved_tokens": reserved_tokens, "reserved_usd": reserved_usd})
            records = []
            for attempt in range(POLICY["max_transport_attempts"]):
                started = utc()
                # A durable per-attempt reservation precedes every transport, including a 429 retry.
                atomic(attempts_dir / (key_hash + "." + str(attempt) + ".reserved.json"),
                       {**base, "attempt": attempt, "utc": started})
                try:
                    content, bill, model = transport(wire_payload(payload), secret)
                    records.append({"attempt": attempt, "started_utc": started, "finished_utc": utc(),
                                    "state": "COMPLETE", "usage": bill})
                    atomic(attempts_dir / (key_hash + "." + str(attempt) + ".result.json"), records[-1])
                    return save(state="COMPLETE", content=content, error=None, model=model,
                                input_token_upper_bound=bound, attempts=records,
                                usage={"api_call": 1, **bill})
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    rejected = code is not None and 400 <= code < 500
                    record = {"attempt": attempt, "started_utc": started, "finished_utc": utc(),
                              "state": "REJECTED" if rejected else "UNCERTAIN",
                              "error": {"type": type(exc).__name__, "http_status": code},
                              "billing_known": rejected, "billed_tokens": 0 if rejected else None}
                    records.append(record)
                    atomic(attempts_dir / (key_hash + "." + str(attempt) + ".result.json"), record)
                    if code in POLICY["retry_http_statuses"] and attempt + 1 < POLICY["max_transport_attempts"]:
                        time.sleep(POLICY["retry_backoff_seconds"])
                        continue
                    return save(state="FALLBACK", content=None, error=record["error"], attempts=records,
                                input_token_upper_bound=bound,
                                usage={"api_call": 0 if rejected else 1, "transport_attempts": len(records),
                                       "uncertain": not rejected, "billing_known": rejected,
                                       "total_tokens": 0 if rejected else None,
                                       "usd_upper_estimate": 0 if rejected else None})
    finally:
        db.close()
    return False


def broker_once(root, transport=call_deepseek):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    with broker_lock(root):
        return _broker_once(root, transport)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mailbox", type=Path, required=True)
    args = parser.parse_args()
    print(canonical({"processed": broker_once(args.mailbox), "utc": utc()}))


if __name__ == "__main__":
    main()
