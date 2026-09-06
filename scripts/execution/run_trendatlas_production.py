from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution import authority_publish_helpers  # noqa: E402
from scripts.execution.production_execution import (  # noqa: E402
    ExecutionJournal,
    ExecutionSafetyError,
    build_execution_plan,
    execute_plan_once,
    extract_positions,
    post_trade_alignment,
    validate_canonical_provenance,
    validate_live_preflight,
)
from scripts.execution.hyperliquid_credentials import redact_sensitive_text  # noqa: E402
from scripts.execution.run_pi_authoritative_producer import build_pi_authoritative_env  # noqa: E402
from scripts.execution.run_pi_fast_daily_authority_refresh import (  # noqa: E402
    build_fast_dependency_steps,
    build_production_core_dependency_materialize_step,
)
from scripts.execution.submit_controlled_real_order import (  # noqa: E402
    HyperliquidProductionExchangeAdapter,
    load_live_market_context,
)
from scripts.execution.validate_hyperliquid_production_signer import (  # noqa: E402
    validate_production_signer,
)
from scripts.production.data_health_common import (  # noqa: E402
    build_report_bundle,
    execution_blocking_sources,
)


PRODUCTION_DIR = ROOT / "outputs" / "production"
EXECUTION_OUTPUTS = ROOT / "outputs" / "execution"
RUNS_DIR = EXECUTION_OUTPUTS / "production_runs"
JOURNAL_DIR = EXECUTION_OUTPUTS / "execution_journal"
LOCK_PATH = RUNS_DIR / "trendatlas_production.lock"
LATEST_RUN_PATH = RUNS_DIR / "latest_production_run.json"

PRODUCTION_PATH = PRODUCTION_DIR / "current_strategy_snapshot.json"
INTENT_PATH = EXECUTION_OUTPUTS / "intents" / "latest_execution_intent.json"
GATE_PATH = EXECUTION_OUTPUTS / "live_gate" / "latest_real_order_gate_decision.json"
ACCOUNT_PATH = EXECUTION_OUTPUTS / "read_only" / "hyperliquid_account_snapshot.json"
HEALTH_PATH = PRODUCTION_DIR / "data_health_report.json"
MODE_PATH = ROOT / "execution" / "config" / "execution_mode.json"
POLICY_PATH = ROOT / "execution" / "config" / "live_order_policy.json"

STAGE_NAMES = (
    "ACQUIRE_LOCK",
    "REFRESH_DATA",
    "PRECHECK_DATA_HEALTH",
    "BUILD_PRODUCTION_CORE",
    "VALIDATE_PRODUCTION_CORE",
    "READ_ACCOUNT_BEFORE",
    "VALIDATE_SIGNER",
    "BUILD_CANONICAL_INTENT",
    "BUILD_REAL_ORDER_GATE",
    "VALIDATE_DATA_HEALTH",
    "RECONCILE",
    "LIVE_PREFLIGHT",
    "EXECUTE",
    "READ_ACCOUNT_AFTER",
    "POST_TRADE_VERIFY",
    "DASHBOARD_RUNTIME",
    "AUTHORITY_PUBLISH",
)
FINAL_EXECUTION_SUCCESS = {"FILLED_AND_ALIGNED", "NO_ACTION"}
PRECHECK_EXECUTION_EXCLUSIONS = {
    "production_current_strategy_snapshot",
    "production_current_strategy_timeseries",
    "production_current_strategy_diagnostics",
    "production_current_strategy_snapshot_quality",
    "execution_latest_execution_intent",
    "execution_latest_real_order_gate_decision",
    "execution_authority_latest_attempt_status",
    "execution_authority_latest_successful_snapshot",
}


class AlreadyRunning(RuntimeError):
    pass


class NoOrderAdapter:
    def query_order_by_cloid(self, _cloid: str) -> dict[str, Any]:
        return {"found": False, "status": "missing"}

    def submit_ioc_order(self, _step: Mapping[str, Any]) -> dict[str, Any]:
        raise AssertionError("NO_ACTION must never submit an order")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("prod_%Y%m%dT%H%M%SZ_%f")


def latest_closed_utc_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return payload


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (json.dumps(dict(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class SingleRunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            self.handle = None
            raise AlreadyRunning("BLOCKED_ALREADY_RUNNING") from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"pid={os.getpid()} acquired_at_utc={utc_now_iso()}\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def new_manifest(run_id: str, target_day: str, *, no_submit: bool) -> dict[str, Any]:
    return {
        "manifest_type": "trendatlas_production_run_manifest",
        "run_id": run_id,
        "started_at": utc_now_iso(),
        "finished_at": None,
        "target_closed_day": target_day,
        "no_submit": no_submit,
        "stages": {name: {"status": "PENDING", "started_at": None, "finished_at": None, "error": None} for name in STAGE_NAMES},
        "strategy_version": None,
        "signal_id": None,
        "model_target_asset": None,
        "model_target_exposure": None,
        "account_equity_before": None,
        "real_position_before": None,
        "target_notional": None,
        "planned_delta": None,
        "execution_action": None,
        "gate_status": None,
        "signer_validation": None,
        "order_requested": False,
        "order_id": None,
        "cloid": None,
        "order_result": None,
        "account_equity_after": None,
        "real_position_after": None,
        "real_exposure_after": None,
        "residual_delta": None,
        "post_trade_verification_status": None,
        "dashboard_status": None,
        "authority_status": None,
        "final_status": "RUNNING",
        "failure_stage": None,
        "failure_reason": None,
        "live_order_chain": "NOT_INVOKED",
        "real_order_sent": False,
        "execution_backend": None,
        "multi_account_execution": None,
    }


class TrendAtlasProductionOrchestrator:
    def __init__(
        self,
        *,
        root: Path = ROOT,
        no_submit: bool = False,
        command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        market_loader: Callable[[], tuple[dict[str, float], dict[str, int]]] = load_live_market_context,
        adapter_factory: Callable[[], Any] = HyperliquidProductionExchangeAdapter,
        signer_validator: Callable[[], dict[str, Any]] | None = None,
        execution_backend: str | None = None,
        now: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.root = root.resolve()
        self.no_submit = no_submit
        self.execution_backend = str(execution_backend or os.environ.get("MRV1_EXECUTION_BACKEND") or "legacy").strip()
        if self.execution_backend not in {"legacy", "multi_account"}:
            raise ValueError("MRV1_EXECUTION_BACKEND must be legacy or multi_account")
        self.command_runner = command_runner
        self.market_loader = market_loader
        self.adapter_factory = adapter_factory
        self.signer_validator = signer_validator or (
            lambda: validate_production_signer(
                account_config_path=self.root / "execution/config/hyperliquid_account.json"
            )
        )
        self.now = now
        self.run_id = run_id_now()
        self.target_day = latest_closed_utc_date()
        self.run_dir = self.root / "outputs" / "execution" / "production_runs" / self.run_id
        self.latest_run_path = self.root / "outputs" / "execution" / "production_runs" / "latest_production_run.json"
        self.manifest = new_manifest(self.run_id, self.target_day, no_submit=no_submit)
        self.manifest["execution_backend"] = self.execution_backend
        self.current_stage: str | None = None
        self.authority_state: dict[str, Any] | None = None
        self.env = build_pi_authoritative_env(env=os.environ, root=self.root)
        self.env["MRV1_CURRENT_AUTHORITY_RUN_ID"] = self.run_id
        self.env["MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY"] = self.target_day
        self.env["MRV1_ALLOW_IN_PROGRESS_AUTHORITY_FOR_SAME_RUN"] = "1"

    def persist(self) -> None:
        atomic_write_json(self.run_dir / "production_run_manifest.json", self.manifest)
        atomic_write_json(self.latest_run_path, self.manifest)

    def stage_start(self, name: str) -> None:
        self.current_stage = name
        stage = self.manifest["stages"][name]
        stage.update({"status": "RUNNING", "started_at": self.now(), "finished_at": None, "error": None})
        self.persist()

    def stage_finish(self, name: str, status: str = "PASSED", **details: Any) -> None:
        stage = self.manifest["stages"][name]
        stage.update({"status": status, "finished_at": self.now(), **details})
        self.persist()
        self.current_stage = None

    def run_script(self, script: Path, *arguments: str, label: str) -> None:
        command = [sys.executable, str(script), *arguments]
        if any(token in command for token in ("--mode", "full-refresh")):
            joined = " ".join(command)
            if "--mode full-refresh" in joined:
                raise RuntimeError("full_refresh_forbidden")
        completed = self.command_runner(command, cwd=str(self.root), env=dict(self.env), check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"{label}_failed_returncode_{completed.returncode}")

    def run_multi_account_backend(self, signal_id: str, *, no_submit: bool) -> tuple[dict[str, Any], int]:
        web_root = Path(str(self.env.get("MRV1_MULTI_ACCOUNT_WEB_ROOT") or "")).resolve()
        node_binary = Path(str(self.env.get("MRV1_MULTI_ACCOUNT_NODE_BINARY") or "")).resolve()
        runner = web_root / "scripts/run-multi-account-production-cycle.ts"
        if web_root != self.root / "web" or not node_binary.is_file() or not os.access(node_binary, os.X_OK) or not runner.is_file():
            raise ExecutionSafetyError("multi_account_runtime_is_incomplete")
        execution_env = dict(self.env)
        execution_env.update({
            "TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE": "dry_run" if no_submit else "live",
            "TRENDATLAS_EXECUTION_OWNER": "multi_account",
            "TRENDATLAS_MULTI_ACCOUNT_EXECUTION_CONTEXT": "canonical_orchestrator",
            "TRENDATLAS_MULTI_ACCOUNT_CONFIRMATION": "ENABLE:ALL_ELIGIBLE_ACCOUNTS",
            "TRENDATLAS_AUTHORITY_REPOSITORY_ROOT": str(self.root),
            "TRENDATLAS_LIVE_SIGNAL_CONFIRMATION": signal_id,
        })
        completed = self.command_runner(
            [
                str(node_binary),
                "--conditions=react-server",
                "--import", "tsx",
                str(runner),
            ],
            cwd=str(web_root),
            env=execution_env,
            check=False,
            capture_output=True,
            text=True,
        )
        stdout = str(completed.stdout or "").strip()
        try:
            report = json.loads(stdout.splitlines()[-1])
        except Exception as exc:
            raise ExecutionSafetyError(
                f"multi_account_runner_failed_returncode_{completed.returncode}"
            ) from exc
        if not isinstance(report, dict) or report.get("runId") != self.run_id or report.get("signalId") != signal_id:
            raise ExecutionSafetyError("multi_account_result_binding_mismatch")
        return report, int(completed.returncode)

    def load_runtime(self) -> tuple[dict, dict, dict, dict, dict, dict]:
        return tuple(
            read_json(path)
            for path in (
                self.root / "outputs/production/current_strategy_snapshot.json",
                self.root / "outputs/execution/intents/latest_execution_intent.json",
                self.root / "outputs/execution/live_gate/latest_real_order_gate_decision.json",
                self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json",
                self.root / "execution/config/execution_mode.json",
                self.root / "execution/config/live_order_policy.json",
            )
        )  # type: ignore[return-value]

    def rebuild_fail_closed_runtime_state(self, *, refresh_account: bool) -> None:
        """Refresh canonical read-only state after a blocked or uncertain run.

        This best-effort path never constructs an exchange adapter and cannot
        submit an order. Its purpose is to ensure that an authority failure does
        not leave an earlier healthy gate or data-health report visible as the
        current execution truth.
        """
        recovery_errors: list[str] = []
        try:
            if refresh_account:
                self.run_script(
                    self.root / "scripts/execution/hyperliquid_read_only_snapshot.py",
                    label="recover_account_after_failure",
                )
        except Exception as exc:
            recovery_errors.append(
                redact_sensitive_text(f"account_readback:{type(exc).__name__}:{exc}")
            )
        try:
            required = (
                self.root / "outputs/production/current_strategy_snapshot.json",
                self.root / "outputs/execution/intents/latest_execution_intent.json",
                self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json",
            )
            if all(path.is_file() for path in required):
                self.run_script(
                    self.root / "scripts/execution/prepare_real_order_gate.py",
                    label="recover_gate_after_failure",
                )
                build_report_bundle(
                    root=self.root,
                    output_dir=self.root / "outputs/production",
                    write_outputs=True,
                )
        except Exception as exc:
            recovery_errors.append(
                redact_sensitive_text(f"canonical_health:{type(exc).__name__}:{exc}")
            )
        try:
            self.persist()
            self.run_script(
                self.root / "scripts/execution/materialize_execution_app_exports.py",
                "--runtime-snapshot-only",
                label="recover_dashboard_after_failure",
            )
        except Exception as exc:
            recovery_errors.append(
                redact_sensitive_text(f"dashboard:{type(exc).__name__}:{exc}")
            )
        if recovery_errors:
            self.manifest["fail_closed_recovery_errors"] = recovery_errors
        self.persist()

    def validate_core(self, production: Mapping[str, Any]) -> None:
        if str(production.get("closed_day") or "") != self.target_day:
            raise ExecutionSafetyError(
                f"production_closed_day_mismatch:expected={self.target_day}:actual={production.get('closed_day')}"
            )
        if str(production.get("validation", {}).get("status") or "").lower() != "passed":
            raise ExecutionSafetyError("production_core_validation_not_passed")
        if not isinstance(production.get("execution_intent"), Mapping):
            raise ExecutionSafetyError("production_core_execution_intent_missing")

    def publish_attempt_started(self) -> None:
        state = authority_publish_helpers.build_authority_publish_state(
            run_id=self.run_id,
            run_dir=self.run_dir,
            refresh_started_at_utc=self.manifest["started_at"],
            target_closed_day_utc=self.target_day,
            latest_available_closed_utc_day=self.target_day,
            env=self.env,
        )
        result = authority_publish_helpers.publish_authority_refresh_started(state, env=self.env)
        if not result.get("published"):
            raise RuntimeError(f"authority_attempt_start_failed:{result.get('reason')}")
        self.authority_state = state

    def run_canonical_builders(self) -> None:
        self.run_script(
            self.root / "scripts/execution/build_execution_intent_from_strategy_exports.py",
            label="build_canonical_intent",
        )
        self.run_script(
            self.root / "scripts/execution/prepare_real_order_gate.py",
            label="build_real_order_gate",
        )

    def post_trade_verifier(self, plan: Mapping[str, Any], action_results: list[dict[str, Any]]) -> dict[str, Any]:
        self.run_script(
            self.root / "scripts/execution/hyperliquid_read_only_snapshot.py",
            label="post_trade_account_readback",
        )
        production, intent, gate, snapshot, _mode, policy = self.load_runtime()
        mids, precision = self.market_loader()
        residual = build_execution_plan(
            production=production,
            intent=intent,
            gate=gate,
            account_snapshot=snapshot,
            policy=policy,
            mids=mids,
            size_decimals=precision,
        )
        positions = extract_positions(snapshot, mids)
        old_assets = {str(step["asset"]) for step in plan.get("steps", []) if step.get("reduce_only")}
        remaining_old = [position for position in positions if position["asset"] in old_assets]
        raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), Mapping) else {}
        open_orders = raw.get("openOrders", []) if isinstance(raw, Mapping) else []
        safe_for_next_step = not remaining_old and not open_orders
        aligned, tolerance, critical_blockers = post_trade_alignment(residual, policy)
        if aligned:
            status = "FILLED_AND_ALIGNED"
        elif open_orders:
            status = "PARTIAL"
        else:
            status = "FILLED_WITH_RESIDUAL"
        return {
            "status": status,
            "safe_for_next_step": safe_for_next_step,
            "account_snapshot_as_of_utc": snapshot.get("as_of_utc"),
            "positions": positions,
            "open_orders": open_orders,
            "residual_delta_usd": residual.get("delta_notional_usd"),
            "post_trade_tolerance_usd": tolerance,
            "critical_block_reasons": critical_blockers,
            "residual_action": residual.get("action"),
            "action_results_count": len(action_results),
        }

    def run(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.persist()
        try:
            self.stage_start("ACQUIRE_LOCK")
            self.stage_finish("ACQUIRE_LOCK")

            self.stage_start("REFRESH_DATA")
            for step in build_fast_dependency_steps(self.root):
                if step.name == "hyperliquid_read_only_snapshot":
                    continue
                self.run_script(step.script_path, *step.args, label=step.name)
            materialize = build_production_core_dependency_materialize_step(self.root)
            self.run_script(materialize.script_path, *materialize.args, label=materialize.name)
            self.stage_finish("REFRESH_DATA")

            self.stage_start("PRECHECK_DATA_HEALTH")
            precheck_bundle = build_report_bundle(root=self.root, write_outputs=False)
            blockers = execution_blocking_sources(
                precheck_bundle["report"], exclude_source_ids=PRECHECK_EXECUTION_EXCLUSIONS
            )
            if blockers:
                raise ExecutionSafetyError([f"{row['source_id']}:{row['status']}" for row in blockers])
            self.stage_finish("PRECHECK_DATA_HEALTH", blocker_count=0)

            self.stage_start("BUILD_PRODUCTION_CORE")
            self.run_script(
                self.root / "scripts/production/build_current_strategy_snapshot.py",
                label="build_production_core",
            )
            self.stage_finish("BUILD_PRODUCTION_CORE")

            self.stage_start("VALIDATE_PRODUCTION_CORE")
            self.run_script(
                self.root / "scripts/production/validate_current_strategy_snapshot.py",
                label="validate_production_core",
            )
            production = read_json(self.root / "outputs/production/current_strategy_snapshot.json")
            self.validate_core(production)
            prod_intent = production["execution_intent"]
            self.manifest.update({
                "strategy_version": production.get("strategy_version"),
                "signal_id": prod_intent.get("signal_id"),
                "model_target_asset": prod_intent.get("target_asset"),
                "model_target_exposure": prod_intent.get("target_exposure"),
            })
            self.stage_finish("VALIDATE_PRODUCTION_CORE")

            self.stage_start("READ_ACCOUNT_BEFORE")
            self.run_script(
                self.root / "scripts/execution/hyperliquid_read_only_snapshot.py",
                label="read_account_before",
            )
            self.publish_attempt_started()
            self.stage_finish("READ_ACCOUNT_BEFORE")

            self.stage_start("VALIDATE_SIGNER")
            if self.execution_backend == "multi_account":
                required_multi_account_env = (
                    "NEXT_PUBLIC_SUPABASE_URL",
                    "SUPABASE_ADMIN_KEY",
                    "TRENDATLAS_AGENT_KEK_B64",
                    "MRV1_MULTI_ACCOUNT_NODE_BINARY",
                    "MRV1_MULTI_ACCOUNT_WEB_ROOT",
                )
                if any(not str(self.env.get(name) or "").strip() for name in required_multi_account_env):
                    raise ExecutionSafetyError("multi_account_credentials_or_runtime_missing")
                signer_validation = {
                    "status": "PASS",
                    "mode": "multi_account_per_account_preflight",
                    "credential_value_exposed": False,
                }
            else:
                signer_validation = self.signer_validator()
                if str(signer_validation.get("status") or "").upper() != "PASS":
                    raise ExecutionSafetyError("production_signer_validation_not_passed")
                if bool(signer_validation.get("credential_value_exposed")):
                    raise ExecutionSafetyError("production_signer_secret_exposure_detected")
            self.manifest["signer_validation"] = signer_validation
            self.stage_finish("VALIDATE_SIGNER")

            self.stage_start("BUILD_CANONICAL_INTENT")
            self.run_script(
                self.root / "scripts/execution/build_execution_intent_from_strategy_exports.py",
                label="build_canonical_intent",
            )
            self.stage_finish("BUILD_CANONICAL_INTENT")

            self.stage_start("BUILD_REAL_ORDER_GATE")
            self.run_script(
                self.root / "scripts/execution/prepare_real_order_gate.py",
                label="build_real_order_gate",
            )
            self.stage_finish("BUILD_REAL_ORDER_GATE")

            self.stage_start("VALIDATE_DATA_HEALTH")
            health_bundle = build_report_bundle(root=self.root, output_dir=self.root / "outputs/production", write_outputs=True)
            health = health_bundle["report"]
            if bool(health.get("summary", {}).get("block_execution")):
                blockers = execution_blocking_sources(health)
                raise ExecutionSafetyError([f"{row['source_id']}:{row['status']}" for row in blockers])
            self.stage_finish("VALIDATE_DATA_HEALTH")

            self.stage_start("RECONCILE")
            production, intent, gate, snapshot, mode, policy = self.load_runtime()
            mids, precision = self.market_loader()
            plan = build_execution_plan(
                production=production,
                intent=intent,
                gate=gate,
                account_snapshot=snapshot,
                policy=policy,
                mids=mids,
                size_decimals=precision,
            )
            atomic_write_json(self.run_dir / "execution_plan.json", plan)
            if plan["status"] == "BLOCKED":
                raise ExecutionSafetyError(list(plan["block_reasons"]))
            self.manifest.update({
                "account_equity_before": plan["account_equity_usd"],
                "real_position_before": {"asset": plan["current_asset"], "notional_usd": plan["current_notional_usd"]},
                "target_notional": plan["target_notional_usd"],
                "planned_delta": plan["delta_notional_usd"],
                "execution_action": plan["action"],
                "gate_status": gate.get("status"),
                "cloid": [step["cloid"] for step in plan.get("steps", [])],
            })
            self.stage_finish("RECONCILE")

            self.stage_start("LIVE_PREFLIGHT")
            provenance_reasons = validate_canonical_provenance(
                production_path=self.root / "outputs/production/current_strategy_snapshot.json",
                intent_path=self.root / "outputs/execution/intents/latest_execution_intent.json",
                account_path=self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json",
                gate=gate,
            )
            preflight_reasons: list[str] = []
            if plan["action"] != "NO_ACTION":
                preflight_reasons = validate_live_preflight(
                    plan=plan,
                    production=production,
                    intent=intent,
                    gate=gate,
                    mode=mode,
                    policy=policy,
                    data_health=health,
                    provenance_reasons=provenance_reasons,
                )
            elif provenance_reasons:
                preflight_reasons = provenance_reasons
            if preflight_reasons:
                raise ExecutionSafetyError(preflight_reasons)
            atomic_write_json(self.run_dir / "live_preflight.json", {
                "status": "READY",
                "no_submit": self.no_submit,
                "plan": plan,
                "checked_at_utc": self.now(),
            })
            self.stage_finish("LIVE_PREFLIGHT")

            self.stage_start("EXECUTE")
            if self.execution_backend == "multi_account":
                if not self.no_submit:
                    self.manifest["live_order_chain"] = "INVOKED"
                    self.manifest["order_requested"] = None
                    self.manifest["real_order_sent"] = None
                    self.manifest["order_result"] = "MULTI_ACCOUNT_EXECUTING_OR_UNCERTAIN"
                    self.persist()
                multi_account_report, returncode = self.run_multi_account_backend(
                    str(self.manifest["signal_id"]),
                    no_submit=self.no_submit,
                )
                self.manifest["multi_account_execution"] = multi_account_report
                self.manifest["real_order_sent"] = multi_account_report.get("realOrderSent")
                self.manifest["order_requested"] = multi_account_report.get("realOrderSent")
                self.manifest["order_result"] = "PREFLIGHT_ONLY" if self.no_submit else ("SUCCESS" if multi_account_report.get("successful") else "FAILED_OR_AMBIGUOUS")
                self.persist()
                if returncode != 0 or multi_account_report.get("successful") is not True:
                    raise ExecutionSafetyError("multi_account_execution_not_terminal_success")
                if self.no_submit:
                    execution_result = {"status": "PREFLIGHT_ONLY", "order_requested": False, "action_results": []}
                    self.stage_finish("EXECUTE", "SKIPPED", reason="multi_account_no_submit")
                else:
                    execution_result = {
                        "status": "FILLED_AND_ALIGNED" if multi_account_report.get("realOrderSent") is True else "NO_ACTION",
                        "order_requested": multi_account_report.get("realOrderSent") is True,
                        "action_results": multi_account_report.get("results", []),
                    }
                    self.stage_finish("EXECUTE")
            elif self.no_submit:
                execution_result = {"status": "PREFLIGHT_ONLY", "order_requested": False, "action_results": []}
                self.stage_finish("EXECUTE", "SKIPPED", reason="no_submit")
            elif plan["action"] == "NO_ACTION":
                execution_result = execute_plan_once(
                    plan=plan,
                    run_id=self.run_id,
                    journal=ExecutionJournal(self.root / "outputs/execution/execution_journal"),
                    adapter=NoOrderAdapter(),
                    refresh_and_verify=self.post_trade_verifier,
                )
                self.stage_finish("EXECUTE", "SKIPPED", reason="no_action")
            else:
                # Persist uncertainty before crossing the exchange mutation
                # boundary. A power loss after this point must never be reported
                # as a definite no-order outcome merely because no response was
                # written locally.
                self.manifest["live_order_chain"] = "INVOKED"
                self.manifest["order_requested"] = True
                self.manifest["real_order_sent"] = None
                self.manifest["order_result"] = "SUBMITTING_OR_UNCERTAIN"
                self.persist()
                execution_result = execute_plan_once(
                    plan=plan,
                    run_id=self.run_id,
                    journal=ExecutionJournal(self.root / "outputs/execution/execution_journal"),
                    adapter=self.adapter_factory(),
                    refresh_and_verify=self.post_trade_verifier,
                )
                self.manifest["real_order_sent"] = bool(execution_result.get("order_requested"))
                self.manifest["order_requested"] = bool(execution_result.get("order_requested"))
                self.manifest["order_result"] = execution_result.get("status")
                action_results = execution_result.get("action_results", [])
                order_ids = [
                    row.get("response", {}).get("oid")
                    for row in action_results
                    if isinstance(row, Mapping) and isinstance(row.get("response"), Mapping)
                ]
                self.manifest["order_id"] = [oid for oid in order_ids if oid is not None]
                self.persist()
                if execution_result.get("status") not in FINAL_EXECUTION_SUCCESS:
                    raise ExecutionSafetyError(f"execution_result:{execution_result.get('status')}")
                self.stage_finish("EXECUTE")
            self.manifest["order_requested"] = bool(execution_result.get("order_requested"))
            self.manifest["order_result"] = execution_result.get("status")
            self.persist()

            self.stage_start("READ_ACCOUNT_AFTER")
            if self.no_submit or self.execution_backend == "multi_account" or plan["action"] == "NO_ACTION":
                self.run_script(
                    self.root / "scripts/execution/hyperliquid_read_only_snapshot.py",
                    label="read_account_after",
                )
            self.stage_finish("READ_ACCOUNT_AFTER")

            self.stage_start("POST_TRADE_VERIFY")
            production, intent, gate, after_snapshot, mode, policy = self.load_runtime()
            after_mids, after_precision = self.market_loader()
            residual_plan = build_execution_plan(
                production=production,
                intent=intent,
                gate=gate,
                account_snapshot=after_snapshot,
                policy=policy,
                mids=after_mids,
                size_decimals=after_precision,
            )
            after_positions = extract_positions(after_snapshot, after_mids)
            aligned_after, post_trade_tolerance, post_trade_blockers = post_trade_alignment(
                residual_plan,
                policy,
            )
            verification_status = (
                "PREFLIGHT_ONLY"
                if self.no_submit
                else (
                    execution_result["status"]
                    if self.execution_backend == "multi_account"
                    else ("NO_ACTION" if plan["action"] == "NO_ACTION" else execution_result["status"])
                )
            )
            if not self.no_submit and verification_status in FINAL_EXECUTION_SUCCESS and not aligned_after:
                raise ExecutionSafetyError("post_trade_account_not_aligned")
            self.manifest.update({
                "account_equity_after": residual_plan.get("account_equity_usd"),
                "real_position_after": after_positions,
                "real_exposure_after": (
                    abs(float(after_positions[0]["notional_usd"])) / float(residual_plan["account_equity_usd"])
                    if len(after_positions) == 1 else 0.0
                ),
                "residual_delta": residual_plan.get("delta_notional_usd"),
                "post_trade_verification_status": verification_status,
                "post_trade_tolerance_usd": post_trade_tolerance,
                "post_trade_block_reasons": post_trade_blockers,
            })
            # Account read-back changed the canonical account fingerprint; rebuild the gate.
            self.run_script(
                self.root / "scripts/execution/prepare_real_order_gate.py",
                label="rebuild_gate_after_account_readback",
            )
            final_health = build_report_bundle(root=self.root, output_dir=self.root / "outputs/production", write_outputs=True)["report"]
            if bool(final_health.get("summary", {}).get("block_execution")):
                raise ExecutionSafetyError("final_data_health_blocks_execution")
            self.stage_finish("POST_TRADE_VERIFY")

            # Public runtime and authority publication must consume a terminal
            # execution result, never the in-progress manifest. Authority status
            # is filled later, but execution is final after verified read-back.
            self.manifest["final_status"] = (
                "PREFLIGHT_READY" if self.no_submit else "SUCCESS"
            )
            self.manifest["finished_at"] = self.now()
            self.persist()

            self.stage_start("DASHBOARD_RUNTIME")
            self.run_script(
                self.root / "scripts/execution/materialize_execution_app_exports.py",
                "--runtime-snapshot-only",
                label="materialize_dashboard_runtime",
            )
            self.manifest["dashboard_status"] = "PASSED"
            self.stage_finish("DASHBOARD_RUNTIME")

            self.stage_start("AUTHORITY_PUBLISH")
            if self.no_submit:
                self.manifest["authority_status"] = "SKIPPED_NO_SUBMIT"
                if self.authority_state is not None:
                    authority_publish_helpers.publish_authority_refresh_failure(
                        self.authority_state,
                        refresh_finished_at_utc=self.now(),
                        error="preflight_only_no_authority_success",
                        env=self.env,
                    )
                self.stage_finish("AUTHORITY_PUBLISH", "SKIPPED", reason="no_submit")
            else:
                self.run_script(
                    self.root / "scripts/execution/run_pi_authoritative_producer.py",
                    "--mode", "publish-existing", "--dry-run",
                    label="authority_publish_existing_dry_run",
                )
                self.run_script(
                    self.root / "scripts/execution/run_pi_authoritative_producer.py",
                    "--mode", "publish-existing",
                    label="authority_publish_existing",
                )
                self.manifest["authority_status"] = "PASSED"
                self.stage_finish("AUTHORITY_PUBLISH")
            self.manifest["finished_at"] = self.now()
            self.persist()
            if self.no_submit:
                self.rebuild_fail_closed_runtime_state(refresh_account=False)
            return self.manifest
        except BaseException as exc:
            if self.authority_state is not None and not self.no_submit:
                try:
                    authority_publish_helpers.publish_authority_refresh_failure(
                        self.authority_state,
                        refresh_finished_at_utc=self.now(),
                        error=redact_sensitive_text(exc),
                        env=self.env,
                    )
                except Exception as authority_exc:
                    self.manifest["authority_failure_publish_error"] = (
                        redact_sensitive_text(
                            f"{type(authority_exc).__name__}:{authority_exc}"
                        )
                    )
            safe_error = redact_sensitive_text(exc)
            if self.current_stage is not None:
                stage = self.manifest["stages"][self.current_stage]
                stage.update({
                    "status": "BLOCKED" if isinstance(exc, ExecutionSafetyError) else "FAILED",
                    "finished_at": self.now(),
                    "error": safe_error,
                })
            self.manifest.update({
                "finished_at": self.now(),
                "final_status": "BLOCKED" if isinstance(exc, ExecutionSafetyError) else "FAILED",
                "failure_stage": self.current_stage,
                "failure_reason": safe_error,
                "traceback": redact_sensitive_text(traceback.format_exc(limit=12)),
            })
            self.persist()
            if self.authority_state is not None:
                self.rebuild_fail_closed_runtime_state(
                    refresh_account=self.manifest.get("live_order_chain") == "INVOKED"
                )
            return self.manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single canonical TrendAtlas daily production orchestrator.")
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Run current production refresh and all preflight checks, but never instantiate the live exchange adapter or submit an order.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    lock_path = ROOT / "outputs/execution/production_runs/trendatlas_production.lock"
    try:
        with SingleRunLock(lock_path):
            result = TrendAtlasProductionOrchestrator(root=ROOT, no_submit=args.no_submit).run()
    except AlreadyRunning:
        print(json.dumps({"final_status": "BLOCKED_ALREADY_RUNNING", "real_order_sent": False}, indent=2))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["final_status"] in {"SUCCESS", "PREFLIGHT_READY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
