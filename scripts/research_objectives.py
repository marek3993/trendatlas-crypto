"""Offline research screening, Pareto selection and evidence gates.

This module does not simulate trades, certify supplied metrics or promote models.
Replay engines supply measured metrics and hash-bound audit artifacts. Missing
evidence fails closed. No production adapter, network or order API is imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "source_of_truth/research_objectives_contract.json"
BINDING_KEYS = ("candidate_id", "input_sha256", "code_sha256", "parameters_sha256", "contract_sha256", "evaluation_sha256")


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def contract_sha256() -> str:
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def evaluation_sha256(candidate: dict) -> str | None:
    payload = {key: candidate.get(key) for key in ("id", "mode", "exposure_cap", "nominee_categories", "development", "oos", "sealed")}
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def metrics_issues(metrics: dict, contract: dict) -> list[str]:
    issues = []
    for key in contract["fitness"]["objectives"]:
        if not finite(metrics.get(key)):
            issues.append(f"missing_or_nonfinite:{key}")
    for key in ("max_drawdown", "profitable_fold_fraction", "parameter_stability"):
        if finite(metrics.get(key)) and not 0 <= metrics[key] <= 1:
            issues.append(f"invalid_fraction:{key}")
    for key in ("asset_log_growth_share", "trade_log_growth_share", "turnover", "cost_drag", "max_realized_exposure"):
        if not finite(metrics.get(key)) or metrics[key] < 0:
            issues.append(f"invalid_nonnegative:{key}")
    for key in ("cagr", "worst_fold_return", "without_best_day_cagr", "without_top_three_trades_cagr",
                "double_cost_cagr", "delayed_entry_cagr"):
        if finite(metrics.get(key)) and metrics[key] < -1:
            issues.append(f"invalid_return:{key}")
    if not issues:
        dd = metrics["max_drawdown"]
        if dd == 0 or not math.isclose(metrics["calmar"], metrics["cagr"] / dd, rel_tol=1e-6, abs_tol=1e-9):
            issues.append("calmar_not_reconciled")
    return issues


def fold_issues(metrics: dict) -> list[str]:
    folds = metrics.get("fold_returns")
    if not isinstance(folds, list) or not folds or any(not finite(x) or x < -1 for x in folds):
        return ["missing_or_invalid_fold_returns"]
    fraction = sum(x > 0 for x in folds) / len(folds)
    if metrics.get("profitable_fold_fraction") != fraction or metrics.get("worst_fold_return") != min(folds):
        return ["fold_summary_not_reconciled"]
    return []


def feasibility(candidate: dict, metrics: dict, contract: dict) -> list[str]:
    issues = metrics_issues(metrics, contract)
    mode = contract["modes"].get(candidate.get("mode"))
    if mode is None:
        return issues + ["invalid_mode"]
    cap = candidate.get("exposure_cap")
    if not finite(cap) or cap not in mode["exposure_caps"]:
        issues.append("invalid_exposure_cap")
    elif finite(metrics.get("max_realized_exposure")) and metrics["max_realized_exposure"] > cap + 1e-12:
        issues.append("account_exposure_cap_exceeded")
    if finite(metrics.get("max_drawdown")) and metrics["max_drawdown"] > mode["drawdown_cap"]:
        issues.append("drawdown_cap_exceeded")
    return issues


def high_return_issues(metrics: dict, contract: dict, *, sealed: bool) -> list[str]:
    gates = contract["high_return_gates"]
    limits = {
        "cagr": ("min", gates["sealed_cagr_min" if sealed else "oos_cagr_min"]),
        "max_drawdown": ("max", gates["max_drawdown_max"]),
        "sharpe": ("min", gates["sharpe_min"]),
        "calmar": ("min", gates["calmar_min"]),
        "without_best_day_cagr": ("min", gates["without_best_day_cagr_min"]),
        "without_top_three_trades_cagr": ("min", gates["without_top_three_trades_cagr_min"]),
        "double_cost_cagr": ("min", gates["double_cost_cagr_min"]),
        "delayed_entry_cagr": ("strict_min", gates["delayed_entry_cagr_strict_min"]),
        "asset_log_growth_share": ("max", gates["asset_log_growth_share_max"]),
        "trade_log_growth_share": ("max", gates["trade_log_growth_share_max"]),
    }
    if not sealed:
        limits.update({"profitable_fold_fraction": ("min", gates["profitable_fold_fraction_min"]),
                       "worst_fold_return": ("min", -gates["worst_fold_loss_max"])})
    issues = []
    for key, (direction, limit) in limits.items():
        value = metrics.get(key)
        if not finite(value) or (direction == "min" and value < limit) or (direction == "max" and value > limit) or (direction == "strict_min" and value <= limit):
            issues.append(key)
    return issues


def audit_passed(name: str, reports: dict, binding: dict, evidence_root: Path) -> bool:
    """Verify result binding and evidence bytes; never infer an audit from CAGR."""
    report = reports.get(name, {})
    if not isinstance(report, dict) or report.get("passed") is not True or report.get("binding") != binding:
        return False
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    root = evidence_root.resolve()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            return False
        path = (root / artifact["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
            return False
    return True


def assess(candidate: dict, evidence_root: Path, *, audit_runner: Callable | None = None) -> dict:
    """Evaluate a frozen candidate. A high result automatically invokes a supplied
    replay audit runner with ALL extended checks before any finalist decision.
    Without a runner, existing bound reports are checked; missing checks block.
    Runner exceptions block the candidate. The CLI never launches arbitrary code.
    """
    contract = load_contract()
    oos, sealed = candidate.get("oos", {}), candidate.get("sealed", {})
    oos_errors = feasibility(candidate, oos, contract) + fold_issues(oos)
    sealed_errors = feasibility(candidate, sealed, contract)
    binding = candidate.get("binding", {})
    binding_valid = (
        set(binding) == set(BINDING_KEYS)
        and isinstance(candidate.get("id"), str) and bool(candidate["id"])
        and binding.get("candidate_id") == candidate["id"]
        and binding.get("contract_sha256") == contract_sha256()
        and binding.get("evaluation_sha256") == evaluation_sha256(candidate)
        and all(isinstance(binding.get(k), str) and len(binding[k]) == 64
                and all(c in "0123456789abcdef" for c in binding[k]) for k in BINDING_KEYS[1:])
    )
    required = list(contract["required_audits"]) + ["sealed_evaluation", "selection_frozen_before_seal"]
    high = any(finite(candidate.get(part, {}).get("cagr"))
               and candidate[part]["cagr"] >= contract["high_return_gates"]["extended_audit_trigger_cagr"]
               for part in ("development", "oos", "sealed"))
    reports = dict(candidate.get("audits", {}))
    audit_error = None
    if high:
        required += contract["extended_audit_checks"]
        if audit_runner is not None:
            try:
                # A failed fresh replay overrides a previously passing report.
                names = contract["extended_audit_checks"]
                refreshed = audit_runner(candidate, tuple(names))
                for name in names:
                    reports[name] = refreshed.get(name, {})
            except Exception as exc:
                audit_error = type(exc).__name__
                for name in contract["extended_audit_checks"]:
                    reports[name] = {}
    missing_audits = [name for name in required if not binding_valid or not audit_passed(name, reports, binding, evidence_root)]
    numeric_failures = {"oos": high_return_issues(oos, contract, sealed=False),
                        "sealed": high_return_issues(sealed, contract, sealed=True)}
    feasible = not (oos_errors or sealed_errors or missing_audits or audit_error)
    high_pass = feasible and not any(numeric_failures.values())
    return {
        "id": candidate.get("id"), "mode": candidate.get("mode"),
        "contract_sha256": contract_sha256(), "binding_valid": binding_valid,
        "feasible_frozen_candidate": feasible,
        "high_return_gates_passed": high_pass,
        "robust_candidate_passed": feasible and candidate.get("mode") == "robust",
        "extended_audit_required": high,
        "extended_audit_runner_invoked": high and audit_runner is not None,
        "audit_error": audit_error, "missing_or_failed_audits": missing_audits,
        "oos_errors": oos_errors, "sealed_errors": sealed_errors,
        "high_return_failures": numeric_failures,
        "production_promotion_allowed": False,
        "interpretation": "Evidence screening only; finalist designation also requires the pre-seal nomination record. No trading experiment is run by this evaluator."
    }


def final_verdict(nominees: dict, candidates: list[dict], evidence_root: Path, *, audit_runner: Callable | None = None) -> dict:
    """Evaluate predeclared A/B/C nominees without selecting on sealed metrics.

    A passed, bound selection_frozen_before_seal report must include evidence of
    the nomination and seal access timeline. Missing nominees stay empty.
    """
    by_id = {c["id"]: c for c in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("Duplicate candidate IDs")
    reviews = {key: assess(candidate, evidence_root, audit_runner=audit_runner) for key, candidate in by_id.items()}
    outcome = {"A": None, "B": None, "C": None}
    flags = {"A": "high_return_gates_passed", "B": "robust_candidate_passed", "C": "feasible_frozen_candidate"}
    for category, flag in flags.items():
        nominee = nominees.get(category)
        if nominee in reviews and reviews[nominee][flag]:
            # Category must appear in the audited nomination artifact; caller
            # cannot change category membership after seeing the seal.
            if category in by_id[nominee].get("nominee_categories", []):
                outcome[category] = nominee
    return {**outcome, "D": outcome["A"] is None, "assessments": reviews,
            "production_promotion_allowed": False,
            "frontier_limit": "Only measured tested candidates; not a global attainable-return bound."}


def pareto_front(candidates: list[dict], *, mode: str, exposure_cap: float) -> list[str]:
    """Separate development front for a single mode/cap. NEVER ranks sealed/OOS.

    Feasibility is checked first, so excessive drawdown cannot buy a higher rank.
    This development front is provisional until scientific audits pass.
    """
    contract = load_contract()
    if mode not in contract["modes"] or exposure_cap not in contract["modes"][mode]["exposure_caps"]:
        raise ValueError("Unsupported mode/exposure partition")
    ids = [c.get("id") for c in candidates]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Candidate IDs must be nonempty and unique")
    pool = [c for c in candidates if c.get("mode") == mode and c.get("exposure_cap") == exposure_cap
            and not feasibility(c, c.get("development", {}), contract)]
    def dominates(left: dict, right: dict) -> bool:
        a, b = left["development"], right["development"]
        comparisons = [(a[k] - b[k]) * (1 if direction == "max" else -1)
                       for k, direction in contract["fitness"]["objectives"].items()]
        return all(x >= 0 for x in comparisons) and any(x > 0 for x in comparisons)
    return sorted(c["id"] for c in pool if not any(dominates(other, c) for other in pool if other is not c))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="Frozen candidate metrics and audit references JSON")
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = assess(candidate, args.candidate.parent)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["feasible_frozen_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
