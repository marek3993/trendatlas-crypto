from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"

TRUTH_PACK_PATH = RESEARCH_OS_ROOT / "single_truth" / "truth_pack.json"
ROOT_MANIFEST_PATH = RESEARCH_OS_ROOT / "research_os_manifest.json"
SCHEMA_INDEX_PATH = RESEARCH_OS_ROOT / "schemas" / "schema_index.json"
CANDIDATES_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"
EXPERIMENT_SPECS_ROOT = RESEARCH_OS_ROOT / "experiment_specs"
BATCHES_ROOT = RESEARCH_OS_ROOT / "batches"

ORCHESTRATOR_V1_PATH = PROJECT_ROOT / "scripts" / "research_os_orchestrator_v1.py"


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def timestamp_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def parse_created_at(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    normalized = raw.replace(" UTC", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw.replace(" UTC", ""), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def priority_rank(value: str) -> int:
    raw = (value or "").strip().lower()
    mapping = {
        "critical": 500,
        "p0": 500,
        "urgent": 450,
        "highest": 400,
        "high": 300,
        "medium": 200,
        "normal": 200,
        "low": 100,
        "lowest": 50,
        "tiny": 25,
    }
    if raw in mapping:
        return mapping[raw]
    try:
        return int(raw)
    except Exception:
        return 0


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


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS Queue Runner v1")
    parser.add_argument("--max-batch-size", type=int, required=True)
    parser.add_argument("--branch", action="append", default=[])
    parser.add_argument("--budget-class", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.max_batch_size <= 0:
        raise SystemExit("--max-batch-size must be > 0")

    if args.dry_run == args.execute:
        raise SystemExit("Choose exactly one of --dry-run or --execute.")

    normalized_branches: List[str] = []
    for item in args.branch:
        for part in item.split(","):
            clean = part.strip()
            if clean:
                normalized_branches.append(clean)
    args.branch = normalized_branches
    return args


def generate_batch_id() -> str:
    return f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def validate_registry_headers(rt: Runtime, headers: List[str]) -> None:
    required = {
        "candidate_id",
        "spec_path",
        "status",
        "latest_run_id",
        "promotion_decision",
        "updated_utc",
    }
    missing = sorted(required - set(headers))
    if missing:
        rt.fail(f"candidates_registry.csv missing required headers: {missing}")


def validate_spec_contract(
    spec: Dict[str, Any],
    spec_schema: Dict[str, Any],
    spec_path: Path,
) -> Tuple[bool, str]:
    required_fields = spec_schema["required_fields"]
    missing = [k for k in required_fields if k not in spec]
    if missing:
        return False, f"missing_required_fields:{missing}"

    strict_rules = spec_schema.get("strict_rules", {})
    if strict_rules.get("allow_unknown_top_level_fields") is False:
        unknown = sorted(set(spec.keys()) - set(required_fields))
        if unknown:
            return False, f"unknown_top_level_fields:{unknown}"

    allowed_status_values = set(spec_schema["allowed_status_values"])
    if spec.get("status") not in allowed_status_values:
        return False, f"status_outside_contract_enum:{spec.get('status')}"

    if spec.get("status") != "spec_ready":
        return False, f"status_not_spec_ready:{spec.get('status')}"

    if not isinstance(spec.get("input_paths"), list) or not spec["input_paths"]:
        return False, "input_paths_invalid"

    if not isinstance(spec.get("script_args"), list):
        return False, "script_args_invalid"

    if not isinstance(spec.get("expected_outputs"), list) or not spec["expected_outputs"]:
        return False, "expected_outputs_invalid"

    script_path = Path(spec["script_path"])
    if not script_path.exists():
        return False, f"script_path_missing:{script_path}"

    baseline_path = Path(spec["baseline_paper_path"])
    if not baseline_path.exists():
        return False, f"baseline_paper_path_missing:{baseline_path}"

    for raw in spec["input_paths"]:
        if not Path(raw).exists():
            return False, f"input_path_missing:{raw}"

    if spec_path.suffix.lower() != ".json":
        return False, f"invalid_spec_extension:{spec_path}"

    return True, "ok"


def load_registry_rows(rt: Runtime) -> List[Dict[str, str]]:
    with CANDIDATES_REGISTRY_PATH.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or []

    validate_registry_headers(rt, headers)
    rt.log(f"CHECK registry rows={len(rows)} cols={len(headers)}")
    return rows


def load_candidate_specs(
    rt: Runtime,
    rows: List[Dict[str, str]],
    spec_schema: Dict[str, Any],
    branch_filters: List[str],
    budget_class_filter: Optional[str],
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    seen_keys = set()

    for row in rows:
        raw_spec_path = (row.get("spec_path") or "").strip()
        if not raw_spec_path:
            continue

        spec_path = Path(raw_spec_path)
        if not spec_path.exists() or not spec_path.is_file():
            rt.log(f"SKIP registry spec_path missing path={spec_path}")
            continue

        try:
            spec = read_json(spec_path)
        except Exception as exc:
            rt.log(f"SKIP invalid json spec_path={spec_path} error={exc}")
            continue

        ok, reason = validate_spec_contract(spec, spec_schema, spec_path)
        if not ok:
            rt.log(f"SKIP non_compliant_spec spec_path={spec_path} reason={reason}")
            continue

        if branch_filters and spec["branch"] not in branch_filters:
            rt.log(f"SKIP branch_filter spec_path={spec_path} branch={spec['branch']}")
            continue

        if budget_class_filter and spec["budget_class"] != budget_class_filter:
            rt.log(f"SKIP budget_filter spec_path={spec_path} budget_class={spec['budget_class']}")
            continue

        dedupe_key = (spec["experiment_id"], str(spec_path.resolve()))
        if dedupe_key in seen_keys:
            rt.log(f"SKIP duplicate_spec spec_path={spec_path} experiment_id={spec['experiment_id']}")
            continue
        seen_keys.add(dedupe_key)

        selected.append(
            {
                "experiment_id": spec["experiment_id"],
                "spec_path": str(spec_path),
                "branch": spec["branch"],
                "budget_class": spec["budget_class"],
                "priority": spec["priority"],
                "priority_rank": priority_rank(str(spec["priority"])),
                "created_at": spec["created_at"],
                "created_at_dt": parse_created_at(str(spec["created_at"])),
                "spec": spec,
            }
        )

    selected.sort(
        key=lambda x: (
            -x["priority_rank"],
            x["created_at_dt"],
            x["experiment_id"],
            x["spec_path"],
        )
    )
    return selected


def build_batch_paths(batch_id: str) -> Tuple[Path, Path, Path, Path]:
    batch_dir = BATCHES_ROOT / batch_id
    return (
        batch_dir,
        batch_dir / "batch_manifest.json",
        batch_dir / "batch_summary.json",
        batch_dir / "batch_summary.csv",
    )


def call_orchestrator_for_spec(
    rt: Runtime,
    spec_path: str,
    execute: bool,
) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(ORCHESTRATOR_V1_PATH),
        "--spec",
        spec_path,
        "--allow-status",
        "spec_ready",
        "--execute" if execute else "--dry-run",
    ]

    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = "src;scripts"

    rt.log(f"DISPATCH cmd={' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    summary = {
        "exit_code": int(result.returncode),
        "stdout_tail": "\n".join(stdout.rstrip().splitlines()[-20:]) if stdout else "",
        "stderr_tail": "\n".join(stderr.rstrip().splitlines()[-20:]) if stderr else "",
        "final_status": None,
        "decision": None,
        "run_dir": None,
        "run_manifest_path": None,
        "run_status_path": None,
        "promotion_decision_path": None,
    }

    for line in stdout.splitlines():
        marker = "] SUMMARY "
        if marker in line:
            payload = line.split(marker, 1)[1]
            if "=" in payload:
                key, value = payload.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key in summary:
                    summary[key] = value

    return summary


def main() -> None:
    rt = Runtime.start("research_os_queue_runner_v1.py")

    try:
        args = parse_args()

        require_dir(rt, RESEARCH_OS_ROOT, "research_os_root")
        require_dir(rt, EXPERIMENT_SPECS_ROOT, "experiment_specs_root")
        require_dir(rt, BATCHES_ROOT, "batches_root") if BATCHES_ROOT.exists() else BATCHES_ROOT.mkdir(parents=True, exist_ok=True)
        require_file(rt, TRUTH_PACK_PATH, "truth_pack")
        require_file(rt, ROOT_MANIFEST_PATH, "research_os_manifest")
        require_file(rt, SCHEMA_INDEX_PATH, "schema_index")
        require_file(rt, CANDIDATES_REGISTRY_PATH, "candidates_registry")
        require_file(rt, ORCHESTRATOR_V1_PATH, "orchestrator_v1")

        schema_index = read_json(SCHEMA_INDEX_PATH)
        spec_schema = read_json(Path(schema_index["schemas"]["experiment_spec"]))

        rows = load_registry_rows(rt)
        eligible_specs = load_candidate_specs(
            rt=rt,
            rows=rows,
            spec_schema=spec_schema,
            branch_filters=args.branch,
            budget_class_filter=args.budget_class,
        )

        selected_specs = eligible_specs[: args.max_batch_size]

        batch_id = generate_batch_id()
        batch_dir, batch_manifest_path, batch_summary_json_path, batch_summary_csv_path = build_batch_paths(batch_id)
        batch_dir.mkdir(parents=True, exist_ok=False)

        selected_spec_paths = [item["spec_path"] for item in selected_specs]
        selected_experiment_ids = [item["experiment_id"] for item in selected_specs]

        batch_manifest = {
            "batch_id": batch_id,
            "created_at": timestamp_utc(),
            "mode": "execute" if args.execute else "dry_run",
            "selection_filters": {
                "max_batch_size": args.max_batch_size,
                "branch": args.branch,
                "budget_class": args.budget_class,
            },
            "selected_specs": selected_spec_paths,
            "selected_experiment_ids": selected_experiment_ids,
            "selected_count": len(selected_specs),
            "dedupe_applied": True,
            "sequential_dispatch": True,
            "orchestrator_v1_path": str(ORCHESTRATOR_V1_PATH),
        }
        save_json(batch_manifest_path, batch_manifest)
        rt.log(f"SAVED kind=json path={batch_manifest_path}")

        if args.dry_run:
            batch_summary = {
                "batch_id": batch_id,
                "started_at": timestamp_utc(),
                "completed_at": timestamp_utc(),
                "selected_specs": len(selected_specs),
                "completed_runs": 0,
                "failed_runs": 0,
                "kill_count": 0,
                "hold_count": 0,
                "rerun_count": 0,
                "promote_to_precheck_count": 0,
                "forensic_ready_count": 0,
                "mode": "dry_run",
                "results": [],
            }
            save_json(batch_summary_json_path, batch_summary)
            rt.log(f"SAVED kind=json path={batch_summary_json_path}")

            csv_rows = []
            save_csv(
                batch_summary_csv_path,
                csv_rows,
                [
                    "batch_id",
                    "experiment_id",
                    "spec_path",
                    "dispatch_exit_code",
                    "final_status",
                    "decision",
                    "run_dir",
                    "run_manifest_path",
                    "run_status_path",
                    "promotion_decision_path",
                ],
            )
            rt.log(f"SAVED kind=csv path={batch_summary_csv_path}")

            rt.set_counter("mode", "dry_run")
            rt.set_counter("selected_specs", len(selected_specs))
            rt.finish_ok(
                {
                    "batch_id": batch_id,
                    "batch_manifest_path": str(batch_manifest_path),
                    "batch_summary_json_path": str(batch_summary_json_path),
                    "batch_summary_csv_path": str(batch_summary_csv_path),
                }
            )
            return

        batch_started_at = timestamp_utc()
        results: List[Dict[str, Any]] = []
        completed_runs = 0
        failed_runs = 0
        kill_count = 0
        hold_count = 0
        rerun_count = 0
        promote_to_precheck_count = 0
        forensic_ready_count = 0

        for item in selected_specs:
            spec_path = item["spec_path"]
            experiment_id = item["experiment_id"]

            rt.log(f"DISPATCH spec_path={spec_path} experiment_id={experiment_id}")
            try:
                result = call_orchestrator_for_spec(rt, spec_path=spec_path, execute=True)
                dispatch_exit_code = int(result["exit_code"])
                if dispatch_exit_code == 0:
                    completed_runs += 1
                else:
                    failed_runs += 1

                decision = result.get("decision")
                final_status = result.get("final_status")

                if decision == "kill":
                    kill_count += 1
                elif decision == "hold":
                    hold_count += 1
                elif decision == "rerun":
                    rerun_count += 1
                elif decision == "promote_to_precheck":
                    promote_to_precheck_count += 1

                if final_status == "forensic_ready":
                    forensic_ready_count += 1

                results.append(
                    {
                        "batch_id": batch_id,
                        "experiment_id": experiment_id,
                        "spec_path": spec_path,
                        "dispatch_exit_code": dispatch_exit_code,
                        "final_status": final_status or "",
                        "decision": decision or "",
                        "run_dir": result.get("run_dir") or "",
                        "run_manifest_path": result.get("run_manifest_path") or "",
                        "run_status_path": result.get("run_status_path") or "",
                        "promotion_decision_path": result.get("promotion_decision_path") or "",
                    }
                )
            except Exception as exc:
                failed_runs += 1
                results.append(
                    {
                        "batch_id": batch_id,
                        "experiment_id": experiment_id,
                        "spec_path": spec_path,
                        "dispatch_exit_code": -1,
                        "final_status": "",
                        "decision": "",
                        "run_dir": "",
                        "run_manifest_path": "",
                        "run_status_path": "",
                        "promotion_decision_path": "",
                    }
                )
                rt.log(f"RUN_FAIL_SOFT spec_path={spec_path} error={exc}")

        batch_completed_at = timestamp_utc()

        batch_summary = {
            "batch_id": batch_id,
            "started_at": batch_started_at,
            "completed_at": batch_completed_at,
            "selected_specs": len(selected_specs),
            "completed_runs": completed_runs,
            "failed_runs": failed_runs,
            "kill_count": kill_count,
            "hold_count": hold_count,
            "rerun_count": rerun_count,
            "promote_to_precheck_count": promote_to_precheck_count,
            "forensic_ready_count": forensic_ready_count,
            "mode": "execute",
            "results": results,
        }
        save_json(batch_summary_json_path, batch_summary)
        rt.log(f"SAVED kind=json path={batch_summary_json_path}")

        save_csv(
            batch_summary_csv_path,
            results,
            [
                "batch_id",
                "experiment_id",
                "spec_path",
                "dispatch_exit_code",
                "final_status",
                "decision",
                "run_dir",
                "run_manifest_path",
                "run_status_path",
                "promotion_decision_path",
            ],
        )
        rt.log(f"SAVED kind=csv path={batch_summary_csv_path}")

        rt.set_counter("mode", "execute")
        rt.set_counter("selected_specs", len(selected_specs))
        rt.set_counter("completed_runs", completed_runs)
        rt.set_counter("failed_runs", failed_runs)
        rt.set_counter("kill_count", kill_count)
        rt.set_counter("hold_count", hold_count)
        rt.set_counter("rerun_count", rerun_count)
        rt.set_counter("promote_to_precheck_count", promote_to_precheck_count)
        rt.set_counter("forensic_ready_count", forensic_ready_count)

        rt.finish_ok(
            {
                "batch_id": batch_id,
                "batch_manifest_path": str(batch_manifest_path),
                "batch_summary_json_path": str(batch_summary_json_path),
                "batch_summary_csv_path": str(batch_summary_csv_path),
            }
        )

    except Exception as exc:
        for line in traceback.format_exc().rstrip().splitlines():
            rt.log(f"TRACE {line}")
        rt.finish_fail(str(exc))
        raise


if __name__ == "__main__":
    main()