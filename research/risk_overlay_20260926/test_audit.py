"""Detection regressions; passing tests do not mean production defects are fixed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_audit as audit
import leverage_audit as leverage
sys.path.insert(0, str(audit.ROOT / "scripts"))
from scripts.dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity import build_cooldown_state_machine
from scripts.execution.production_execution import build_execution_plan


def current_plan(old="BTC", target="AVAX", exchange_setting=2, open_orders=None, exposure=1.25):
    """Pure synthetic inputs; no policy file mutations or exchange adapter."""
    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    exp = 0.0 if target == "CASH" else exposure
    signal = {"signal_id": "synthetic", "target_asset": target, "target_exposure": exp,
              "stale_signal": False, "allow_live_order_candidate": target != "CASH"}
    production = {"closed_day": "2026-09-25", "strategy_version": "synthetic", "execution_intent": signal,
                  "validation": {"status": "passed"}}
    intent = {"signal_id": "synthetic", "target_asset": target, "target_size_pct": exp,
              "as_of_source": "2026-09-25", "strategy_model": "synthetic", "allow_live_order_candidate": target != "CASH"}
    policy = json.loads((audit.ROOT / "execution/config/live_order_policy.json").read_text())
    # Simulated supported markets, not a new live allowlist.
    policy.update(allowed_assets=["BTC", "AVAX", "ETH", "CASH"], execution_leverage=exchange_setting, max_execution_leverage=10)
    snapshot = {"as_of_utc": now.isoformat(), "summary": {"account_abstraction": "unifiedAccount",
                "spot_stable_total_usd": 1000, "spot_stable_available_usd": 1000,
                "perp_account_value": 200}, "raw": {"openOrders": open_orders or [],
                "clearinghouseState": {"assetPositions": [{"position": {"coin": old, "szi": "12.5", "positionValue": "1250", "leverage": {"type": "cross", "value": 10}}}]}}}
    return build_execution_plan(production=production, intent=intent,
        gate={"signal_id": "synthetic", "target_asset": target, "production_signal_context": {"closed_day": "2026-09-25"}},
        account_snapshot=snapshot, policy=policy, mids={"BTC": 100, "AVAX": 100, "ETH": 100},
        size_decimals={"BTC": 5, "AVAX": 2, "ETH": 4}, now=now)


class AuditTests(unittest.TestCase):
    def test_reproduction_rejects_return_change(self):
        a = pd.DataFrame({"date": ["2024-01-01"], "return": [0.1]})
        b = a.copy()
        b.loc[0, "return"] = 0.11
        self.assertFalse(audit.compare_frames(a, b)["passed"])

    def test_reproduction_rejects_missing_column(self):
        self.assertFalse(audit.compare_frames(pd.DataFrame({"a": [1], "b": [2]}), pd.DataFrame({"a": [1]}))["passed"])

    def test_reproduction_rejects_date_reordering(self):
        a = pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "ret": [0, 0]})
        self.assertFalse(audit.compare_frames(a, a.iloc[::-1])["passed"])

    def test_reproduction_rejects_nan_to_zero(self):
        self.assertFalse(audit.compare_frames(pd.DataFrame({"a": [float("nan")]}), pd.DataFrame({"a": [0.0]}))["passed"])

    def test_reproduction_accepts_csv_rounding(self):
        self.assertTrue(audit.compare_frames(pd.DataFrame({"a": [0.1]}), pd.DataFrame({"a": [0.1 + 1e-13]}))["passed"])

    def test_bad_baseline_never_claims_overlay_results(self):
        v = audit.scientific_verdict({"passed": False}, True, True, True)
        self.assertEqual(v["variants_executed"], 0)
        self.assertIsNone(v["holdout"])
        self.assertIn("canonical_reproduction_mismatch", v["issues"])

    def test_matching_exports_do_not_override_causality_failure(self):
        v = audit.scientific_verdict({"passed": True}, True, False, True)
        self.assertEqual(v["research_status"], "STOPPED_AT_BASELINE_PREREQUISITES")

    def test_missing_venue_data_cannot_be_treated_as_zero_cost(self):
        v = audit.scientific_verdict({"passed": True}, True, True, False)
        self.assertIn("hyperliquid_mark_and_hourly_funding_history_missing", v["issues"])

    def test_bundle_bytes_are_hash_verified(self):
        manifest = json.loads((audit.HERE / "local_input_manifest.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.zip"
            bad.write_bytes((audit.HERE / "local_frozen_inputs.zip").read_bytes() + b"corruption")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                audit.verify_bundle(bad, manifest, Path(tmp) / "inputs")

    def test_frozen_baseline_counterexamples(self):
        manifest = json.loads((audit.HERE / "local_input_manifest.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit.verify_bundle(audit.HERE / "local_frozen_inputs.zip", manifest, root)
            f = pd.read_csv(root / "outputs/production/current_strategy_timeseries.csv")
            row = audit.asset_identity(f[f.date.eq("2024-12-03")], root).iloc[0]
            self.assertEqual(row.model_asset, "DOGE")
            self.assertAlmostEqual(row.same_day_asset_return, -0.042984666839390395)
            self.assertGreater(row.residual, 1.0)
            trx = audit.close_returns(root / "data/ohlcv/TRXUSDT_1d.csv").loc[row.date]
            self.assertAlmostEqual(trx, row.canonical_gross_return, places=10)

    def test_production_state_machine_exhibits_same_day_censoring(self):
        """Characterize existing defect; do not silently repair production."""
        frame = pd.DataFrame({
            "baseline_cash": [True, True], "hard_invalidation_on": [False, False],
            "btc_price_filter_pass": [True, True], "flow_2_of_last_3_positive_flag": [True, True],
            "permission_on": [True, True], "portfolio_held_asset": ["CASH", "CASH"],
            "effective_leverage": [0.0, 0.0], "realistic_ret_gross": [0.0, 0.0],
            "btc_return": [0.02, -0.06]}, index=pd.date_range("2025-01-01", periods=2))
        kept, _ = build_cooldown_state_machine(frame, 15)
        changed = frame.copy()
        changed.iloc[1, changed.columns.get_loc("btc_price_filter_pass")] = False
        changed.iloc[1, changed.columns.get_loc("permission_on")] = False
        exited, _ = build_cooldown_state_machine(changed, 15)
        self.assertEqual(kept.probe_strategy_return_gross.iloc[1], -0.03)
        self.assertEqual(exited.probe_strategy_return_gross.iloc[1], 0.0)
        self.assertEqual(kept.probe_strategy_return_gross.iloc[0], exited.probe_strategy_return_gross.iloc[0])

    def test_real_sizing_expression_independent_of_exchange_setting(self):
        result = leverage.sizing_audit()
        self.assertEqual(result["target_notional_by_exchange_setting"], {"2": 125.0, "10": 125.0})

    def test_unified_capture_does_not_sum_perp_and_spot_for_exposure(self):
        capture = {"account_abstraction": "unifiedAccount", "usdc_balance": {"total": "100"},
                   "perp_margin_summary": {"accountValue": "20"}, "positions": [{"positionValue": "125"}]}
        result = leverage.account_analysis(capture)
        self.assertEqual(result["notional_over_unified_usdc_balance"], 1.25)
        self.assertEqual(result["legacy_local_target_at_1p25"], 150)
        self.assertEqual(result["current_canonical_sizing_equity"], 100)
        self.assertFalse(result["leverage_patch_prepared"])

    def test_account_mode_must_be_verified(self):
        with self.assertRaises(ValueError):
            leverage.account_analysis({"account_abstraction": "unknown"})

    def test_info_client_rejects_exchange_mutations_before_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network called")):
            for kind in ["order", "cancel", "updateLeverage", "withdraw"]:
                with self.assertRaises(ValueError):
                    leverage.info(kind)

    def test_contract_prevents_production_writes_and_new_gates(self):
        contract = json.loads((audit.HERE / "contract.json").read_text())
        self.assertFalse(contract["research_rules"]["production_writes"])
        self.assertFalse(contract["research_rules"]["orders_or_leverage_updates"])
        self.assertIn("global_execution_gate", contract["overlay_architecture"]["forbidden"])
        self.assertEqual(contract["planned_variants_not_executed"]["total_including_baseline"], 18)

    def test_current_baseline_inputs_fail_without_refresh(self):
        from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter
        manifest = json.loads((audit.HERE / "input_manifest.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            audit.verify_bundle(audit.HERE / "frozen_inputs.zip", manifest, Path(tmp))
            with self.assertRaisesRegex(ValueError, "btc_last_day=2026-05-05 fallback_last_day=2026-05-08 source_day=2026-09-25"):
                Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter().load_inputs(root=Path(tmp))

    def test_canonical_rotations_close_old_before_new(self):
        for old, target in [("BTC", "AVAX"), ("AVAX", "ETH")]:
            plan = current_plan(old, target)
            self.assertEqual(plan["status"], "READY")
            self.assertEqual(plan["action"], "ROTATE")
            self.assertEqual([s["asset"] for s in plan["steps"]], [old, target])
            self.assertEqual([s["reduce_only"] for s in plan["steps"]], [True, False])

    def test_canonical_cash_exit_is_reduce_only(self):
        plan = current_plan("AVAX", "CASH")
        self.assertEqual(plan["status"], "READY")
        self.assertEqual(plan["action"], "EXIT")
        self.assertEqual(len(plan["steps"]), 1)
        self.assertTrue(plan["steps"][0]["reduce_only"])

    def test_actual_planner_preserves_notional_at_2_and_10(self):
        a, b = current_plan(exchange_setting=2), current_plan(exchange_setting=10)
        self.assertEqual(a["target_notional_usd"], 1250)
        self.assertEqual(a["target_notional_usd"], b["target_notional_usd"])
        self.assertEqual(a["steps"][1]["quantity"], b["steps"][1]["quantity"])
        self.assertAlmostEqual(a["required_initial_margin_usd"], 656.25)
        self.assertAlmostEqual(b["required_initial_margin_usd"], 131.25)

    def test_no_action_does_not_reconcile_old_exchange_leverage(self):
        plan = current_plan("AVAX", "AVAX")
        self.assertEqual(plan["action"], "NO_ACTION")
        self.assertEqual(plan["steps"], [])

    def test_existing_open_order_guard_blocks_even_reduce_only_protection(self):
        plan = current_plan(open_orders=[{"coin": "BTC", "reduceOnly": True, "isTrigger": True}])
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("conflicting_open_order", plan["block_reasons"])

    def test_policy_max_exposure_needs_more_than_2_with_buffer(self):
        plan = current_plan(exposure=2.0)
        self.assertIn("insufficient_margin_or_available_balance", plan["block_reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
