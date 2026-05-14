from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]

PHASE60_PINNED_MODEL = "phase60_restore_trx_sol_base"
PHASE63_PINNED_VARIANT = (
    "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3"
)

PHASE60_FAST_ARGS = (
    "--dependency-only",
    "--model-key",
    PHASE60_PINNED_MODEL,
)
PHASE63_FAST_ARGS = (
    "--winner-only",
    "--variant-key",
    PHASE63_PINNED_VARIANT,
)
PUBLISH_EXISTING_DRY_RUN_ARGS = ("--mode", "publish-existing", "--dry-run")
PUBLISH_EXISTING_REAL_ARGS = ("--mode", "publish-existing")

FORBIDDEN_COMMAND_TOKENS = (
    "full-refresh",
    "--execute-live",
    "FULL_AUTO_EXECUTION",
)
FORBIDDEN_LIVE_ORDER_PATH_FRAGMENTS = (
    "submit_controlled_real_order.py",
    "hyperliquid_live_canary.py",
    "app_execute_bridge.py",
    "run_full_auto_execution_cycle.py",
    "run_full_auto_scheduler_entry.py",
)


@dataclass(frozen=True)
class PythonStep:
    name: str
    script_path: Path
    args: tuple[str, ...] = ()


def relative_display_path(path: Path, *, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def build_fast_dependency_steps(root: Path = ROOT) -> tuple[PythonStep, ...]:
    return (
        PythonStep("refresh_legacy_ohlcv", root / "scripts" / "refresh_legacy_ohlcv.py"),
        PythonStep(
            "refresh_phase67_top100_shortlist_ohlcv",
            root / "scripts" / "refresh_phase67_top100_shortlist_ohlcv.py",
        ),
        PythonStep(
            "phase60_selective_restore_robustness",
            root / "phase60_selective_restore_robustness.py",
            PHASE60_FAST_ARGS,
        ),
        PythonStep(
            "phase63_btc_participation_overlay",
            root / "scripts" / "phase63_btc_participation_overlay.py",
            PHASE63_FAST_ARGS,
        ),
        PythonStep(
            "phase66g_production_candidate_live",
            root / "scripts" / "phase66g_production_candidate_live.py",
        ),
        PythonStep(
            "phase67j_final_narrow_validation_pack",
            root / "scripts" / "phase67j_final_narrow_validation_pack.py",
        ),
        PythonStep(
            "dev_only_build_btc_etf_flow_daily_panel",
            root / "scripts" / "dev_only_build_btc_etf_flow_daily_panel.py",
        ),
        PythonStep(
            "verify_app_freshness",
            root / "scripts" / "verify_app_freshness.py",
        ),
    )


def build_publish_existing_dry_run_step(root: Path = ROOT) -> PythonStep:
    return PythonStep(
        "publish_existing_dry_run",
        root / "scripts" / "execution" / "run_pi_authoritative_producer.py",
        PUBLISH_EXISTING_DRY_RUN_ARGS,
    )


def build_publish_existing_real_step(root: Path = ROOT) -> PythonStep:
    return PythonStep(
        "publish_existing_real",
        root / "scripts" / "execution" / "run_pi_authoritative_producer.py",
        PUBLISH_EXISTING_REAL_ARGS,
    )


def build_command(step: PythonStep) -> list[str]:
    return [sys.executable, str(step.script_path), *step.args]


def command_contains_forbidden_path(command: Sequence[str]) -> bool:
    command_text = " ".join(command)
    return any(fragment in command_text for fragment in FORBIDDEN_LIVE_ORDER_PATH_FRAGMENTS)


def validate_safe_step(step: PythonStep) -> None:
    command = build_command(step)
    command_text = " ".join(command)
    forbidden_tokens = [token for token in FORBIDDEN_COMMAND_TOKENS if token in command_text]
    if forbidden_tokens:
        raise ValueError(
            f"Unsafe Pi fast daily authority command for {step.name}: {forbidden_tokens}"
        )
    if command_contains_forbidden_path(command):
        raise ValueError(f"Live-order command path is forbidden in {step.name}")
    if step.name == "phase60_selective_restore_robustness" and step.args != PHASE60_FAST_ARGS:
        raise ValueError("Phase60 must use the dependency-only pinned fast path")
    if step.name == "phase63_btc_participation_overlay" and step.args != PHASE63_FAST_ARGS:
        raise ValueError("Phase63 must use the winner-only pinned fast path")


def build_runtime_env(env: Mapping[str, str] | None = None, *, root: Path = ROOT) -> dict[str, str]:
    runtime_env = dict(os.environ)
    if env is not None:
        runtime_env.update(dict(env))
    pythonpath_entries = [str(root / "src"), str(root / "scripts")]
    current_pythonpath = str(runtime_env.get("PYTHONPATH") or "").strip()
    if current_pythonpath:
        pythonpath_entries.append(current_pythonpath)
    runtime_env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    runtime_env["PYTHONUNBUFFERED"] = "1"
    return runtime_env


def authority_real_publish_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return (
        str(source.get("MRV1_ENABLE_AUTHORITY_PUBLISH") or "").strip() == "1"
        and str(source.get("MRV1_AUTHORITY_MODE") or "").strip().lower()
        == "authoritative"
    )


def run_python_step(
    step: PythonStep,
    *,
    env: Mapping[str, str],
    root: Path = ROOT,
) -> dict[str, Any]:
    validate_safe_step(step)
    if not step.script_path.exists() or not step.script_path.is_file():
        raise FileNotFoundError(
            f"Missing required Pi fast daily authority step script: {step.script_path}"
        )

    command = build_command(step)
    print(
        f"[PI-FAST-DAILY] step_start={step.name} script={relative_display_path(step.script_path, root=root)}",
        flush=True,
    )
    completed = subprocess.run(
        command,
        cwd=str(root),
        env=dict(env),
        check=False,
    )
    result = {
        "step_name": step.name,
        "script_path": relative_display_path(step.script_path, root=root),
        "args": list(step.args),
        "returncode": completed.returncode,
    }
    if completed.returncode != 0:
        print(
            f"[PI-FAST-DAILY] step_fail={step.name} returncode={completed.returncode}",
            flush=True,
        )
        raise RuntimeError(f"{step.name} failed with exit code {completed.returncode}")

    print(f"[PI-FAST-DAILY] step_ok={step.name}", flush=True)
    return result


def run_fast_daily_authority_refresh(
    *,
    env: Mapping[str, str] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    runtime_env = build_runtime_env(env, root=root)
    results: list[dict[str, Any]] = []

    for step in build_fast_dependency_steps(root):
        results.append(run_python_step(step, env=runtime_env, root=root))

    dry_run_step = build_publish_existing_dry_run_step(root)
    results.append(run_python_step(dry_run_step, env=runtime_env, root=root))

    real_publish_status = "skipped_env_gate"
    if authority_real_publish_enabled(env):
        real_step = build_publish_existing_real_step(root)
        results.append(run_python_step(real_step, env=runtime_env, root=root))
        real_publish_status = "completed"
    else:
        print(
            "[PI-FAST-DAILY] publish_existing_real=skipped_env_gate "
            "requires MRV1_ENABLE_AUTHORITY_PUBLISH=1 and MRV1_AUTHORITY_MODE=authoritative",
            flush=True,
        )

    return {
        "status": "OK",
        "mode": "fast_daily_authority_refresh",
        "full_refresh_mode": "not_invoked",
        "phase60_fast_dependency": "dependency_only",
        "phase63_fast_dependency": "winner_only",
        "publish_existing_dry_run": "completed",
        "publish_existing_real": real_publish_status,
        "live_order_chain": "not_invoked",
        "steps": results,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Run the safe Pi fast daily dependency refresh chain, then publish-existing "
            "dry-run, then env-gated real publish."
        )
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    parser.parse_args(argv)
    result = run_fast_daily_authority_refresh(root=ROOT)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
