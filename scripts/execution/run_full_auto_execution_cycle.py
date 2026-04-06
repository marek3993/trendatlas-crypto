from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution import submit_controlled_real_order as controlled_submitter  # noqa: E402
from scripts.execution.hyperliquid_live_canary import (  # noqa: E402
    fetch_open_orders,
    fetch_spot_user_state,
    fetch_user_state,
    summarize_snapshot,
)


EXECUTION_DIR = ROOT / "execution"
CONFIG_DIR = EXECUTION_DIR / "config"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
FULL_AUTO_DIR = OUTPUTS_DIR / "full_auto"
LOGS_DIR = OUTPUTS_DIR / "logs"

ACCOUNT_CONFIG_PATH = CONFIG_DIR / "hyperliquid_account.json"
MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"

DEFAULT_INTENT_PATH = OUTPUTS_DIR / "intents" / "latest_execution_intent.json"
DEFAULT_GATE_PATH = OUTPUTS_DIR / "live_gate" / "latest_real_order_gate_decision.json"
DEFAULT_RECON_PATH = OUTPUTS_DIR / "reconciliation" / "latest_reconciliation_report.json"
DEFAULT_RUNNER_SNAPSHOT_PATH = FULL_AUTO_DIR / "latest_full_auto_runner_snapshot.json"

RUNNER_DECISION_PATH = FULL_AUTO_DIR / "latest_full_auto_runner_decision.json"
RUNNER_MANIFEST_PATH = FULL_AUTO_DIR / "latest_full_auto_runner_manifest.json"
LAST_EXECUTED_SIGNAL_RECORD_PATH = FULL_AUTO_DIR / "last_executed_signal_record.json"
SKIP_REASON_PATH = FULL_AUTO_DIR / "latest_full_auto_skip_reason.json"
LOG_PATH = LOGS_DIR / "run_full_auto_execution_cycle.log"

MATERIALIZE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"
BUILD_INTENT_SCRIPT_PATH = ROOT / "scripts" / "execution" / "build_execution_intent_from_strategy_exports.py"
RECONCILE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "reconcile_live_execution_state.py"
PREPARE_GATE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "prepare_real_order_gate.py"

MANUAL_CONFIRM_TOKEN = "FULL_AUTO_EXECUTION"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def log(msg: str) -> None:
    print(msg)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    raise SystemExit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON in {path}: {exc}")
    except Exception as exc:
        fail(f"Failed reading {path}: {exc}")
    raise RuntimeError("unreachable")


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def require_manual_execution(args: argparse.Namespace) -> None:
    if not args.execute_live:
        return
    if args.manual_confirm != MANUAL_CONFIRM_TOKEN:
        fail(
            "Manual confirmation missing. "
            f"Pass --manual-confirm {MANUAL_CONFIRM_TOKEN} together with --execute-live."
        )


def run_python_script(script_path: Path, arguments: list[str]) -> None:
    command = [sys.executable, str(script_path), *arguments]
    try:
        subprocess.run(command, cwd=str(ROOT), check=True)
    except subprocess.CalledProcessError as exc:
        fail(f"Script failed ({script_path.name}) with exit code {exc.returncode}")


def refresh_runner_snapshot(account_config_path: Path, output_path: Path) -> dict[str, Any]:
    account_cfg = read_json(account_config_path)
    account_address = str(account_cfg.get("account_address", "")).strip()
    if not account_address:
        fail(f"{account_config_path} missing account_address")

    state = fetch_user_state(account_address)
    spot_state = fetch_spot_user_state(account_address)
    open_orders = fetch_open_orders(account_address)
    snapshot = summarize_snapshot(account_address, state, spot_state, open_orders)
    write_json(output_path, snapshot)
    return snapshot


def materialize_and_build_official_intent() -> Path:
    run_python_script(MATERIALIZE_SCRIPT_PATH, [])
    run_python_script(BUILD_INTENT_SCRIPT_PATH, [])
    return DEFAULT_INTENT_PATH


def refresh_reconciliation_and_gate(
    *,
    intent_path: Path,
    snapshot_path: Path,
    mode_config_path: Path,
    live_order_policy_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_python_script(
        RECONCILE_SCRIPT_PATH,
        [
            "--intent-path", str(intent_path),
            "--snapshot-path", str(snapshot_path),
            "--mode-config-path", str(mode_config_path),
            "--live-order-policy-path", str(live_order_policy_path),
        ],
    )
    run_python_script(
        PREPARE_GATE_SCRIPT_PATH,
        [
            "--intent-path", str(intent_path),
            "--snapshot-path", str(snapshot_path),
            "--mode-config-path", str(mode_config_path),
            "--live-order-policy-path", str(live_order_policy_path),
        ],
    )
    return read_json(DEFAULT_RECON_PATH), read_json(DEFAULT_GATE_PATH)


def invoke_controlled_submitter(
    *,
    execute_live: bool,
    manual_confirm: str,
    intent_path: Path,
    gate_path: Path,
    reconciliation_path: Path,
    snapshot_path: Path | None,
    mode_config_path: Path,
    live_order_policy_path: Path,
    account_config_path: Path,
) -> dict[str, Any]:
    original_mode = controlled_submitter.MODE_CONFIG_PATH
    original_policy = controlled_submitter.LIVE_ORDER_POLICY_PATH
    original_account = controlled_submitter.ACCOUNT_CONFIG_PATH
    original_argv = sys.argv[:]

    try:
        controlled_submitter.MODE_CONFIG_PATH = mode_config_path
        controlled_submitter.LIVE_ORDER_POLICY_PATH = live_order_policy_path
        controlled_submitter.ACCOUNT_CONFIG_PATH = account_config_path

        argv = [
            str(controlled_submitter.Path(__file__).resolve()),
            "--intent-path", str(intent_path),
            "--gate-path", str(gate_path),
            "--reconciliation-path", str(reconciliation_path),
        ]
        if snapshot_path is not None:
            argv.extend(["--snapshot-path", str(snapshot_path)])
        if execute_live:
            argv.extend(["--execute-live", "--manual-confirm", manual_confirm])

        sys.argv = argv
        controlled_submitter.main()
    except SystemExit as exc:
        if int(exc.code or 0) != 0:
            fail(f"submit_controlled_real_order failed with exit code {exc.code}")
    finally:
        sys.argv = original_argv
        controlled_submitter.MODE_CONFIG_PATH = original_mode
        controlled_submitter.LIVE_ORDER_POLICY_PATH = original_policy
        controlled_submitter.ACCOUNT_CONFIG_PATH = original_account

    return {
        "decision": read_json(controlled_submitter.DECISION_PATH),
        "manifest": read_json(controlled_submitter.MANIFEST_PATH),
        "request_payload": read_json(controlled_submitter.REQUEST_PAYLOAD_PATH),
        "exchange_response": read_json(controlled_submitter.EXCHANGE_RESPONSE_PATH),
        "leverage_response": read_json(controlled_submitter.LEVERAGE_RESPONSE_PATH),
        "post_reconciliation": read_json(controlled_submitter.POST_RECON_PATH),
    }


def build_idempotency_key(submit_decision: dict[str, Any]) -> str:
    submit_plan = submit_decision.get("submit_plan", {})
    normalized_steps = []
    for step in submit_plan.get("steps", []):
        if not isinstance(step, dict):
            continue
        normalized_steps.append(
            {
                "step_type": step.get("step_type"),
                "reason": step.get("reason"),
                "coin": step.get("coin"),
                "side": step.get("side"),
                "reduce_only": step.get("reduce_only"),
                "exchange_leverage_target": step.get("exchange_leverage_target"),
                "exchange_margin_mode": step.get("exchange_margin_mode"),
                "order_size": step.get("order_size"),
            }
        )
    payload = {
        "signal_id": submit_decision.get("signal_id"),
        "target_asset": submit_decision.get("target_asset"),
        "target_regime": submit_decision.get("target_regime"),
        "current_state": submit_plan.get("current_state"),
        "target_size": submit_plan.get("target_size"),
        "target_notional_usd": submit_plan.get("target_notional_usd"),
        "runner_action_shape": "no_action" if not normalized_steps else "submit",
        "steps": normalized_steps,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def should_skip_as_duplicate(
    last_record: dict[str, Any] | None,
    current_idempotency_key: str,
) -> bool:
    if not isinstance(last_record, dict):
        return False
    if not bool(last_record.get("duplicate_guard_active", False)):
        return False
    return str(last_record.get("idempotency_key", "")).strip() == current_idempotency_key


def build_signal_record(
    *,
    submit_decision: dict[str, Any],
    runner_status: str,
    preview_only: bool,
    real_order_sent: bool,
    duplicate_guard_active: bool,
) -> dict[str, Any]:
    submit_plan = submit_decision.get("submit_plan", {})
    return {
        "artifact_type": "full_auto_last_executed_signal_record",
        "recorded_at_utc": utc_now_iso(),
        "signal_id": submit_decision.get("signal_id"),
        "target_asset": submit_decision.get("target_asset"),
        "target_regime": submit_decision.get("target_regime"),
        "runner_status": runner_status,
        "submit_status": submit_decision.get("status"),
        "preview_only": preview_only,
        "real_order_sent": real_order_sent,
        "duplicate_guard_active": duplicate_guard_active,
        "idempotency_key": build_idempotency_key(submit_decision),
        "current_state": submit_plan.get("current_state"),
        "target_size": submit_plan.get("target_size"),
        "target_notional_usd": submit_plan.get("target_notional_usd"),
        "steps": submit_plan.get("steps", []),
        "decision_path": str(controlled_submitter.DECISION_PATH.resolve()),
        "post_reconciliation_path": str(controlled_submitter.POST_RECON_PATH.resolve()),
    }


def write_skip_reason(
    *,
    reason: str,
    runner_status: str,
    signal_id: str,
    target_asset: str,
    gate: dict[str, Any],
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "artifact_type": "full_auto_skip_reason",
        "generated_at_utc": utc_now_iso(),
        "runner_status": runner_status,
        "skip_reason": reason,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "gate_status": gate.get("status"),
        "gate_block_reasons": gate.get("block_reasons", []),
        "reconciliation_action": reconciliation.get("reconciliation_action"),
        "current_state": reconciliation.get("current_state"),
    }
    write_json(SKIP_REASON_PATH, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot full-auto execution cycle that refreshes intent inputs, "
            "rebuilds gate/reconciliation context, and invokes the controlled real submitter."
        )
    )
    parser.add_argument("--execute-live", action="store_true", help="Actually send live exchange actions.")
    parser.add_argument("--manual-confirm", default="", help=f"Required with --execute-live. Must equal {MANUAL_CONFIRM_TOKEN}.")
    parser.add_argument("--intent-path", type=Path, default=None, help="Optional override intent JSON. If omitted, official intent is refreshed and used.")
    parser.add_argument("--snapshot-path", type=Path, default=None, help="Optional snapshot override for preview/testing.")
    parser.add_argument("--mode-config-path", type=Path, default=MODE_CONFIG_PATH, help="Execution mode config path.")
    parser.add_argument("--live-order-policy-path", type=Path, default=LIVE_ORDER_POLICY_PATH, help="Live order policy config path.")
    parser.add_argument("--account-config-path", type=Path, default=ACCOUNT_CONFIG_PATH, help="Hyperliquid account config path.")
    parser.add_argument(
        "--commit-idempotency-record",
        action="store_true",
        help=(
            "Persist idempotency record even in preview mode when the cycle reaches ready_if_enabled. "
            "Useful for duplicate-prevention validation."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_manual_execution(args)

    FULL_AUTO_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at_utc = utc_now_iso()
    log(
        "[START] run_full_auto_execution_cycle "
        f"execute_live={args.execute_live} intent_override={args.intent_path is not None}"
    )

    effective_intent_path = args.intent_path.resolve() if args.intent_path is not None else materialize_and_build_official_intent().resolve()

    runner_snapshot_path = DEFAULT_RUNNER_SNAPSHOT_PATH
    if args.snapshot_path is not None:
        snapshot_payload = read_json(args.snapshot_path.resolve())
        write_json(runner_snapshot_path, snapshot_payload)
    else:
        refresh_runner_snapshot(args.account_config_path.resolve(), runner_snapshot_path)

    reconciliation, gate = refresh_reconciliation_and_gate(
        intent_path=effective_intent_path,
        snapshot_path=runner_snapshot_path,
        mode_config_path=args.mode_config_path.resolve(),
        live_order_policy_path=args.live_order_policy_path.resolve(),
    )

    preview_bundle = invoke_controlled_submitter(
        execute_live=False,
        manual_confirm="",
        intent_path=effective_intent_path,
        gate_path=DEFAULT_GATE_PATH,
        reconciliation_path=DEFAULT_RECON_PATH,
        snapshot_path=runner_snapshot_path,
        mode_config_path=args.mode_config_path.resolve(),
        live_order_policy_path=args.live_order_policy_path.resolve(),
        account_config_path=args.account_config_path.resolve(),
    )
    preview_decision = preview_bundle["decision"]

    signal_id = str(preview_decision.get("signal_id", "")).strip()
    target_asset = normalize_asset(preview_decision.get("target_asset"))
    runner_status = str(preview_decision.get("status", "")).strip() or "unknown"
    last_record = read_json_if_exists(LAST_EXECUTED_SIGNAL_RECORD_PATH)
    current_idempotency_key = build_idempotency_key(preview_decision)
    duplicate_prevented = should_skip_as_duplicate(last_record, current_idempotency_key)

    final_submit_bundle = preview_bundle
    final_submit_decision = preview_decision
    real_order_sent = False
    committed_record = False
    skip_reason_payload: dict[str, Any] | None = None

    if runner_status == "blocked":
        skip_reason_payload = write_skip_reason(
            reason="preview_blocked",
            runner_status="blocked",
            signal_id=signal_id,
            target_asset=target_asset,
            gate=gate,
            reconciliation=reconciliation,
        )
    elif runner_status == "no_action_needed":
        committed_record = True
        skip_reason_payload = write_skip_reason(
            reason="no_action_needed",
            runner_status="no_action_needed",
            signal_id=signal_id,
            target_asset=target_asset,
            gate=gate,
            reconciliation=reconciliation,
        )
    elif duplicate_prevented:
        runner_status = "duplicate_prevented"
        skip_reason_payload = write_skip_reason(
            reason="duplicate_submit_prevented_for_same_signal_and_plan",
            runner_status=runner_status,
            signal_id=signal_id,
            target_asset=target_asset,
            gate=gate,
            reconciliation=reconciliation,
        )
    elif args.execute_live:
        final_submit_bundle = invoke_controlled_submitter(
            execute_live=True,
            manual_confirm=args.manual_confirm,
            intent_path=effective_intent_path,
            gate_path=DEFAULT_GATE_PATH,
            reconciliation_path=DEFAULT_RECON_PATH,
            snapshot_path=None,
            mode_config_path=args.mode_config_path.resolve(),
            live_order_policy_path=args.live_order_policy_path.resolve(),
            account_config_path=args.account_config_path.resolve(),
        )
        final_submit_decision = final_submit_bundle["decision"]
        runner_status = str(final_submit_decision.get("status", "")).strip() or "unknown"
        real_order_sent = bool(final_submit_decision.get("real_order_sent", False))
        committed_record = True
    else:
        runner_status = str(preview_decision.get("status", "")).strip() or "ready_if_enabled"
        committed_record = bool(args.commit_idempotency_record)

    if skip_reason_payload is None:
        skip_reason_payload = {
            "artifact_type": "full_auto_skip_reason",
            "generated_at_utc": utc_now_iso(),
            "runner_status": runner_status,
            "skip_reason": None,
            "signal_id": signal_id,
            "target_asset": target_asset,
            "gate_status": gate.get("status"),
            "gate_block_reasons": gate.get("block_reasons", []),
            "reconciliation_action": reconciliation.get("reconciliation_action"),
            "current_state": reconciliation.get("current_state"),
        }
        write_json(SKIP_REASON_PATH, skip_reason_payload)

    if committed_record and runner_status != "duplicate_prevented":
        write_json(
            LAST_EXECUTED_SIGNAL_RECORD_PATH,
            build_signal_record(
                submit_decision=final_submit_decision,
                runner_status=runner_status,
                preview_only=not args.execute_live,
                real_order_sent=real_order_sent,
                duplicate_guard_active=True,
            ),
        )

    decision = {
        "artifact_type": "full_auto_execution_runner_decision",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at_utc,
        "execute_live": bool(args.execute_live),
        "signal_id": signal_id,
        "target_asset": target_asset,
        "status": runner_status,
        "runner_snapshot_path": str(runner_snapshot_path.resolve()),
        "effective_intent_path": str(effective_intent_path.resolve()),
        "gate_path": str(DEFAULT_GATE_PATH.resolve()),
        "reconciliation_path": str(DEFAULT_RECON_PATH.resolve()),
        "duplicate_prevented": duplicate_prevented,
        "idempotency_key": current_idempotency_key,
        "idempotency_record_written": committed_record and runner_status != "duplicate_prevented",
        "real_order_sent": real_order_sent,
        "preview_submit_status": preview_decision.get("status"),
        "final_submit_status": final_submit_decision.get("status"),
        "gate_status": gate.get("status"),
        "gate_block_reasons": gate.get("block_reasons", []),
        "reconciliation_action": reconciliation.get("reconciliation_action"),
        "reconciliation_current_state": reconciliation.get("current_state"),
        "reconciliation_open_orders_count": reconciliation.get("open_orders_count"),
        "preview_submit_decision": preview_decision,
        "final_submit_decision": final_submit_decision,
        "submit_artifact_paths": {
            "decision_path": str(controlled_submitter.DECISION_PATH.resolve()),
            "manifest_path": str(controlled_submitter.MANIFEST_PATH.resolve()),
            "request_payload_path": str(controlled_submitter.REQUEST_PAYLOAD_PATH.resolve()),
            "exchange_response_path": str(controlled_submitter.EXCHANGE_RESPONSE_PATH.resolve()),
            "leverage_response_path": str(controlled_submitter.LEVERAGE_RESPONSE_PATH.resolve()),
            "post_reconciliation_path": str(controlled_submitter.POST_RECON_PATH.resolve()),
        },
        "last_executed_signal_record_path": str(LAST_EXECUTED_SIGNAL_RECORD_PATH.resolve()),
        "skip_reason_path": str(SKIP_REASON_PATH.resolve()),
        "notes": [
            "This runner is one-shot only. It never loops.",
            "Duplicate prevention is keyed by signal_id plus the resolved submit plan fingerprint.",
            "Live submit still reuses the controlled submitter path and its one-shot safety discipline.",
        ],
    }

    manifest = {
        "artifact_type": "full_auto_execution_runner_manifest",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at_utc,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(args.mode_config_path.resolve()),
            str(args.live_order_policy_path.resolve()),
            str(args.account_config_path.resolve()),
            str(effective_intent_path.resolve()),
            str(runner_snapshot_path.resolve()),
            str(DEFAULT_RECON_PATH.resolve()),
            str(DEFAULT_GATE_PATH.resolve()),
        ],
        "output_paths": [
            str(RUNNER_DECISION_PATH.resolve()),
            str(RUNNER_MANIFEST_PATH.resolve()),
            str(LAST_EXECUTED_SIGNAL_RECORD_PATH.resolve()),
            str(SKIP_REASON_PATH.resolve()),
        ],
        "status": runner_status,
        "execute_live": bool(args.execute_live),
    }

    write_json(RUNNER_DECISION_PATH, decision)
    write_json(RUNNER_MANIFEST_PATH, manifest)

    log(f"[SAVED] {RUNNER_DECISION_PATH}")
    log(f"[SAVED] {RUNNER_MANIFEST_PATH}")
    if committed_record and runner_status != "duplicate_prevented":
        log(f"[SAVED] {LAST_EXECUTED_SIGNAL_RECORD_PATH}")
    if SKIP_REASON_PATH.exists():
        log(f"[SAVED] {SKIP_REASON_PATH}")
    log(f"[END] run_full_auto_execution_cycle status={runner_status}")


if __name__ == "__main__":
    main()
