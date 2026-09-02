from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.execution.production_execution import (
    ExecutionJournal,
    build_execution_plan,
    deterministic_cloid,
    execute_plan_once,
    post_trade_alignment,
    recover_existing_execution,
    validate_canonical_provenance,
    validate_live_preflight,
)
from scripts.execution.hyperliquid_live_canary import order_request_to_wire
from scripts.execution.hyperliquid_read_only_snapshot import summarize_balance_sources


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
MID = {"BTC": 100_000.0, "ETH": 4_000.0}
PRECISION = {"BTC": 5, "ETH": 4}


def production(asset: str = "BTC", exposure: float = 0.5, *, stale: bool = False) -> dict:
    cash = asset == "CASH"
    return {
        "artifact_type": "current_strategy_snapshot",
        "closed_day": "2026-08-31",
        "strategy_version": "model_v1",
        "validation": {"status": "passed"},
        "execution_intent": {
            "signal_id": "sig-2026-08-31",
            "target_asset": asset,
            "target_exposure": exposure,
            "stale_signal": stale,
            "allow_live_order_candidate": not cash and not stale,
        },
    }


def intent(asset: str = "BTC", exposure: float = 0.5, *, stale: bool = False) -> dict:
    return {
        "as_of_source": "2026-08-31",
        "strategy_model": "model_v1",
        "signal_id": "sig-2026-08-31",
        "target_asset": asset,
        "target_size_pct": exposure,
        "stale_signal": stale,
        "allow_live_order_candidate": asset != "CASH" and not stale,
    }


def gate(asset: str = "BTC", *, ready: bool = True) -> dict:
    return {
        "signal_id": "sig-2026-08-31",
        "target_asset": asset,
        "status": "ready_if_enabled" if ready else "blocked",
        "would_place_real_order": ready,
        "real_orders_enabled": True,
        "production_signal_context": {"closed_day": "2026-08-31"},
    }


def account(
    equity: float = 20_000.0,
    *,
    asset: str | None = None,
    notional: float = 0.0,
    short: bool = False,
    age_seconds: int = 0,
    open_orders: list | None = None,
    abstraction: str = "unifiedAccount",
) -> dict:
    size = (notional / MID[asset]) if asset else 0.0
    if short:
        size *= -1
    positions = []
    if asset:
        positions.append({"position": {"coin": asset, "szi": str(size), "positionValue": str(abs(notional))}})
    timestamp = datetime.fromtimestamp(NOW.timestamp() - age_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "as_of_utc": timestamp,
        "account_address": "0xabc",
        "summary": {
            "account_abstraction": abstraction,
            "spot_stable_total_usd": equity,
            "spot_stable_available_usd": equity,
            "perp_account_value": equity if abstraction == "disabled" else 0,
            "perp_withdrawable": equity if abstraction == "disabled" else 0,
        },
        "raw": {
            "clearinghouseState": {"assetPositions": positions},
            "openOrders": list(open_orders or []),
        },
    }


def policy(**overrides) -> dict:
    base = {
        "allow_live_orders": True,
        "manual_approval_required": False,
        "require_kill_switch_off": True,
        "sizing_mode": "equity_target_exposure",
        "max_strategy_target_exposure": 2.0,
        "max_delta_fraction_of_equity": 2.0,
        "execution_leverage": 2,
        "max_execution_leverage": 3,
        "margin_buffer_fraction": 0.05,
        "reconciliation_tolerance_fraction_of_equity": 0.01,
        "post_trade_tolerance_fraction_of_equity": 0.02,
        "minimum_order_notional_usd": 10.0,
        "max_slippage_bps": 100,
        "account_snapshot_max_age_seconds": 180,
        "allowed_assets": ["BTC", "ETH", "CASH"],
    }
    base.update(overrides)
    return base


def make_plan(
    target_asset: str = "BTC",
    exposure: float = 0.5,
    snapshot: dict | None = None,
    **policy_overrides,
) -> dict:
    return build_execution_plan(
        production=production(target_asset, exposure),
        intent=intent(target_asset, exposure),
        gate=gate(target_asset),
        account_snapshot=snapshot or account(),
        policy=policy(**policy_overrides),
        mids=MID,
        size_decimals=PRECISION,
        now=NOW,
    )


def test_cash_to_btc_uses_dynamic_equity_sizing() -> None:
    for equity in [50.0, 20_000.0, 100_000.0]:
        plan = make_plan(snapshot=account(equity))
        assert plan["action"] == "INCREASE"
        assert plan["target_notional_usd"] == equity * 0.5
        assert plan["delta_notional_usd"] == equity * 0.5


def test_target_above_250_is_not_clipped() -> None:
    plan = make_plan(snapshot=account(100_000))
    assert plan["target_notional_usd"] == 50_000
    assert plan["delta_notional_usd"] == 50_000
    assert "max_order_notional_usd" not in plan
    assert plan["planned_quantity"] * MID["BTC"] == 50_000


def test_already_aligned_btc_is_no_action() -> None:
    assert make_plan(snapshot=account(asset="BTC", notional=10_000))["action"] == "NO_ACTION"


def test_partial_btc_increases_only_residual() -> None:
    plan = make_plan(snapshot=account(asset="BTC", notional=7_500))
    assert plan["action"] == "INCREASE"
    assert plan["delta_notional_usd"] == 2_500


def test_excessive_btc_reduces_only_residual() -> None:
    plan = make_plan(snapshot=account(asset="BTC", notional=13_000))
    assert plan["action"] == "REDUCE"
    assert plan["delta_notional_usd"] == -3_000
    assert plan["steps"][0]["reduce_only"] is True


def test_btc_to_cash_exits_without_entry() -> None:
    plan = make_plan("CASH", 0, account(asset="BTC", notional=10_000))
    assert plan["action"] == "EXIT"
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["reduce_only"] is True


def test_cash_target_with_cash_account_is_no_action() -> None:
    plan = make_plan("CASH", 0, account())
    assert plan["action"] == "NO_ACTION"
    assert plan["steps"] == []


def test_asset_rotation_closes_then_enters() -> None:
    plan = make_plan("ETH", 0.5, account(asset="BTC", notional=4_000))
    assert plan["action"] == "ROTATE"
    assert [(s["asset"], s["reduce_only"]) for s in plan["steps"]] == [("BTC", True), ("ETH", False)]


def test_short_position_is_controlled_rotation() -> None:
    plan = make_plan(snapshot=account(asset="BTC", notional=2_000, short=True))
    assert plan["action"] == "ROTATE"
    assert plan["steps"][0]["side"] == "BUY"
    assert plan["steps"][0]["reduce_only"] is True


def test_stale_strategy_blocks() -> None:
    plan = build_execution_plan(
        production=production(stale=True), intent=intent(stale=True), gate=gate(),
        account_snapshot=account(), policy=policy(), mids=MID, size_decimals=PRECISION, now=NOW,
    )
    assert "stale_strategy" in plan["block_reasons"]


def test_stale_account_blocks() -> None:
    assert "stale_account_snapshot" in make_plan(snapshot=account(age_seconds=181))["block_reasons"]


def test_production_intent_mismatch_blocks() -> None:
    for field, value, reason in [
        ("signal_id", "wrong", "production_intent_mismatch:signal_id"),
        ("target_asset", "ETH", "production_intent_mismatch:target_asset"),
        ("target_size_pct", 0.75, "production_intent_mismatch:target_exposure"),
    ]:
        bad_intent = intent()
        bad_intent[field] = value
        plan = build_execution_plan(
            production=production(), intent=bad_intent, gate=gate(), account_snapshot=account(),
            policy=policy(), mids=MID, size_decimals=PRECISION, now=NOW,
        )
        assert reason in plan["block_reasons"]


def test_intent_gate_mismatch_blocks() -> None:
    bad_gate = gate()
    bad_gate["signal_id"] = "wrong"
    plan = build_execution_plan(
        production=production(), intent=intent(), gate=bad_gate, account_snapshot=account(),
        policy=policy(), mids=MID, size_decimals=PRECISION, now=NOW,
    )
    assert "intent_gate_mismatch:signal_id" in plan["block_reasons"]


def test_disallowed_asset_blocks() -> None:
    plan = build_execution_plan(
        production=production("ETH"), intent=intent("ETH"), gate=gate("ETH"), account_snapshot=account(),
        policy=policy(allowed_assets=["BTC", "CASH"]), mids=MID, size_decimals=PRECISION, now=NOW,
    )
    assert "disallowed_asset" in plan["block_reasons"]


def test_invalid_quantity_blocks() -> None:
    plan = make_plan(snapshot=account(50), minimum_order_notional_usd=10, max_slippage_bps=100)
    assert plan["planned_quantity"] > 0
    broken = build_execution_plan(
        production=production(), intent=intent(), gate=gate(), account_snapshot=account(50),
        policy=policy(), mids={"BTC": 100_000_000_000.0, "ETH": 4_000.0},
        size_decimals={"BTC": 5, "ETH": 4}, now=NOW,
    )
    assert "invalid_quantity:BTC" in broken["block_reasons"]


def test_insufficient_margin_blocks_standard_account() -> None:
    snapshot = account(20_000, abstraction="disabled")
    snapshot["summary"]["perp_withdrawable"] = 100
    assert "insufficient_margin_or_available_balance" in make_plan(snapshot=snapshot)["block_reasons"]


def test_conflicting_open_order_blocks() -> None:
    assert "conflicting_open_order" in make_plan(snapshot=account(open_orders=[{"oid": 1}]))["block_reasons"]


def test_relative_safety_ceiling_blocks_without_clipping() -> None:
    plan = make_plan(exposure=1.5, max_strategy_target_exposure=1.0)
    assert plan["target_notional_usd"] == 30_000
    assert "target_exposure_exceeds_relative_safety_ceiling" in plan["block_reasons"]


def test_bad_provenance_hash_blocks(tmp_path: Path) -> None:
    paths = [tmp_path / name for name in ("production.json", "intent.json", "account.json")]
    for path in paths:
        path.write_text("{}\n", encoding="utf-8")
    reasons = validate_canonical_provenance(
        production_path=paths[0], intent_path=paths[1], account_path=paths[2],
        gate={"source_fingerprints": {"production_snapshot_sha256": "bad"}},
    )
    assert len(reasons) == 3


def test_data_health_kill_switch_and_blocked_gate_fail_preflight() -> None:
    plan = make_plan()
    reasons = validate_live_preflight(
        plan=plan, production=production(), intent=intent(), gate=gate(ready=False),
        mode={"mode": "live", "trading_enabled": True, "kill_switch": True},
        policy=policy(), data_health={"summary": {"execution_status": "blocked", "block_execution": True}},
        provenance_reasons=[],
    )
    assert "kill_switch_not_off" in reasons
    assert "data_health_blocks_execution" in reasons
    assert "real_order_gate_not_ready" in reasons


def test_cash_exit_is_not_blocked_by_market_entry_candidate_flag() -> None:
    snapshot = account(asset="BTC", notional=5_000)
    plan = make_plan("CASH", 0.0, snapshot=snapshot)
    reasons = validate_live_preflight(
        plan=plan,
        production=production("CASH", 0.0),
        intent=intent("CASH", 0.0),
        gate=gate("CASH"),
        mode={"mode": "live", "trading_enabled": True, "kill_switch": False},
        policy=policy(),
        data_health={"summary": {"execution_status": "ok", "block_execution": False}},
        provenance_reasons=[],
    )
    assert "strategy_disallows_live_candidate" not in reasons
    assert reasons == []


def test_post_trade_tolerance_accepts_precision_limited_residual() -> None:
    residual = make_plan(snapshot=account(39.48, asset="BTC", notional=19.0))
    aligned, tolerance, blockers = post_trade_alignment(residual, policy())
    assert abs(residual["delta_notional_usd"] - 0.74) < 1e-9
    assert tolerance == 39.48 * 0.02
    assert aligned is True
    assert blockers == []


def test_precision_limited_same_asset_residual_is_recurring_no_action() -> None:
    plan = make_plan(snapshot=account(39.465861, asset="BTC", notional=19.12275))
    assert 0 < plan["delta_notional_usd"] < policy()["minimum_order_notional_usd"]
    assert plan["delta_notional_usd"] <= (
        39.465861 * policy()["post_trade_tolerance_fraction_of_equity"]
    )
    assert plan["action"] == "NO_ACTION"
    assert plan["status"] == "NO_ACTION"
    assert plan["steps"] == []
    assert plan["block_reasons"] == []
    assert plan["reason"] == "precision_limited_residual_within_post_trade_tolerance"


def test_below_minimum_residual_outside_post_trade_tolerance_still_blocks() -> None:
    plan = make_plan(snapshot=account(100.0, asset="BTC", notional=41.0))
    assert plan["action"] == "INCREASE"
    assert plan["status"] == "BLOCKED"
    assert "order_below_exchange_minimum:BTC" in plan["block_reasons"]


def test_order_wire_contains_exact_deterministic_cloid() -> None:
    cloid = deterministic_cloid("exec_wire", 0)
    wire = order_request_to_wire(
        {
            "is_buy": True,
            "limit_px": 100_000.0,
            "sz": 0.00019,
            "reduce_only": False,
            "order_type": {"limit": {"tif": "Ioc"}},
            "cloid": cloid,
        },
        0,
    )
    assert wire["c"] == cloid


def test_spot_collateral_is_used_only_for_unified_account() -> None:
    clearinghouse = {
        "marginSummary": {"accountValue": "0"},
        "withdrawable": "0",
    }
    spot = {"balances": [{"coin": "USDC", "total": "39.48", "available": "39.48"}]}
    standard = summarize_balance_sources(clearinghouse, spot, "default")
    unified = summarize_balance_sources(clearinghouse, spot, "unifiedAccount")
    assert standard["account_equity_usd"] == 0.0
    assert standard["spot_balance_usable_for_perps"] is False
    assert unified["account_equity_usd"] == 39.48
    assert unified["spot_balance_usable_for_perps"] is True


class FakeAdapter:
    def __init__(self, *, query=None, response=None, crash=False):
        self.query = query or {"found": False, "status": "missing"}
        self.response = response or {"acknowledged": True, "submit_state": "filled", "oid": 123}
        self.crash = crash
        self.submits = []

    def query_order_by_cloid(self, cloid: str):
        return dict(self.query)

    def submit_ioc_order(self, step):
        self.submits.append(dict(step))
        if self.crash:
            raise TimeoutError("response lost")
        return dict(self.response)


def test_deterministic_cloid_is_128_bit_hex() -> None:
    cloid = deterministic_cloid("exec_abc", 0)
    assert cloid.startswith("0x") and len(cloid) == 34
    int(cloid[2:], 16)


def test_journal_is_durable_before_submit(tmp_path: Path) -> None:
    plan = make_plan()
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(plan, run_id="run-1")
    assert payload["state"] == "PREPARED"
    assert journal.path_for(plan["execution_id"]).exists()
    assert payload["steps"][0]["cloid"] == plan["steps"][0]["cloid"]


def test_duplicate_execution_id_never_submits_again(tmp_path: Path) -> None:
    plan = make_plan()
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(plan, run_id="run-1")
    journal.transition(payload, "FILLED_AND_ALIGNED")
    adapter = FakeAdapter()
    result = execute_plan_once(
        plan=plan, run_id="run-2", journal=journal, adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert result["status"] == "UNCERTAIN"
    assert adapter.submits == []


def test_process_death_before_submit_can_resume_once(tmp_path: Path) -> None:
    plan = make_plan()
    journal = ExecutionJournal(tmp_path)
    journal.prepare(plan, run_id="run-1")
    adapter = FakeAdapter()
    result = execute_plan_once(
        plan=plan, run_id="run-2", journal=journal, adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert result["status"] == "FILLED_AND_ALIGNED"
    assert len(adapter.submits) == 1


def test_process_death_after_exchange_acceptance_recovers_without_duplicate(tmp_path: Path) -> None:
    plan = make_plan()
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(plan, run_id="run-1")
    journal.transition(payload, "SUBMITTING")
    adapter = FakeAdapter(query={"found": True, "status": "filled"})
    recovered = execute_plan_once(
        plan=plan, run_id="run-2", journal=journal, adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert recovered["status"] == "UNCERTAIN"
    assert adapter.submits == []


def test_uncertain_exchange_response_is_not_retried(tmp_path: Path) -> None:
    plan = make_plan()
    adapter = FakeAdapter(crash=True)
    result = execute_plan_once(
        plan=plan, run_id="run-1", journal=ExecutionJournal(tmp_path), adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert result["status"] == "UNCERTAIN"
    assert len(adapter.submits) == 1
    adapter2 = FakeAdapter(query={"found": True, "status": "filled"})
    again = execute_plan_once(
        plan=plan, run_id="run-2", journal=ExecutionJournal(tmp_path), adapter=adapter2,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert again["status"] == "UNCERTAIN"
    assert adapter2.submits == []


def test_partial_fill_status_is_preserved_without_repeat(tmp_path: Path) -> None:
    for verification, expected in [
        ({"status": "FILLED_WITH_RESIDUAL"}, "FILLED_WITH_RESIDUAL"),
        ({"status": "PARTIAL"}, "PARTIAL"),
    ]:
        case_path = tmp_path / expected
        plan = make_plan()
        adapter = FakeAdapter()
        result = execute_plan_once(
            plan=plan, run_id="run-1", journal=ExecutionJournal(case_path), adapter=adapter,
            refresh_and_verify=lambda _p, _r, value=verification: value,
        )
        assert result["status"] == expected
        assert len(adapter.submits) == 1


def test_rejected_order_is_terminal_and_not_repeated(tmp_path: Path) -> None:
    plan = make_plan()
    adapter = FakeAdapter(response={"acknowledged": False, "submit_state": "error", "error": "margin"})
    result = execute_plan_once(
        plan=plan, run_id="run-1", journal=ExecutionJournal(tmp_path), adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "UNCERTAIN"},
    )
    assert result["status"] == "REJECTED"
    assert len(adapter.submits) == 1


def test_rotation_stops_if_exit_not_verified(tmp_path: Path) -> None:
    plan = make_plan("ETH", 0.5, account(asset="BTC", notional=4_000))
    adapter = FakeAdapter()
    result = execute_plan_once(
        plan=plan, run_id="run-1", journal=ExecutionJournal(tmp_path), adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "PARTIAL", "safe_for_next_step": False},
    )
    assert result["status"] == "PARTIAL"
    assert len(adapter.submits) == 1


def test_recovery_without_exchange_evidence_fails_closed(tmp_path: Path) -> None:
    plan = make_plan()
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(plan, run_id="run-1")
    payload = journal.transition(payload, "SUBMITTING")
    recovery = recover_existing_execution(payload, FakeAdapter())
    assert recovery["status"] == "UNCERTAIN"


def test_prior_same_signal_open_cloid_blocks_residual_submission(tmp_path: Path) -> None:
    first = make_plan(snapshot=account())
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(first, run_id="run-1")
    journal.transition(payload, "PARTIAL")
    residual = make_plan(snapshot=account(asset="BTC", notional=5_000))
    adapter = FakeAdapter(query={"found": True, "status": "open"})
    result = execute_plan_once(
        plan=residual, run_id="run-2", journal=journal, adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert result["status"] == "UNCERTAIN"
    assert adapter.submits == []


def test_terminal_prior_cloid_allows_objective_residual_reconciliation(tmp_path: Path) -> None:
    first = make_plan(snapshot=account())
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(first, run_id="run-1")
    journal.transition(payload, "FILLED_WITH_RESIDUAL")
    residual = make_plan(snapshot=account(asset="BTC", notional=5_000))
    adapter = FakeAdapter(query={"found": True, "status": "filled"})
    result = execute_plan_once(
        plan=residual, run_id="run-2", journal=journal, adapter=adapter,
        refresh_and_verify=lambda _p, _r: {"status": "FILLED_AND_ALIGNED"},
    )
    assert result["status"] == "FILLED_AND_ALIGNED"
    assert len(adapter.submits) == 1


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        parameters = inspect.signature(function).parameters
        if "tmp_path" in parameters:
            def run_with_temp(function=function):
                with tempfile.TemporaryDirectory() as directory:
                    function(Path(directory))

            suite.addTest(unittest.FunctionTestCase(run_with_temp, description=name))
        else:
            suite.addTest(unittest.FunctionTestCase(function, description=name))
    return suite


if __name__ == "__main__":
    unittest.main()
