import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.execution import materialize_execution_app_exports as export
from scripts.production import data_health_common as health


class ExecutionPublicStateTests(unittest.TestCase):
    def status(self, account, run=None, performance=None):
        return export.build_dashboard_public_status_contract(
            account_summary=account,
            intent_payload={"target_asset": "BTC", "target_size_pct": 0.49},
            dry_run_payload={}, gate_payload={"status": "blocked", "would_place_real_order": False},
            production_snapshot_payload={
                "closed_day": "2026-09-24", "candidate_asset": "AVAX", "model_candidate_exposure": 1.25,
                "validation": {"status": "passed"},
                "trend_permission_active": True,
                "execution_intent": {"target_asset": "AVAX", "target_exposure": 1.25,
                                     "signal_id": "current", "stale_signal": False, "allow_live_order_candidate": True},
            }, production_run_payload=run or {}, real_account_performance=performance,
            live_market_payload={"btc_24h_pct": 9.0},
        )

    def test_confirmed_target_wallet_and_staying_cash_are_separate(self):
        status = self.status({"positions_count": 0, "current_position": "CASH"}, {
            "run_id": "run", "final_status": "EXITED_ENTRY_FAILED_STAYING_CASH",
            "real_order_sent": True,
        })
        self.assertEqual(status["model_target_state"]["asset"], "AVAX")
        self.assertEqual(status["model_target_state"]["exposure_x"], 1.25)
        self.assertTrue(status["model_target_state"]["validated"])
        self.assertEqual(status["execution"]["target_asset"], "AVAX")
        self.assertEqual(status["real_account"]["asset"], "CASH")
        self.assertEqual(status["real_account"]["exposure_x"], 0)
        self.assertTrue(status["execution_result_state"]["staying_cash"])
        self.assertNotIn("STAYING_CASH", status["execution_result_state"]["public_message_sk"])
        views = export.build_runtime_public_status_views_from_dashboard_public_status(status)
        self.assertEqual(views["model_target_state"], status["model_target_state"])
        self.assertEqual(views["execution_result_state"], status["execution_result_state"])

    def test_missing_wallet_never_uses_target_or_gate(self):
        for account in ({}, export.build_runtime_account_summary({}, {"error": "network"})):
            with self.subTest(account=account):
                state = self.status(account)["real_account"]
                self.assertIsNone(state["asset"])
                self.assertIsNone(state["exposure_x"])
                self.assertIsNone(state["in_market"])
                self.assertFalse(state["state_available"])

    def test_all_positions_and_short_notionals_are_wallet_truth(self):
        account = export.build_runtime_account_summary({}, {
            "summary": {"account_equity_usd": 100},
            "raw": {"clearinghouseState": {"assetPositions": [
                {"position": {"coin": "BTC", "szi": "0.001", "positionValue": "49"}},
                {"position": {"coin": "ETH", "szi": "-0.01", "positionValue": "-25"}},
            ]}},
        })
        status = self.status(account)
        self.assertEqual(status["real_account"]["asset"], "MULTIPLE")
        self.assertEqual(status["real_account"]["exposure_x"], 0.74)
        self.assertEqual(len(status["real_account"]["positions"]), 2)
        self.assertEqual(status["real_account"]["positions"][1]["side"], "SHORT")
        self.assertEqual(account["position_notional_usd"], 74)

    def test_wallet_missing_notional_does_not_fabricate_exposure(self):
        state = self.status({"open_position": {"symbol": "BTC", "size": 1}})["real_account"]
        self.assertEqual(state["asset"], "BTC")
        self.assertIsNone(state["exposure_x"])

    def test_real_24h_return_requires_exchange_window_even_when_flat(self):
        account = {"positions_count": 0, "current_position": "CASH"}
        self.assertIsNone(self.status(account)["live_market_state"]["account_24h_pct"])
        status = self.status(account, performance={"windows": {"24h": {"available": True, "return_pct": 2.0}}})
        self.assertEqual(status["live_market_state"]["account_24h_pct"], 2)
        self.assertEqual(status["live_market_state"]["account_vs_btc_24h_pct"], -7)

    def test_running_manifest_is_not_a_terminal_execution_result(self):
        status = self.status({}, {"final_status": "RUNNING", "order_result": "FILLED_AND_ALIGNED"})
        self.assertIsNone(status["execution_result_state"]["outcome"])

    def test_failed_owner_readback_cannot_reuse_stale_wallet_as_current_state(self):
        status = self.status({"positions_count": 0, "current_position": "CASH"}, {
            "final_status": "EXECUTION_COMPLETE_PUBLISH_FAILED", "execution_outcome": "FILLED_AND_ALIGNED",
            "owner_account_snapshot_available": False, "finished_at": "2026-09-25T01:00:00Z",
        })
        self.assertFalse(status["real_account"]["state_available"])
        self.assertIsNone(status["real_account"]["asset"])
        self.assertIsNone(status["real_account"]["exposure_x"])
        self.assertEqual(status["execution_result_state"]["outcome"], "FILLED_AND_ALIGNED")
        self.assertEqual(status["execution_result_state"]["completed_at_utc"], "2026-09-25T01:00:00Z")

    def test_legacy_model_performance_fields_also_never_estimate_wallet_pnl(self):
        status = self.status({"open_position": {"symbol": "BTC", "size": 1}, "current_exposure": 0.49})
        self.assertIsNone(status["model_performance"]["account_24h_pct"])
        self.assertIsNone(status["model_performance"]["account_vs_btc_24h_pct"])


class ExecutionHealthScopeTests(unittest.TestCase):
    def test_missing_authority_is_presentation_only(self):
        with TemporaryDirectory() as folder:
            for key in ("execution_authority_latest_successful_snapshot", "execution_authority_latest_attempt_status"):
                source = health.evaluate_source(spec=health.SOURCE_INDEX[key], root=Path(folder),
                    reference_now=None, context={"latest_closed_utc_day": "2026-09-24"},
                    path_overrides={}, env_overrides={})
                summary = health.summarize_sources([source])
                self.assertFalse(summary["block_execution"])
                self.assertEqual(summary["app_status"], "degraded")
                self.assertEqual(health.execution_blocking_sources({"sources": [source]}), [])

    def test_direct_production_dependency_still_blocks(self):
        source = {"source_id": "data_ohlcv_btcusdt_1d", "status": "stale",
                  "criticality": "production_critical", "action": "block_execution",
                  "user_message_sk": "", "user_message_en": ""}
        self.assertTrue(health.summarize_sources([source])["block_execution"])


if __name__ == "__main__":
    unittest.main()
