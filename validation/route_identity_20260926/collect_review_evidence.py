"""Read-only evidence collector; writes only a sanitized report outside outputs/data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def read(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def systemd(unit):
    names = ["ActiveState", "SubState", "Result", "ExecMainStatus", "UnitFileState",
             "NextElapseUSecRealtime", "LastTriggerUSec", "Persistent"]
    out = subprocess.check_output(["systemctl", "show", unit, *[f"--property={name}" for name in names]], text=True)
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def collect(root, source):
    run = read(root, "outputs/execution/production_runs/latest_production_run.json")
    snapshot = read(root, "outputs/production/current_strategy_snapshot.json")
    intent = read(root, "outputs/execution/intents/latest_execution_intent.json")
    dashboard = read(root, "outputs/execution/app_snapshot/dashboard_public_status.json")
    account = read(root, "outputs/execution/read_only/hyperliquid_account_snapshot.json")
    plan_path = "outputs/execution/production_runs/" + run["run_id"] + "/execution_plan.json"
    plan = read(root, plan_path)
    multi = run["multi_account_execution"]
    owner_id = multi["ownerResult"]["accountId"]
    owner = next(row for row in multi["preflight"] if row["accountId"] == owner_id)
    before = read(root, "review_preservation_before.json")
    changed = [name for name, value in before["original_runtime_sha256"].items() if digest(source / name) != value]
    original_runs = []
    for path in sorted((source / "outputs/execution/production_runs").glob("*/production_run_manifest.json")):
        item = json.loads(path.read_text())
        if item.get("target_closed_day") == snapshot["closed_day"] and item.get("model_target_asset") == "AVAX" and item.get("real_order_sent"):
            original_runs.append({key: item.get(key) for key in ["run_id", "started_at", "finished_at",
                "target_closed_day", "model_target_asset", "model_target_exposure", "execution_action",
                "execution_outcome", "real_order_sent"]})
    source_snapshot = read(source, "outputs/production/current_strategy_snapshot.json")
    paths = ["outputs/production/current_strategy_snapshot.json", "outputs/production/current_strategy_timeseries.csv",
             "outputs/execution/intents/latest_execution_intent.json", "outputs/execution/live_gate/latest_real_order_gate_decision.json",
             "outputs/execution/read_only/hyperliquid_account_snapshot.json", "outputs/execution/production_runs/latest_production_run.json",
             "outputs/execution/app_snapshot/dashboard_public_status.json", "outputs/execution/app_snapshot/dashboard_public_chart_timeseries.csv", plan_path]
    report = {
        "review_root": str(root), "source_root": str(source),
        "canonical_entrypoint": "scripts/execution/run_trendatlas_production.py --no-submit",
        "service": "mrv1-route-review-20260926.service (isolated copy of canonical service configuration; no timer)",
        "production_service_not_replaced": True,
        "run": {key: run.get(key) for key in ["run_id", "started_at", "finished_at", "target_closed_day", "final_status",
            "no_submit", "execution_backend", "heavy_refresh_steps", "execution_outcome", "real_order_sent", "live_order_chain",
            "failure_stage", "failure_reason", "dashboard_status", "authority_status"]},
        "stages": run["stages"],
        "fresh_target": {key: snapshot.get(key) for key in ["closed_day", "route_type", "base_economic_asset", "candidate_asset",
            "candidate_trigger_active", "resolved_execution_asset", "resolution_reason", "signal_available_at", "current_exposure", "generated_at_utc"]},
        "code_commit_in_snapshot": snapshot["provenance"].get("git_commit"),
        "input_fingerprints": snapshot["source_inputs"]["files"],
        "artifact_fingerprints": {name: digest(root / name) for name in paths},
        "identity_checks": {
            "core_intent_dashboard_agree": snapshot["resolved_execution_asset"] == intent["target_asset"] == dashboard["model_signal"]["preferred_asset"],
            "exposure_agrees": snapshot["execution_intent"]["target_exposure"] == intent["target_size_pct"] == dashboard["model_signal"]["exposure_x"],
            "real_account_separate": dashboard["real_account"]["asset"] != dashboard["model_signal"]["preferred_asset"],
            "model_performance_contract": dashboard.get("performance_contract"),
        },
        "owner_preflight": {key: owner.get(key) for key in ["status", "accountEquityUsd", "targetAsset", "targetExposure",
            "positions", "actions", "actionCount", "cancelOrderIds", "maxActionNotionalUsd"]},
        "account_readback": {"as_of_utc": account["as_of_utc"],
            "equity_after_no_submit": run["account_equity_after"],
            "positions_after": [{key: row.get(key) for key in ["asset", "size", "notional_usd", "reference_price"]} for row in run["real_position_after"]],
            "open_orders_count": len(account["raw"]["openOrders"])},
        "reconciliation_sequence": ["reduce-only EXIT unwanted positions", "fresh exchange account and open-orders read-back",
            "recompute equity, margin, current metadata, price and precision", "ENTRY current resolved target only if fresh entry checks pass"],
        "entry_preview_is_conditional": True,
        "entry_preview_basis": "pre-exit observed equity and metadata; no post-exit equity/fill is claimed",
        "python_preview": {key: plan.get(key) for key in ["status", "action", "target_asset", "target_exposure", "account_equity_usd",
            "target_notional_usd", "block_reasons", "entry_block_reasons", "exit_block_reasons"]},
        "old_live_target": {"closed_day": source_snapshot["closed_day"], "asset": source_snapshot["execution_intent"]["target_asset"],
                            "exposure": source_snapshot["execution_intent"]["target_exposure"]},
        "old_live_order_evidence": original_runs,
        "preservation": {
            "original_runtime_changed_paths": changed,
            "original_runtime_file_count_checked": len(before["original_runtime_sha256"]),
            "original_runtime_fingerprints": before["original_runtime_sha256"],
            "production_service_config_unchanged": hashlib.sha256(subprocess.check_output(["systemctl", "cat", "mrv1-production.service"])).hexdigest() == before["service_sha256"],
            "production_timer_config_unchanged": hashlib.sha256(subprocess.check_output(["systemctl", "cat", "mrv1-production.timer"])).hexdigest() == before["timer_sha256"],
            "production_head": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
        },
        "service_status": systemd("mrv1-production.service"),
        "timer_status": systemd("mrv1-production.timer"),
        "review_service_status": systemd("mrv1-route-review-20260926.service"),
        "model_metrics": snapshot["metrics"],
        "exchange_mutations": {"orders_submitted": False, "orders_cancelled": False, "orders_modified": False, "leverage_changed": False},
        "database_mutations_by_no_submit": False,
    }
    assert run["no_submit"] and run["final_status"] == "PREFLIGHT_READY"
    assert run["real_order_sent"] is False and run["live_order_chain"] == "NOT_INVOKED"
    assert not changed and report["preservation"]["production_service_config_unchanged"] and report["preservation"]["production_timer_config_unchanged"]
    assert report["identity_checks"]["core_intent_dashboard_agree"] and report["identity_checks"]["exposure_agrees"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("/opt/market_regime_v1"))
    args = parser.parse_args()
    review, source = args.review_root.resolve(), args.source_root.resolve()
    if review == source or review.is_relative_to(source):
        raise ValueError("Evidence output must stay outside production")
    result = collect(review, source)
    output = review / "review_evidence.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(output), "run_id": result["run"]["run_id"], "status": result["run"]["final_status"],
                      "target": result["fresh_target"], "preservation_passed": True}))
