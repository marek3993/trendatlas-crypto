from __future__ import annotations

from typing import Dict, List, Set


ALLOWED_STATUS_FLOW: Dict[str, List[str]] = {
    "proposed": ["spec_ready"],
    "spec_ready": ["queued"],
    "queued": ["running"],
    "running": ["run_failed", "ran"],
    "ran": ["scored"],
    "scored": ["precheck_failed", "precheck_passed"],
    "precheck_passed": ["forensic_ready"],
    "precheck_failed": ["archived"],
    "run_failed": ["archived"],
    "forensic_ready": [],
    "archived": [],
}

FORBIDDEN_FINAL_STATES: Set[str] = {"promoted", "forensic_passed"}


def validate_transition(from_status: str, to_status: str) -> None:
    allowed = ALLOWED_STATUS_FLOW.get(from_status, [])
    if to_status not in allowed:
        raise RuntimeError(f"invalid lifecycle transition: {from_status} -> {to_status}")