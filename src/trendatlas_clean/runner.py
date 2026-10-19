"""Daily signal-only runner. Its only exchange interactions are public-data GETs."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pandas as pd

from .core import LIVE_PARAMS, STRATEGY_ID, explain_day, target_weights, weights_dict
from .data import REFERENCE_SYMBOLS, load
from .fetch_data import _atomic_bytes, discover_universe, fetch_all, last_closed_day


def code_sha256() -> str:
    digest = hashlib.sha256()
    for name in ("core.py", "data.py", "fetch_data.py", "runner.py"):
        p = Path(__file__).parent / name
        digest.update(p.name.encode() + b"\0" + p.read_bytes())
    return digest.hexdigest()


def build_signal(close: pd.DataFrame, qv: pd.DataFrame, closed_day: str, *, input_sha256: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC-aware generation time required")
    day = pd.Timestamp(closed_day)
    if day >= pd.Timestamp(now.astimezone(timezone.utc).date()):
        raise ValueError("Cannot decide on an unclosed UTC day")
    c, v = close.loc[:closed_day], qv.loc[:closed_day]
    if c.empty or c.index[-1] != day or pd.isna(c.at[day, "BTC"]):
        raise ValueError("Fresh observed BTC close is required; stale data is not a CASH signal")
    W = target_weights(c, v)
    targets = weights_dict(W.iloc[-1])
    holding_day = (day + pd.Timedelta(days=1)).date().isoformat()
    return {
        "schema_version": 1, "strategy_id": STRATEGY_ID, "mode": "SIGNAL_ONLY",
        "generated_at_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision_closed_day_utc": closed_day,
        "rozhodnute_na_close_utc": closed_day + "T23:59:59.999Z",
        "drzat_pocas_dna_utc": holding_day, "ciel_vahy": targets,
        "gross_target_exposure": float(W.iloc[-1].sum()), "params": asdict(LIVE_PARAMS),
        "input_sha256": input_sha256, "code_sha256": code_sha256(),
        "orders_sent": 0, "live_order_chain": "NOT_INVOKED_BY_SIGNAL_PRODUCER",
        "routes_metadata": {c: {"venue": "spot" if c in {"BTC", "ETH"} else "perp",
                                    "symbol": {"BTC": "UBTC", "ETH": "UETH"}.get(c, c),
                                    "target_notional_multiple": w}
                            for c, w in targets.items() if c != "CASH"},
        "diagnostics": explain_day(c, v, closed_day),
    }


def compare_reference(signal: dict, path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"status": "NOT_PROVIDED", "matched": None}
    reference = json.loads(path.read_text())
    if reference.get("decision_closed_day_utc") != signal["decision_closed_day_utc"]:
        return {"status": "WRONG_DAY", "matched": False}
    expected = reference.get("ciel_vahy")
    if not isinstance(expected, dict):
        raise ValueError("Reference must contain ciel_vahy")
    matched = expected == signal["ciel_vahy"]
    return {"status": "MATCH" if matched else "MISMATCH", "matched": matched, "expected": expected,
            "reference_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def persist(state_dir: Path, signal: dict, comparison: dict) -> dict:
    """One immutable signal per closed day; crash recovery rematerializes identical JSON."""
    state_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(state_dir / "dry_run.sqlite3", timeout=30)) as db:
        return _persist(db, state_dir, signal, comparison)


def _persist(db: sqlite3.Connection, state_dir: Path, signal: dict, comparison: dict) -> dict:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS runs(day TEXT PRIMARY KEY, binding TEXT NOT NULL, generated TEXT NOT NULL, signal_json TEXT NOT NULL, comparison_json TEXT NOT NULL)")
    semantic_keys = ("strategy_id", "decision_closed_day_utc", "ciel_vahy", "params")
    binding = hashlib.sha256(json.dumps({k: signal[k] for k in semantic_keys}, sort_keys=True).encode()).hexdigest()
    db.execute("CREATE TABLE IF NOT EXISTS verifications(day TEXT, generated TEXT, input_sha256 TEXT, code_sha256 TEXT, PRIMARY KEY(day,generated,input_sha256,code_sha256))")
    with db:
        row = db.execute("SELECT binding,signal_json FROM runs WHERE day=?", (signal["decision_closed_day_utc"],)).fetchone()
        if row:
            original = json.loads(row[1])
            if any(original.get(k) != signal.get(k) for k in semantic_keys):
                raise ValueError("DAY_REVISION_DETECTED: existing signal preserved; no silent rewrite")
            if row[0] != binding:
                # Migrate an old provenance-based binding, never its frozen target.
                db.execute("UPDATE runs SET binding=? WHERE day=?", (binding, signal["decision_closed_day_utc"]))
            db.execute("INSERT OR IGNORE INTO verifications VALUES(?,?,?,?)", (signal["decision_closed_day_utc"], signal["generated_at_utc"], signal["input_sha256"], signal["code_sha256"]))
            signal = json.loads(row[1])
            # An external comparison may arrive later without changing the signal.
            if comparison["status"] != "NOT_PROVIDED":
                db.execute("UPDATE runs SET comparison_json=? WHERE day=?", (json.dumps(comparison, sort_keys=True), signal["decision_closed_day_utc"]))
        else:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (signal["decision_closed_day_utc"], binding, signal["generated_at_utc"], json.dumps(signal, sort_keys=True), json.dumps(comparison, sort_keys=True)))
    _atomic_bytes(state_dir / "signals" / f"{signal['decision_closed_day_utc']}.json", json.dumps(signal, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")
    _atomic_bytes(state_dir / "signal.json", json.dumps(signal, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")
    rows = db.execute("SELECT day,generated,comparison_json FROM runs ORDER BY day").fetchall()
    first_seen = min(datetime.fromisoformat(x[1].replace("Z", "+00:00")) for x in rows)
    now = datetime.now(timezone.utc)
    elapsed = (now - first_seen).total_seconds() / 86400
    # Marek removed the seven-day waiting period. These records never arm a trader.
    comparison_passes = sum(json.loads(x[2]).get("matched") is True for x in rows)
    status = {"status": "SIGNAL_RECORDED_OPERATOR_ACTIVATION_SEPARATE",
              "last_closed_day": signal["decision_closed_day_utc"], "distinct_days": len(rows),
              "elapsed_days": elapsed, "mandatory_wait_days": 0,
              "reference_comparisons_passed": comparison_passes,
              "automatic_live_promotion": False, "orders_sent": 0}
    _atomic_bytes(state_dir / "status.json", json.dumps(status, indent=2).encode() + b"\n")
    backup = sqlite3.connect(state_dir / "dry_run.backup.sqlite3")
    db.backup(backup)
    backup.close()
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--closed-day", default=last_closed_day())
    parser.add_argument("--universe", choices=("reference", "all"), default="reference")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--exclusions", type=Path, default=Path(__file__).resolve().parents[2] / "source_of_truth" / "clean_5050_asset_exclusions.json")
    parser.add_argument("--reference-signal", type=Path)
    args = parser.parse_args(argv)
    if args.closed_day != last_closed_day():
        parser.error("Daily runner requires the current last closed UTC day; use validate_reference for historical replay")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    # flock serializes timer/retry/manual dry-run activations; systemd also serializes its unit.
    from .execution_cli import exclusive_lock
    with exclusive_lock(args.state_dir / "runner.lock"):
        try:
            if args.universe == "all":
                universe = discover_universe(args.exclusions)
                symbols = universe["symbols"]
            else:
                symbols = list(REFERENCE_SYMBOLS)
                universe = {"symbols": symbols, "source": "USER_FROZEN_59_REFERENCE"}
            _atomic_bytes(args.state_dir / "universe.json", json.dumps(universe, indent=2).encode() + b"\n")
            if args.refresh:
                report = fetch_all(args.data_dir, symbols, args.closed_day)
                if report["failures"]:
                    raise ValueError("INCOMPLETE_FETCH: incomplete universe is not silently accepted")
            panel = load(args.data_dir, args.closed_day, symbols)
            if args.refresh:
                from concurrent.futures import ThreadPoolExecutor
                from .fetch_data import fetch_funding
                history_weights = target_weights(panel.close, panel.quote_volume).loc["2020-12-31":]
                funding_assets = ["BTC"] + [c for c in history_weights if c not in {"BTC", "ETH"} and history_weights[c].gt(0).any()]
                with ThreadPoolExecutor(4) as pool:
                    funding_report = list(pool.map(lambda s: fetch_funding(s, args.data_dir, args.closed_day), funding_assets))
                _atomic_bytes(args.state_dir / "funding_report.json", json.dumps(funding_report, indent=2).encode())
                panel = load(args.data_dir, args.closed_day, symbols)
            signal = build_signal(panel.close, panel.quote_volume, args.closed_day, input_sha256=panel.input_sha256)
            signal["universe"] = {"kind": args.universe, "symbol_count": len(symbols),
                                  "sha256": hashlib.sha256(json.dumps(universe, sort_keys=True).encode()).hexdigest()}
            comparison = compare_reference(signal, args.reference_signal)
            status = persist(args.state_dir, signal, comparison)
            signal = json.loads((args.state_dir / "signal.json").read_text())
            from .public_metrics import publish_public
            publish_public(panel, signal["universe"], args.state_dir)
            print(json.dumps({"signal": signal, "reference_comparison": comparison, "status": status}, allow_nan=False))
            return 0
        except Exception as exc:
            error = {"status": "DRY_RUN_ERROR", "error_type": type(exc).__name__, "reason": str(exc),
                     "observed_at_utc": datetime.now(timezone.utc).isoformat(), "orders_sent": 0,
                     "previous_signal_preserved": True}
            _atomic_bytes(args.state_dir / "last_error.json", json.dumps(error, indent=2).encode() + b"\n")
            print(json.dumps(error), file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
