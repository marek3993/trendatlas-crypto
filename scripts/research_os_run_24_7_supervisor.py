from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

LAUNCHER = ROOT / "scripts" / "research_os_launch_autonomous_batch.py"
PROJECT_TRUTH_JSON = ROOT / "source_of_truth" / "project_truth.json"
LOOP_OUTPUT_DIR = ROOT / "outputs" / "research_os_autonomous_loop_v1"
ZEROSEL_JSON = LOOP_OUTPUT_DIR / "zero_selection_diagnostics.json"
LOOP_SUMMARY_JSON = LOOP_OUTPUT_DIR / "autonomous_loop_run_summary.json"

SUPERVISOR_DIR = ROOT / "outputs" / "research_os_supervisor_v1"
SUPERVISOR_JSON = SUPERVISOR_DIR / "supervisor_latest_status.json"
SUPERVISOR_CYCLE_JSONL = SUPERVISOR_DIR / "supervisor_cycle_log.jsonl"
SUPERVISOR_SUMMARY_TXT = SUPERVISOR_DIR / "supervisor_human_report.txt"
SUPERVISOR_DECISION_JSON = SUPERVISOR_DIR / "supervisor_decision.json"


class SupervisorError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def get_active_strategy_line() -> tuple[str | None, dict]:
    truth = read_json_if_exists(PROJECT_TRUTH_JSON)
    active_line_id = truth.get("ai_lab_runtime", {}).get("active_strategy_line_id")
    lines = truth.get("ai_lab_strategy_lines", {})
    return active_line_id, lines.get(active_line_id, {})


def run_launcher() -> int:
    cmd = [str(PYTHON), str(LAUNCHER), "--execute"]
    print(f"[SUPERVISOR] cmd={' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def load_cycle_result() -> dict[str, Any]:
    loop_summary = read_json_if_exists(LOOP_SUMMARY_JSON)
    zerosel = read_json_if_exists(ZEROSEL_JSON)

    return {
        "selected_spec_paths": loop_summary.get("selected_spec_paths", []),
        "loop_status": loop_summary.get("status"),
        "candidate_runs_started_count": loop_summary.get("candidate_runs_started_count"),
        "candidate_runs_completed_count": loop_summary.get("candidate_runs_completed_count"),
        "scoring_completed_count": loop_summary.get("scoring_completed_count"),
        "precheck_completed_count": loop_summary.get("precheck_completed_count"),
        "selection_completed_count": loop_summary.get("selection_completed_count"),
        "governance_candidates_count": loop_summary.get("governance_candidates_count"),
        "worthy_candidates_count": zerosel.get("worthy_candidates_count"),
        "zero_selection_confirmed": zerosel.get("zero_selection_confirmed"),
        "reason_code_counts": zerosel.get("reason_code_counts", {})
    }


def make_human_report(
    cycle_index: int,
    total_cycles_completed: int,
    latest: dict[str, Any],
    stop_reason: str,
    sleep_seconds: int,
    max_cycles: int | None,
) -> str:
    lines = [
        "RESEARCH OS 24/7 SUPERVISOR REPORT",
        f"time_utc = {now_utc()}",
        f"cycle_index = {cycle_index}",
        f"total_cycles_completed = {total_cycles_completed}",
        f"max_cycles = {max_cycles}",
        f"sleep_seconds = {sleep_seconds}",
        "",
        f"loop_status = {latest.get('loop_status')}",
        f"selected_spec_paths = {latest.get('selected_spec_paths')}",
        f"candidate_runs_started_count = {latest.get('candidate_runs_started_count')}",
        f"candidate_runs_completed_count = {latest.get('candidate_runs_completed_count')}",
        f"scoring_completed_count = {latest.get('scoring_completed_count')}",
        f"precheck_completed_count = {latest.get('precheck_completed_count')}",
        f"selection_completed_count = {latest.get('selection_completed_count')}",
        f"governance_candidates_count = {latest.get('governance_candidates_count')}",
        f"worthy_candidates_count = {latest.get('worthy_candidates_count')}",
        f"zero_selection_confirmed = {latest.get('zero_selection_confirmed')}",
        f"reason_code_counts = {latest.get('reason_code_counts')}",
        "",
        f"stop_reason = {stop_reason}",
    ]
    return "\n".join(lines) + "\n"


def classify_stop_reason(returncode: int, latest: dict[str, Any], args: argparse.Namespace, total_cycles_completed: int) -> str | None:
    if returncode != 0:
        return f"launcher_failed_returncode_{returncode}"

    worthy = latest.get("worthy_candidates_count")
    if args.stop_on_worthy and isinstance(worthy, int) and worthy > 0:
        return "worthy_candidate_found"

    if latest.get("loop_status") != "OK":
        return f"loop_status_not_ok:{latest.get('loop_status')}"

    if latest.get("worthy_candidates_count") == 0 and latest.get("zero_selection_confirmed") is True:
        return "human_seeded_line_exhausted_escalate_to_master"

    if args.max_cycles is not None and total_cycles_completed >= args.max_cycles:
        return "max_cycles_reached"

    if not args.continue_on_zero_worthy:
        return "continue_on_zero_worthy_disabled"

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="24/7 supervisor for autonomous research batches.")
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=int, default=300)
    parser.add_argument("--stop-on-worthy", action="store_true", default=True)
    parser.add_argument("--continue-on-zero-worthy", action="store_true", default=True)
    args = parser.parse_args()

    if not PYTHON.exists():
        raise SupervisorError(f"python executable not found: {PYTHON}")
    if not LAUNCHER.exists():
        raise SupervisorError(f"launcher script not found: {LAUNCHER}")

    SUPERVISOR_DIR.mkdir(parents=True, exist_ok=True)

    active_line_id, active_line = get_active_strategy_line()

    if active_line.get("status") == "retired_from_autonomous_ideation":
        latest = {
            "selected_spec_paths": [],
            "loop_status": "SKIPPED_RETIRED_STRATEGY_LINE",
            "candidate_runs_started_count": 0,
            "candidate_runs_completed_count": 0,
            "scoring_completed_count": 0,
            "precheck_completed_count": 0,
            "selection_completed_count": 0,
            "governance_candidates_count": 0,
            "worthy_candidates_count": 0,
            "zero_selection_confirmed": False,
            "reason_code_counts": {}
        }
        stop_reason = "strategy_line_retired_do_not_run"
        decision_payload = {
            "ts": now_utc(),
            "cycle_index": 0,
            "stop_reason": stop_reason,
            "requires_master_escalation": False,
            "worthy_candidate_found": False,
            "latest": latest,
            "strategy_line_id": active_line_id
        }
        write_json(SUPERVISOR_JSON, decision_payload)
        write_json(SUPERVISOR_DECISION_JSON, decision_payload)
        write_text(SUPERVISOR_SUMMARY_TXT, make_human_report(0, 0, latest, stop_reason, args.sleep_seconds, args.max_cycles))
        print(f"[SUPERVISOR] stop_reason={stop_reason}")
        print(f"[SUPERVISOR] latest_status_json={SUPERVISOR_JSON}")
        print(f"[SUPERVISOR] decision_json={SUPERVISOR_DECISION_JSON}")
        print(f"[SUPERVISOR] human_report_txt={SUPERVISOR_SUMMARY_TXT}")
        return 0

    if active_line.get("status") == "paused_for_later_objective_reframing" or active_line.get("autonomous_ideation_allowed") is not True:
        latest = {
            "selected_spec_paths": [],
            "loop_status": "SKIPPED_PAUSED_STRATEGY_LINE",
            "candidate_runs_started_count": 0,
            "candidate_runs_completed_count": 0,
            "scoring_completed_count": 0,
            "precheck_completed_count": 0,
            "selection_completed_count": 0,
            "governance_candidates_count": 0,
            "worthy_candidates_count": 0,
            "zero_selection_confirmed": False,
            "reason_code_counts": {}
        }
        stop_reason = "strategy_line_paused_waiting_for_master_reframe"
        decision_payload = {
            "ts": now_utc(),
            "cycle_index": 0,
            "stop_reason": stop_reason,
            "requires_master_escalation": False,
            "worthy_candidate_found": False,
            "latest": latest,
            "strategy_line_id": active_line_id
        }
        write_json(SUPERVISOR_JSON, decision_payload)
        write_json(SUPERVISOR_DECISION_JSON, decision_payload)
        write_text(SUPERVISOR_SUMMARY_TXT, make_human_report(0, 0, latest, stop_reason, args.sleep_seconds, args.max_cycles))
        print(f"[SUPERVISOR] stop_reason={stop_reason}")
        print(f"[SUPERVISOR] latest_status_json={SUPERVISOR_JSON}")
        print(f"[SUPERVISOR] decision_json={SUPERVISOR_DECISION_JSON}")
        print(f"[SUPERVISOR] human_report_txt={SUPERVISOR_SUMMARY_TXT}")
        return 0

    cycle_index = 0
    total_cycles_completed = 0
    stop_reason = "unknown"
    latest: dict[str, Any] = {}

    while True:
        cycle_index += 1
        print(f"[SUPERVISOR] cycle_start={cycle_index}")

        returncode = run_launcher()
        latest = load_cycle_result()

        cycle_payload = {
            "ts": now_utc(),
            "cycle_index": cycle_index,
            "launcher_returncode": returncode,
            "strategy_line_id": active_line_id,
            **latest
        }
        append_jsonl(SUPERVISOR_CYCLE_JSONL, cycle_payload)
        write_json(SUPERVISOR_JSON, cycle_payload)

        total_cycles_completed += 1

        stop_reason = classify_stop_reason(returncode, latest, args, total_cycles_completed)
        if stop_reason is not None:
            break

        print(f"[SUPERVISOR] cycle_complete={cycle_index}")
        print(f"[SUPERVISOR] worthy_candidates_count={latest.get('worthy_candidates_count')}")
        print(f"[SUPERVISOR] sleeping_seconds={args.sleep_seconds}")
        time.sleep(args.sleep_seconds)

    decision_payload = {
        "ts": now_utc(),
        "cycle_index": cycle_index,
        "stop_reason": stop_reason,
        "requires_master_escalation": stop_reason == "human_seeded_line_exhausted_escalate_to_master",
        "worthy_candidate_found": stop_reason == "worthy_candidate_found",
        "latest": latest,
        "strategy_line_id": active_line_id
    }
    write_json(SUPERVISOR_DECISION_JSON, decision_payload)
    write_text(
        SUPERVISOR_SUMMARY_TXT,
        make_human_report(
            cycle_index=cycle_index,
            total_cycles_completed=total_cycles_completed,
            latest=latest,
            stop_reason=stop_reason,
            sleep_seconds=args.sleep_seconds,
            max_cycles=args.max_cycles
        )
    )

    print(f"[SUPERVISOR] stop_reason={stop_reason}")
    print(f"[SUPERVISOR] latest_status_json={SUPERVISOR_JSON}")
    print(f"[SUPERVISOR] decision_json={SUPERVISOR_DECISION_JSON}")
    print(f"[SUPERVISOR] cycle_log_jsonl={SUPERVISOR_CYCLE_JSONL}")
    print(f"[SUPERVISOR] human_report_txt={SUPERVISOR_SUMMARY_TXT}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[SUPERVISOR][FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
