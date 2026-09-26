"""Opt-in public /info reads only. No signing, keys, orders, or exchange writes."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.execution.production_execution import account_equity_and_available
ALLOWED_INFO = frozenset({"clearinghouseState", "spotClearinghouseState", "userFees", "userAbstraction", "meta"})


def info(kind: str, user: str | None = None):
    if kind not in ALLOWED_INFO:
        raise ValueError("Only specified read-only info requests are supported")
    body = {"type": kind}
    if user is not None:
        body["user"] = user
    request = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def sizing_expression():
    """Compile the real sizing expression, without importing a live submitter."""
    path = ROOT / "scripts/execution/production_execution.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    plan = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_execution_plan")
    assignment = next(n for n in ast.walk(plan) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "target_notional" for t in n.targets)
                      and isinstance(n.value, ast.IfExp))
    return compile(ast.Expression(assignment.value), str(path), "eval"), ast.unparse(assignment.value)


def sizing_audit(equity: float = 100.0) -> dict:
    expression, source = sizing_expression()
    values = {str(leverage): eval(expression, {"__builtins__": {}, "float": float}, {
        "equity": equity, "target_exposure": 1.25, "is_cash": lambda asset: asset == "CASH",
        "target_asset": "AVAX", "execution_leverage": leverage}) for leverage in (2, 10)}
    return {"source_expression": source, "synthetic_equity": equity, "strategy_exposure": 1.25,
            "target_notional_by_exchange_setting": values, "notional_invariant_given_fixed_equity": values["2"] == values["10"]}


def account_analysis(capture: dict) -> dict:
    if capture["account_abstraction"] != "unifiedAccount":
        raise ValueError("This captured-account analysis requires verified unifiedAccount mode")
    spot = float(capture["usdc_balance"]["total"])
    notional = sum(abs(float(p["positionValue"])) for p in capture["positions"])
    legacy_sum = spot + float(capture["perp_margin_summary"]["accountValue"])
    canonical_equity, _, equity_source = account_equity_and_available({"summary": {
        "account_abstraction": "unifiedAccount", "spot_stable_total_usd": spot,
        "spot_stable_available_usd": spot - float(capture["usdc_balance"].get("hold", 0)),
        "perp_account_value": float(capture["perp_margin_summary"]["accountValue"])}})
    policy = json.loads((ROOT / "execution/config/live_order_policy.json").read_text())
    return {"published_usdc_collateral_balance": spot, "position_notional": notional,
            "notional_over_unified_usdc_balance": notional / spot,
            "scope": "single observed USDC-collateral AVAX position; sequential read-only responses, not an atomic snapshot",
            "required_margin_at_10x": notional / 10, "required_margin_at_2x": notional / 2,
            "margin_fraction_at_target_1p25_and_2x": 1.25 / 2,
            "legacy_local_sizing_equity_sum": legacy_sum,
            "legacy_local_target_at_1p25": legacy_sum * 1.25,
            "unified_balance_target_at_1p25": spot * 1.25,
            "current_canonical_sizing_equity": canonical_equity, "current_equity_source": equity_source,
            "legacy_issue_scope": "Legacy manual recovery planner only; superseded by abstraction-aware production_execution.py; not a current canonical sizing defect",
            "repository_policy": {k: policy[k] for k in ["execution_leverage", "max_execution_leverage", "max_strategy_target_exposure", "margin_buffer_fraction"]},
            "margin_fraction_target_1p25_at_2x_with_buffer": 1.25 / 2 * (1 + policy["margin_buffer_fraction"]),
            "margin_fraction_policy_max_at_2x_with_buffer": policy["max_strategy_target_exposure"] / 2 * (1 + policy["margin_buffer_fraction"]),
            "avax_in_tracked_policy": "AVAX" in policy["allowed_assets"],
            "leverage_patch_prepared": False,
            "reason": "Current tracked policy already sets execution_leverage=2, while exchange AVAX remains 10. Deployed Pi policy and no-action leverage reconciliation require separate investigation; no speculative config patch."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-live", action="store_true")
    args = parser.parse_args()
    path = HERE / "exchange_readonly_capture.json"
    if args.capture_live:
        if path.exists():
            raise FileExistsError("Preserve the original exchange evidence")
        saved = json.loads((ROOT / "outputs/execution/read_only/hyperliquid_account_snapshot.json").read_text())
        user = saved["account_address"]
        capture = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                   "source": "https://api.hyperliquid.xyz/info", "account_address_saved": False}
        capture["account_abstraction"] = info("userAbstraction", user)
        state = info("clearinghouseState", user)
        capture["exchange_time_ms"] = state["time"]
        capture["perp_margin_summary"] = state["marginSummary"]
        capture["positions"] = [{k: row["position"][k] for k in ["coin", "szi", "leverage", "positionValue", "marginUsed", "maxLeverage", "liquidationPx"]} for row in state["assetPositions"]]
        spot = info("spotClearinghouseState", user)
        capture["usdc_balance"] = next(row for row in spot["balances"] if row["coin"] == "USDC")
        fees = info("userFees", user)
        capture["fees"] = {k: fees[k] for k in ["userCrossRate", "userAddRate", "activeReferralDiscount"]}
        meta = info("meta")
        capture["market_rules"] = [m for m in meta["universe"] if m["name"] in ["BTC", "AVAX", "ETH"]]
        path.write_text(json.dumps(capture, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    capture = json.loads(path.read_text())
    result = {"capture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "sizing": sizing_audit(), "account_analysis": account_analysis(capture),
              "production_leverage_changed": False, "network_on_replay": False}
    (HERE / "leverage_results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
