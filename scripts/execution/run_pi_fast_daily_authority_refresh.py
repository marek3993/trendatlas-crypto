from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
import hashlib
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
PRODUCTION_CORE_DEPENDENCY_MATERIALIZE_ARGS = ("--production-core-dependencies-only",)

REBALANCE_BOUNDARY_BLOCKED_CODE = "BLOCKED_REBALANCE_BOUNDARY_NEEDS_BASELINE_REFRESH"

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


@dataclass(frozen=True)
class RebalanceBoundaryDependencyCheck:
    status: str
    needs_refresh: bool
    source_day: str | None = None
    target_day: str | None = None
    next_rebalance_date: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "needs_refresh": self.needs_refresh,
            "source_day": self.source_day,
            "target_day": self.target_day,
            "next_rebalance_date": self.next_rebalance_date,
            "reason": self.reason,
        }


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
        PythonStep(
            "hyperliquid_read_only_snapshot",
            root / "scripts" / "execution" / "hyperliquid_read_only_snapshot.py",
        ),
        PythonStep(
            "hyperliquid_real_performance_ledger",
            root / "scripts" / "execution" / "build_hyperliquid_real_performance_ledger.py",
        ),
    )


def build_production_core_dependency_materialize_step(root: Path = ROOT) -> PythonStep:
    return PythonStep(
        "materialize_production_core_dependencies",
        root / "scripts" / "execution" / "materialize_execution_app_exports.py",
        PRODUCTION_CORE_DEPENDENCY_MATERIALIZE_ARGS,
    )


def build_current_strategy_snapshot_step(root: Path = ROOT) -> PythonStep:
    return PythonStep(
        "build_current_strategy_snapshot",
        root / "scripts" / "production" / "build_current_strategy_snapshot.py",
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
    if (
        step.name == "materialize_production_core_dependencies"
        and step.args != PRODUCTION_CORE_DEPENDENCY_MATERIALIZE_ARGS
    ):
        raise ValueError(
            "Production Core dependency materialization must use the dependency-only path"
        )


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


def _load_required_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Canonical execution sync validation missing {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Canonical execution sync validation could not read {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Canonical execution sync validation expected object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    try:
        return abs(float(expected) - float(actual)) <= 1e-9
    except (TypeError, ValueError):
        return str(expected or "").strip() == str(actual or "").strip()


def validate_canonical_execution_chain_sync(
    *,
    root: Path = ROOT,
    require_execution_health: bool,
) -> dict[str, Any]:
    production_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    intent_path = (
        root / "outputs" / "execution" / "intents" / "latest_execution_intent.json"
    )
    gate_path = (
        root
        / "outputs"
        / "execution"
        / "live_gate"
        / "latest_real_order_gate_decision.json"
    )
    account_path = (
        root
        / "outputs"
        / "execution"
        / "read_only"
        / "hyperliquid_account_snapshot.json"
    )
    data_health_path = root / "outputs" / "production" / "data_health_report.json"
    production = _load_required_json(production_path)
    intent = _load_required_json(intent_path)
    gate = _load_required_json(gate_path)
    account = _load_required_json(account_path)
    data_health = _load_required_json(data_health_path)
    production_intent = production.get("execution_intent")
    if not isinstance(production_intent, dict):
        raise RuntimeError("Production Core execution_intent is missing")

    expected_intent_fields = {
        "as_of_source": production.get("closed_day"),
        "strategy_model": production.get("strategy_version"),
        "signal_id": production_intent.get("signal_id"),
        "target_asset": production_intent.get("target_asset"),
        "target_size_pct": production_intent.get("target_exposure"),
        "stale_signal": production_intent.get("stale_signal"),
        "allow_live_order_candidate": production_intent.get(
            "allow_live_order_candidate"
        ),
    }
    mismatches = [
        field_name
        for field_name, expected_value in expected_intent_fields.items()
        if not _sync_values_match(expected_value, intent.get(field_name))
    ]
    if mismatches:
        raise RuntimeError(
            "Canonical execution intent diverges from Production Core: "
            + ", ".join(mismatches)
        )

    gate_context = gate.get("production_signal_context")
    gate_context = gate_context if isinstance(gate_context, dict) else {}
    if not _sync_values_match(intent.get("signal_id"), gate.get("signal_id")):
        mismatches.append("gate.signal_id")
    if not _sync_values_match(intent.get("target_asset"), gate.get("target_asset")):
        mismatches.append("gate.target_asset")
    if not _sync_values_match(production.get("closed_day"), gate_context.get("closed_day")):
        mismatches.append("gate.production_signal_context.closed_day")
    source_paths = gate.get("source_paths")
    source_paths = source_paths if isinstance(source_paths, dict) else {}
    gate_intent_path = Path(str(source_paths.get("intent_path") or ""))
    gate_account_path = Path(str(source_paths.get("account_snapshot_path") or ""))
    if gate_intent_path.resolve() != intent_path.resolve():
        mismatches.append("gate.source_paths.intent_path")
    if gate_account_path.resolve() != account_path.resolve():
        mismatches.append("gate.source_paths.account_snapshot_path")
    fingerprints = gate.get("source_fingerprints")
    fingerprints = fingerprints if isinstance(fingerprints, dict) else {}
    expected_fingerprints = {
        "intent_sha256": _sha256_file(intent_path),
        "production_snapshot_sha256": _sha256_file(production_path),
        "account_snapshot_sha256": _sha256_file(account_path),
    }
    for field_name, expected_value in expected_fingerprints.items():
        if fingerprints.get(field_name) != expected_value:
            mismatches.append(f"gate.source_fingerprints.{field_name}")
    if mismatches:
        raise RuntimeError(
            "Canonical real-order gate diverges from the canonical execution chain: "
            + ", ".join(mismatches)
        )

    health_summary = data_health.get("summary")
    health_summary = health_summary if isinstance(health_summary, dict) else {}
    block_execution = bool(health_summary.get("block_execution"))
    if require_execution_health and block_execution:
        raise RuntimeError(
            "Canonical execution chain is aligned but data health still blocks execution"
        )
    return {
        "production_closed_day": production.get("closed_day"),
        "strategy_model": production.get("strategy_version"),
        "intent_closed_day": intent.get("as_of_source"),
        "intent_signal_id": intent.get("signal_id"),
        "intent_target_asset": intent.get("target_asset"),
        "intent_target_size_pct": intent.get("target_size_pct"),
        "gate_signal_id": gate.get("signal_id"),
        "gate_target_asset": gate.get("target_asset"),
        "gate_status": gate.get("status"),
        "gate_would_place_real_order": gate.get("would_place_real_order"),
        "account_as_of_utc": account.get("as_of_utc"),
        "data_health_block_execution": block_execution,
    }


def _normalize_iso_day(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{field_name} is not an ISO day: {value}")
    date.fromisoformat(text)
    return text


def _read_last_csv_row(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required CSV for rebalance-boundary check: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"CSV has no rows for rebalance-boundary check: {path}")
    return {
        str(key or "").strip(): str(value or "").strip()
        for key, value in rows[-1].items()
    }


def _read_last_csv_day(path: Path, *, field_name: str) -> str:
    row = _read_last_csv_row(path)
    return _normalize_iso_day(row.get(field_name), field_name=f"{path}.{field_name}")


def detect_rebalance_boundary_dependency_refresh(
    *,
    root: Path = ROOT,
) -> RebalanceBoundaryDependencyCheck:
    phase66g_live_status_path = (
        root / "outputs" / "execution" / "app_exports" / "phase66g_live_status.csv"
    )
    btc_ohlcv_path = root / "data" / "ohlcv" / "BTCUSDT_1d.csv"

    try:
        phase66g_status_row = _read_last_csv_row(phase66g_live_status_path)
        source_day = _normalize_iso_day(
            phase66g_status_row.get("latest_available_date"),
            field_name=f"{phase66g_live_status_path}.latest_available_date",
        )
        target_day = _read_last_csv_day(btc_ohlcv_path, field_name="date")
        next_rebalance_raw = str(
            phase66g_status_row.get("next_rebalance_date") or ""
        ).strip()
        next_rebalance_date = (
            _normalize_iso_day(
                next_rebalance_raw,
                field_name=f"{phase66g_live_status_path}.next_rebalance_date",
            )
            if next_rebalance_raw
            else None
        )
    except (FileNotFoundError, ValueError) as exc:
        return RebalanceBoundaryDependencyCheck(
            status="not_evaluated",
            needs_refresh=True,
            reason=str(exc),
        )

    source = date.fromisoformat(source_day)
    target = date.fromisoformat(target_day)
    if target <= source:
        return RebalanceBoundaryDependencyCheck(
            status="not_crossed",
            needs_refresh=False,
            source_day=source_day,
            target_day=target_day,
            next_rebalance_date=next_rebalance_date,
            reason="target_day_not_after_source_day",
        )

    if next_rebalance_date is None:
        return RebalanceBoundaryDependencyCheck(
            status="source_stale_missing_next_rebalance_date",
            needs_refresh=True,
            source_day=source_day,
            target_day=target_day,
            next_rebalance_date=None,
            reason="source_day_before_target_day_without_next_rebalance_date",
        )

    next_rebalance = date.fromisoformat(next_rebalance_date)
    if target >= next_rebalance:
        return RebalanceBoundaryDependencyCheck(
            status="rebalance_boundary_crossed",
            needs_refresh=True,
            source_day=source_day,
            target_day=target_day,
            next_rebalance_date=next_rebalance_date,
            reason="target_day_reaches_or_crosses_next_rebalance_date",
        )

    return RebalanceBoundaryDependencyCheck(
        status="not_crossed",
        needs_refresh=False,
        source_day=source_day,
        target_day=target_day,
        next_rebalance_date=next_rebalance_date,
        reason="target_day_before_next_rebalance_date",
    )


def maybe_run_rebalance_boundary_dependency_refresh(
    *,
    env: Mapping[str, str],
    root: Path = ROOT,
) -> tuple[str, RebalanceBoundaryDependencyCheck, list[dict[str, Any]]]:
    check = detect_rebalance_boundary_dependency_refresh(root=root)
    check_payload = check.as_dict()
    if not check.needs_refresh:
        print(
            "[PI-FAST-DAILY] rebalance_boundary_dependency_refresh=skipped "
            f"check={json.dumps(check_payload, sort_keys=True)}",
            flush=True,
        )
        return "skipped_no_boundary", check, []

    print(
        "[PI-FAST-DAILY] rebalance_boundary_dependency_refresh=required "
        f"check={json.dumps(check_payload, sort_keys=True)}",
        flush=True,
    )

    refresh_results: list[dict[str, Any]] = []
    for step in (
        build_production_core_dependency_materialize_step(root),
        build_current_strategy_snapshot_step(root),
    ):
        try:
            refresh_results.append(run_python_step(step, env=env, root=root))
        except Exception as exc:
            raise RuntimeError(
                f"{REBALANCE_BOUNDARY_BLOCKED_CODE}: safe minimal dependency refresh "
                "failed before publish-existing dry-run "
                f"(step={step.name} source_day={check.source_day or 'unknown'} "
                f"target_day={check.target_day or 'unknown'} "
                f"next_rebalance_date={check.next_rebalance_date or 'missing'} "
                f"status={check.status})"
            ) from exc

    return "completed", check, refresh_results


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

    (
        rebalance_boundary_dependency_refresh,
        rebalance_boundary_check,
        rebalance_refresh_results,
    ) = maybe_run_rebalance_boundary_dependency_refresh(env=runtime_env, root=root)
    results.extend(rebalance_refresh_results)

    dry_run_step = build_publish_existing_dry_run_step(root)
    results.append(run_python_step(dry_run_step, env=runtime_env, root=root))
    canonical_execution_sync = validate_canonical_execution_chain_sync(
        root=root,
        require_execution_health=False,
    )

    real_publish_status = "skipped_env_gate"
    if authority_real_publish_enabled(env):
        real_step = build_publish_existing_real_step(root)
        results.append(run_python_step(real_step, env=runtime_env, root=root))
        real_publish_status = "completed"
        canonical_execution_sync = validate_canonical_execution_chain_sync(
            root=root,
            require_execution_health=True,
        )
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
        "hyperliquid_read_only_snapshot": "completed",
        "hyperliquid_real_performance_ledger": "completed",
        "rebalance_boundary_dependency_refresh": rebalance_boundary_dependency_refresh,
        "rebalance_boundary_check": rebalance_boundary_check.as_dict(),
        "publish_existing_dry_run": "completed",
        "publish_existing_real": real_publish_status,
        "live_order_chain": "not_invoked",
        "canonical_execution_sync": canonical_execution_sync,
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
