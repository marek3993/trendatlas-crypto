"""Durable per-day targets, pre-submit CLOIDs and monotonic signing nonces."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time


TERMINAL_ORDERS = {"FILLED", "CANCELED", "REJECTED"}


class ConfirmedRejection(RuntimeError):
    """The exchange returned an explicit whole-action rejection."""
    pass


class NoSubmission(RuntimeError):
    """A failure proven to precede the signed HTTP request boundary."""
    pass


class Journal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(day TEXT PRIMARY KEY, binding TEXT NOT NULL, signal TEXT NOT NULL,
          state TEXT NOT NULL, receipt TEXT, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(cloid TEXT PRIMARY KEY, day TEXT NOT NULL, phase TEXT NOT NULL,
          market_key TEXT NOT NULL, sequence INTEGER NOT NULL, tif TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL, created REAL NOT NULL, deadline REAL NOT NULL, status_json TEXT,
          UNIQUE(day,sequence));
        CREATE TABLE IF NOT EXISTS nonces(id INTEGER PRIMARY KEY CHECK(id=1), last INTEGER NOT NULL);
        """)

    def close(self):
        self.db.close()

    def begin(self, day: str, binding: str, signal: dict) -> dict:
        with self.db:
            row = self.db.execute("SELECT * FROM runs WHERE day=?", (day,)).fetchone()
            if row and row["binding"] != binding:
                raise ValueError("DIFFERENT_TARGET_FOR_FROZEN_DAY")
            if not row:
                now = time.time()
                self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (day, binding, json.dumps(signal, sort_keys=True), "RUNNING", None, now, now))
        return self.run(day)

    def run(self, day: str) -> dict:
        row = self.db.execute("SELECT * FROM runs WHERE day=?", (day,)).fetchone()
        return dict(row) if row else {}

    def finish(self, day: str, state: str, receipt: dict):
        with self.db:
            self.db.execute("UPDATE runs SET state=?,receipt=?,updated=? WHERE day=?", (state, json.dumps(receipt, sort_keys=True, allow_nan=False), time.time(), day))

    def reserve(self, day: str, binding: str, phase: str, market_key: str, tif: str, payload: dict, deadline: float) -> dict:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            sequence = self.db.execute("SELECT COALESCE(MAX(sequence),-1)+1 FROM orders WHERE day=?", (day,)).fetchone()[0]
            raw = f"clean5050|{day}|{binding}|{phase}|{market_key}|{sequence}|{tif}"
            cloid = "0x" + hashlib.sha256(raw.encode()).hexdigest()[:32]
            self.db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cloid, day, phase, market_key, sequence, tif, json.dumps(payload, sort_keys=True), "PREPARED", time.time(), deadline, None))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.order(cloid)

    def order(self, cloid: str) -> dict:
        row = self.db.execute("SELECT * FROM orders WHERE cloid=?", (cloid,)).fetchone()
        return dict(row) if row else {}

    def update(self, cloid: str, state: str, status: dict | None = None):
        with self.db:
            self.db.execute("UPDATE orders SET state=?,status_json=? WHERE cloid=?", (state, json.dumps(status, sort_keys=True) if status else None, cloid))

    def pending(self) -> list[dict]:
        return [dict(x) for x in self.db.execute("SELECT * FROM orders WHERE state NOT IN ('FILLED','CANCELED','REJECTED') ORDER BY day,sequence")]

    def owned_cloids(self) -> set[str]:
        return {x[0] for x in self.db.execute("SELECT cloid FROM orders")}

    def nonce(self, now_ms: int | None = None) -> int:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT last FROM nonces WHERE id=1").fetchone()
            value = max(now_ms, row[0] + 1 if row else now_ms)
            self.db.execute("INSERT OR REPLACE INTO nonces VALUES(1,?)", (value,))
            self.db.commit()
            return value
        except BaseException:
            self.db.rollback()
            raise

    def backup(self):
        with closing(sqlite3.connect(self.path.with_suffix(".backup.sqlite3"))) as backup:
            self.db.backup(backup)


def target_binding(signal: dict) -> str:
    payload = {k: signal[k] for k in ("strategy_id", "decision_closed_day_utc", "ciel_vahy")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
