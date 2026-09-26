from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from scripts.production.route_identity import FIELDS, resolve_route, validate_target_identity
from scripts.production.strategy_adapters.causal_route_adapter import CausalRouteAdapter, validate_route_payloads
from scripts.production.build_current_strategy_snapshot import _build_snapshot, _build_diagnostics
from scripts.execution import materialize_execution_app_exports as dashboard
from scripts.execution.build_execution_intent_from_strategy_exports import validate_production_snapshot
from scripts.execution.production_execution import build_execution_plan
from tests.test_production_execution import production, intent, gate, account, policy, NOW, MID, PRECISION

ROOT = Path(__file__).resolve().parents[1]


class RouteIdentityTests(unittest.TestCase):
    def route(self, route="BASE", base="LTC", candidate="AVAX", active=False, exposure=1.25):
        return resolve_route(route_type=route, base_economic_asset=base, candidate_asset=candidate,
            candidate_trigger_active=active, target_exposure=exposure,
            signal_available_at="2026-09-26T12:00:00Z")

    def test_all_routes(self):
        for route, base, candidate, active, exposure, target in [
            ("BASE", "LTC", "AVAX", False, 1.25, "LTC"),
            ("BASE", "TRX", "DOGE", False, 1.25, "TRX"),
            ("BASE", "SOL", "AVAX", False, 1.25, "SOL"),
            ("CANDIDATE", "LTC", "AVAX", True, 1.25, "AVAX"),
            ("BTC", "LTC", "AVAX", False, .5, "BTC"),
            ("CASH", "LTC", "AVAX", False, 0, "CASH"),
        ]:
            with self.subTest(route=route, base=base):
                self.assertEqual(self.route(route, base, candidate, active, exposure)["resolved_execution_asset"], target)

    def test_legacy_portfolio_path_requires_active_route(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import phase68g_portfolio_exposure_leverage_validation as lev
        governance = pd.DataFrame({"date": ["2026-09-24", "2026-09-25"], "route_type": ["BASE", "CANDIDATE"],
            "executed_position": ["LTCUSDT", "AVAX"], "overlay_candidate_raw": ["AVAX", "AVAX"], "base_ret": [.1, .2]})
        base = pd.DataFrame({"date": governance.date, "baseline_held_asset": ["LTC", "TRX"]})
        result = lev.build_portfolio_exposure_frame(governance, base)
        self.assertEqual(result.portfolio_held_asset.tolist(), ["LTC", "AVAX"])
        with self.assertRaises(ValueError):
            lev.build_portfolio_exposure_frame(governance.drop(columns="route_type"), base)

    def test_phase63_base_return_label_is_not_shifted_twice(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import phase63_btc_participation_overlay as p63
        data = pd.DataFrame({"base_selected_symbol": ["BTCUSDT", "LTCUSDT", "SOLUSDT"],
            "base_return": [.1, .2, .3], "btc_return": [0., 0., 0.], "risk_off": False, "btc_preference": False})
        for col in ["btc_close", "base_strength_lb", "base_is_weak", "btc_fast_ma", "btc_slow_ma", "btc_risk_ma", "btc_ret_lb", "btc_vol", "btc_trend_ok"]:
            data[col] = 0.
        with patch.object(p63, "compute_regime_columns", return_value=data):
            result = p63.simulate_variant(data, None)
        self.assertEqual(result.executed_position.tolist(), ["CASH", "LTCUSDT", "SOLUSDT"])
        self.assertEqual(result.strategy_return.tolist(), [0., .2, .3])

    def test_inactive_candidate_never_overrides_base_or_needs_membership(self):
        for base in ("LTC", "SOL", "TRX", "NEWMARKET123"):
            for candidate in ("AVAX", "DOGE", "CASH", "XYZ"):
                self.assertEqual(self.route(base=base, candidate=candidate)["resolved_execution_asset"], base)

    def test_ambiguous_and_invalid_routes_fail(self):
        for kwargs in ({"route": "BASE", "base": "BASE"}, {"route": "CANDIDATE"},
                       {"route": "BASE", "active": True}, {"route": "CASH"},
                       {"exposure": float("nan")}, {"route": "UNKNOWN"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.route(**kwargs)

    def test_rotations_use_dynamic_market_metadata(self):
        mids = {**MID, "LTC": 125., "SOL": 200., "NEWMARKET123": 3.}
        precision = {**PRECISION, "LTC": 3, "SOL": 3, "NEWMARKET123": 2}
        routes = [self.route("BTC", exposure=.5), self.route(),
                  self.route("CANDIDATE", active=True), self.route(base="SOL"),
                  self.route("CASH", exposure=0)]
        targets = [r["resolved_execution_asset"] for r in routes]
        for old, target in list(zip(targets, targets[1:])) + [("AVAX", "NEWMARKET123")]:
            snapshot = account(1000)
            snapshot["raw"]["clearinghouseState"]["assetPositions"] = [{"position": {
                "coin": old, "szi": "1", "positionValue": str(mids[old])}}]
            exp = 0 if target == "CASH" else 1.25
            plan = build_execution_plan(production=production(target, exp), intent=intent(target, exp),
                gate=gate(target), account_snapshot=snapshot, policy=policy(), mids=mids,
                size_decimals=precision, now=NOW)
            self.assertEqual(plan["block_reasons"], [])
            self.assertEqual(plan["steps"][0]["asset"], old)
            self.assertTrue(plan["steps"][0]["reduce_only"])
            if target != "CASH":
                self.assertEqual(plan["steps"][-1]["asset"], target)
                self.assertFalse(plan["steps"][-1]["reduce_only"])

    def test_unsupported_entry_keeps_old_position_exit_available(self):
        plan = build_execution_plan(production=production("UNSUPPORTED", 1.25), intent=intent("UNSUPPORTED", 1.25),
            gate=gate("UNSUPPORTED"), account_snapshot=account(1000, asset="AVAX", notional=500),
            policy=policy(), mids=MID, size_decimals=PRECISION, now=NOW)
        self.assertEqual(plan["status"], "READY")
        self.assertEqual(plan["block_reasons"], [])
        self.assertTrue(plan["entry_block_reasons"])
        self.assertEqual(plan["steps"][0]["asset"], "AVAX")
        self.assertTrue(plan["steps"][0]["reduce_only"])


class RoutePipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        with zipfile.ZipFile(ROOT / "research/causal_baseline_20260926/input_bundle.zip") as bundle:
            # Trusted hash-pinned audit fixture. Runtime account/secrets aren't used.
            for name in bundle.namelist():
                if name.startswith(("data/", "outputs/", "source_of_truth/")):
                    destination = (cls.root / name).resolve()
                    destination.relative_to(cls.root.resolve())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(bundle.read(name))
        contract = "source_of_truth/production_route_identity_contract.json"
        (cls.root / contract).write_bytes((ROOT / contract).read_bytes())
        cls.adapter = CausalRouteAdapter()
        cls.inputs = cls.adapter.load_inputs(root=cls.root)
        cls.frame = cls.adapter.build_timeseries(cls.inputs)
        cls.snapshot = _build_snapshot(generated_at_utc="2026-09-26T12:00:00Z", adapter=cls.adapter,
            inputs=cls.inputs, timeseries=cls.frame, build_command="fixture", git_commit="fixture")
        cls.snapshot["validation"] = {"status": "passed", "errors": [], "warnings": []}
        cls.diagnostics = _build_diagnostics(generated_at_utc=cls.snapshot["generated_at_utc"],
            adapter=cls.adapter, inputs=cls.inputs, timeseries=cls.frame, validation=cls.snapshot["validation"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_causal_dependency_preparation_never_rebuilds_old_same_day_model(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(dashboard, "ROOT", self.root))
            stack.enter_context(patch.object(dashboard, "read_json", return_value={"artifacts": {}}))
            stack.enter_context(patch.object(dashboard, "load_app_live_mode_contract", return_value={}))
            stack.enter_context(patch.object(dashboard, "PRODUCTION_CORE_DEPENDENCY_ARTIFACT_KEYS", ()))
            stack.enter_context(patch.object(dashboard, "write_json"))
            legacy = stack.enter_context(patch.object(dashboard, "refresh_phase68g_native_outputs_if_needed", side_effect=AssertionError("legacy path")))
            result = dashboard.materialize_production_core_dependency_artifacts()
            self.assertEqual(result["status"], "success")
            legacy.assert_not_called()

    def test_original_failure_is_fixed_by_fresh_derivation(self):
        self.assertEqual(self.snapshot["resolved_execution_asset"], "LTC")
        self.assertEqual(self.snapshot["candidate_asset"], "AVAX")
        self.assertFalse(self.snapshot["candidate_trigger_active"])
        self.assertEqual(self.snapshot["execution_intent"]["target_exposure"], 1.25)
        self.assertTrue(self.frame.route_return_asset.eq(self.frame.resolved_execution_asset).all())
        self.assertEqual(self.adapter.build_snapshot_metrics(self.inputs, self.frame)["total_return_pct_net"], 892.7171)

    def test_all_ledger_assets_follow_their_own_available_signal(self):
        by_day = self.frame.set_index("date")
        for row in self.frame.itertuples():
            if row.performance_signal_data_day:
                source = by_day.loc[row.performance_signal_data_day]
                self.assertEqual(row.performance_executed_held_asset, source.resolved_execution_asset)
                self.assertLessEqual(pd.Timestamp(source.signal_available_at), pd.Timestamp(row.performance_return_interval_start))
        self.assertNotEqual(self.frame.iloc[-1].performance_executed_held_asset, self.snapshot["resolved_execution_asset"])

    def test_validator_rederives_source_and_rejects_old_same_day_returns(self):
        args = dict(snapshot=self.snapshot, timeseries=self.frame, diagnostics=self.diagnostics,
                    adapter=self.adapter, inputs=self.inputs)
        result = validate_route_payloads(**args)
        self.assertEqual(result["errors"], [])
        bad = self.frame.copy()
        bad.loc[bad.index[-1], "return_net"] = .9
        args["timeseries"] = bad
        self.assertEqual(validate_route_payloads(**args)["status"], "failed")

    def test_intent_and_dashboard_use_resolved_asset_not_candidate(self):
        context = validate_production_snapshot(self.snapshot,
            source_path=self.root / "outputs/production/current_strategy_snapshot.json")
        self.assertEqual(context["target_asset"], "LTC")
        status = dashboard.build_dashboard_public_status_contract(
            production_snapshot_payload=self.snapshot, gate_payload={}, dry_run_payload={},
            account_summary={"positions_count": 1, "current_position": "AVAX", "current_exposure": 1.1,
                             "positions": [{"symbol": "AVAX"}], "open_position": {"symbol": "AVAX", "size": 1}},
            intent_payload={}, product_snapshot_payload={}, live_market_payload={}, data_health_payload={})
        self.assertEqual(status["model_signal"]["preferred_asset"], context["target_asset"])
        self.assertEqual(status["real_account"]["asset"], "AVAX")

    def test_etf_metric_window_keeps_days_with_missing_features(self):
        frame = self.frame.copy()
        frame["etf_flow_feature_available"] = False
        frame.loc[[1000, 1002, 1005], "etf_flow_feature_available"] = True
        returns = frame.return_net.to_numpy()[1000:]
        expected = round((np.prod(1 + returns) ** (365.25 / len(returns)) - 1) * 100, 4)
        self.assertEqual(self.adapter.build_snapshot_metrics(self.inputs, frame)["since_etf_start_cagr_pct"], expected)

    def test_route_tampering_rejected(self):
        bad = copy.deepcopy(self.snapshot)
        bad["execution_intent"]["target_asset"] = "AVAX"
        with self.assertRaises(ValueError):
            validate_target_identity(bad)

    def test_chart_ignores_same_day_legacy_fields_and_keeps_account_separate(self):
        row = self.frame.iloc[-1].to_dict()
        row.update(authorized_equity=9999, authorized_return_net=.9, effective_market_exposure=99)
        self.assertEqual(dashboard.dashboard_model_index_from_source_row(row), row["performance_model_equity"])
        self.assertEqual(dashboard.dashboard_model_return_net_from_source_row(row), row["performance_net_strategy_return"])
        self.assertEqual(dashboard.dashboard_model_exposure_from_source_row(row), row["performance_exposure"])
        del row["performance_model_equity"]
        with self.assertRaises(ValueError):
            dashboard.dashboard_model_index_from_source_row(row)


if __name__ == "__main__":
    unittest.main()
