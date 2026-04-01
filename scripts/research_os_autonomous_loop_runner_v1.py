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
POLICY_PATH = ROOT / "research_os_autonomous_loop_policy_v1.json"
SPEC_POLICY_PATH = ROOT / "research_os_spec_generator_policy_v1.json"
BOOTSTRAP_REGISTRY_PATH = ROOT / "research_os" / "leaderboards" / "research_os_registry.csv"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv_optional(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def ensure_bootstrap_registry(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fieldnames = [
            "candidate_id",
            "status",
            "lifecycle_stage",
            "branch",
            "segment_owner",
            "hypothesis_label",
            "model_key",
            "script_path",
            "created_at_utc",
            "updated_at_utc",
        ]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
    return path


def is_truth_pack_json(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if (
        "official_baseline" in payload
        or "official_baseline_model_key" in payload
        or "baseline_model_key" in payload
    ):
        return True
    return path.name.lower() == "truth_pack.json" and len(payload) > 0


def resolve_first_existing(
    candidates: list[str],
    label: str,
    fallback_globs: list[str] | None = None,
    validator: Any | None = None,
) -> Path:
    checked: list[str] = []

    for raw in candidates:
        path = Path(raw)
        checked.append(str(path))
        if path.exists() and path.is_file():
            if validator is None or validator(path):
                return path

    discovered: list[Path] = []
    for pattern in fallback_globs or []:
        discovered.extend(ROOT.glob(pattern))

    unique_sorted = sorted({p.resolve() for p in discovered if p.exists() and p.is_file()})
    for path in unique_sorted:
        if validator is None or validator(path):
            return path

    if label == "registry csv":
        return ensure_bootstrap_registry(BOOTSTRAP_REGISTRY_PATH)

    joined = "\n".join(checked)
    discovered_text = "\n".join(str(p) for p in unique_sorted) if unique_sorted else "(none)"
    raise FileNotFoundError(
        f"Missing required {label}. Checked explicit candidates:\n{joined}\n"
        f"Fallback matches checked:\n{discovered_text}"
    )


def collect_existing_files(candidates: list[str], fallback_globs: list[str] | None = None) -> list[Path]:
    found: list[Path] = []

    for raw in candidates:
        path = Path(raw)
        if path.exists() and path.is_file():
            found.append(path.resolve())

    for pattern in fallback_globs or []:
        for path in ROOT.glob(pattern):
            if path.exists() and path.is_file():
                found.append(path.resolve())

    return sorted({p for p in found})


def read_registry_snapshot(path: Path) -> list[dict[str, Any]]:
    return load_csv_optional(path)


def determine_winners(registry_rows: list[dict[str, Any]]) -> list[str]:
    winners: list[str] = []
    for row in registry_rows:
        status = str(row.get("status", "")).strip().lower()
        lifecycle = str(row.get("lifecycle_stage", "")).strip().lower()
        if status in {"forensic_ready", "master_pending"} or lifecycle in {"forensic_ready", "master_pending"}:
            candidate_id = str(row.get("candidate_id", "")).strip()
            if candidate_id:
                winners.append(candidate_id)
    return sorted(set(winners))


def run_subprocess(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def script_help_text(script_path: Path) -> str:
    proc = run_subprocess([sys.executable, str(script_path), "--help"])
    return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def detect_flag_from_help(help_text: str, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in help_text:
            return candidate
    return None


def resolve_pipeline_runner(
    candidates: list[str],
    fallback_globs: list[str],
    spec_arg_names: list[str],
) -> tuple[Path, str, list[str]]:
    scripts = collect_existing_files(candidates, fallback_globs)
    if not scripts:
        raise FileNotFoundError("Missing required pipeline runner. No candidate scripts found.")

    diagnostics: list[str] = []
    spec_candidates = list(spec_arg_names)
    if "--spec" not in spec_candidates:
        spec_candidates.append("--spec")

    for script_path in scripts:
        help_text = script_help_text(script_path)
        spec_arg = detect_flag_from_help(help_text, spec_candidates)

        extra_args: list[str] = []
        if spec_arg == "--spec" and "--allow-status" in help_text:
            extra_args = ["--allow-status", "spec_ready"]

        diagnostics.append(
            f"{script_path} :: spec_arg={spec_arg or 'NONE'} :: extra_args={' '.join(extra_args) if extra_args else '(none)'}"
        )

        if spec_arg:
            return script_path, spec_arg, extra_args

    diag_text = "\n".join(diagnostics)
    raise RuntimeError(
        "Unable to detect compatible spec-driven pipeline runner.\n"
        f"Checked scripts:\n{diag_text}"
    )


def build_base_command(
    script_path: Path,
    mode: str,
    dry_run_flags: list[str],
    execute_flags: list[str],
) -> list[str]:
    command = [sys.executable, str(script_path)]
    if mode == "execute":
        command.extend(execute_flags)
    else:
        command.extend(dry_run_flags)
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--max-hypotheses-per-cycle", type=int, default=None)
    parser.add_argument("--branch", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run and args.execute:
        raise ValueError("Use either --dry-run or --execute, not both.")
    mode = "execute" if args.execute else "dry-run"

    policy = load_json(POLICY_PATH)
    if policy.get("policy_version") != "research_os_autonomous_loop_policy_v1":
        raise ValueError("Unexpected autonomous loop policy version.")

    spec_policy = load_json(SPEC_POLICY_PATH)

    output_dir = Path(str(policy["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    files = policy["output_files"]
    log_path = output_dir / str(files["log_jsonl"])

    ideation_script = Path(str(policy["script_paths"]["ideation_agent"]))
    spec_generator_script = Path(str(policy["script_paths"]["spec_generator"]))
    if not ideation_script.exists():
        raise FileNotFoundError(f"Missing ideation agent: {ideation_script}")
    if not spec_generator_script.exists():
        raise FileNotFoundError(f"Missing spec generator: {spec_generator_script}")

    truth_pack_path = resolve_first_existing(
        policy["required_inputs"]["truth_pack_candidates"],
        "truth pack",
        fallback_globs=[
            "research_os/single_truth/truth_pack.json",
            "outputs/**/research_os_truth_pack*.json",
            "outputs/**/*truth_pack*.json",
            "research_os_truth_pack*.json",
            "*truth_pack*.json",
        ],
        validator=is_truth_pack_json,
    )

    registry_path = resolve_first_existing(
        policy["required_inputs"]["registry_csv_candidates"],
        "registry csv",
        fallback_globs=[
            "research_os/leaderboards/research_os_registry.csv",
            "research_os/leaderboards/registry.csv",
            "outputs/**/research_os_registry*.csv",
            "outputs/**/registry.csv",
        ],
    )

    cli_candidates = policy["pipeline_runner_cli_candidates"]
    pipeline_runner_path, pipeline_spec_arg, pipeline_extra_args = resolve_pipeline_runner(
        candidates=list(policy["required_inputs"]["pipeline_runner_candidates"]),
        fallback_globs=[
            "scripts/research_os_pipeline_runner*.py",
            "scripts/research_os_orchestrator*.py",
            "scripts/research_os_queue_runner*.py",
        ],
        spec_arg_names=list(cli_candidates["spec_arg_names"]),
    )

    max_cycles = int(args.max_cycles or policy["max_cycles_default"])
    max_hypotheses_per_cycle = int(args.max_hypotheses_per_cycle or policy["max_hypotheses_per_cycle_default"])

    manifest: dict[str, Any] = {
        "policy_version": policy["policy_version"],
        "macro_frozen_mode": bool(policy["macro_frozen_mode"]),
        "mode": mode,
        "max_cycles": max_cycles,
        "max_hypotheses_per_cycle": max_hypotheses_per_cycle,
        "branch_filter": args.branch,
        "truth_pack_path": str(truth_pack_path),
        "registry_path": str(registry_path),
        "pipeline_runner_path": str(pipeline_runner_path),
        "pipeline_runner_spec_arg": pipeline_spec_arg,
        "pipeline_runner_extra_args": pipeline_extra_args,
        "cycles": [],
        "started_at_utc": now_utc(),
    }
    summary_rows: list[dict[str, Any]] = []

    for cycle in range(1, max_cycles + 1):
        cycle_label = f"cycle_{cycle:02d}"
        registry_before = read_registry_snapshot(registry_path)

        ideation_cmd = [
            sys.executable,
            str(ideation_script),
            "--max-hypotheses",
            str(max_hypotheses_per_cycle),
        ]
        if args.branch:
            ideation_cmd.extend(["--branch", args.branch])
        ideation_cmd.append("--execute" if mode == "execute" else "--dry-run")

        ideation_proc = run_subprocess(ideation_cmd)
        if ideation_proc.returncode != 0:
            raise RuntimeError(
                f"Ideation agent failed in {cycle_label}.\nSTDOUT:\n{ideation_proc.stdout}\nSTDERR:\n{ideation_proc.stderr}"
            )

        spec_cmd = [
            sys.executable,
            str(spec_generator_script),
            "--execute" if mode == "execute" else "--dry-run",
        ]
        spec_proc = run_subprocess(spec_cmd)
        if spec_proc.returncode != 0:
            raise RuntimeError(
                f"Spec generator failed in {cycle_label}.\nSTDOUT:\n{spec_proc.stdout}\nSTDERR:\n{spec_proc.stderr}"
            )

        spec_summary_path = Path(str(spec_policy["output_dir"])) / str(spec_policy["output_files"]["summary_csv"])
        spec_rows = load_csv_optional(spec_summary_path)
        cycle_rows: list[dict[str, Any]] = []
        cycle_winners: list[str] = []

        for spec_row in spec_rows:
            spec_file = Path(str(spec_row.get("spec_file", "")).strip())
            if not spec_file.exists():
                raise FileNotFoundError(f"Missing generated spec file: {spec_file}")

            pipeline_cmd = build_base_command(
                pipeline_runner_path,
                mode=mode,
                dry_run_flags=list(cli_candidates["dry_run_flags"]),
                execute_flags=list(cli_candidates["execute_flags"]),
            )
            pipeline_cmd.extend(pipeline_extra_args)
            pipeline_cmd.extend([pipeline_spec_arg, str(spec_file)])

            proc = run_subprocess(pipeline_cmd)
            registry_after = read_registry_snapshot(registry_path)
            new_winners = sorted(set(determine_winners(registry_after)) - set(determine_winners(registry_before)))
            cycle_winners.extend(new_winners)

            status = "success" if proc.returncode == 0 else "failed"
            row = {
                "cycle": cycle,
                "spec_id": spec_row.get("spec_id", ""),
                "branch": spec_row.get("branch", ""),
                "spec_file": str(spec_file),
                "pipeline_status": status,
                "pipeline_returncode": proc.returncode,
                "new_worthy_candidates": "|".join(new_winners),
                "macro_frozen_mode": bool(policy["macro_frozen_mode"]),
                "mode": mode,
            }
            cycle_rows.append(row)
            summary_rows.append(row)

            log_jsonl(
                log_path,
                {
                    "ts_utc": now_utc(),
                    "event": "candidate_pipeline_run",
                    "cycle": cycle,
                    "spec_id": spec_row.get("spec_id", ""),
                    "spec_file": str(spec_file),
                    "returncode": proc.returncode,
                    "pipeline_status": status,
                    "new_worthy_candidates": new_winners,
                    "stdout_tail": (proc.stdout or "")[-2000:],
                    "stderr_tail": (proc.stderr or "")[-2000:],
                },
            )

            registry_before = registry_after

        cycle_manifest = {
            "cycle": cycle,
            "mode": mode,
            "ideation_returncode": ideation_proc.returncode,
            "spec_generation_returncode": spec_proc.returncode,
            "spec_count": len(spec_rows),
            "candidate_runs": cycle_rows,
            "staged_governance_candidates": sorted(set(cycle_winners)),
        }
        manifest["cycles"].append(cycle_manifest)

        log_jsonl(
            log_path,
            {
                "ts_utc": now_utc(),
                "event": "cycle_complete",
                "cycle": cycle,
                "spec_count": len(spec_rows),
                "staged_governance_candidates": sorted(set(cycle_winners)),
            },
        )

        if not spec_rows:
            break

    manifest["finished_at_utc"] = now_utc()
    write_json(output_dir / str(files["manifest_json"]), manifest)
    write_json(
        output_dir / str(files["summary_json"]),
        {
            "rows": summary_rows,
            "macro_frozen_mode": bool(policy["macro_frozen_mode"]),
        },
    )
    write_csv(output_dir / str(files["summary_csv"]), summary_rows)

    print(f"[AUTOLOOP] mode={mode}")
    print(f"[AUTOLOOP] macro_frozen_mode={policy['macro_frozen_mode']}")
    print(f"[AUTOLOOP] cycles={len(manifest['cycles'])}")
    print(f"[AUTOLOOP] output_dir={output_dir}")


if __name__ == "__main__":
    main()