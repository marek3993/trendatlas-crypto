"""Plan-only by default. Live mode is for the operator-activated systemd unit."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import sys

from .core import STRATEGY_ID
from .execution import Engine
from .fetch_data import _atomic_bytes
from .hyperliquid import Broker
from .journal import Journal
from .portfolio import Policy, normalized_weights, plan


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def validate_signal(signal: dict, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC_TIME_REQUIRED")
    today = now.astimezone(timezone.utc).date()
    expected = (today - timedelta(days=1)).isoformat()
    if signal.get("strategy_id") != STRATEGY_ID:
        raise ValueError("WRONG_STRATEGY")
    if signal.get("decision_closed_day_utc") != expected or signal.get("drzat_pocas_dna_utc") != today.isoformat():
        raise ValueError("STALE_OR_UNCLOSED_SIGNAL")
    normalized_weights(signal.get("ciel_vahy"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute-live", action="store_true")
    mode.add_argument("--verify-signer-only", action="store_true")
    args = parser.parse_args(argv)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    journal = None
    try:
        with exclusive_lock(args.state_dir / "portfolio.lock"):
            config = json.loads(args.config.read_text())
            signal = json.loads(args.signal.read_text())
            validate_signal(signal)
            policy = Policy(**config.get("policy", {}))
            journal = Journal(args.state_dir / "execution.sqlite3")
            broker = Broker(config["account"], journal, args.config)
            if args.verify_signer_only or args.execute_live:
                signer = broker.arm(config["agent_name"])
            if args.execute_live:
                if config.get("kill_switch") is not False or config.get("trading_enabled") is not True:
                    raise ValueError("CLEAN_TRADING_DISABLED")
                receipt = Engine(broker, journal, policy).execute(signal)
                receipt["mode"] = "LIVE"
                # Capture economic fills corresponding to this journal's OIDs.
                oids = set()
                for row in journal.db.execute("SELECT status_json FROM orders WHERE day=?", (signal["decision_closed_day_utc"],)):
                    value = json.loads(row[0]) if row[0] else {}
                    if value.get("oid"):
                        oids.add(value["oid"])
                try:
                    receipt["verified_fills"] = [f for f in broker.info("userFills", user=broker.account) if f.get("oid") in oids]
                except Exception as exc:
                    receipt["fill_readback_error"] = type(exc).__name__
                destination = args.state_dir / "execution_receipt.json"
            else:
                p = plan(signal["ciel_vahy"], broker.snapshot(), broker.catalog(), policy)
                receipt = {"mode": "SIGNER_VERIFIED_NO_SUBMIT" if args.verify_signer_only else "PLAN_ONLY",
                           "strategy_id": STRATEGY_ID, "decision_closed_day_utc": signal["decision_closed_day_utc"],
                           "orders_sent_this_invocation": 0, "plan": p.public(), "policy": asdict(policy)}
                if args.verify_signer_only:
                    receipt.update(signer)
                destination = args.state_dir / "execution_preflight.json"
            receipt["observed_at_utc"] = datetime.now(timezone.utc).isoformat()
            _atomic_bytes(destination, json.dumps(receipt, indent=2, allow_nan=False).encode() + b"\n")
            print(json.dumps(receipt, allow_nan=False))
            return 0 if not args.execute_live or receipt.get("account_aligned", receipt.get("readback", {}).get("aligned", False)) else 2
    except Exception as exc:
        # Never stringify SDK/HTTP exceptions: they can contain signed payloads.
        known = ("STALE_OR_UNCLOSED_SIGNAL", "WRONG_STRATEGY", "CLEAN_TRADING_DISABLED", "SYSTEMD_CREDENTIAL_REQUIRED",
                 "NAMED_AGENT_NOT_AUTHORIZED_OR_EXPIRED", "DIFFERENT_TARGET_FOR_FROZEN_DAY")
        reason = str(exc) if str(exc) in known else type(exc).__name__
        error = {"status": "RECONCILE_REQUIRED" if args.execute_live else "PREFLIGHT_FAILED", "reason": reason,
                 "live_mode_requested": args.execute_live, "orders_sent": "UNKNOWN_CHECK_DURABLE_JOURNAL" if args.execute_live else 0,
                 "observed_at_utc": datetime.now(timezone.utc).isoformat()}
        _atomic_bytes(args.state_dir / "execution_error.json", json.dumps(error, indent=2).encode() + b"\n")
        print(json.dumps(error), file=sys.stderr)
        return 2
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
