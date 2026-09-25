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
MID = {"BTC": 100_000.0, "ETH": 4_000.0, "AVAX": 25.0, "NEWCOIN": 2.0}
PRECISION = {"BTC": 5, "ETH": 4, "AVAX": 2, "NEWCOIN": 1}


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
        "sizing_mode": "equity_target_exposure",
        "execution_leverage": 2,
        "margin_buffer_fraction": 0.05,
        "reconciliation_tolerance_fraction_of_equity": 0.01,
        "post_trade_tolerance_fraction_of_equity": 0.02,
        "minimum_order_notional_usd": 10.0,
        "max_slippage_bps": 100,
        "account_snapshot_max_age_seconds": 180,
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


def test_legacy_asset_membership_cannot_reject_supported_strategy_target() -> None:
    plan = build_execution_plan(
        production=production("ETH"), intent=intent("ETH"), gate=gate("ETH"), account_snapshot=account(),
        policy=policy(allowed_assets=["BTC", "CASH"]), mids=MID, size_decimals=PRECISION, now=NOW,
    )
    assert plan["status"] == "READY"
    assert plan["block_reasons"] == []


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


def test_conflicting_open_order_is_a_reconciliation_step() -> None:
    plan = make_plan(snapshot=account(open_orders=[{"oid": 1, "coin": "BTC"}]))
    assert plan["block_reasons"] == []
    assert plan["cancel_orders"][0]["oid"] == 1


def test_executor_cannot_override_validated_strategy_exposure() -> None:
    plan = make_plan(exposure=1.5, max_strategy_target_exposure=1.0)
    assert plan["target_notional_usd"] == 30_000
    assert plan["status"] == "READY"


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
    assert result["status"] == "FILLED_AND_ALIGNED"
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
    assert recovered["status"] == "FILLED_AND_ALIGNED"
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
    assert again["status"] == "FILLED_AND_ALIGNED"
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
    payload = journal.transition(payload, "SUBMITTING", active_step_index=0)
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



class StatefulExchange:
    """Exchange fixture with actual account changes, read-backs and CLOID lookup."""
    def __init__(self, snapshot, target="AVAX", exposure=1.25, *, mids=None, precision=None, fail_entry=False, available_after_exit=None):
        import copy
        self.snapshot = copy.deepcopy(snapshot)
        self.target, self.exposure = target, exposure
        self.mids = dict(MID if mids is None else mids)
        self.precision = dict(PRECISION if precision is None else precision)
        self.fail_entry = fail_entry
        self.available_after_exit = available_after_exit
        self.submits, self.cancelled, self.queries, self.readbacks = [], [], [], []
        self.orders = {}

    def plan(self):
        return build_execution_plan(production=production(self.target, self.exposure), intent=intent(self.target, self.exposure), gate=gate(self.target), account_snapshot=self.snapshot, policy=policy(), mids=self.mids, size_decimals=self.precision, now=NOW)

    def submit_ioc_order(self, step):
        self.submits.append(dict(step))
        if self.fail_entry and not step["reduce_only"]:
            response = {"acknowledged": False, "submit_state": "error", "error": "entry_rejected"}
            self.orders[step["cloid"]] = {"found": True, "status": "rejected"}
            return response
        positions = self.snapshot["raw"]["clearinghouseState"]["assetPositions"]
        existing = next((p for p in positions if p["position"]["coin"] == step["asset"]), None)
        size = float(existing["position"]["szi"]) if existing else 0
        delta = step["quantity"] * (1 if step["side"] == "BUY" else -1)
        new_size = 0 if step.get("full_close") else size + delta
        positions[:] = [p for p in positions if p["position"]["coin"] != step["asset"]]
        if abs(new_size) > 1e-12:
            positions.append({"position": {"coin": step["asset"], "szi": str(new_size), "positionValue": str(abs(new_size) * self.mids[step["asset"]])}})
        if step["reduce_only"] and self.available_after_exit is not None:
            self.snapshot["summary"]["spot_stable_available_usd"] = self.available_after_exit
        self.orders[step["cloid"]] = {"found": True, "status": "filled"}
        return {"acknowledged": True, "submit_state": "filled", "oid": len(self.submits)}

    def query_order_by_cloid(self, cloid):
        self.queries.append(cloid)
        return self.orders.get(cloid, {"found": False, "status": "missing"})

    def cancel_order(self, order):
        self.cancelled.append(order["oid"])
        self.snapshot["raw"]["openOrders"] = [row for row in self.snapshot["raw"]["openOrders"] if row["oid"] != order["oid"]]
        return {"acknowledged": True}

    def verify(self, original, results):
        residual = self.plan()
        positions = residual["current_positions"]
        self.readbacks.append([p["asset"] for p in positions])
        last = results[-1]["step"] if results else None
        last_closed = not last or not last.get("full_close") or not any(p["asset"] == last["asset"] for p in positions)
        aligned, _, _ = post_trade_alignment(residual, policy())
        return {"status": "FILLED_AND_ALIGNED" if aligned else "FILLED_WITH_RESIDUAL", "safe_for_next_step": last_closed and not self.snapshot["raw"]["openOrders"], "positions": positions, "open_orders": self.snapshot["raw"]["openOrders"], "residual_plan": residual}

    def run(self, path, plan=None):
        return execute_plan_once(plan=plan or self.plan(), run_id="fixture", journal=ExecutionJournal(path), adapter=self, refresh_and_verify=self.verify)


def test_incident_btc_point49_to_avax_125(tmp_path: Path) -> None:
    exchange = StatefulExchange(account(1000, asset="BTC", notional=490))
    result = exchange.run(tmp_path)
    assert result["status"] == "FILLED_AND_ALIGNED"
    assert [(s["asset"], s["side"], s["reduce_only"]) for s in exchange.submits] == [("BTC", "SELL", True), ("AVAX", "BUY", False)]
    assert exchange.readbacks[0] == []
    assert exchange.plan()["current_notional_usd"] == 1250


def test_every_metadata_asset_can_rotate_to_every_supported_target(tmp_path: Path) -> None:
    # Iteration is driven by the fixture's metadata, with no executor asset list.
    for current in MID:
        for target in MID:
            exchange = StatefulExchange(account(1000, asset=current, notional=490), target=target)
            result = exchange.run(tmp_path / current / target)
            assert result["status"] == "FILLED_AND_ALIGNED", (current, target, result)
            assert exchange.plan()["current_asset"] == target


def test_cash_to_avax_and_avax_to_btc(tmp_path: Path) -> None:
    for name, snapshot, target in [("entry", account(1000), "AVAX"), ("rotation", account(1000, asset="AVAX", notional=490), "BTC")]:
        exchange = StatefulExchange(snapshot, target=target)
        assert exchange.run(tmp_path / name)["status"] == "FILLED_AND_ALIGNED"
        assert exchange.plan()["current_asset"] == target


def test_cash_closes_all_long_and_short_positions(tmp_path: Path) -> None:
    snapshot = account(1000, asset="BTC", notional=490)
    snapshot["raw"]["clearinghouseState"]["assetPositions"] += account(1000, asset="AVAX", notional=200, short=True)["raw"]["clearinghouseState"]["assetPositions"]
    exchange = StatefulExchange(snapshot, target="CASH", exposure=0)
    result = exchange.run(tmp_path)
    assert result["status"] == "FILLED_AND_ALIGNED"
    assert len(exchange.submits) == 2
    assert all(s["reduce_only"] for s in exchange.submits)
    assert exchange.submits[0]["asset"] == "AVAX" and exchange.submits[0]["side"] == "BUY"
    assert exchange.plan()["current_positions"] == []


def test_multiple_positions_are_closed_before_target_entry(tmp_path: Path) -> None:
    snapshot = account(1000, asset="BTC", notional=490)
    snapshot["raw"]["clearinghouseState"]["assetPositions"] += account(1000, asset="ETH", notional=200)["raw"]["clearinghouseState"]["assetPositions"]
    exchange = StatefulExchange(snapshot)
    assert exchange.run(tmp_path)["status"] == "FILLED_AND_ALIGNED"
    assert [s["reduce_only"] for s in exchange.submits] == [True, True, False]
    assert exchange.readbacks[1] == []


def test_unsupported_entry_still_exits_and_stays_cash(tmp_path: Path) -> None:
    exchange = StatefulExchange(account(1000, asset="BTC", notional=490), target="UNLISTED")
    assert exchange.plan()["status"] == "READY"
    result = exchange.run(tmp_path)
    assert result["status"] == "EXITED_ENTRY_FAILED_STAYING_CASH"
    assert result["staying_cash"] is True
    assert [s["asset"] for s in exchange.submits] == ["BTC"]
    assert exchange.plan()["current_positions"] == []


def test_margin_is_rechecked_after_exit_and_never_blocks_exit(tmp_path: Path) -> None:
    for available, expected in [(0, "EXITED_ENTRY_FAILED_STAYING_CASH"), (1000, "FILLED_AND_ALIGNED")]:
        snapshot = account(1000, asset="BTC", notional=490)
        snapshot["summary"]["spot_stable_available_usd"] = 0
        exchange = StatefulExchange(snapshot, available_after_exit=available)
        assert exchange.plan()["status"] == "READY"
        result = exchange.run(tmp_path / str(available))
        assert result["status"] == expected
        assert exchange.submits[0]["reduce_only"] is True


def test_entry_precision_and_minimum_do_not_block_exit(tmp_path: Path) -> None:
    missing_precision = StatefulExchange(account(1000, asset="BTC", notional=490), precision={"BTC": 5})
    minimum = StatefulExchange(account(5, asset="BTC", notional=2.45))
    for name, exchange in [("precision", missing_precision), ("minimum", minimum)]:
        result = exchange.run(tmp_path / name)
        assert result["status"] == "EXITED_ENTRY_FAILED_STAYING_CASH"
        assert len(exchange.submits) == 1 and exchange.submits[0]["reduce_only"]


def test_rejected_entry_after_exit_never_reopens_old_asset(tmp_path: Path) -> None:
    exchange = StatefulExchange(account(1000, asset="BTC", notional=490), fail_entry=True)
    result = exchange.run(tmp_path)
    assert result["status"] == "EXITED_ENTRY_FAILED_STAYING_CASH"
    assert exchange.plan()["current_positions"] == []
    assert [s["asset"] for s in exchange.submits] == ["BTC", "AVAX"]


def test_power_loss_after_exit_resumes_only_missing_entry(tmp_path: Path) -> None:
    exchange = StatefulExchange(account(1000, asset="BTC", notional=490))
    original = exchange.plan()
    def power_loss(plan, results):
        raise RuntimeError("simulated process termination after exchange fill")
    try:
        execute_plan_once(plan=original, run_id="before", journal=ExecutionJournal(tmp_path), adapter=exchange, refresh_and_verify=power_loss)
    except RuntimeError:
        pass
    assert [s["asset"] for s in exchange.submits] == ["BTC"]
    result = exchange.run(tmp_path, original)
    assert result["status"] == "FILLED_AND_ALIGNED"
    assert [s["asset"] for s in exchange.submits] == ["BTC", "AVAX"]
    assert exchange.queries == [original["steps"][0]["cloid"]]


def test_repeated_filled_signal_does_not_duplicate_order(tmp_path: Path) -> None:
    exchange = StatefulExchange(account(1000, asset="BTC", notional=490))
    original = exchange.plan()
    assert exchange.run(tmp_path, original)["status"] == "FILLED_AND_ALIGNED"
    count = len(exchange.submits)
    assert exchange.run(tmp_path, original)["status"] == "FILLED_AND_ALIGNED"
    assert len(exchange.submits) == count


def test_owned_conflicting_order_is_cancelled_and_freshly_reconciled(tmp_path: Path) -> None:
    snapshot = account(1000, open_orders=[{"oid": 9, "coin": "AVAX", "managed_by_execution": True}])
    exchange = StatefulExchange(snapshot)
    assert exchange.run(tmp_path)["status"] == "FILLED_AND_ALIGNED"
    assert exchange.cancelled == [9]
    assert exchange.snapshot["raw"]["openOrders"] == []
    assert exchange.readbacks[0] == []


def test_unknown_order_ownership_is_not_cancelled_blindly(tmp_path: Path) -> None:
    exchange = StatefulExchange(account(1000, open_orders=[{"oid": 9, "coin": "AVAX"}]))
    assert exchange.run(tmp_path)["status"] == "BLOCKED"
    assert exchange.cancelled == [] and exchange.submits == []


def test_dynamic_metadata_loader_uses_coherent_meta_and_contexts() -> None:
    from unittest.mock import patch
    from scripts.execution import submit_controlled_real_order as submit
    metadata = {"universe": [{"name": "NEWMARKET", "szDecimals": 3}]}
    with patch.object(submit, "fetch_meta_and_asset_contexts", return_value=(metadata, [{"midPx": "3.5"}])):
        mids, precision = submit.load_live_market_context()
    assert mids == {"NEWMARKET": 3.5} and precision == {"NEWMARKET": 3}


def test_standalone_live_submit_is_disabled() -> None:
    from argparse import Namespace
    from unittest.mock import patch
    from scripts.execution import submit_controlled_real_order as submit
    with patch.object(submit, "fail", side_effect=RuntimeError("disabled")):
        try:
            submit.ensure_manual_execution(Namespace(execute_live=True, manual_confirm="CONTROLLED_REAL_ORDER"))
        except RuntimeError as exc:
            assert str(exc) == "disabled"
        else:
            raise AssertionError("standalone live helper must be disabled")


def test_account_identity_is_bound_into_cloid() -> None:
    first = account()
    second = account()
    second["account_address"] = "0xdef"
    assert make_plan(snapshot=first)["steps"][0]["cloid"] != make_plan(snapshot=second)["steps"][0]["cloid"]


def test_missing_entry_collateral_still_allows_reduce_only_exit(tmp_path: Path) -> None:
    snapshot = account(1000, asset="BTC", notional=490)
    snapshot["summary"]["spot_stable_available_usd"] = None
    exchange = StatefulExchange(snapshot)
    assert exchange.plan()["status"] == "READY"
    result = exchange.run(tmp_path)
    assert result["status"] == "EXITED_ENTRY_FAILED_STAYING_CASH"
    assert len(exchange.submits) == 1 and exchange.submits[0]["reduce_only"]


def test_prior_filled_exit_does_not_hide_unknown_entry_cloid(tmp_path: Path) -> None:
    first = make_plan("AVAX", 1.25, account(1000, asset="BTC", notional=490))
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(first, run_id="before")
    rows = payload["steps"]
    rows[0]["state"] = "VERIFIED"
    rows[1]["state"] = "SUBMITTING"
    journal.transition(payload, "UNCERTAIN", active_step_index=1, steps=rows)
    residual = make_plan("AVAX", 1.25, account(1000))
    class AmbiguousAdapter(FakeAdapter):
        def query_order_by_cloid(self, cloid):
            return {"found": True, "status": "filled"} if cloid == first["steps"][0]["cloid"] else {"found": False, "status": "unknown"}
    adapter = AmbiguousAdapter()
    result = execute_plan_once(plan=residual, run_id="after", journal=journal, adapter=adapter, refresh_and_verify=lambda p, r: {"positions": [], "status": "FILLED_WITH_RESIDUAL"})
    assert result["status"] == "UNCERTAIN" and adapter.submits == []


def test_active_python_execution_has_no_static_trading_membership_or_duplicate_gates() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = ("allowed_assets", "allowed_approval_gate_statuses", "allow_live_orders", "require_kill_switch_off", "max_live_order_attempts_per_run", "target_asset_not_allowlisted", "disallowed_asset")
    for relative in ("execution/config/live_order_policy.json", "scripts/execution/prepare_real_order_gate.py", "scripts/execution/production_execution.py", "scripts/execution/submit_controlled_real_order.py", "scripts/execution/hyperliquid_live_canary.py", "scripts/execution/preview_live_order_enable_package.py", "scripts/execution/app_execute_bridge.py", "scripts/execution/reconcile_live_execution_state.py", "scripts/execution/run_dry_execution_bridge.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden), relative


def test_unresolved_prior_day_other_asset_blocks_new_signal_until_cloid_resolved(tmp_path: Path) -> None:
    old = make_plan("BTC", .5, account(1000))
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(old, run_id="prior-day")
    journal.transition(payload, "SUBMITTING", active_step_index=0)
    new_production = production("AVAX", 1.25)
    new_intent = intent("AVAX", 1.25)
    new_gate = gate("AVAX")
    new_production["execution_intent"]["signal_id"] = "next-day-signal"
    new_intent["signal_id"] = new_gate["signal_id"] = "next-day-signal"
    current = build_execution_plan(production=new_production, intent=new_intent, gate=new_gate, account_snapshot=account(1000), policy=policy(), mids=MID, size_decimals=PRECISION, now=NOW)
    adapter = FakeAdapter()
    result = execute_plan_once(plan=current, run_id="new-day", journal=journal, adapter=adapter, refresh_and_verify=lambda p, r: {"status": "FILLED_WITH_RESIDUAL", "positions": []})
    assert result["status"] == "UNCERTAIN" and adapter.submits == []
    # Once the prior request is definitively rejected, an untouched current
    # journal must remain recoverable, instead of inventing another unknown order.
    adapter.query = {"found": True, "status": "rejected"}
    resumed = execute_plan_once(plan=current, run_id="resolved", journal=journal, adapter=adapter, refresh_and_verify=lambda p, r: {"status": "FILLED_AND_ALIGNED", "positions": []})
    assert resumed["status"] == "FILLED_AND_ALIGNED" and len(adapter.submits) == 1


def test_malformed_submit_response_remains_uncertain_not_safe_to_retry(tmp_path: Path) -> None:
    adapter = FakeAdapter(response={"acknowledged": False, "submit_state": "manual_review_required", "normalization_ok": False})
    plan = make_plan()
    result = execute_plan_once(plan=plan, run_id="malformed", journal=ExecutionJournal(tmp_path), adapter=adapter, refresh_and_verify=lambda p, r: {"status": "FILLED_WITH_RESIDUAL", "positions": []})
    assert result["status"] == "UNCERTAIN"
    assert result["journal"]["steps"][0]["state"] == "SUBMITTING"
    again = execute_plan_once(plan=plan, run_id="retry", journal=ExecutionJournal(tmp_path), adapter=adapter, refresh_and_verify=lambda p, r: {"status": "FILLED_WITH_RESIDUAL", "positions": []})
    assert again["status"] == "UNCERTAIN" and len(adapter.submits) == 1


def test_open_order_ownership_can_be_proved_by_durable_exchange_oid(tmp_path: Path) -> None:
    old = make_plan("AVAX", 1.25, account(1000))
    journal = ExecutionJournal(tmp_path)
    payload = journal.prepare(old, run_id="owned")
    rows = payload["steps"]
    rows[0].update({"state": "ACKNOWLEDGED", "response": {"oid": 9}})
    # Definitive old journal retained the exchange OID; openOrders need not
    # expose a CLOID for ownership to be recoverable.
    journal.transition(payload, "FILLED_WITH_RESIDUAL", steps=rows)
    exchange = StatefulExchange(account(1000, open_orders=[{"oid": 9, "coin": "AVAX"}]))
    exchange.orders[old["steps"][0]["cloid"]] = {"found": True, "status": "filled"}
    result = exchange.run(tmp_path)
    assert result["status"] == "FILLED_WITH_RESIDUAL" or result["status"] == "FILLED_AND_ALIGNED"
    assert exchange.cancelled == [9]


def test_read_only_account_query_never_depends_on_obsolete_runtime_modes() -> None:
    from scripts.execution.hyperliquid_read_only_snapshot import validate_runtime_posture
    for config in ({}, {"mode": "read_only", "trading_enabled": True, "kill_switch": False}, {"mode": "obsolete", "dry_run_enabled": False}, {"mode": "live", "trading_enabled": True, "kill_switch": True}):
        posture = validate_runtime_posture(config)
        assert posture["runtime_posture"] == "read_only_observability"
        assert posture["exchange_writes_allowed"] is False


def test_only_explicit_valid_empty_exchange_positions_mean_cash() -> None:
    from scripts.execution.production_execution import ExecutionSafetyError, extract_positions
    assert extract_positions(account(), MID) == []
    malformed = [
        {}, {"raw": None}, {"raw": {}}, {"raw": {"clearinghouseState": None}},
        {"raw": {"clearinghouseState": {}}},
        {"raw": {"clearinghouseState": {"assetPositions": None}}},
        {"raw": {"clearinghouseState": {"assetPositions": {}}}},
    ]
    for snapshot in malformed:
        try:
            extract_positions(snapshot, MID)
        except ExecutionSafetyError:
            pass
        else:
            raise AssertionError(f"Malformed exchange observation was treated as CASH: {snapshot}")


def test_invalid_position_rows_never_disappear_from_account_state() -> None:
    from scripts.execution.production_execution import ExecutionSafetyError, extract_positions
    rows = [None, {}, {"position": None}, {"coin": "BTC", "szi": "1"},
        {"position": {"szi": "0"}}, {"position": {"coin": None, "szi": "0"}},
        {"position": {"coin": 123, "szi": "0"}}, {"position": {"coin": "BTC USD", "szi": "0"}},
        {"position": {"coin": "CASH", "szi": "0"}},
        {"position": {"coin": "BTC"}}, {"position": {"coin": "BTC", "size": "0"}},
        {"position": {"coin": "BTC", "szi": None}},
        {"position": {"coin": "BTC", "szi": "nan"}},
        {"position": {"coin": "BTC", "szi": "infinity"}},
        {"position": {"coin": "BTC", "szi": "unknown"}}]
    for row in rows:
        snapshot = account()
        snapshot["raw"]["clearinghouseState"]["assetPositions"] = [row]
        try:
            extract_positions(snapshot, MID)
        except ExecutionSafetyError:
            pass
        else:
            raise AssertionError(f"Malformed position was silently discarded: {row}")


def test_known_zero_position_is_ignored_but_real_dust_position_remains() -> None:
    from scripts.execution.production_execution import extract_positions
    snapshot = account()
    snapshot["raw"]["clearinghouseState"]["assetPositions"] = [
        {"position": {"coin": "BTC", "szi": "0"}},
        {"position": {"coin": "AVAX", "szi": "0.0000000000001", "positionValue": "0.0000000000025"}},
    ]
    positions = extract_positions(snapshot, MID)
    assert len(positions) == 1 and positions[0]["asset"] == "AVAX"
    assert positions[0]["size"] > 0


def test_malformed_account_blocks_order_planning_instead_of_entering_as_cash() -> None:
    from scripts.execution.production_execution import ExecutionSafetyError
    snapshot = account(1000)
    del snapshot["raw"]["clearinghouseState"]["assetPositions"]
    try:
        make_plan("AVAX", 1.25, snapshot)
    except ExecutionSafetyError as exc:
        assert "account_positions_missing_or_invalid" in exc.reasons
    else:
        raise AssertionError("Missing exchange positions must never create an ENTRY plan")

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
