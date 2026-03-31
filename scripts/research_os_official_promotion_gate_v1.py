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
BATCHES_ROOT = RESEARCH_OS_ROOT / "batches"
RUNS_ROOT = RESEARCH_OS_ROOT / "runs"
DEFAULT_POLICY_PATH = POLICIES_DIR / "research_os_official_promotion_policy_v1.json"
DEFAULT_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_dt_maybe(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = text.replace(" UTC", "+00:00").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


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
            json.dump(payload, f, indent=2, ensure_ascii=False)
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
    batch_dir: Path
    run_dir: Path
    spec_path: Path
    created_at: str
    final_score: float
    promotion_recommendation: str
    lifecycle_status: str
    scoring_policy_version: str
    precheck_policy_version: str
    selection_policy_version: str


def load_json(rt: Runtime, label: str, path: Path) -> Dict[str, Any]:
    rt.check_file(label, path)
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        rt.fail(f"{label} must be a json object: {path}")
    return payload


def load_jsonl(rt: Runtime, label: str, path: Path) -> List[Dict[str, Any]]:
    rt.check_file(label, path)
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception as exc:
                rt.fail(f"invalid jsonl in {label} line={idx}: {exc}")
            if not isinstance(obj, dict):
                rt.fail(f"jsonl row must be object in {label} line={idx}")
            rows.append(obj)
    return rows


def load_registry_rows(rt: Runtime, path: Path) -> List[Dict[str, Any]]:
    rt.check_file("candidates_registry", path)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        rt.fail("candidates_registry.csv is empty")
    return rows


def find_latest_batch_dir(rt: Runtime) -> Path:
    rt.check_dir("batches_root", BATCHES_ROOT)
    dirs = [p for p in BATCHES_ROOT.iterdir() if p.is_dir()]
    if not dirs:
        rt.fail(f"no batch directories found in {BATCHES_ROOT}")
    dirs.sort(key=lambda p: p.name, reverse=True)
    return dirs[0]


def normalize_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        if text == "" or text.lower() == "null":
            return default
        return float(text)
    except Exception:
        return default


def resolve_scoring_final_score(scoring_result: Dict[str, Any], fallback: float = 0.0) -> float:
    top_level = scoring_result.get("final_score")
    if top_level is not None:
        return normalize_float(top_level, fallback)

    score_breakdown = scoring_result.get("score_breakdown", {})
    if isinstance(score_breakdown, dict):
        nested = score_breakdown.get("final_score")
        if nested is not None:
            return normalize_float(nested, fallback)

    candidate_metrics = scoring_result.get("candidate_metrics", {})
    if isinstance(candidate_metrics, dict):
        maybe_score = candidate_metrics.get("score")
        if maybe_score is not None:
            return normalize_float(maybe_score, fallback)

    return fallback


def resolve_run_status_value(run_status: Dict[str, Any]) -> str:
    for key in ("final_status", "status", "lifecycle_status"):
        value = str(run_status.get(key, "")).strip()
        if value:
            return value
    return ""


def resolve_candidate_ids(
    rt: Runtime,
    candidate_id_arg: Optional[str],
    batch_selection_result: Dict[str, Any],
) -> List[str]:
    if candidate_id_arg:
        return [candidate_id_arg]

    selected = batch_selection_result.get("selected_candidates", [])
    if not isinstance(selected, list):
        rt.fail("batch_selection_result.selected_candidates must be a list")

    candidate_ids: List[str] = []
    for row in selected:
        if isinstance(row, dict):
            cid = str(row.get("candidate_id", "")).strip()
            if cid:
                candidate_ids.append(cid)

    if not candidate_ids:
        rt.fail("no selected candidates found in batch_selection_result and no --candidate-id provided")

    return candidate_ids


def load_selection_decision_for_candidate(
    decision_log_rows: List[Dict[str, Any]],
    candidate_id: str,
) -> Dict[str, Any]:
    for row in decision_log_rows:
        if str(row.get("candidate_id", "")).strip() == candidate_id:
            return row
    return {}


def ensure_required_artifacts(
    run_dir: Path,
    required_files: List[str],
) -> List[str]:
    missing: List[str] = []
    for filename in required_files:
        path = run_dir / filename
        if not path.exists() or not path.is_file():
            missing.append(filename)
    return missing


def find_candidate_registry_row(rt: Runtime, registry_rows: List[Dict[str, Any]], candidate_id: str) -> Dict[str, Any]:
    row = next((r for r in registry_rows if str(r.get("candidate_id", "")).strip() == candidate_id), None)
    if row is None:
        rt.fail(f"candidate_id not found in registry: {candidate_id}")
    return row


def candidate_run_dirs(candidate_id: str) -> List[Path]:
    pattern = f"run_*_{candidate_id}"
    dirs = [p for p in RUNS_ROOT.glob(pattern) if p.is_dir()]
    dirs.sort(key=lambda p: p.name, reverse=True)
    return dirs


def is_valid_governance_run(run_dir: Path) -> bool:
    required = [
        "run_manifest.json",
        "run_status.json",
        "artifacts_index.json",
        "quality_report.json",
        "summary.csv",
        "paper.csv",
        "compare.csv",
        "scoring_result.json",
        "precheck_result.json",
    ]
    return all((run_dir / name).exists() for name in required)


def resolve_run_dir_for_candidate(
    rt: Runtime,
    candidate_id: str,
    registry_row: Dict[str, Any],
    batch_selection_result: Dict[str, Any],
) -> Path:
    selected = batch_selection_result.get("selected_candidates", [])
    if isinstance(selected, list):
        for row in selected:
            if not isinstance(row, dict):
                continue
            if str(row.get("candidate_id", "")).strip() != candidate_id:
                continue
            run_dir_raw = str(row.get("run_dir", "")).strip()
            if run_dir_raw:
                candidate_run = Path(run_dir_raw)
                if candidate_run.exists() and candidate_run.is_dir() and is_valid_governance_run(candidate_run):
                    return candidate_run

    latest_run_id = str(registry_row.get("latest_run_id", "")).strip()
    if latest_run_id:
        candidate_run = RUNS_ROOT / latest_run_id
        if candidate_run.exists() and candidate_run.is_dir() and is_valid_governance_run(candidate_run):
            return candidate_run

    all_runs = candidate_run_dirs(candidate_id)
    valid_runs = [p for p in all_runs if is_valid_governance_run(p)]
    if valid_runs:
        return valid_runs[0]

    scanned = [str(p) for p in all_runs[:10]]
    rt.fail(
        f"no valid governance run found for candidate_id={candidate_id}; "
        f"latest_run_id={latest_run_id or 'EMPTY'} scanned_runs={scanned}"
    )
    raise RuntimeError("unreachable")


def build_candidate_context(
    rt: Runtime,
    candidate_id: str,
    batch_dir: Path,
    registry_rows: List[Dict[str, Any]],
    batch_selection_result: Dict[str, Any],
) -> CandidateContext:
    registry_row = find_candidate_registry_row(rt, registry_rows, candidate_id)

    spec_path_raw = str(registry_row.get("spec_path", "")).strip()
    if not spec_path_raw:
        rt.fail(f"missing spec_path for candidate_id={candidate_id}")
    spec_path = Path(spec_path_raw)
    rt.check_file("spec_path", spec_path)

    run_dir = resolve_run_dir_for_candidate(rt, candidate_id, registry_row, batch_selection_result)
    rt.check_dir("run_dir", run_dir)

    scoring_result = load_json(rt, "scoring_result", run_dir / "scoring_result.json")
    precheck_result = load_json(rt, "precheck_result", run_dir / "precheck_result.json")

    return CandidateContext(
        candidate_id=candidate_id,
        batch_dir=batch_dir,
        run_dir=run_dir,
        spec_path=spec_path,
        created_at=str(registry_row.get("created_utc", "") or registry_row.get("updated_utc", "")).strip(),
        final_score=resolve_scoring_final_score(scoring_result, normalize_float(registry_row.get("latest_score", 0.0))),
        promotion_recommendation=str(scoring_result.get("promotion_recommendation", "")).strip(),
        lifecycle_status=str(registry_row.get("status", "")).strip(),
        scoring_policy_version=str(scoring_result.get("policy_version", "unknown")).strip(),
        precheck_policy_version=str(precheck_result.get("policy_version", "unknown")).strip(),
        selection_policy_version=str(batch_selection_result.get("policy_version", "unknown")).strip(),
    )


def build_checklist(
    policy: Dict[str, Any],
    selection_row: Dict[str, Any],
    scoring_result: Dict[str, Any],
    precheck_result: Dict[str, Any],
    run_status: Dict[str, Any],
    evidence_complete: bool,
    lineage_present: bool,
    policy_context_present: bool,
) -> List[Dict[str, Any]]:
    items = policy["promotion_checklist"]["items"]
    run_status_value = resolve_run_status_value(run_status)
    results_map = {
        "batch_selection_selected": selection_row.get("selection_decision") == "selected",
        "scoring_promote_to_precheck": scoring_result.get("promotion_recommendation") == "promote_to_precheck",
        "precheck_passed": precheck_result.get("decision") == "precheck_passed",
        "run_status_forensic_ready": run_status_value == "forensic_ready",
        "evidence_bundle_complete": evidence_complete,
        "lineage_context_present": lineage_present,
        "policy_context_present": policy_context_present,
        "manual_approval_pending_or_complete": True,
        "rollback_record_ready": True,
    }

    rows: List[Dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "check_item": item,
                "passed": int(bool(results_map.get(item, False))),
                "details": "",
            }
        )
    return rows


def decide_gate_outcome(
    policy: Dict[str, Any],
    selection_row: Dict[str, Any],
    scoring_result: Dict[str, Any],
    precheck_result: Dict[str, Any],
    run_status: Dict[str, Any],
    evidence_missing: List[str],
    lineage_present: bool,
    policy_context_present: bool,
) -> Tuple[str, List[str], str]:
    reasons: List[str] = []
    scoring_final_score = resolve_scoring_final_score(scoring_result, 0.0)
    run_status_value = resolve_run_status_value(run_status)

    if selection_row.get("selection_decision") != "selected":
        reasons.append("batch_not_selected")

    if scoring_result.get("promotion_recommendation") != policy["admission_rules"]["required_scoring_recommendation"]:
        reasons.append("scoring_not_admissible")

    if precheck_result.get("decision") != policy["admission_rules"]["required_precheck_decision"]:
        reasons.append("precheck_not_passed")

    if policy["admission_rules"]["require_forensic_ready_status"]:
        if run_status_value != "forensic_ready":
            reasons.append("run_not_forensic_ready")

    if scoring_final_score < float(policy["admission_rules"]["minimum_final_score"]):
        reasons.append("score_below_minimum")

    if evidence_missing:
        reasons.append("missing_evidence")

    if not lineage_present:
        reasons.append("broken_lineage_context")

    if not policy_context_present:
        reasons.append("broken_policy_context")

    if reasons:
        return "gate_failed", reasons, "pending_manual_approval"

    return "gate_passed", [], policy["manual_approval_hook"]["approval_status_default"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Research OS Official Promotion Gate v1")
    parser.add_argument("--batch-dir", default="", help="Explicit batch dir")
    parser.add_argument("--candidate-id", default="", help="Explicit candidate id")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    rt = Runtime("research_os_official_promotion_gate_v1.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    rt.check_dir("research_os_root", RESEARCH_OS_ROOT)
    rt.check_dir("policies_dir", POLICIES_DIR)

    batch_dir = Path(args.batch_dir) if args.batch_dir else find_latest_batch_dir(rt)
    rt.check_dir("batch_dir", batch_dir)

    policy = load_json(rt, "official_promotion_policy", DEFAULT_POLICY_PATH)
    registry_rows = load_registry_rows(rt, DEFAULT_REGISTRY_PATH)

    batch_selection_result_path = batch_dir / "batch_selection_result.json"
    batch_selection_summary_path = batch_dir / "batch_selection_summary.csv"
    decision_log_path = batch_dir / "selection_decision_log.jsonl"

    batch_selection_result = load_json(rt, "batch_selection_result", batch_selection_result_path)
    rt.check_file("batch_selection_summary", batch_selection_summary_path)
    decision_log_rows = load_jsonl(rt, "selection_decision_log", decision_log_path)

    candidate_ids = resolve_candidate_ids(rt, args.candidate_id.strip() or None, batch_selection_result)

    if len(candidate_ids) > 1:
        ranked_contexts: List[CandidateContext] = []
        for cid in candidate_ids:
            ranked_contexts.append(build_candidate_context(rt, cid, batch_dir, registry_rows, batch_selection_result))
        ranked_contexts.sort(key=lambda c: (-c.final_score, parse_dt_maybe(c.created_at), c.candidate_id))
        candidate_ids = [ranked_contexts[0].candidate_id]

    candidate = build_candidate_context(rt, candidate_ids[0], batch_dir, registry_rows, batch_selection_result)

    scoring_result = load_json(rt, "scoring_result", candidate.run_dir / "scoring_result.json")
    precheck_result = load_json(rt, "precheck_result", candidate.run_dir / "precheck_result.json")
    run_manifest = load_json(rt, "run_manifest", candidate.run_dir / "run_manifest.json")
    run_status = load_json(rt, "run_status", candidate.run_dir / "run_status.json")
    artifacts_index = load_json(rt, "artifacts_index", candidate.run_dir / "artifacts_index.json")

    selection_row = load_selection_decision_for_candidate(decision_log_rows, candidate.candidate_id)
    if not selection_row:
        rt.fail(f"candidate_id missing in selection_decision_log: {candidate.candidate_id}")

    evidence_missing = ensure_required_artifacts(
        candidate.run_dir,
        policy["evidence_requirements"]["required_run_artifacts"],
    )

    lineage_present = candidate.spec_path.exists() and candidate.run_dir.exists()
    if policy["evidence_requirements"]["require_registry_lineage_context"]:
        lineage_present = lineage_present and DEFAULT_REGISTRY_PATH.exists()

    policy_context_present = bool(
        candidate.scoring_policy_version
        and candidate.precheck_policy_version
        and candidate.selection_policy_version
        and policy.get("policy_version")
    )

    gate_decision, reason_codes, approval_status = decide_gate_outcome(
        policy=policy,
        selection_row=selection_row,
        scoring_result=scoring_result,
        precheck_result=precheck_result,
        run_status=run_status,
        evidence_missing=evidence_missing,
        lineage_present=lineage_present,
        policy_context_present=policy_context_present,
    )

    checklist_rows = build_checklist(
        policy=policy,
        selection_row=selection_row,
        scoring_result=scoring_result,
        precheck_result=precheck_result,
        run_status=run_status,
        evidence_complete=len(evidence_missing) == 0,
        lineage_present=lineage_present,
        policy_context_present=policy_context_present,
    )

    resolved_final_score = resolve_scoring_final_score(scoring_result, candidate.final_score)
    resolved_run_status = resolve_run_status_value(run_status)

    evidence_bundle = {
        "candidate_id": candidate.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(candidate.run_dir),
        "spec_path": str(candidate.spec_path),
        "batch_selection_result_path": str(batch_selection_result_path),
        "batch_selection_summary_path": str(batch_selection_summary_path),
        "selection_decision_log_path": str(decision_log_path),
        "run_manifest_path": str(candidate.run_dir / "run_manifest.json"),
        "run_status_path": str(candidate.run_dir / "run_status.json"),
        "artifacts_index_path": str(candidate.run_dir / "artifacts_index.json"),
        "quality_report_path": str(candidate.run_dir / "quality_report.json"),
        "precheck_inputs_path": str(candidate.run_dir / "precheck_inputs.json"),
        "summary_csv_path": str(candidate.run_dir / "summary.csv"),
        "paper_csv_path": str(candidate.run_dir / "paper.csv"),
        "compare_csv_path": str(candidate.run_dir / "compare.csv"),
        "scoring_result_path": str(candidate.run_dir / "scoring_result.json"),
        "precheck_result_path": str(candidate.run_dir / "precheck_result.json"),
        "evidence_missing": evidence_missing,
        "policy_version_context": {
            "official_promotion_policy_version": policy.get("policy_version", "unknown"),
            "scoring_policy_version": candidate.scoring_policy_version,
            "precheck_policy_version": candidate.precheck_policy_version,
            "selection_policy_version": candidate.selection_policy_version
        }
    }

    rollback_record = {
        "record_version": "1.0",
        "generated_at": utc_now_iso(),
        "candidate_id": candidate.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(candidate.run_dir),
        "spec_path": str(candidate.spec_path),
        "run_id": candidate.run_dir.name,
        "policy_version_lineage": evidence_bundle["policy_version_context"],
        "selection_lineage": selection_row,
        "scoring_lineage": {
            "final_score": resolved_final_score,
            "promotion_recommendation": scoring_result.get("promotion_recommendation"),
            "reason_codes": scoring_result.get("reason_codes", [])
        },
        "precheck_lineage": {
            "decision": precheck_result.get("decision"),
            "reason_codes": precheck_result.get("reason_codes", [])
        },
        "rollback_ready": True,
        "official_truth_changed": False
    }

    gate_result = {
        "policy_version": policy.get("policy_version", "unknown"),
        "generated_at": utc_now_iso(),
        "candidate_id": candidate.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(candidate.run_dir),
        "spec_path": str(candidate.spec_path),
        "gate_decision": gate_decision,
        "approval_status": approval_status,
        "manual_approval_required": bool(policy["admission_rules"]["require_manual_approval"]),
        "reason_codes": reason_codes,
        "final_score": resolved_final_score,
        "promotion_recommendation": scoring_result.get("promotion_recommendation"),
        "precheck_decision": precheck_result.get("decision"),
        "run_final_status": resolved_run_status,
        "evidence_complete": len(evidence_missing) == 0,
        "evidence_missing_count": len(evidence_missing),
        "lineage_context_present": lineage_present,
        "policy_context_present": policy_context_present,
        "official_truth_changed": False
    }

    decision_log_row = {
        "ts": utc_now_iso(),
        "candidate_id": candidate.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(candidate.run_dir),
        "spec_path": str(candidate.spec_path),
        "gate_decision": gate_decision,
        "approval_status": approval_status,
        "reason_codes": reason_codes,
        "policy_version": policy.get("policy_version", "unknown")
    }

    checklist_csv_rows: List[Dict[str, Any]] = []
    for row in checklist_rows:
        checklist_csv_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "check_item": row["check_item"],
                "passed": row["passed"],
                "details": row["details"]
            }
        )

    result_path = batch_dir / "official_promotion_gate_result.json"
    checklist_path = batch_dir / "official_promotion_checklist.csv"
    evidence_path = batch_dir / "promotion_evidence_bundle.json"
    rollback_path = batch_dir / "rollback_ready_promotion_record.json"
    decision_log_output_path = batch_dir / "promotion_gate_decision_log.jsonl"

    if args.execute:
        rt.save_json(result_path, gate_result)
        rt.save_csv(
            checklist_path,
            checklist_csv_rows,
            fieldnames=["candidate_id", "check_item", "passed", "details"],
        )
        rt.save_json(evidence_path, evidence_bundle)
        rt.save_json(rollback_path, rollback_record)
        rt.save_jsonl(decision_log_output_path, [decision_log_row])

    rt.log(f"candidate_id={candidate.candidate_id}")
    rt.log(f"resolved_run_dir={candidate.run_dir}")
    rt.log(f"resolved_final_score={resolved_final_score}")
    rt.log(f"resolved_run_status={resolved_run_status}")
    rt.log(f"gate_decision={gate_decision}")
    rt.log(f"approval_status={approval_status}")
    rt.log(f"evidence_missing_count={len(evidence_missing)}")
    rt.log(f"reason_codes_count={len(reason_codes)}")
    rt.log(f"END status=OK saved_files_count={len(rt.saved_files)}")

    rt.log(f"SUMMARY mode={'execute' if args.execute else 'dry_run'}")
    rt.log(f"SUMMARY candidate_id={candidate.candidate_id}")
    rt.log(f"SUMMARY resolved_run_dir={candidate.run_dir}")
    rt.log(f"SUMMARY resolved_final_score={resolved_final_score}")
    rt.log(f"SUMMARY resolved_run_status={resolved_run_status}")
    rt.log(f"SUMMARY gate_decision={gate_decision}")
    rt.log(f"SUMMARY approval_status={approval_status}")
    rt.log(f"SUMMARY evidence_missing_count={len(evidence_missing)}")
    rt.log(f"SUMMARY result_path={result_path}")
    rt.log(f"SUMMARY checklist_path={checklist_path}")
    rt.log(f"SUMMARY evidence_path={evidence_path}")
    rt.log(f"SUMMARY rollback_path={rollback_path}")
    rt.log(f"SUMMARY decision_log_path={decision_log_output_path}")


if __name__ == "__main__":
    main()