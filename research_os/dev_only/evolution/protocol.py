"""Frozen chronological controls; no selection or strategy changes."""
from datetime import date, timedelta
import re


RULE = "all_controls_and_continuous_union_beat_cash_net_return_and_fitness_exploratory_failure_vetoes"


def validate_protocol(protocol, bindings):
    if protocol.get("protocol_version") != "cash_stability_v2" or protocol.get("decision_rule") != RULE:
        raise ValueError("Unsupported chronological protocol")
    for key, expected in bindings.items():
        if protocol.get(key) != expected:
            raise ValueError(f"Protocol binding mismatch: {key}")
    if protocol.get("iml_required") is not False or protocol.get("promotion_allowed") is not False:
        raise ValueError("Protocol must exclude IML and promotion")
    controls = protocol.get("control_windows", [])
    if len(controls) < 3:
        raise ValueError("At least three chronological control windows required")
    exploratory = protocol.get("exploratory", {})
    if exploratory.get("already_seen") is not True or exploratory.get("evidence_role") != "exploratory_only":
        raise ValueError("Explicit already-seen exploratory disclosure required")
    expected_start = date.fromisoformat(bindings["validation_end"]) + timedelta(days=1)
    ids = {"train", "validation_1", "validation_2", "final_test", "control_continuous"}
    for window in [*controls, exploratory]:
        name = window.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", name) or name in ids:
            raise ValueError("Invalid or duplicate evaluation window ID")
        ids.add(name)
        start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
        if start != expected_start or (end - start).days < 29:
            raise ValueError("Controls must be consecutive, forward-only periods of at least 30 days")
        expected_start = end + timedelta(days=1)
    if exploratory["end"] != bindings["holdout_end"]:
        raise ValueError("Exploratory period must end at the frozen input horizon")


def comparison(candidate, cash, btc):
    beats_return = candidate["total_return"] > cash["total_return"]
    beats_fitness = candidate["fitness"] > cash["fitness"]
    return {
        "candidate": candidate, "cash": cash, "buy_and_hold": btc,
        "beats_cash_return": beats_return, "beats_cash_risk_adjusted": beats_fitness,
        "return_delta_vs_cash": candidate["total_return"] - cash["total_return"],
        "fitness_delta_vs_cash": candidate["fitness"] - cash["fitness"],
        "return_delta_vs_btc": candidate["total_return"] - btc["total_return"],
        "fitness_delta_vs_btc": candidate["fitness"] - btc["fitness"],
        "status": "PASS" if beats_return and beats_fitness else "REJECT",
    }


def stability_decision(controls, continuous, exploratory):
    passing = sum(window["status"] == "PASS" for window in controls)
    stable = passing == len(controls) and continuous["status"] == "PASS"
    exploratory_veto = exploratory["status"] != "PASS"
    passed = stable and not exploratory_veto
    return {
        "status": "PASS" if passed else "REJECT",
        "control_windows_passed": passing, "control_window_count": len(controls),
        "stable_against_cash": stable, "exploratory_failure_veto": exploratory_veto,
        "exploratory_evidence_role": "already_seen_exploratory_only",
        "generation_extension_allowed": False, "promotion_allowed": False,
        "next_action": "prospective_observation_only" if passed else "stop_and_propose_different_strategy_family",
    }
