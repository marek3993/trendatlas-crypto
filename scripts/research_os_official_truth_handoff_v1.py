from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"
POLICIES_DIR = RESEARCH_OS_ROOT / "policies"
BATCHES_ROOT = RESEARCH_OS_ROOT / "batches"
DEFAULT_POLICY_PATH = POLICIES_DIR / "research_os_official_truth_handoff_policy_v1.json"
DEFAULT_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


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
class HandoffContext:
    candidate_id: str
    batch_dir: Path
    run_dir: Path
    spec_path: Path
    gate_decision: str
    approval_status: str
    evidence_complete: bool
    lineage_context_present: bool
    policy_context_present: bool
    policy_version: str
    gate_result_path: Path
    checklist_path: Path
    evidence_bundle_path: Path
    rollback_record_path: Path
    registry_row: Dict[str, Any]


def load_json(rt: Runtime, label: str, path: Path) -> Dict[str, Any]:
    rt.check_file(label, path)
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        rt.fail(f"{label} must be json object: {path}")
    return payload


def load_csv_rows(rt: Runtime, label: str, path: Path) -> List[Dict[str, Any]]:
    rt.check_file(label, path)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


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
    return load_csv_rows(rt, "candidates_registry", path)


def find_latest_batch_dir(rt: Runtime) -> Path:
    rt.check_dir("batches_root", BATCHES_ROOT)
    dirs = [p for p in BATCHES_ROOT.iterdir() if p.is_dir()]
    if not dirs:
        rt.fail(f"no batch directories found in {BATCHES_ROOT}")
    dirs.sort(key=lambda p: p.name, reverse=True)
    return dirs[0]


def resolve_candidate_id(
    rt: Runtime,
    candidate_id_arg: Optional[str],
    gate_result: Dict[str, Any],
) -> str:
    if candidate_id_arg:
        return candidate_id_arg
    candidate_id = str(gate_result.get("candidate_id", "")).strip()
    if not candidate_id:
        rt.fail("candidate_id missing from official_promotion_gate_result.json")
    return candidate_id


def find_registry_row(rt: Runtime, registry_rows: List[Dict[str, Any]], candidate_id: str) -> Dict[str, Any]:
    row = next((r for r in registry_rows if str(r.get("candidate_id", "")).strip() == candidate_id), None)
    if row is None:
        rt.fail(f"candidate_id not found in registry: {candidate_id}")
    return row


def build_context(
    rt: Runtime,
    batch_dir: Path,
    candidate_id_arg: Optional[str],
    registry_rows: List[Dict[str, Any]],
) -> HandoffContext:
    gate_result_path = batch_dir / "official_promotion_gate_result.json"
    checklist_path = batch_dir / "official_promotion_checklist.csv"
    evidence_bundle_path = batch_dir / "promotion_evidence_bundle.json"
    rollback_record_path = batch_dir / "rollback_ready_promotion_record.json"

    gate_result = load_json(rt, "official_promotion_gate_result", gate_result_path)
    load_csv_rows(rt, "official_promotion_checklist", checklist_path)
    evidence_bundle = load_json(rt, "promotion_evidence_bundle", evidence_bundle_path)
    load_json(rt, "rollback_ready_promotion_record", rollback_record_path)

    candidate_id = resolve_candidate_id(rt, candidate_id_arg, gate_result)
    registry_row = find_registry_row(rt, registry_rows, candidate_id)

    run_dir = Path(str(gate_result.get("run_dir", "")).strip())
    spec_path = Path(str(gate_result.get("spec_path", "")).strip())
    if not str(run_dir):
        rt.fail("run_dir missing in official_promotion_gate_result.json")
    if not str(spec_path):
        rt.fail("spec_path missing in official_promotion_gate_result.json")

    rt.check_dir("run_dir", run_dir)
    rt.check_file("spec_path", spec_path)

    evidence_complete = bool(gate_result.get("evidence_complete", False))
    lineage_context_present = bool(gate_result.get("lineage_context_present", False))
    policy_context_present = bool(gate_result.get("policy_context_present", False))
    approval_status = str(gate_result.get("approval_status", "")).strip()
    gate_decision = str(gate_result.get("gate_decision", "")).strip()
    policy_version = str(gate_result.get("policy_version", "")).strip()

    if evidence_bundle.get("candidate_id") != candidate_id:
        rt.fail("promotion_evidence_bundle candidate_id mismatch")

    return HandoffContext(
        candidate_id=candidate_id,
        batch_dir=batch_dir,
        run_dir=run_dir,
        spec_path=spec_path,
        gate_decision=gate_decision,
        approval_status=approval_status,
        evidence_complete=evidence_complete,
        lineage_context_present=lineage_context_present,
        policy_context_present=policy_context_present,
        policy_version=policy_version,
        gate_result_path=gate_result_path,
        checklist_path=checklist_path,
        evidence_bundle_path=evidence_bundle_path,
        rollback_record_path=rollback_record_path,
        registry_row=registry_row,
    )


def evaluate_handoff(policy: Dict[str, Any], ctx: HandoffContext) -> tuple[str, List[str], str]:
    reasons: List[str] = []

    admission = policy["handoff_admission_rules"]
    manual = policy["manual_approval_validation_rules"]
    safe = policy["safe_outcomes"]

    if ctx.gate_decision != admission["required_gate_decision"]:
        reasons.append("gate_not_passed")

    if ctx.approval_status not in manual["approval_status_allowed"]:
        reasons.append("invalid_manual_approval_state")

    if ctx.approval_status == "rejected":
        return safe["manual_rejected"], ["manual_rejected"], "manual_rejected"

    if ctx.approval_status not in admission["required_approval_statuses"]:
        reasons.append("approval_state_not_admissible")

    if admission["require_evidence_complete"] and not ctx.evidence_complete:
        reasons.append("evidence_incomplete")

    if admission["require_lineage_context"] and not ctx.lineage_context_present:
        reasons.append("lineage_incomplete")

    if admission["require_policy_context"] and not ctx.policy_context_present:
        reasons.append("policy_context_incomplete")

    if reasons:
        return safe["missing_approval"], reasons, "blocked"

    if ctx.approval_status == "approved":
        finalization_state = "finalization_ready"
    else:
        finalization_state = manual["manual_finalization_status_default"]

    return "handoff_staged", [], finalization_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Research OS Official Truth Handoff v1")
    parser.add_argument("--batch-dir", default="", help="Explicit batch dir")
    parser.add_argument("--candidate-id", default="", help="Explicit candidate id")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    rt = Runtime("research_os_official_truth_handoff_v1.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    rt.check_dir("research_os_root", RESEARCH_OS_ROOT)
    rt.check_dir("policies_dir", POLICIES_DIR)

    batch_dir = Path(args.batch_dir) if args.batch_dir else find_latest_batch_dir(rt)
    rt.check_dir("batch_dir", batch_dir)

    policy = load_json(rt, "official_truth_handoff_policy", DEFAULT_POLICY_PATH)
    registry_rows = load_registry_rows(rt, DEFAULT_REGISTRY_PATH)
    ctx = build_context(rt, batch_dir, args.candidate_id.strip() or None, registry_rows)

    handoff_decision, reason_codes, finalization_state = evaluate_handoff(policy, ctx)

    policy_context = {
        "official_truth_handoff_policy_version": policy.get("policy_version", "unknown"),
        "gate_policy_version": ctx.policy_version
    }

    truth_update_staging = {
        "record_version": "1.0",
        "generated_at": utc_now_iso(),
        "candidate_id": ctx.candidate_id,
        "run_dir": str(ctx.run_dir),
        "spec_path": str(ctx.spec_path),
        "promotion_manifest_path": str(batch_dir / "promotion_manifest.json"),
        "rollback_pointer_path": str(batch_dir / "rollback_pointer.json"),
        "policy_version": policy.get("policy_version", "unknown"),
        "approval_status": ctx.approval_status,
        "gate_decision": ctx.gate_decision,
        "finalization_state": finalization_state,
        "staging_only": True,
        "write_truth_pack_directly": False
    }

    promotion_manifest = {
        "record_version": "1.0",
        "generated_at": utc_now_iso(),
        "candidate_id": ctx.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(ctx.run_dir),
        "spec_path": str(ctx.spec_path),
        "gate_result_path": str(ctx.gate_result_path),
        "checklist_path": str(ctx.checklist_path),
        "evidence_bundle_path": str(ctx.evidence_bundle_path),
        "rollback_record_path": str(ctx.rollback_record_path),
        "truth_update_staging_path": str(batch_dir / "truth_update_staging.json"),
        "policy_version": policy.get("policy_version", "unknown"),
        "approval_status": ctx.approval_status,
        "handoff_decision": handoff_decision,
        "finalization_state": finalization_state
    }

    rollback_pointer = {
        "record_version": "1.0",
        "generated_at": utc_now_iso(),
        "candidate_id": ctx.candidate_id,
        "run_id": ctx.run_dir.name,
        "spec_path": str(ctx.spec_path),
        "rollback_record_path": str(ctx.rollback_record_path),
        "promotion_manifest_path": str(batch_dir / "promotion_manifest.json"),
        "created_at": utc_now_iso(),
        "policy_version": policy.get("policy_version", "unknown")
    }

    manual_finalization_record = {
        "record_version": "1.0",
        "generated_at": utc_now_iso(),
        "candidate_id": ctx.candidate_id,
        "approval_status": ctx.approval_status,
        "handoff_decision": handoff_decision,
        "finalization_state": finalization_state,
        "manual_finalization_required": True,
        "official_truth_changed": False,
        "policy_version_context": policy_context,
        "reason_codes": reason_codes
    }

    handoff_result = {
        "policy_version": policy.get("policy_version", "unknown"),
        "generated_at": utc_now_iso(),
        "candidate_id": ctx.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(ctx.run_dir),
        "spec_path": str(ctx.spec_path),
        "handoff_decision": handoff_decision,
        "approval_status": ctx.approval_status,
        "finalization_state": finalization_state,
        "evidence_complete": ctx.evidence_complete,
        "lineage_context_present": ctx.lineage_context_present,
        "policy_context_present": ctx.policy_context_present,
        "official_truth_changed": False,
        "reason_codes": reason_codes
    }

    handoff_log_row = {
        "ts": utc_now_iso(),
        "candidate_id": ctx.candidate_id,
        "batch_dir": str(batch_dir),
        "run_dir": str(ctx.run_dir),
        "spec_path": str(ctx.spec_path),
        "handoff_decision": handoff_decision,
        "approval_status": ctx.approval_status,
        "finalization_state": finalization_state,
        "reason_codes": reason_codes,
        "policy_version": policy.get("policy_version", "unknown")
    }

    result_path = batch_dir / "official_truth_handoff_result.json"
    staging_path = batch_dir / "truth_update_staging.json"
    manifest_path = batch_dir / "promotion_manifest.json"
    rollback_pointer_path = batch_dir / "rollback_pointer.json"
    finalization_record_path = batch_dir / "manual_finalization_record.json"
    log_path = batch_dir / "official_truth_handoff_log.jsonl"

    if args.execute:
        rt.save_json(result_path, handoff_result)
        rt.save_json(staging_path, truth_update_staging)
        rt.save_json(manifest_path, promotion_manifest)
        rt.save_json(rollback_pointer_path, rollback_pointer)
        rt.save_json(finalization_record_path, manual_finalization_record)
        rt.save_jsonl(log_path, [handoff_log_row])

    rt.log(f"candidate_id={ctx.candidate_id}")
    rt.log(f"handoff_decision={handoff_decision}")
    rt.log(f"approval_status={ctx.approval_status}")
    rt.log(f"finalization_state={finalization_state}")
    rt.log(f"reason_codes_count={len(reason_codes)}")
    rt.log(f"END status=OK saved_files_count={len(rt.saved_files)}")

    rt.log(f"SUMMARY mode={'execute' if args.execute else 'dry_run'}")
    rt.log(f"SUMMARY candidate_id={ctx.candidate_id}")
    rt.log(f"SUMMARY handoff_decision={handoff_decision}")
    rt.log(f"SUMMARY approval_status={ctx.approval_status}")
    rt.log(f"SUMMARY finalization_state={finalization_state}")
    rt.log(f"SUMMARY result_path={result_path}")
    rt.log(f"SUMMARY staging_path={staging_path}")
    rt.log(f"SUMMARY manifest_path={manifest_path}")
    rt.log(f"SUMMARY rollback_pointer_path={rollback_pointer_path}")
    rt.log(f"SUMMARY finalization_record_path={finalization_record_path}")
    rt.log(f"SUMMARY log_path={log_path}")


if __name__ == "__main__":
    main()