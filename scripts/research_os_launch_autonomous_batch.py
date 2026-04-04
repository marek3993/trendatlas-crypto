from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

IDEATION = ROOT / "scripts" / "research_os_controlled_ideation_agent_v1.py"
SPEC_GEN = ROOT / "scripts" / "research_os_experiment_spec_generator_v1.py"
AUTOLOOP = ROOT / "scripts" / "research_os_autonomous_loop_runner_v1.py"
ZEROSEL = ROOT / "scripts" / "research_os_zero_selection_diagnostics_v1.py"

GENERATED_DIR = ROOT / "research_os" / "experiment_specs" / "generated"
LOOP_OUTPUT_DIR = ROOT / "outputs" / "research_os_autonomous_loop_v1"
LOOP_SUMMARY_JSON = LOOP_OUTPUT_DIR / "autonomous_loop_run_summary.json"
ZEROSEL_JSON = LOOP_OUTPUT_DIR / "zero_selection_diagnostics.json"


class LaunchError(RuntimeError):
    pass


def run_step(cmd: list[str], label: str) -> None:
    print(f"[LAUNCH] step={label}")
    print(f"[LAUNCH] cmd={' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise LaunchError(f"{label} failed with returncode={result.returncode}")


def clean_generated_specs() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in GENERATED_DIR.glob("*.spec_ready.json"):
        path.unlink()
        removed += 1
    print(f"[LAUNCH] cleaned_spec_files={removed}")


def read_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def print_final_summary(prefix: str = "") -> None:
    loop_summary = read_json_if_exists(LOOP_SUMMARY_JSON)
    zerosel = read_json_if_exists(ZEROSEL_JSON)

    print(f"[LAUNCH] {prefix}final_summary_start")
    print(f"[LAUNCH] loop_summary_json={LOOP_SUMMARY_JSON}")
    print(f"[LAUNCH] zero_selection_json={ZEROSEL_JSON}")
    print(f"[LAUNCH] selected_spec_paths={json.dumps(loop_summary.get('selected_spec_paths', []), ensure_ascii=False)}")
    print(f"[LAUNCH] candidate_runs_started_count={loop_summary.get('candidate_runs_started_count')}")
    print(f"[LAUNCH] candidate_runs_completed_count={loop_summary.get('candidate_runs_completed_count')}")
    print(f"[LAUNCH] scoring_completed_count={loop_summary.get('scoring_completed_count')}")
    print(f"[LAUNCH] precheck_completed_count={loop_summary.get('precheck_completed_count')}")
    print(f"[LAUNCH] selection_completed_count={loop_summary.get('selection_completed_count')}")
    print(f"[LAUNCH] governance_candidates_count={loop_summary.get('governance_candidates_count')}")
    print(f"[LAUNCH] loop_status={loop_summary.get('status')}")
    print(f"[LAUNCH] worthy_candidates_count={zerosel.get('worthy_candidates_count')}")
    print(f"[LAUNCH] zero_selection_confirmed={zerosel.get('zero_selection_confirmed')}")
    print(f"[LAUNCH] reason_code_counts={json.dumps(zerosel.get('reason_code_counts'), ensure_ascii=False)}")
    print(f"[LAUNCH] {prefix}final_summary_end")


def get_zero_worthy() -> bool:
    zerosel = read_json_if_exists(ZEROSEL_JSON)
    return zerosel.get("worthy_candidates_count") == 0 and zerosel.get("zero_selection_confirmed") is True


def run_wave(wave: str, mode_flag: str, skip_clean: bool) -> None:
    if not skip_clean:
        clean_generated_specs()

    run_step([str(PYTHON), str(IDEATION), mode_flag, "--wave", wave], f"{wave}_ideation")
    run_step([str(PYTHON), str(SPEC_GEN), mode_flag], f"{wave}_spec_generation")
    run_step([str(PYTHON), str(AUTOLOOP), mode_flag], f"{wave}_autonomous_loop")

    if mode_flag == "--execute":
        run_step(
            [str(PYTHON), str(ZEROSEL), "--loop-output-dir", str(LOOP_OUTPUT_DIR), "--execute"],
            f"{wave}_zero_selection_diagnostics",
        )
        print_final_summary(prefix=f"{wave}_")


def main() -> int:
    parser = argparse.ArgumentParser(description="Single entry launcher for autonomous research batch with automatic wave fallback.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--disable-wave2-fallback", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise LaunchError("choose exactly one of --dry-run or --execute")

    mode_flag = "--dry-run" if args.dry_run else "--execute"

    if not PYTHON.exists():
        raise LaunchError(f"python executable not found: {PYTHON}")

    run_wave("wave1", mode_flag, args.skip_clean)

    if args.execute and not args.disable_wave2_fallback and get_zero_worthy():
        print("[LAUNCH] wave1 returned zero worthy candidates")
        print("[LAUNCH] automatic_fallback=wave2_loss_shape_response")
        run_wave("wave2", mode_flag, False)

    print("[LAUNCH] batch_complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[LAUNCH][FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)