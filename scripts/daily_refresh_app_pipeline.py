from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "app_refresh_pipeline"

LEGACY_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_legacy_ohlcv.py"
MACRO_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_global_liquidity_weekly.py"
TOP100_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_phase67_top100_shortlist_ohlcv.py"
PHASE67B_SCRIPT = ROOT / "scripts" / "phase67b_top100_forensic_prune_and_rerun.py"
PHASE60_SCRIPT = ROOT / "phase60_selective_restore_robustness.py"
PHASE63_SCRIPT = ROOT / "scripts" / "phase63_btc_participation_overlay.py"
PHASE66G_SCRIPT = ROOT / "scripts" / "phase66g_production_candidate_live.py"
PHASE67J_SCRIPT = ROOT / "scripts" / "phase67j_final_narrow_validation_pack.py"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_app_freshness.py"
MATERIALIZE_SCRIPT = ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"
SCHEDULER_ENTRY_SCRIPT = ROOT / "scripts" / "execution" / "run_full_auto_scheduler_entry.py"
DEV_ONLY_ANOMALY_SCRIPT = ROOT / "scripts" / "dev_only_anomaly_operating_mode_runner.py"
PHASE60_PINNED_MODEL = "phase60_restore_trx_sol_base"
PHASE63_PINNED_MODEL = "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3"
PHASE67J_PINNED_PROFILE = "phase67j_no_neo_main"

PHASE67J_PAPER = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_no_neo_main_paper.csv"
PHASE67J_SUMMARY = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_final_narrow_validation_summary.csv"
PHASE67J_LIVE = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_live_status.csv"

PHASE66G_PAPER = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_production_soft_filters_paper.csv"
PHASE66G_SUMMARY = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_production_candidate_summary.csv"
PHASE66G_LIVE = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_live_status.csv"
PHASE66G_TREND = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"

BTC_RAW = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
MACRO_FILE = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"

FRESHNESS_REPORT = ROOT / "outputs" / "app_freshness_verification" / "app_freshness_report.json"
MACRO_REFRESH_REPORT = ROOT / "outputs" / "app_freshness_verification" / "macro_refresh_report.json"
MATERIALIZE_REPORT = ROOT / "outputs" / "execution" / "refresh_pipeline" / "materialize_execution_app_exports_report.json"

REQUIRED_OUTPUTS = [
    PHASE67J_PAPER,
    PHASE67J_SUMMARY,
    PHASE67J_LIVE,
    PHASE66G_PAPER,
    PHASE66G_SUMMARY,
    PHASE66G_LIVE,
    PHASE66G_TREND,
    BTC_RAW,
    MACRO_FILE,
    FRESHNESS_REPORT,
    MACRO_REFRESH_REPORT,
    MATERIALIZE_REPORT,
]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_file(path: Path, label: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required {label}: {path}")


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    wanted = os.pathsep.join([str(ROOT / "src"), str(ROOT / "scripts")])
    current = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = wanted if not current else wanted + os.pathsep + current
    return env


def run_step(
    step_name: str,
    script_path: Path,
    env: dict[str, str],
    step_logs_dir: Path,
    script_args: list[str] | None = None,
) -> dict[str, Any]:
    ensure_file(script_path, f"script for step {step_name}")

    stdout_path = step_logs_dir / f"{step_name}.stdout.log"
    stderr_path = step_logs_dir / f"{step_name}.stderr.log"
    cmd = [sys.executable, str(script_path)]
    if script_args:
        cmd.extend(script_args)

    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )
    elapsed = time.monotonic() - started

    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Step failed: {step_name}\n"
            f"script={script_path}\n"
            f"returncode={proc.returncode}\n"
            f"stdout_log={stdout_path}\n"
            f"stderr_log={stderr_path}"
        )

    print(f"[APP-REFRESH] step_ok={step_name} elapsed_sec={elapsed:.2f}", flush=True)

    return {
        "step_name": step_name,
        "script_path": str(script_path),
        "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }


def run_non_fatal_post_step(
    step_name: str,
    script_path: Path,
    env: dict[str, str],
    step_logs_dir: Path,
    script_args: list[str] | None = None,
    dev_only: bool = True,
    non_authoritative_outputs_only: bool = True,
) -> dict[str, Any]:
    stdout_path = step_logs_dir / f"{step_name}.stdout.log"
    stderr_path = step_logs_dir / f"{step_name}.stderr.log"
    started_at_utc = now_utc()
    cmd = [sys.executable, str(script_path)]
    if script_args:
        cmd.extend(script_args)

    try:
        ensure_file(script_path, f"script for non-fatal post step {step_name}")
        started = time.monotonic()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            check=False,
        )
        elapsed = time.monotonic() - started

        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")

        result: dict[str, Any] = {
            "step_name": step_name,
            "script_path": str(script_path),
            "command": cmd,
            "started_at_utc": started_at_utc,
            "finished_at_utc": now_utc(),
            "elapsed_sec": round(elapsed, 3),
            "returncode": proc.returncode,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "status": "OK" if proc.returncode == 0 else "NON_FATAL_FAIL",
            "non_fatal": True,
            "dev_only": dev_only,
            "non_authoritative_outputs_only": non_authoritative_outputs_only,
        }

        if proc.returncode == 0:
            print(f"[APP-REFRESH] post_step_ok={step_name} elapsed_sec={elapsed:.2f}", flush=True)
        else:
            result["failure_details"] = {
                "reason": "non_zero_exit",
                "message": f"Non-fatal post step failed with return code {proc.returncode}.",
            }
            print(
                f"[APP-REFRESH] post_step_non_fatal_fail={step_name} returncode={proc.returncode}",
                flush=True,
            )

        return result
    except Exception as exc:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"[APP-REFRESH] post_step_non_fatal_fail={step_name} error={exc}", flush=True)
        return {
            "step_name": step_name,
            "script_path": str(script_path),
            "command": cmd,
            "started_at_utc": started_at_utc,
            "finished_at_utc": now_utc(),
            "returncode": None,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "status": "NON_FATAL_FAIL",
            "non_fatal": True,
            "dev_only": dev_only,
            "non_authoritative_outputs_only": non_authoritative_outputs_only,
            "failure_details": {
                "reason": "exception",
                "message": str(exc),
                "exception_type": type(exc).__name__,
            },
        }


def verify_outputs() -> list[str]:
    missing: list[str] = []
    for path in REQUIRED_OUTPUTS:
        if not path.exists() or not path.is_file():
            missing.append(str(path))
    return missing


def load_json(path: Path) -> dict[str, Any]:
    ensure_file(path, "json file")
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    manifest_path = run_dir / "app_refresh_pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def run_post_strategy_runtime_refresh(
    env: dict[str, str],
    logs_dir: Path,
) -> dict[str, Any]:
    return run_step(
        "run_full_auto_scheduler_entry",
        SCHEDULER_ENTRY_SCRIPT,
        env,
        logs_dir,
        script_args=[],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast production refresh chain for MRV1 app")
    parser.add_argument("--skip-legacy-refresh", action="store_true")
    parser.add_argument("--skip-macro-refresh", action="store_true")
    parser.add_argument("--skip-top100-refresh", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_stamp
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    env = build_env()

    manifest: dict[str, Any] = {
        "started_at_utc": now_utc(),
        "root": str(ROOT),
        "python": sys.executable,
        "mode": "fast_app_refresh",
        "skip_legacy_refresh": bool(args.skip_legacy_refresh),
        "skip_macro_refresh": bool(args.skip_macro_refresh),
        "skip_top100_refresh": bool(args.skip_top100_refresh),
        "main_refresh_chain_status": "RUNNING",
        "strategy_refresh_chain_status": "RUNNING",
        "post_strategy_runtime_refresh_status": "NOT_RUN",
        "steps": [],
        "dev_only_post_step": {
            "step_name": "dev_only_anomaly_operating_mode_runner",
            "script_path": str(DEV_ONLY_ANOMALY_SCRIPT),
            "status": "NOT_RUN",
            "non_fatal": True,
            "dev_only": True,
            "non_authoritative_outputs_only": True,
            "reason": "main_refresh_chain_not_completed",
        },
        "required_outputs": [str(p) for p in REQUIRED_OUTPUTS],
    }

    try:
        if not args.skip_legacy_refresh:
            manifest["steps"].append(
                run_step("refresh_legacy_ohlcv", LEGACY_REFRESH_SCRIPT, env, logs_dir)
            )

        if not args.skip_macro_refresh:
            manifest["steps"].append(
                run_step("refresh_global_liquidity_weekly", MACRO_REFRESH_SCRIPT, env, logs_dir)
            )

        if not args.skip_top100_refresh:
            manifest["steps"].append(
                run_step("refresh_phase67_top100_shortlist_ohlcv", TOP100_REFRESH_SCRIPT, env, logs_dir)
            )

        manifest["steps"].append(
            run_step("phase67b_top100_forensic_prune_and_rerun", PHASE67B_SCRIPT, env, logs_dir)
        )
        manifest["steps"].append(
            run_step(
                "phase60_selective_restore_robustness",
                PHASE60_SCRIPT,
                env,
                logs_dir,
                script_args=["--only-model", PHASE60_PINNED_MODEL],
            )
        )
        manifest["steps"].append(
            run_step(
                "phase63_btc_participation_overlay",
                PHASE63_SCRIPT,
                env,
                logs_dir,
                script_args=["--only-model", PHASE63_PINNED_MODEL],
            )
        )
        manifest["steps"].append(
            run_step("phase66g_production_candidate_live", PHASE66G_SCRIPT, env, logs_dir)
        )
        manifest["steps"].append(
            run_step(
                "phase67j_final_narrow_validation_pack",
                PHASE67J_SCRIPT,
                env,
                logs_dir,
                script_args=["--only-profile", PHASE67J_PINNED_PROFILE],
            )
        )
        manifest["steps"].append(
            run_step("verify_app_freshness", VERIFY_SCRIPT, env, logs_dir)
        )
        manifest["steps"].append(
            run_step("materialize_execution_app_exports", MATERIALIZE_SCRIPT, env, logs_dir)
        )

        missing_outputs = verify_outputs()
        if missing_outputs:
            raise RuntimeError(
                "App refresh finished but required outputs are missing:\n" + "\n".join(missing_outputs)
            )

        freshness = load_json(FRESHNESS_REPORT)
        macro_report = load_json(MACRO_REFRESH_REPORT)

        manifest["strategy_refresh_chain_finished_at_utc"] = now_utc()
        manifest["strategy_refresh_chain_status"] = "OK"
        manifest["freshness_report_path"] = str(FRESHNESS_REPORT)
        manifest["macro_refresh_report_path"] = str(MACRO_REFRESH_REPORT)
        manifest["freshness_report"] = freshness
        manifest["macro_refresh_report"] = macro_report
        manifest["post_strategy_runtime_refresh"] = run_post_strategy_runtime_refresh(
            env,
            logs_dir,
        )
        manifest["post_strategy_runtime_refresh_status"] = "OK"
        manifest["main_refresh_chain_finished_at_utc"] = now_utc()
        manifest["main_refresh_chain_status"] = "OK"
        manifest["status"] = "OK"
        manifest["dev_only_post_step"] = run_non_fatal_post_step(
            "dev_only_anomaly_operating_mode_runner",
            DEV_ONLY_ANOMALY_SCRIPT,
            env,
            logs_dir,
        )
        manifest["finished_at_utc"] = now_utc()

        manifest_path = write_manifest(run_dir, manifest)

        print("[APP-REFRESH] status=OK", flush=True)
        print(f"[APP-REFRESH] manifest={manifest_path}", flush=True)
        print(f"[APP-REFRESH] freshness_report={FRESHNESS_REPORT}", flush=True)
        print(f"[APP-REFRESH] macro_refresh_report={MACRO_REFRESH_REPORT}", flush=True)
        print(f"[APP-REFRESH] phase67j_live={PHASE67J_LIVE}", flush=True)
        print(f"[APP-REFRESH] phase67j_summary={PHASE67J_SUMMARY}", flush=True)
        print(f"[APP-REFRESH] phase67j_paper={PHASE67J_PAPER}", flush=True)

    except Exception as exc:
        manifest["finished_at_utc"] = now_utc()
        if manifest.get("strategy_refresh_chain_status") == "RUNNING":
            manifest["strategy_refresh_chain_status"] = "FAIL"
        if manifest.get("post_strategy_runtime_refresh_status") == "NOT_RUN":
            manifest["post_strategy_runtime_refresh_status"] = "FAIL"
        manifest["main_refresh_chain_status"] = "FAIL"
        manifest["status"] = "FAIL"
        manifest["error"] = str(exc)

        manifest_path = write_manifest(run_dir, manifest)

        print("[APP-REFRESH] status=FAIL", flush=True)
        print(f"[APP-REFRESH] manifest={manifest_path}", flush=True)
        print(f"[APP-REFRESH] error={exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
