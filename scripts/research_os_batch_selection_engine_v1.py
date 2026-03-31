from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"
POLICIES_DIR = RESEARCH_OS_ROOT / "policies"
DEFAULT_BATCH_POLICY_PATH = POLICIES_DIR / "research_os_batch_selection_policy_v1.json"
DEFAULT_CONSTRAINTS_POLICY_PATH = POLICIES_DIR / "research_os_portfolio_constraints_policy_v1.json"
DEFAULT_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"
DEFAULT_BATCHES_ROOT = RESEARCH_OS_ROOT / "batches"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_dt(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        return datetime.max.replace(tzinfo=timezone.utc)
    text = text.replace(" UTC", "+00:00").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.max.replace(tzinfo=timezone.utc)


class Runtime:
    def __init__(self, script_name: str) -> None:
        self.script_name = script_name
        self.saved_files: List[Path] = []

    def log(self, message: str) -> None:
        print(f"[{self.script_name}] {message}")

    def fail(self, message: str) -> None:
        self.log(f"FAIL {message}")
        raise RuntimeError(message)

    def check_file(self, label: str, path: Path) -> None:
        self.log(f"CHECK file {label}: {path}")
        if not path.exists() or not path.is_file():
            self.fail(f"missing file {label}: {path}")
        self.log(f"OK file {label}: size_bytes={path.stat().st_size}")

    def check_dir(self, label: str, path: Path) -> None:
        self.log(f"CHECK dir {label}: {path}")
        if not path.exists() or not path.is_dir():
            self.fail(f"missing dir {label}: {path}")
        self.log(f"OK dir {label}")

    def save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self.saved_files.append(path)
        self.log(f"SAVED kind=json path={path}")

    def save_csv(self, path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        self.saved_files.append(path)
        self.log(f"SAVED kind=csv path={path} rows={len(rows)} cols={len(fieldnames)}")

    def save_jsonl(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.saved_files.append(path)
        self.log(f"SAVED kind=jsonl path={path} rows={len(rows)}")


@dataclass
class CandidateContext:
    candidate_id: str
    batch_id: str
    batch_dir: Path
    run_dir: Optional[Path]
    spec_path: Optional[Path]
    branch: str
    experiment_family: str
    policy_version: str
    created_at: str
    final_score: float
    promotion_recommendation: str
    compare_context_missing: int
    precheck_decision: str
    precheck_failed: int
    suspicious_uplift_flag: int
    lifecycle_status: str
    recent_failure_ts: str
    raw: Dict[str, Any]


REQUIRED_REGISTRY_COLUMNS = [
    "candidate_id",
]

OPTIONAL_REGISTRY_ALIASES = {
    "candidate_id": ["candidate_id", "experiment_id"],
    "run_dir": ["run_dir", "latest_run_dir"],
    "spec_path": ["spec_path", "experiment_spec_path"],
    "branch": ["branch", "scope"],
    "experiment_family": ["experiment_family", "family"],
    "policy_version": ["policy_version", "scoring_policy_version"],
    "created_at": ["created_at", "created_utc"],
    "final_score": ["final_score", "latest_score"],
    "promotion_recommendation": ["promotion_recommendation", "promotion_decision"],
    "compare_context_missing": ["compare_context_missing"],
    "precheck_decision": ["precheck_decision", "decision"],
    "precheck_failed": ["precheck_failed"],
    "suspicious_uplift_flag": ["suspicious_uplift_flag"],
    "lifecycle_status": ["lifecycle_status", "status", "final_status", "lifecycle_stage"],
    "recent_failure_ts": ["recent_failure_ts", "last_failure_at", "failed_at", "updated_utc"],
}


def normalize_int(value: Any, default: int = 0) -> int:
    text = str(value if value is not None else "").strip()
    if text == "":
        return default
    try:
        return int(float(text))
    except Exception:
        return default


def normalize_float(value: Any, default: float = 0.0) -> float:
    text = str(value if value is not None else "").strip()
    if text == "":
        return default
    try:
        return float(text)
    except Exception:
        return default


def resolve_column(row: Dict[str, Any], logical_name: str, default: str = "") -> str:
    for candidate in OPTIONAL_REGISTRY_ALIASES.get(logical_name, [logical_name]):
        if candidate in row and str(row[candidate]).strip() != "":
            return str(row[candidate]).strip()
    return default


def load_json_file(rt: Runtime, label: str, path: Path) -> Dict[str, Any]:
    rt.check_file(label, path)
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        rt.fail(f"{label} must be json object: {path}")
    return payload


def load_registry_rows(rt: Runtime, path: Path) -> List[Dict[str, Any]]:
    rt.check_file("candidates_registry", path)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        rt.fail("candidates_registry.csv is empty")

    headers = list(rows[0].keys())
    for required in REQUIRED_REGISTRY_COLUMNS:
        aliases = OPTIONAL_REGISTRY_ALIASES[required]
        if not any(alias in headers for alias in aliases):
            rt.fail(f"missing required registry column for {required}; expected one of {aliases}")

    rt.log(f"CHECK registry rows={len(rows)} cols={len(headers)}")
    return rows


def build_candidate_contexts(
    registry_rows: List[Dict[str, Any]],
    selected_candidate_ids: Optional[set[str]],
    batch_id: str,
    batch_dir: Path,
) -> List[CandidateContext]:
    contexts: List[CandidateContext] = []

    for row in registry_rows:
        candidate_id = resolve_column(row, "candidate_id")
        if not candidate_id:
            continue
        if selected_candidate_ids and candidate_id not in selected_candidate_ids:
            continue

        run_dir_raw = resolve_column(row, "run_dir")
        spec_path_raw = resolve_column(row, "spec_path")
        score_value = normalize_float(resolve_column(row, "final_score", "0"))

        promotion_value = resolve_column(row, "promotion_recommendation", "")
        if not promotion_value:
            promotion_value = "hold" if score_value > 0 else "kill"

        created_value = resolve_column(row, "created_at", "")
        if not created_value:
            created_value = str(row.get("created_utc", "")).strip() or str(row.get("updated_utc", "")).strip()

        branch_value = resolve_column(row, "branch", "__default__") or "__default__"
        family_value = resolve_column(row, "experiment_family", "unknown") or "unknown"

        contexts.append(
            CandidateContext(
                candidate_id=candidate_id,
                batch_id=batch_id,
                batch_dir=batch_dir,
                run_dir=Path(run_dir_raw) if run_dir_raw else None,
                spec_path=Path(spec_path_raw) if spec_path_raw else None,
                branch=branch_value,
                experiment_family=family_value,
                policy_version=resolve_column(row, "policy_version", "unknown"),
                created_at=created_value,
                final_score=score_value,
                promotion_recommendation=promotion_value,
                compare_context_missing=normalize_int(resolve_column(row, "compare_context_missing", "0")),
                precheck_decision=resolve_column(row, "precheck_decision", ""),
                precheck_failed=normalize_int(resolve_column(row, "precheck_failed", "0")),
                suspicious_uplift_flag=normalize_int(resolve_column(row, "suspicious_uplift_flag", "0")),
                lifecycle_status=resolve_column(row, "lifecycle_status", ""),
                recent_failure_ts=resolve_column(row, "recent_failure_ts", ""),
                raw=row,
            )
        )

    return contexts


def require_batch_id_from_batch_dir(batch_dir: Optional[Path]) -> Tuple[str, Path]:
    if batch_dir is None:
        batch_id = f"selection_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        batch_dir = DEFAULT_BATCHES_ROOT / batch_id
    else:
        batch_id = batch_dir.name
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_id, batch_dir


def is_recent_failure(candidate: CandidateContext, cooldown_hours: int) -> bool:
    if not candidate.recent_failure_ts:
        return False
    failed_at = parse_dt(candidate.recent_failure_ts)
    if failed_at == datetime.max.replace(tzinfo=timezone.utc):
        return False
    age_seconds = (datetime.now(timezone.utc) - failed_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds < cooldown_hours * 3600


def branch_priority(policy: Dict[str, Any], branch: str) -> int:
    table = policy.get("branch_priority", {})
    if branch in table:
        return int(table[branch])
    return int(table.get("__default__", 0))


def selection_rank_key(policy: Dict[str, Any], candidate: CandidateContext) -> Tuple[Any, ...]:
    return (
        -candidate.final_score,
        -branch_priority(policy, candidate.branch),
        parse_dt(candidate.created_at),
        candidate.candidate_id,
    )


def validate_candidate_context(candidate: CandidateContext, selection_policy: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if candidate.compare_context_missing != 0 and bool(selection_policy.get("require_compare_context", True)):
        reasons.append("compare_context_missing")

    if candidate.promotion_recommendation not in selection_policy.get("allowed_recommendations", []):
        reasons.append("invalid_promotion_recommendation")

    if candidate.final_score < float(selection_policy.get("minimum_final_score", 0.0)):
        reasons.append("below_minimum_final_score")

    if candidate.promotion_recommendation not in selection_policy.get("eligible_recommendations", []):
        reasons.append("non_eligible_recommendation")

    if bool(selection_policy.get("require_precheck_pass_for_selection", False)):
        if candidate.precheck_decision != "precheck_passed" or candidate.precheck_failed != 0:
            reasons.append("precheck_not_passed")

    if not candidate.created_at:
        reasons.append("missing_created_at")

    if not candidate.candidate_id:
        reasons.append("missing_candidate_id")

    return len(reasons) == 0, reasons


def family_key(policy: Dict[str, Any], candidate: CandidateContext) -> str:
    fields = policy.get("duplicate_family_suppression", {}).get("family_key_fields", ["experiment_family", "branch"])
    parts: List[str] = []

    for field in fields:
        if field == "experiment_family":
            parts.append(candidate.experiment_family)
        elif field == "branch":
            parts.append(candidate.branch)
        else:
            parts.append(str(candidate.raw.get(field, "")))

    return "|".join(parts)


def select_candidates(
    candidates: List[CandidateContext],
    batch_policy: Dict[str, Any],
    constraints_policy: Dict[str, Any],
) -> Tuple[List[CandidateContext], List[Dict[str, Any]]]:
    logs: List[Dict[str, Any]] = []
    ranked = sorted(candidates, key=lambda c: selection_rank_key(batch_policy, c))

    selected: List[CandidateContext] = []
    seen_ids: set[str] = set()
    branch_counts: Dict[str, int] = {}
    family_counts: Dict[str, int] = {}
    promote_slots_used = 0

    top_n = int(batch_policy.get("top_n_per_batch", 0))
    quotas = constraints_policy.get("branch_quotas", {})
    diversity = constraints_policy.get("diversity_constraints", {})
    cooldown_cfg = batch_policy.get("recent_failure_cooldown", {})
    duplicate_cfg = batch_policy.get("duplicate_family_suppression", {})
    slot_cfg = batch_policy.get("promotion_slot_allocation", {})

    for candidate in ranked:
        allowed, hard_reasons = validate_candidate_context(candidate, batch_policy)
        decision = "selected"
        reason_codes: List[str] = []

        if not allowed:
            decision = "rejected"
            reason_codes.extend(hard_reasons)

        if candidate.candidate_id in seen_ids:
            decision = "rejected"
            reason_codes.append("duplicate_candidate_id")

        if cooldown_cfg.get("enabled", False):
            cooldown_hours = int(cooldown_cfg.get("cooldown_hours", 24))
            if is_recent_failure(candidate, cooldown_hours):
                decision = "rejected"
                reason_codes.append("recent_failure_cooldown")

        branch_quota = int(quotas.get(candidate.branch, quotas.get("__default__", top_n)))
        if branch_counts.get(candidate.branch, 0) >= branch_quota:
            decision = "rejected"
            reason_codes.append("branch_quota_exceeded")

        if diversity.get("enabled", True):
            max_same_branch = int(diversity.get("max_same_branch", branch_quota))
            if branch_counts.get(candidate.branch, 0) >= max_same_branch:
                decision = "rejected"
                reason_codes.append("diversity_same_branch_exceeded")

            max_same_family = int(diversity.get("max_same_family", 1))
            fam_key = family_key(batch_policy, candidate)
            if family_counts.get(fam_key, 0) >= max_same_family:
                decision = "rejected"
                reason_codes.append("diversity_same_family_exceeded")

        if duplicate_cfg.get("enabled", True):
            fam_key = family_key(batch_policy, candidate)
            max_per_family = int(duplicate_cfg.get("max_per_family", 1))
            if family_counts.get(fam_key, 0) >= max_per_family:
                decision = "rejected"
                reason_codes.append("duplicate_family_suppressed")

        if candidate.promotion_recommendation == "promote_to_precheck":
            total_slots = int(slot_cfg.get("total_slots", top_n))
            per_branch_max = int(slot_cfg.get("per_branch_max", branch_quota))
            if promote_slots_used >= total_slots:
                decision = "rejected"
                reason_codes.append("promotion_slots_exhausted")
            elif branch_counts.get(candidate.branch, 0) >= per_branch_max:
                decision = "rejected"
                reason_codes.append("promotion_branch_slots_exhausted")

        if len(selected) >= top_n:
            decision = "rejected"
            reason_codes.append("top_n_limit_reached")

        if decision == "selected":
            selected.append(candidate)
            seen_ids.add(candidate.candidate_id)
            branch_counts[candidate.branch] = branch_counts.get(candidate.branch, 0) + 1

            fam_key = family_key(batch_policy, candidate)
            family_counts[fam_key] = family_counts.get(fam_key, 0) + 1

            if candidate.promotion_recommendation == "promote_to_precheck":
                promote_slots_used += 1

        logs.append(
            {
                "ts": now_utc_iso(),
                "batch_id": candidate.batch_id,
                "candidate_id": candidate.candidate_id,
                "branch": candidate.branch,
                "experiment_family": candidate.experiment_family,
                "final_score": round(candidate.final_score, 6),
                "promotion_recommendation": candidate.promotion_recommendation,
                "selection_decision": decision,
                "reason_codes": reason_codes,
            }
        )

    return selected, logs


def build_result_payload(
    batch_id: str,
    batch_dir: Path,
    selected: List[CandidateContext],
    decision_logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "batch_id": batch_id,
        "batch_dir": str(batch_dir),
        "generated_at": now_utc_iso(),
        "selected_count": len(selected),
        "selected_candidates": [
            {
                "candidate_id": c.candidate_id,
                "branch": c.branch,
                "experiment_family": c.experiment_family,
                "final_score": round(c.final_score, 6),
                "promotion_recommendation": c.promotion_recommendation,
                "policy_version": c.policy_version,
                "run_dir": str(c.run_dir) if c.run_dir else "",
                "spec_path": str(c.spec_path) if c.spec_path else "",
            }
            for c in selected
        ],
        "decision_log_count": len(decision_logs),
    }


def build_summary_rows(batch_id: str, selected: List[CandidateContext], decision_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rejected = [x for x in decision_logs if x["selection_decision"] == "rejected"]
    promote_count = sum(1 for c in selected if c.promotion_recommendation == "promote_to_precheck")
    hold_count = sum(1 for c in selected if c.promotion_recommendation == "hold")

    return [
        {
            "batch_id": batch_id,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "promote_to_precheck_count": promote_count,
            "hold_count": hold_count,
            "unique_branches_selected": len({c.branch for c in selected}),
            "unique_families_selected": len({c.experiment_family for c in selected}),
            "generated_at": now_utc_iso(),
        }
    ]


def parse_candidate_ids(values: Optional[List[str]]) -> Optional[set[str]]:
    if not values:
        return None
    out: set[str] = set()
    for item in values:
        for piece in item.split(","):
            piece = piece.strip()
            if piece:
                out.add(piece)
    return out or None


def main() -> None:
    parser = argparse.ArgumentParser(description="Research OS Batch Selection Engine v1")
    parser.add_argument("--batch-dir", dest="batch_dir", default="", help="Explicit batch output dir")
    parser.add_argument("--candidate-id", action="append", dest="candidate_ids", help="Candidate id filter; repeatable or comma list")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    rt = Runtime("research_os_batch_selection_engine_v1.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    rt.check_dir("research_os_root", RESEARCH_OS_ROOT)
    rt.check_dir("policies_dir", POLICIES_DIR)

    batch_policy = load_json_file(rt, "batch_selection_policy", DEFAULT_BATCH_POLICY_PATH)
    constraints_policy = load_json_file(rt, "portfolio_constraints_policy", DEFAULT_CONSTRAINTS_POLICY_PATH)
    registry_rows = load_registry_rows(rt, DEFAULT_REGISTRY_PATH)

    batch_id, batch_dir = require_batch_id_from_batch_dir(Path(args.batch_dir) if args.batch_dir else None)
    selected_candidate_ids = parse_candidate_ids(args.candidate_ids)

    contexts = build_candidate_contexts(
        registry_rows=registry_rows,
        selected_candidate_ids=selected_candidate_ids,
        batch_id=batch_id,
        batch_dir=batch_dir,
    )

    if not contexts:
        rt.fail("no candidate contexts matched input filters")

    selected, decision_logs = select_candidates(contexts, batch_policy, constraints_policy)

    outputs_cfg = constraints_policy["selection_outputs"]
    result_path = batch_dir / outputs_cfg["batch_selection_result_filename"]
    summary_path = batch_dir / outputs_cfg["batch_selection_summary_filename"]
    log_path = batch_dir / outputs_cfg["selection_decision_log_filename"]

    if args.execute:
        result_payload = build_result_payload(batch_id, batch_dir, selected, decision_logs)
        summary_rows = build_summary_rows(batch_id, selected, decision_logs)

        rt.save_json(result_path, result_payload)
        rt.save_csv(
            summary_path,
            summary_rows,
            fieldnames=[
                "batch_id",
                "selected_count",
                "rejected_count",
                "promote_to_precheck_count",
                "hold_count",
                "unique_branches_selected",
                "unique_families_selected",
                "generated_at",
            ],
        )
        rt.save_jsonl(log_path, decision_logs)

    rejected_count = sum(1 for x in decision_logs if x["selection_decision"] == "rejected")
    promote_count = sum(1 for c in selected if c.promotion_recommendation == "promote_to_precheck")
    hold_count = sum(1 for c in selected if c.promotion_recommendation == "hold")

    rt.log(f"mode={'execute' if args.execute else 'dry_run'}")
    rt.log(f"batch_id={batch_id}")
    rt.log(f"selected_count={len(selected)}")
    rt.log(f"rejected_count={rejected_count}")
    rt.log(f"promote_to_precheck_count={promote_count}")
    rt.log(f"hold_count={hold_count}")
    rt.log(f"END status=OK saved_files_count={len(rt.saved_files)}")

    rt.log(f"SUMMARY mode={'execute' if args.execute else 'dry_run'}")
    rt.log(f"SUMMARY batch_id={batch_id}")
    rt.log(f"SUMMARY selected_count={len(selected)}")
    rt.log(f"SUMMARY rejected_count={rejected_count}")
    rt.log(f"SUMMARY result_path={result_path}")
    rt.log(f"SUMMARY summary_path={summary_path}")
    rt.log(f"SUMMARY decision_log_path={log_path}")


if __name__ == "__main__":
    main()