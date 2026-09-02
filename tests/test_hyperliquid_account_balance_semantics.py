from __future__ import annotations

import math
import inspect
import unittest

from scripts.execution import materialize_execution_app_exports as materializer
from scripts.execution.hyperliquid_read_only_snapshot import summarize_balance_sources
from scripts.execution.hyperliquid_live_canary import summarize_snapshot as summarize_canary_snapshot


def clearinghouse_state(*, margin: float, notional: float, withdrawable: float) -> dict:
    return {
        "marginSummary": {
            "accountValue": str(max(margin + withdrawable, 0.0)),
            "totalMarginUsed": str(margin),
            "totalNtlPos": str(notional),
        },
        "crossMarginSummary": {
            "accountValue": str(max(margin + withdrawable, 0.0)),
            "totalMarginUsed": str(margin),
            "totalNtlPos": str(notional),
        },
        "crossMaintenanceMarginUsed": "0.24" if margin else "0",
        "withdrawable": str(withdrawable),
        "assetPositions": [],
    }


def unified_spot(*, total: float, hold: float | None) -> dict:
    balance = {"coin": "USDC", "token": 0, "total": str(total)}
    if hold is not None:
        balance["hold"] = str(hold)
    return {
        "balances": [balance],
        "tokenToAvailableAfterMaintenance": [[0, str(total - 0.24)]],
    }


def test_cash_account_may_have_equal_equity_and_free_collateral() -> None:
    summary = summarize_balance_sources(
        clearinghouse_state(margin=0.0, notional=0.0, withdrawable=0.0),
        unified_spot(total=40.0, hold=0.0),
        "unifiedAccount",
    )

    assert summary["account_equity_usd"] == 40.0
    assert summary["free_collateral_usd"] == 40.0
    assert summary["available_balance_usd"] == 40.0
    assert summary["margin_used_usd"] == 0.0
    assert summary["position_notional_usd"] == 0.0


def test_open_perp_uses_native_spot_hold_for_free_collateral() -> None:
    summary = summarize_balance_sources(
        clearinghouse_state(margin=9.639875, notional=19.27975, withdrawable=0.07778),
        unified_spot(total=39.622141, hold=9.639875),
        "unifiedAccount",
    )

    assert summary["account_equity_usd"] == 39.622141
    assert math.isclose(summary["free_collateral_usd"], 29.982266, abs_tol=1e-12)
    assert summary["available_balance_usd"] == summary["free_collateral_usd"]
    assert summary["free_collateral_usd"] < summary["account_equity_usd"]
    assert summary["margin_used_usd"] == 9.639875
    assert summary["position_notional_usd"] == 19.27975
    assert summary["free_collateral_source"].endswith("stable_total_minus_native_hold")


def test_unified_spot_total_never_implies_free_collateral_without_native_hold() -> None:
    summary = summarize_balance_sources(
        clearinghouse_state(margin=9.0, notional=18.0, withdrawable=1.0),
        unified_spot(total=40.0, hold=None),
        "unifiedAccount",
    )

    assert summary["account_equity_usd"] == 40.0
    assert summary["free_collateral_usd"] is None
    assert summary["available_balance_usd"] is None
    assert summary["free_collateral_status"] == "unavailable"


def test_withdrawable_is_native_only_for_the_current_abstraction() -> None:
    state = clearinghouse_state(margin=9.0, notional=18.0, withdrawable=1.0)
    spot = unified_spot(total=40.0, hold=9.0)

    standard = summarize_balance_sources(state, spot, "disabled")
    unified = summarize_balance_sources(state, spot, "unifiedAccount")

    assert standard["withdrawable_usd"] == 1.0
    assert standard["withdrawable_source"] == "clearinghouseState.withdrawable"
    assert unified["perp_withdrawable"] == 1.0
    assert unified["withdrawable_usd"] is None
    assert unified["withdrawable_status"] == "unavailable"


def test_manual_canary_reuses_the_canonical_balance_contract() -> None:
    snapshot = summarize_canary_snapshot(
        "0xabc",
        clearinghouse_state(margin=9.0, notional=18.0, withdrawable=1.0),
        unified_spot(total=40.0, hold=9.0),
        [],
        "unifiedAccount",
    )

    assert snapshot["account_equity_usd"] == 40.0
    assert snapshot["free_collateral_usd"] == 31.0
    assert snapshot["available_balance_usd"] == 31.0
    assert snapshot["withdrawable_usd"] is None


def test_public_and_pi_runtime_keep_additive_balance_fields_and_btc_position() -> None:
    snapshot = {
        "source": {"provider": "Hyperliquid"},
        "summary": {
            "account_equity_usd": 39.622141,
            "free_collateral_usd": 29.982266,
            "available_balance_usd": 29.982266,
            "withdrawable_usd": None,
            "margin_used_usd": 9.639875,
            "position_notional_usd": 19.27975,
            "balance_source_of_truth": "spot_stable_balance",
            "free_collateral_source": "spotClearinghouseState.stable_total_minus_native_hold",
            "withdrawable_source": "unavailable_individual_perp_state_not_meaningful",
            "positions_count": 1,
            "open_orders_count": 0,
        },
        "raw": {
            "clearinghouseState": {
                "assetPositions": [
                    {
                        "position": {
                            "coin": "BTC",
                            "szi": "0.00025",
                            "positionValue": "19.27975",
                        }
                    }
                ]
            }
        },
    }
    account = materializer.build_runtime_account_summary({}, snapshot)
    public = materializer.build_dashboard_public_status_contract(
        account_summary=account,
        intent_payload={"target_asset": "BTC", "target_size_pct": 0.5},
        dry_run_payload={},
        gate_payload={"status": "ready_if_enabled", "would_place_real_order": False},
        production_snapshot_payload={"closed_day": "2026-09-01"},
    )
    pi_view = materializer.build_runtime_public_status_views_from_dashboard_public_status(public)

    assert public["schema_version"] == 1
    assert public["real_account"]["asset"] == "BTC"
    assert public["real_account"]["free_collateral_usd"] == 29.982266
    assert public["real_account"]["available_balance_usd"] == 29.982266
    assert public["real_account"]["margin_used_usd"] == 9.639875
    assert public["real_account"]["position_notional_usd"] == 19.27975
    assert public["real_account"]["withdrawable_usd"] is None
    assert public["real_account"]["exposure_x"] == 0.48659
    assert pi_view["real_account_state"]["free_collateral_usd"] == 29.982266
    assert pi_view["real_account_state"]["position_notional_usd"] == 19.27975


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(function):
            suite.addTest(unittest.FunctionTestCase(function, description=name))
    return suite


if __name__ == "__main__":
    unittest.main()
