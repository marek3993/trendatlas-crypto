from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research_os_registry_io import (
    append_jsonl,
    ensure_text_file,
    extract_numeric_score,
    read_json,
    save_json,
    timestamp_local,
    timestamp_utc,
    update_candidates_registry,
)
from research_os_state_machine import (
    FORBIDDEN_FINAL_STATES,
    validate_transition,
)


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"

TRUTH_PACK_PATH = RESEARCH_OS_ROOT / "single_truth" / "truth_pack.json"
ROOT_MANIFEST_PATH = RESEARCH_OS_ROOT / "research_os_manifest.json"
SCHEMA_INDEX_PATH = RESEARCH_OS_ROOT / "schemas" / "schema_index.json"
CANDIDATES_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"

RUNS_ROOT = RESEARCH_OS_ROOT / "runs"
PROMOTION_QUEUE_ROOT = RESEARCH_OS_ROOT / "promotion_queue"

RUN_FOLDER_CONTRACT_PATH = RESEARCH_OS_ROOT / "runs" / "templates" / "run_folder_contract.json"
RUN_STATUS_TEMPLATE_PATH = RESEARCH_OS_ROOT / "runs" / "templates" / "run_status.template.json"

DEFAULT_SCORE_THRESHOLD = 0.0
TRANSIENT_EXIT_CODES = {124, 137, 143, -9}


@dataclass
class Runtime:
    script_name: str
    started_mono: float
    counters: Dict[str, Any]

    @classmethod
    def start(cls, script_name: str) -> "Runtime":
        rt = cls(script_name=script_name, started_mono=time.monotonic(), counters={})
        rt.log("START")
        rt.log(f"cwd={Path.cwd()}")
        rt.log(f"python={sys.executable}")
        rt.log(f"argv={' '.join(sys.argv)}")
        return rt

    def log(self, message: str) -> None:
        print(f"[{timestamp_local()}] [{self.script_name}] {message}", flush=True)

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value
        self.log(f"{key}={value}")

    def fail(self, message: str) -> None:
        self.log(f"FAIL {message}")
        raise RuntimeError(message)

    def finish_ok(self, extra: Optional[Dict[str, Any]] = None) -> None:
        elapsed = time.monotonic() - self.started_mono
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")
        if extra:
            for k, v in extra.items():
                self.log(f"SUMMARY {k}={v}")

    def finish_fail(self, message: str) -> None:
        elapsed = time.monotonic() - self.started_mono
        self.log(f"ERROR {message}")
        self.log(f"END status=FAIL elapsed_sec={elapsed:.3f}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")


def require_file(rt: Runtime, path: Path, label: str) -> Path:
    rt.log(f"CHECK file {label}: {path}")
    if not path.exists() or not path.is_file():
        rt.fail(f"missing required file: {path}")
    rt.log(f"OK file {label}: size_bytes={path.stat().st_size}")
    return path


def require_dir(rt: Runtime, path: Path, label: str) -> Path:
    rt.log(f"CHECK dir {label}: {path}")
    if not path.exists() or not path.is_dir():
        rt.fail(f"missing required directory: {path}")
    rt.log(f"OK dir {label}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS Orchestrator v1")
    parser.add_argument("--spec", required=True, help="Explicit path to experiment spec JSON")
    parser.add_argument("--allow-status", required=True, choices=["spec_ready"], help="Allowed starting spec status")
    parser.add_argument("--dry-run", action="store_true", help="Validate and plan only")
    parser.add_argument("--execute", action="store_true", help="Execute the explicit script")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise SystemExit("Choose exactly one of --dry-run or --execute.")
    return args


def generate_run_id(experiment_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = experiment_id.lower().replace(" ", "_")
    return f"run_{stamp}_{safe}"


def validate_spec_against_contract(
    rt: Runtime,
    spec: Dict[str, Any],
    schema: Dict[str, Any],
    allow_status: str,
) -> None:
    required_fields = schema["required_fields"]
    missing = [k for k in required_fields if k not in spec]
    if missing:
        rt.fail(f"spec missing required fields: {missing}")

    strict_rules = schema.get("strict_rules", {})
    if strict_rules.get("allow_unknown_top_level_fields") is False:
        unknown = sorted(set(spec.keys()) - set(required_fields))
        if unknown:
            rt.fail(f"spec contains unknown top-level fields: {unknown}")

    allowed_status_values = schema["allowed_status_values"]
    if spec["status"] not in allowed_status_values:
        rt.fail(f"spec status outside contract enum: {spec['status']}")

    if spec["status"] != allow_status:
        rt.fail(f"spec status must equal --allow-status={allow_status}, got {spec['status']}")

    if not isinstance(spec["input_paths"], list) or not spec["input_paths"]:
        rt.fail("spec input_paths must be non-empty list")
    if not isinstance(spec["script_args"], list):
        rt.fail("spec script_args must be list")
    if not isinstance(spec["expected_outputs"], list) or not spec["expected_outputs"]:
        rt.fail("spec expected_outputs must be non-empty list")

    script_path = Path(spec["script_path"])
    require_file(rt, script_path, "script_path")

    baseline_path = Path(spec["baseline_paper_path"])
    require_file(rt, baseline_path, "baseline_paper_path")

    for idx, raw_path in enumerate(spec["input_paths"], start=1):
        require_file(rt, Path(raw_path), f"input_path_{idx}")

    rt.log("OK spec contract validation")


def make_run_folder(rt: Runtime, run_id: str) -> Path:
    run_dir = RUNS_ROOT / run_id
    rt.log(f"ENSURE dir run_dir: {run_dir}")
    if run_dir.exists():
        rt.fail(f"run_dir already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    rt.log("OK dir run_dir")
    return run_dir


def init_run_files(
    rt: Runtime,
    run_dir: Path,
    run_id: str,
    spec_path: Path,
    spec: Dict[str, Any],
    contract: Dict[str, Any],
) -> Tuple[Path, Path, Path, Path, Path, Path, Path]:
    lifecycle_audit_path = run_dir / "lifecycle_audit.jsonl"
    run_manifest_path = run_dir / "run_manifest.json"
    run_status_path = run_dir / "run_status.json"
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    artifacts_index_path = run_dir / "artifacts_index.json"
    quality_report_path = run_dir / "quality_report.json"
    precheck_inputs_path = run_dir / "precheck_inputs.json"

    ensure_text_file(stdout_path, "")
    ensure_text_file(stderr_path, "")

    manifest = {
        "schema_version": "2.0",
        "run_id": run_id,
        "experiment_id": spec["experiment_id"],
        "candidate_id": spec["experiment_id"],
        "status": "queued",
        "started_utc": None,
        "ended_utc": None,
        "artifact_root": str(run_dir),
        "spec_path": str(spec_path),
        "input_refs": spec["input_paths"],
        "output_refs": [],
        "metrics": {},
        "quality_checks": {
            "status": "pending",
            "checks": [],
        },
        "exit_code": None,
        "notes": None,
    }
    save_json(run_manifest_path, manifest)

    run_status_template = read_json(RUN_STATUS_TEMPLATE_PATH)
    run_status_template["run_id"] = run_id
    run_status_template["experiment_id"] = spec["experiment_id"]
    run_status_template["candidate_id"] = spec["experiment_id"]
    run_status_template["status"] = "queued"
    run_status_template["updated_at"] = timestamp_utc()
    save_json(run_status_path, run_status_template)

    save_json(
        precheck_inputs_path,
        {
            "schema_version": "2.0",
            "run_id": run_id,
            "spec_path": str(spec_path),
            "baseline_paper_path": spec["baseline_paper_path"],
            "input_paths": spec["input_paths"],
            "expected_outputs": spec["expected_outputs"],
            "run_folder_contract": contract["required_run_artifacts"],
        },
    )

    save_json(
        artifacts_index_path,
        {
            "schema_version": "2.0",
            "run_id": run_id,
            "required_run_artifacts": contract["required_run_artifacts"],
            "conditional_artifacts": contract.get("conditional_artifacts", {}),
            "produced_files": [],
        },
    )

    save_json(
        quality_report_path,
        {
            "schema_version": "2.0",
            "run_id": run_id,
            "status": "pending",
            "checks": [],
        },
    )

    append_jsonl(
        lifecycle_audit_path,
        {
            "ts": timestamp_utc(),
            "run_id": run_id,
            "from_status": spec["status"],
            "to_status": "queued",
            "reason": "orchestrator_init",
        },
    )

    rt.log(f"SAVED kind=json path={run_manifest_path}")
    rt.log(f"SAVED kind=json path={run_status_path}")
    rt.log(f"SAVED kind=json path={precheck_inputs_path}")
    rt.log(f"SAVED kind=json path={artifacts_index_path}")
    rt.log(f"SAVED kind=json path={quality_report_path}")
    rt.log(f"SAVED kind=jsonl path={lifecycle_audit_path}")

    return (
        run_manifest_path,
        run_status_path,
        stdout_path,
        stderr_path,
        artifacts_index_path,
        quality_report_path,
        lifecycle_audit_path,
    )


def update_run_status_file(run_status_path: Path, new_status: str, reason: str) -> None:
    payload = read_json(run_status_path)
    payload["status"] = new_status
    payload["status_reason"] = reason
    payload["updated_at"] = timestamp_utc()
    if new_status == "running" and payload.get("started_at") is None:
        payload["started_at"] = timestamp_utc()
    if new_status in {"ran", "run_failed", "archived", "precheck_failed", "precheck_passed", "forensic_ready"}:
        payload["ended_at"] = timestamp_utc()
    save_json(run_status_path, payload)


def update_run_manifest_file(
    run_manifest_path: Path,
    *,
    status: Optional[str] = None,
    started_utc: Optional[str] = None,
    ended_utc: Optional[str] = None,
    exit_code: Optional[int] = None,
    output_refs: Optional[List[str]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    quality_checks: Optional[Dict[str, Any]] = None,
) -> None:
    payload = read_json(run_manifest_path)
    if status is not None:
        payload["status"] = status
    if started_utc is not None:
        payload["started_utc"] = started_utc
    if ended_utc is not None:
        payload["ended_utc"] = ended_utc
    if exit_code is not None:
        payload["exit_code"] = exit_code
    if output_refs is not None:
        payload["output_refs"] = output_refs
    if metrics is not None:
        payload["metrics"] = metrics
    if quality_checks is not None:
        payload["quality_checks"] = quality_checks
    save_json(run_manifest_path, payload)


def execute_script(
    rt: Runtime,
    spec: Dict[str, Any],
    run_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> Tuple[int, bool]:
    cmd = [sys.executable, spec["script_path"], *spec["script_args"]]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    env["RESEARCH_OS_RUN_DIR"] = str(run_dir)
    env["RESEARCH_OS_EXPERIMENT_ID"] = spec["experiment_id"]

    rt.log(f"EXEC cmd={' '.join(cmd)}")
    rt.log(f"EXEC cwd={run_dir}")

    timed_out = False
    with stdout_path.open("w", encoding="utf-8") as stdout_f, stderr_path.open("w", encoding="utf-8") as stderr_f:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(run_dir),
                env=env,
                stdout=stdout_f,
                stderr=stderr_f,
                text=True,
                timeout=None,
                check=False,
            )
            exit_code = int(result.returncode)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
            stderr_f.write("TimeoutExpired\n")

    rt.log(f"EXEC exit_code={exit_code}")
    rt.log(f"EXEC timed_out={int(timed_out)}")
    return exit_code, timed_out


def collect_outputs(spec: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    produced_files: List[str] = []
    expected_output_paths: List[Path] = []

    for name in spec["expected_outputs"]:
        out_path = run_dir / name
        expected_output_paths.append(out_path)
        if out_path.exists():
            produced_files.append(str(out_path))

    summary_path = run_dir / "summary.csv"
    paper_path = run_dir / "paper.csv"
    compare_path = run_dir / "compare.csv"

    return {
        "expected_output_paths": [str(p) for p in expected_output_paths],
        "produced_files": produced_files,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "paper_path": str(paper_path) if paper_path.exists() else None,
        "compare_path": str(compare_path) if compare_path.exists() else None,
        "has_summary": summary_path.exists(),
        "has_paper": paper_path.exists(),
        "has_compare": compare_path.exists(),
    }


def validate_required_artifacts(
    contract: Dict[str, Any],
    run_dir: Path,
    spec: Dict[str, Any],
) -> Tuple[bool, List[str], List[str]]:
    missing_required: List[str] = []
    for name in contract["required_run_artifacts"]:
        if not (run_dir / name).exists():
            missing_required.append(name)

    missing_expected_outputs: List[str] = []
    for name in spec["expected_outputs"]:
        if not (run_dir / name).exists():
            missing_expected_outputs.append(name)

    return (len(missing_required) == 0, missing_required, missing_expected_outputs)


def decide_post_run(
    *,
    exit_code: int,
    timed_out: bool,
    artifacts_ok: bool,
    missing_required: List[str],
    missing_expected_outputs: List[str],
    extracted_score: Optional[float],
    compare_valid: bool,
    score_threshold: float,
) -> Tuple[str, str, str]:
    """
    Returns:
      next_state_after_scored: one of scored / precheck_failed / precheck_passed
      decision: kill / hold / rerun / promote_to_precheck
      reason: string
    """
    if exit_code != 0:
        raise RuntimeError("decide_post_run called for non-zero exit code")

    if not artifacts_ok:
        return ("precheck_failed", "kill", f"missing_required_artifacts:{missing_required}")

    if missing_expected_outputs:
        return ("precheck_failed", "kill", f"invalid_ingest_missing_outputs:{missing_expected_outputs}")

    if extracted_score is None:
        return ("scored", "hold", "valid_run_but_no_numeric_score")

    if not compare_valid:
        return ("scored", "hold", "valid_run_but_compare_missing_or_invalid")

    if extracted_score > score_threshold:
        return ("precheck_passed", "promote_to_precheck", f"score_above_threshold:{extracted_score}")

    return ("scored", "hold", f"score_not_above_threshold:{extracted_score}")


def main() -> None:
    args = parse_args()
    rt = Runtime.start("research_os_orchestrator_v1.py")

    try:
        require_dir(rt, RESEARCH_OS_ROOT, "research_os_root")
        require_dir(rt, RUNS_ROOT, "runs_root")
        require_dir(rt, PROMOTION_QUEUE_ROOT, "promotion_queue_root")

        require_file(rt, TRUTH_PACK_PATH, "truth_pack")
        require_file(rt, ROOT_MANIFEST_PATH, "research_os_manifest")
        require_file(rt, SCHEMA_INDEX_PATH, "schema_index")
        require_file(rt, RUN_FOLDER_CONTRACT_PATH, "run_folder_contract")
        require_file(rt, RUN_STATUS_TEMPLATE_PATH, "run_status_template")
        require_file(rt, CANDIDATES_REGISTRY_PATH, "candidates_registry")

        spec_path = Path(args.spec)
        require_file(rt, spec_path, "spec_path")

        schema_index = read_json(SCHEMA_INDEX_PATH)
        contract = read_json(RUN_FOLDER_CONTRACT_PATH)
        spec_schema = read_json(Path(schema_index["schemas"]["experiment_spec"]))
        promotion_schema = read_json(Path(schema_index["schemas"]["promotion_decision"]))

        spec = read_json(spec_path)
        validate_spec_against_contract(rt, spec, spec_schema, args.allow_status)

        run_id = generate_run_id(spec["experiment_id"])
        rt.set_counter("run_id", run_id)
        rt.set_counter("mode", "dry_run" if args.dry_run else "execute")

        if args.dry_run:
            rt.log(f"DRY_RUN would create run_dir={RUNS_ROOT / run_id}")
            rt.log(f"DRY_RUN would execute script_path={spec['script_path']}")
            rt.log(f"DRY_RUN script_args={spec['script_args']}")
            rt.finish_ok(
                {
                    "spec_path": str(spec_path),
                    "allow_status": args.allow_status,
                    "candidate_id": spec["experiment_id"],
                }
            )
            return

        run_dir = make_run_folder(rt, run_id)
        (
            run_manifest_path,
            run_status_path,
            stdout_path,
            stderr_path,
            artifacts_index_path,
            quality_report_path,
            lifecycle_audit_path,
        ) = init_run_files(rt, run_dir, run_id, spec_path, spec, contract)

        validate_transition("spec_ready", "queued")
        update_run_status_file(run_status_path, "queued", "orchestrator_queued")
        update_run_manifest_file(run_manifest_path, status="queued")

        validate_transition("queued", "running")
        append_jsonl(
            lifecycle_audit_path,
            {
                "ts": timestamp_utc(),
                "run_id": run_id,
                "from_status": "queued",
                "to_status": "running",
                "reason": "execution_started",
            },
        )
        update_run_status_file(run_status_path, "running", "execution_started")
        update_run_manifest_file(run_manifest_path, status="running", started_utc=timestamp_utc())

        exit_code, timed_out = execute_script(rt, spec, run_dir, stdout_path, stderr_path)

        if exit_code != 0:
            validate_transition("running", "run_failed")
            append_jsonl(
                lifecycle_audit_path,
                {
                    "ts": timestamp_utc(),
                    "run_id": run_id,
                    "from_status": "running",
                    "to_status": "run_failed",
                    "reason": f"process_exit_code_{exit_code}",
                },
            )
            update_run_status_file(run_status_path, "run_failed", f"process_exit_code_{exit_code}")
            update_run_manifest_file(
                run_manifest_path,
                status="run_failed",
                ended_utc=timestamp_utc(),
                exit_code=exit_code,
            )

            decision = "rerun" if timed_out or exit_code in TRANSIENT_EXIT_CODES else "kill"
            decision_reason = "transient_incomplete_run" if decision == "rerun" else f"run_failed_exit_code_{exit_code}"

            validate_transition("run_failed", "archived")
            append_jsonl(
                lifecycle_audit_path,
                {
                    "ts": timestamp_utc(),
                    "run_id": run_id,
                    "from_status": "run_failed",
                    "to_status": "archived",
                    "reason": decision_reason,
                },
            )
            update_run_status_file(run_status_path, "archived", decision_reason)
            update_run_manifest_file(run_manifest_path, status="archived")

            outputs = collect_outputs(spec, run_dir)
            artifacts_ok, missing_required, missing_expected_outputs = validate_required_artifacts(contract, run_dir, spec)
            extracted_score = extract_numeric_score(run_dir)
            compare_valid = outputs["has_compare"]

        else:
            validate_transition("running", "ran")
            append_jsonl(
                lifecycle_audit_path,
                {
                    "ts": timestamp_utc(),
                    "run_id": run_id,
                    "from_status": "running",
                    "to_status": "ran",
                    "reason": f"process_exit_code_{exit_code}",
                },
            )
            update_run_status_file(run_status_path, "ran", f"process_exit_code_{exit_code}")
            update_run_manifest_file(
                run_manifest_path,
                status="ran",
                ended_utc=timestamp_utc(),
                exit_code=exit_code,
            )

            outputs = collect_outputs(spec, run_dir)
            artifacts_ok, missing_required, missing_expected_outputs = validate_required_artifacts(contract, run_dir, spec)
            extracted_score = extract_numeric_score(run_dir)
            compare_valid = outputs["has_compare"]

            validate_transition("ran", "scored")
            append_jsonl(
                lifecycle_audit_path,
                {
                    "ts": timestamp_utc(),
                    "run_id": run_id,
                    "from_status": "ran",
                    "to_status": "scored",
                    "reason": "post_run_ingest_started",
                },
            )
            update_run_status_file(run_status_path, "scored", "post_run_ingest_started")
            update_run_manifest_file(run_manifest_path, status="scored")

            next_state_after_scored, decision, decision_reason = decide_post_run(
                exit_code=exit_code,
                timed_out=timed_out,
                artifacts_ok=artifacts_ok,
                missing_required=missing_required,
                missing_expected_outputs=missing_expected_outputs,
                extracted_score=extracted_score,
                compare_valid=compare_valid,
                score_threshold=DEFAULT_SCORE_THRESHOLD,
            )

            if next_state_after_scored == "precheck_failed":
                validate_transition("scored", "precheck_failed")
                append_jsonl(
                    lifecycle_audit_path,
                    {
                        "ts": timestamp_utc(),
                        "run_id": run_id,
                        "from_status": "scored",
                        "to_status": "precheck_failed",
                        "reason": decision_reason,
                    },
                )
                update_run_status_file(run_status_path, "precheck_failed", decision_reason)
                update_run_manifest_file(run_manifest_path, status="precheck_failed")

                validate_transition("precheck_failed", "archived")
                append_jsonl(
                    lifecycle_audit_path,
                    {
                        "ts": timestamp_utc(),
                        "run_id": run_id,
                        "from_status": "precheck_failed",
                        "to_status": "archived",
                        "reason": "orchestrator_archive_after_failed_precheck",
                    },
                )
                update_run_status_file(run_status_path, "archived", "orchestrator_archive_after_failed_precheck")
                update_run_manifest_file(run_manifest_path, status="archived")

            elif next_state_after_scored == "precheck_passed":
                validate_transition("scored", "precheck_passed")
                append_jsonl(
                    lifecycle_audit_path,
                    {
                        "ts": timestamp_utc(),
                        "run_id": run_id,
                        "from_status": "scored",
                        "to_status": "precheck_passed",
                        "reason": decision_reason,
                    },
                )
                update_run_status_file(run_status_path, "precheck_passed", decision_reason)
                update_run_manifest_file(run_manifest_path, status="precheck_passed")

                validate_transition("precheck_passed", "forensic_ready")
                append_jsonl(
                    lifecycle_audit_path,
                    {
                        "ts": timestamp_utc(),
                        "run_id": run_id,
                        "from_status": "precheck_passed",
                        "to_status": "forensic_ready",
                        "reason": "orchestrator_queue_for_forensic",
                    },
                )
                update_run_status_file(run_status_path, "forensic_ready", "orchestrator_queue_for_forensic")
                update_run_manifest_file(run_manifest_path, status="forensic_ready")

            elif next_state_after_scored == "scored":
                # hold path, stays in scored
                pass
            else:
                rt.fail(f"unexpected next_state_after_scored: {next_state_after_scored}")

        final_registry_status = read_json(run_status_path)["status"]
        if final_registry_status in FORBIDDEN_FINAL_STATES:
            rt.fail(f"orchestrator attempted forbidden final state: {final_registry_status}")

        artifacts_index = read_json(artifacts_index_path)
        artifacts_index["produced_files"] = outputs["produced_files"]
        artifacts_index["ingest"] = {
            "summary_path": outputs["summary_path"],
            "paper_path": outputs["paper_path"],
            "compare_path": outputs["compare_path"],
            "has_summary": outputs["has_summary"],
            "has_paper": outputs["has_paper"],
            "has_compare": outputs["has_compare"],
        }
        save_json(artifacts_index_path, artifacts_index)

        quality_report = {
            "schema_version": "2.0",
            "run_id": run_id,
            "status": "passed" if artifacts_ok and not missing_expected_outputs else "failed",
            "checks": [
                {"name": "required_run_artifacts", "ok": artifacts_ok, "missing": missing_required},
                {"name": "expected_outputs", "ok": len(missing_expected_outputs) == 0, "missing": missing_expected_outputs},
                {"name": "numeric_score_extract", "ok": extracted_score is not None, "value": extracted_score},
                {"name": "compare_valid", "ok": compare_valid},
            ],
        }
        save_json(quality_report_path, quality_report)

        update_run_manifest_file(
            run_manifest_path,
            output_refs=outputs["produced_files"],
            metrics={"extracted_score": extracted_score},
            quality_checks=quality_report,
        )

        promotion_decision = {
            "decision_id": f"decision_{run_id}",
            "candidate_id": spec["experiment_id"],
            "source_run_id": run_id,
            "decision": decision,
            "decision_reason": decision_reason,
            "decided_by": "research_os_orchestrator_v1",
            "decided_at": timestamp_utc(),
            "evidence_refs": outputs["produced_files"],
        }

        if decision not in promotion_schema["allowed_decision_values"]:
            rt.fail(f"promotion decision outside allowed contract enum: {decision}")

        promotion_path = PROMOTION_QUEUE_ROOT / f"{run_id}_promotion_decision.json"
        save_json(promotion_path, promotion_decision)
        rt.log(f"SAVED kind=json path={promotion_path}")

        update_candidates_registry(
            CANDIDATES_REGISTRY_PATH,
            candidate_id=spec["experiment_id"],
            fields={
                "candidate_name": spec["experiment_id"],
                "family": spec["experiment_family"],
                "scope": spec["segment_owner"],
                "baseline_ref": spec["baseline_model"],
                "spec_path": str(spec_path),
                "owner": spec["created_by"],
                "status": final_registry_status,
                "lifecycle_stage": final_registry_status,
                "latest_run_id": run_id,
                "latest_score": extracted_score if extracted_score is not None else "",
                "promotion_decision": decision,
                "updated_utc": timestamp_utc(),
                "notes": decision_reason,
            },
        )

        rt.set_counter("exit_code", exit_code)
        rt.set_counter("final_status", final_registry_status)
        rt.set_counter("decision", decision)
        rt.set_counter("artifacts_ok", int(artifacts_ok))
        rt.set_counter("missing_expected_outputs", len(missing_expected_outputs))

        rt.finish_ok(
            {
                "run_dir": str(run_dir),
                "run_manifest_path": str(run_manifest_path),
                "run_status_path": str(run_status_path),
                "promotion_decision_path": str(promotion_path),
            }
        )

    except Exception as exc:
        for line in traceback.format_exc().rstrip().splitlines():
            rt.log(f"TRACE {line}")
        rt.finish_fail(str(exc))
        raise


if __name__ == "__main__":
    main()