from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

AUTHORITATIVE_GENERATED_SPECS_DIR = ROOT / "research_os" / "experiment_specs" / "generated"
AUTHORITATIVE_IDEATION_PATHS = [
    ROOT / "outputs" / "research_os_ideation_v1" / "ideation_hypotheses.json",
    ROOT / "research_os" / "ideation" / "ideation_hypotheses.json",
]
AUTHORITATIVE_ORCHESTRATOR_PATH = ROOT / "scripts" / "research_os_orchestrator_v1.py"
AUTHORITATIVE_RUNS_ROOT = ROOT / "research_os" / "runs"
AUTHORITATIVE_REGISTRY_PATHS = [
    ROOT / "research_os" / "leaderboards" / "research_os_registry.csv",
    ROOT / "research_os" / "candidates_registry.csv",
]

OUTPUT_DIR = ROOT / "outputs" / "research_os_autonomous_loop_v1"
MANIFEST_PATH = OUTPUT_DIR / "autonomous_loop_run_manifest.json"
SUMMARY_JSON_PATH = OUTPUT_DIR / "autonomous_loop_run_summary.json"
SUMMARY_CSV_PATH = OUTPUT_DIR / "autonomous_loop_run_summary.csv"
LOG_JSONL_PATH = OUTPUT_DIR / "autonomous_loop_log.jsonl"

MANDATORY_EXECUTE_OUTPUTS = [
    MANIFEST_PATH,
    SUMMARY_JSON_PATH,
    SUMMARY_CSV_PATH,
    LOG_JSONL_PATH,
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_optional(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS Autonomous Loop Runner v1")
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--max-hypotheses-per-cycle", type=int, default=4)
    parser.add_argument("--branch", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise SystemExit("Choose exactly one of --dry-run or --execute.")
    if args.max_cycles <= 0:
        raise SystemExit("--max-cycles must be > 0")
    if args.max_hypotheses_per_cycle <= 0:
        raise SystemExit("--max-hypotheses-per-cycle must be > 0")
    return args


def print_kv(key: str, value: Any) -> None:
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, ensure_ascii=False)
    else:
        rendered = str(value)
    print(f"[AUTOLOOP] {key}={rendered}", flush=True)


def tail_text(text: str, limit: int = 2000) -> str:
    if not text:
        return ""
    return text[-limit:] if len(text) > limit else text


def load_hypotheses_count() -> tuple[int, str | None]:
    path = first_existing(AUTHORITATIVE_IDEATION_PATHS)
    if path is None:
        return 0, None

    payload = load_json(path)
    if isinstance(payload, list):
        return len(payload), str(path)
    if isinstance(payload, dict):
        if isinstance(payload.get("hypotheses"), list):
            return len(payload["hypotheses"]), str(path)
        if isinstance(payload.get("rows"), list):
            return len(payload["rows"]), str(path)

    return 0, str(path)


def load_generated_specs(branch_filter: str | None) -> list[dict[str, Any]]:
    if not AUTHORITATIVE_GENERATED_SPECS_DIR.exists():
        raise FileNotFoundError(
            f"Missing authoritative generated spec dir: {AUTHORITATIVE_GENERATED_SPECS_DIR}"
        )

    out: list[dict[str, Any]] = []
    for path in sorted(AUTHORITATIVE_GENERATED_SPECS_DIR.glob("*.spec_ready.json")):
        spec = load_json(path)
        if not isinstance(spec, dict):
            raise ValueError(f"Spec is not a JSON object: {path}")

        branch = str(spec.get("branch", "")).strip()
        if branch_filter and branch != branch_filter:
            continue

        out.append(
            {
                "path": path,
                "spec": spec,
                "branch": branch,
                "experiment_id": str(spec.get("experiment_id", "")).strip(),
                "status": str(spec.get("status", "")).strip(),
            }
        )

    return out


def resolve_registry_path() -> Path | None:
    return first_existing(AUTHORITATIVE_REGISTRY_PATHS)


def count_governance_candidates(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        status = str(row.get("status", "")).strip().lower()
        lifecycle = str(row.get("lifecycle_stage", "")).strip().lower()
        if status in {"forensic_ready", "master_pending"} or lifecycle in {
            "forensic_ready",
            "master_pending",
        }:
            count += 1
    return count


def list_run_dirs() -> set[Path]:
    if not AUTHORITATIVE_RUNS_ROOT.exists():
        return set()
    return {p.resolve() for p in AUTHORITATIVE_RUNS_ROOT.iterdir() if p.is_dir()}


def inspect_new_run_dirs(new_run_dirs: list[Path]) -> tuple[int, int]:
    scoring_completed = 0
    precheck_completed = 0

    for run_dir in new_run_dirs:
        if (run_dir / "quality_report.json").exists():
            scoring_completed += 1
        if (run_dir / "precheck_inputs.json").exists():
            precheck_completed += 1

    return scoring_completed, precheck_completed


def run_orchestrator(spec_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(AUTHORITATIVE_ORCHESTRATOR_PATH),
        "--spec",
        str(spec_path),
        "--allow-status",
        "spec_ready",
        "--dry-run" if mode == "dry-run" else "--execute",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def save_outputs(
    manifest: dict[str, Any],
    summary_payload: dict[str, Any],
    summary_rows: list[dict[str, Any]],
) -> None:
    write_json(MANIFEST_PATH, manifest)
    write_json(SUMMARY_JSON_PATH, summary_payload)
    write_csv(SUMMARY_CSV_PATH, summary_rows)


def main() -> None:
    args = parse_args()
    mode = "execute" if args.execute else "dry-run"

    ensure_dir(OUTPUT_DIR)

    current_stage = "startup"
    status = "OK"
    exit_code = 0
    first_blocker_stage: str | None = None
    first_blocker_reason: str | None = None

    summary_rows: list[dict[str, Any]] = []
    selected_spec_paths: list[str] = []

    counts = {
        "hypotheses_loaded_count": 0,
        "specs_generated_count": 0,
        "specs_selected_count": 0,
        "candidate_runs_started_count": 0,
        "candidate_runs_completed_count": 0,
        "scoring_completed_count": 0,
        "precheck_completed_count": 0,
        "selection_completed_count": 0,
        "governance_candidates_count": 0,
    }

    registry_path = resolve_registry_path()

    manifest: dict[str, Any] = {
        "policy_version": "research_os_autonomous_loop_runner_v1_hardened",
        "mode": mode,
        "started_at_utc": now_utc_iso(),
        "max_cycles": args.max_cycles,
        "max_hypotheses_per_cycle": args.max_hypotheses_per_cycle,
        "branch_filter": args.branch,
        "authoritative_generated_spec_dir": str(AUTHORITATIVE_GENERATED_SPECS_DIR),
        "authoritative_orchestrator_path": str(AUTHORITATIVE_ORCHESTRATOR_PATH),
        "authoritative_runs_root": str(AUTHORITATIVE_RUNS_ROOT),
        "authoritative_registry_path": str(registry_path) if registry_path else None,
        "cycles": [],
        "status": "RUNNING",
        "first_blocker_stage": None,
        "first_blocker_reason": None,
        "counts": counts,
    }

    try:
        current_stage = "orchestrator_path_validation"
        print_kv("mode", mode)
        print_kv("authoritative_generated_spec_dir", str(AUTHORITATIVE_GENERATED_SPECS_DIR))
        print_kv("authoritative_orchestrator_path", str(AUTHORITATIVE_ORCHESTRATOR_PATH))
        print_kv("authoritative_registry_path", str(registry_path) if registry_path else "")

        if not AUTHORITATIVE_ORCHESTRATOR_PATH.exists():
            raise FileNotFoundError(f"Missing orchestrator: {AUTHORITATIVE_ORCHESTRATOR_PATH}")

        current_stage = "load_hypotheses"
        hypotheses_loaded_count, hypotheses_source_path = load_hypotheses_count()
        counts["hypotheses_loaded_count"] = hypotheses_loaded_count
        print_kv("hypotheses_loaded_count", counts["hypotheses_loaded_count"])
        print_kv("hypotheses_source_path", hypotheses_source_path or "")

        current_stage = "load_generated_specs"
        all_specs = load_generated_specs(branch_filter=args.branch)
        counts["specs_generated_count"] = len(all_specs)
        print_kv("specs_generated_count", counts["specs_generated_count"])

        if counts["specs_generated_count"] == 0:
            raise RuntimeError("No generated specs found in authoritative generated spec dir.")

        current_stage = "select_specs"
        selected_specs = all_specs[: args.max_hypotheses_per_cycle]
        counts["specs_selected_count"] = len(selected_specs)
        selected_spec_paths = [str(item["path"]) for item in selected_specs]

        print_kv("specs_selected_count", counts["specs_selected_count"])
        print_kv("selected_spec_paths", selected_spec_paths)

        if mode == "execute" and counts["specs_selected_count"] == 0:
            raise RuntimeError("Zero selected specs in execute mode.")

        for cycle in range(1, args.max_cycles + 1):
            current_stage = f"cycle_{cycle}_start"
            print_kv("cycle_start", cycle)

            cycle_info: dict[str, Any] = {
                "cycle": cycle,
                "selected_spec_paths": selected_spec_paths,
                "rows": [],
            }

            registry_before_rows = read_csv_optional(registry_path)
            governance_before = count_governance_candidates(registry_before_rows)

            for dispatch_index, item in enumerate(selected_specs, start=1):
                spec_path = item["path"]
                spec = item["spec"]
                experiment_id = item["experiment_id"] or spec_path.stem

                current_stage = f"cycle_{cycle}_dispatch_{dispatch_index}"
                print_kv("stage", current_stage)
                print_kv("dispatch_spec_path", str(spec_path))

                run_dirs_before = list_run_dirs()
                proc = run_orchestrator(spec_path=spec_path, mode=mode)
                run_dirs_after = list_run_dirs()
                new_run_dirs = sorted(run_dirs_after - run_dirs_before)

                row = {
                    "cycle": cycle,
                    "dispatch_index": dispatch_index,
                    "mode": mode,
                    "spec_path": str(spec_path),
                    "experiment_id": experiment_id,
                    "branch": item["branch"],
                    "spec_status": item["status"],
                    "dispatch_returncode": proc.returncode,
                    "new_run_dirs": "|".join(str(p) for p in new_run_dirs),
                    "candidate_run_started": 0,
                    "candidate_run_completed": 0,
                    "scoring_completed": 0,
                    "precheck_completed": 0,
                    "selection_completed_delta": 0,
                    "governance_candidates_after": governance_before,
                    "stdout_tail": tail_text(proc.stdout or ""),
                    "stderr_tail": tail_text(proc.stderr or ""),
                }

                summary_rows.append(row)
                cycle_info["rows"].append(row)

                append_jsonl(
                    LOG_JSONL_PATH,
                    {
                        "ts_utc": now_utc_iso(),
                        "event": "dispatch_result",
                        "cycle": cycle,
                        "dispatch_index": dispatch_index,
                        "mode": mode,
                        "spec_path": str(spec_path),
                        "experiment_id": experiment_id,
                        "dispatch_returncode": proc.returncode,
                        "new_run_dirs": [str(p) for p in new_run_dirs],
                        "stdout_tail": row["stdout_tail"],
                        "stderr_tail": row["stderr_tail"],
                    },
                )

                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Dispatch failed for spec {spec_path}. "
                        f"returncode={proc.returncode}. stderr_tail={row['stderr_tail']}"
                    )

                if mode == "execute":
                    if not new_run_dirs:
                        current_stage = f"cycle_{cycle}_candidate_run_creation_{dispatch_index}"
                        raise RuntimeError(
                            f"Execute dispatch created zero candidate runs for spec {spec_path}."
                        )

                    run_count = len(new_run_dirs)
                    counts["candidate_runs_started_count"] += run_count
                    counts["candidate_runs_completed_count"] += run_count

                    scoring_completed, precheck_completed = inspect_new_run_dirs(new_run_dirs)
                    counts["scoring_completed_count"] += scoring_completed
                    counts["precheck_completed_count"] += precheck_completed

                    registry_after_rows = read_csv_optional(registry_path)
                    selection_delta = max(0, len(registry_after_rows) - len(registry_before_rows))
                    counts["selection_completed_count"] += selection_delta
                    counts["governance_candidates_count"] = count_governance_candidates(
                        registry_after_rows
                    )

                    row["candidate_run_started"] = run_count
                    row["candidate_run_completed"] = run_count
                    row["scoring_completed"] = scoring_completed
                    row["precheck_completed"] = precheck_completed
                    row["selection_completed_delta"] = selection_delta
                    row["governance_candidates_after"] = counts["governance_candidates_count"]

                    registry_before_rows = registry_after_rows

                print_kv("dispatch_returncode", proc.returncode)
                if mode == "execute":
                    print_kv("new_run_dirs", [str(p) for p in new_run_dirs])
                    print_kv("candidate_runs_started_count", counts["candidate_runs_started_count"])
                    print_kv(
                        "candidate_runs_completed_count",
                        counts["candidate_runs_completed_count"],
                    )
                    print_kv("scoring_completed_count", counts["scoring_completed_count"])
                    print_kv("precheck_completed_count", counts["precheck_completed_count"])
                    print_kv("selection_completed_count", counts["selection_completed_count"])
                    print_kv(
                        "governance_candidates_count",
                        counts["governance_candidates_count"],
                    )

            manifest["cycles"].append(cycle_info)
            print_kv("cycle_complete", cycle)

        current_stage = "execute_zero_work_validation"
        if mode == "execute":
            if counts["specs_selected_count"] == 0:
                raise RuntimeError("Zero selected specs in execute mode.")
            if counts["candidate_runs_started_count"] == 0:
                raise RuntimeError("Zero candidate runs started in execute mode.")
            if counts["candidate_runs_completed_count"] == 0:
                raise RuntimeError("Zero candidate runs completed in execute mode.")

        status = "OK"
        exit_code = 0

    except Exception as exc:
        status = "FAIL"
        exit_code = 1
        if first_blocker_stage is None:
            first_blocker_stage = current_stage
        if first_blocker_reason is None:
            first_blocker_reason = str(exc)

        print_kv("first_blocker_stage", first_blocker_stage)
        print_kv("first_blocker_reason", first_blocker_reason)

        append_jsonl(
            LOG_JSONL_PATH,
            {
                "ts_utc": now_utc_iso(),
                "event": "first_blocker",
                "mode": mode,
                "first_blocker_stage": first_blocker_stage,
                "first_blocker_reason": first_blocker_reason,
            },
        )

    finally:
        manifest["finished_at_utc"] = now_utc_iso()
        manifest["status"] = status
        manifest["first_blocker_stage"] = first_blocker_stage
        manifest["first_blocker_reason"] = first_blocker_reason
        manifest["counts"] = counts

        summary_payload = {
            "status": status,
            "mode": mode,
            "counts": counts,
            "first_blocker_stage": first_blocker_stage,
            "first_blocker_reason": first_blocker_reason,
            "selected_spec_paths": selected_spec_paths,
            "rows": summary_rows,
        }

        save_outputs(manifest=manifest, summary_payload=summary_payload, summary_rows=summary_rows)

        if mode == "execute":
            missing_outputs = [str(path) for path in MANDATORY_EXECUTE_OUTPUTS if not path.exists()]
            if missing_outputs:
                status = "FAIL"
                exit_code = 1
                if first_blocker_stage is None:
                    first_blocker_stage = "mandatory_output_persistence"
                if first_blocker_reason is None:
                    first_blocker_reason = f"Missing mandatory outputs: {missing_outputs}"

                manifest["status"] = status
                manifest["first_blocker_stage"] = first_blocker_stage
                manifest["first_blocker_reason"] = first_blocker_reason
                summary_payload["status"] = status
                summary_payload["first_blocker_stage"] = first_blocker_stage
                summary_payload["first_blocker_reason"] = first_blocker_reason

                save_outputs(
                    manifest=manifest,
                    summary_payload=summary_payload,
                    summary_rows=summary_rows,
                )

        print_kv("hypotheses_loaded_count", counts["hypotheses_loaded_count"])
        print_kv("specs_generated_count", counts["specs_generated_count"])
        print_kv("specs_selected_count", counts["specs_selected_count"])
        print_kv("selected_spec_paths", selected_spec_paths)

        if mode == "execute":
            print_kv("candidate_runs_started_count", counts["candidate_runs_started_count"])
            print_kv("candidate_runs_completed_count", counts["candidate_runs_completed_count"])
            print_kv("scoring_completed_count", counts["scoring_completed_count"])
            print_kv("precheck_completed_count", counts["precheck_completed_count"])
            print_kv("selection_completed_count", counts["selection_completed_count"])
            print_kv("governance_candidates_count", counts["governance_candidates_count"])

        print_kv("status", status)
        if first_blocker_stage:
            print_kv("first_blocker_stage", first_blocker_stage)
        if first_blocker_reason:
            print_kv("first_blocker_reason", first_blocker_reason)

        print_kv("autonomous_loop_run_manifest_json", str(MANIFEST_PATH))
        print_kv("autonomous_loop_run_summary_json", str(SUMMARY_JSON_PATH))
        print_kv("autonomous_loop_run_summary_csv", str(SUMMARY_CSV_PATH))
        print_kv("autonomous_loop_log_jsonl", str(LOG_JSONL_PATH))

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()