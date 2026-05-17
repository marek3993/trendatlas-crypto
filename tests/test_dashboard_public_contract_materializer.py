import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scripts.execution import materialize_execution_app_exports as materializer


ROOT = Path(__file__).resolve().parents[1]


class TestDashboardPublicContractMaterializer(unittest.TestCase):
    def build_cash_blocked_status(self, *, live_market_payload: dict | None = None) -> dict:
        return materializer.build_dashboard_public_status_contract(
            account_summary={
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
                "account_equity_usd": 39.475466,
                "available_balance_usd": 39.475466,
            },
            intent_payload={
                "target_asset": "CASH",
                "target_size_pct": 0.0,
            },
            dry_run_payload={
                "target_asset": "BTC",
                "target_size_pct": 0.75,
            },
            gate_payload={
                "target_asset": "CASH",
                "status": "blocked",
                "would_place_real_order": False,
            },
            production_snapshot_payload={
                "closed_day": "2026-05-10",
                "candidate_asset": "BTC",
                "model_candidate_exposure": 0.75,
                "effective_market_exposure": 0.75,
                "actual_held_asset": "BTC",
                "current_asset": "BTC",
            },
            product_snapshot_payload={
                "main_strategy_top_performance_metrics": {
                    "cagr_pct": 216.86,
                    "since2023_cagr_pct": 322.34,
                    "since2025_cagr_pct": 251.64,
                }
            },
            production_timeseries_last_row={
                "date": "2026-05-10",
                "btc_return": -0.005,
                "authorized_return_net": 0.013901162393,
            },
            data_health_payload={
                "reference_closed_day_utc": "2026-05-10",
                "summary": {
                    "overall_status": "ok",
                    "block_app": False,
                    "block_execution": False,
                },
            },
            live_market_payload=live_market_payload,
            generated_at_utc="2026-05-11T08:15:00Z",
        )

    def test_chart_contract_uses_authorized_model_series_and_separate_real_account_columns(self):
        status = self.build_cash_blocked_status()
        rows = [
            {
                "date": "2026-05-09",
                "authorized_equity": "1.25",
                "equity": "9.99",
                "model_candidate_equity": "7.77",
                "btc_baseline_equity": "1.10",
                "authorized_return_net": "0.015",
                "authorized_return_gross": "0.020",
                "btc_return": "-0.005",
                "effective_market_exposure": "0.75",
                "asset_transition_day": True,
                "fees_daily": "0.002",
                "funding_daily": "0.001",
                "borrow_cost_daily": "0.001",
                "slippage_cost_daily": "0.001",
            }
        ]

        chart_contract = materializer.build_dashboard_public_chart_timeseries_contract(
            production_timeseries_rows=rows,
            dashboard_public_status=status,
        )

        self.assertEqual(
            chart_contract["fieldnames"],
            [
                "date",
                "live_strategy_index",
                "live_strategy_exposure_x",
                "live_strategy_return_net",
                "live_strategy_vs_btc_return",
                "live_strategy_source",
                "strategy_execution_index",
                "model_index",
                "btc_index",
                "strategy_execution_exposure_x",
                "strategy_execution_return_net",
                "strategy_execution_vs_btc_return",
                "strategy_execution_source",
                "model_authorized_exposure_x",
                "model_authorized_return_net",
                "model_authorized_return_gross",
                "model_transition_cost",
                "model_asset_transition_day",
                "real_account_index",
                "real_account_exposure_x",
                "real_account_return_net",
                "real_account_vs_btc_return",
                "real_account_source",
                "chart_scope",
            ],
        )
        self.assertEqual(chart_contract["chart_scope"], "real_account_flat_no_history")
        self.assertEqual(chart_contract["live_strategy_start_date"], "2026-05-08")
        self.assertEqual(chart_contract["rows"][0]["live_strategy_index"], 1.0)
        self.assertEqual(chart_contract["rows"][0]["live_strategy_exposure_x"], 0.75)
        self.assertEqual(chart_contract["rows"][0]["live_strategy_return_net"], 0.015)
        self.assertEqual(chart_contract["rows"][0]["live_strategy_vs_btc_return"], 0.02)
        self.assertEqual(
            chart_contract["rows"][0]["live_strategy_source"],
            "production_authority_live_strategy",
        )
        self.assertEqual(chart_contract["rows"][0]["strategy_execution_index"], 1.0)
        self.assertEqual(chart_contract["rows"][0]["strategy_execution_exposure_x"], 0.75)
        self.assertEqual(chart_contract["rows"][0]["strategy_execution_return_net"], 0.015)
        self.assertEqual(chart_contract["rows"][0]["strategy_execution_vs_btc_return"], 0.02)
        self.assertEqual(
            chart_contract["rows"][0]["strategy_execution_source"],
            "production_authority_live_strategy",
        )
        self.assertEqual(chart_contract["rows"][0]["model_index"], 1.25)
        self.assertEqual(chart_contract["rows"][0]["model_authorized_exposure_x"], 0.75)
        self.assertEqual(chart_contract["rows"][0]["real_account_index"], 1.0)
        self.assertEqual(chart_contract["rows"][0]["real_account_exposure_x"], 0.0)
        self.assertEqual(chart_contract["rows"][0]["real_account_return_net"], 0.0)
        self.assertEqual(chart_contract["rows"][0]["real_account_vs_btc_return"], 0.005)
        self.assertEqual(chart_contract["rows"][0]["real_account_source"], "real_account_flat_no_history")

    def test_live_account_vs_btc_uses_live_market_input_not_snapshot(self):
        status = self.build_cash_blocked_status(
            live_market_payload={
                "btc_24h_pct": 1.9,
                "btc_24h_pct_source": "live_ticker",
            }
        )

        self.assertEqual(status["model_performance"]["btc_24h_pct"], -0.5)
        self.assertEqual(status["live_market_state"]["btc_24h_pct"], 1.9)
        self.assertEqual(status["live_market_state"]["account_24h_pct"], 0.0)
        self.assertEqual(status["live_market_state"]["account_vs_btc_24h_pct"], -1.9)

    def test_model_signal_preserves_desired_exposure_but_normalizes_internal_asset_label(self):
        status = materializer.build_dashboard_public_status_contract(
            account_summary={"current_position": "CASH", "positions_count": 0, "open_position": None},
            intent_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            dry_run_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            gate_payload={"target_asset": "CASH", "status": "blocked", "would_place_real_order": False},
            production_snapshot_payload={
                "closed_day": "2026-05-10",
                "candidate_asset": "BASE",
                "selected_asset": "BASE",
                "model_candidate_exposure": 1.0,
                "effective_market_exposure": 0.0,
                "actual_held_asset": "CASH",
                "current_asset": "CASH",
                "trend_permission_active": False,
            },
            production_timeseries_last_row={"date": "2026-05-10", "btc_return": 0.02},
            generated_at_utc="2026-05-11T08:15:00Z",
        )

        self.assertEqual(status["model_signal"]["preferred_asset"], "CASH")
        self.assertEqual(status["model_signal"]["exposure_x"], 1.0)
        self.assertTrue(status["model_signal"]["not_real_wallet_exposure"])

    def test_public_model_chart_stays_flat_when_candidate_crypto_is_not_authorized(self):
        status = materializer.build_dashboard_public_status_contract(
            account_summary={"current_position": "CASH", "positions_count": 0, "open_position": None},
            intent_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            dry_run_payload={"target_asset": "BTC", "target_size_pct": 1.0},
            gate_payload={"target_asset": "CASH", "status": "blocked", "would_place_real_order": False},
            production_snapshot_payload={
                "closed_day": "2026-05-10",
                "candidate_asset": "BTC",
                "selected_asset": "BTC",
                "model_candidate_exposure": 1.0,
                "effective_market_exposure": 0.0,
                "actual_held_asset": "CASH",
                "current_asset": "CASH",
                "trend_permission_active": False,
            },
            production_timeseries_last_row={"date": "2026-05-10", "btc_return": 0.05},
            generated_at_utc="2026-05-11T08:15:00Z",
        )
        rows = [
            {
                "date": "2026-05-09",
                "candidate_asset": "BTC",
                "selected_asset": "BTC",
                "model_candidate_exposure": "1.0",
                "model_candidate_equity": "1.0",
                "model_candidate_return_net": "0.0",
                "btc_baseline_equity": "1.0",
                "btc_return": "0.0",
                "authorized_return_net": "0.0",
                "authorized_return_gross": "0.0",
                "effective_market_exposure": "0.0",
                "actual_held_asset": "CASH",
                "current_asset": "CASH",
                "execution_target_asset": "CASH",
                "execution_target_exposure": "0.0",
                "trend_permission_active": False,
                "asset_transition_day": False,
            },
            {
                "date": "2026-05-10",
                "candidate_asset": "BTC",
                "selected_asset": "BTC",
                "model_candidate_exposure": "1.0",
                "model_candidate_equity": "1.25",
                "model_candidate_return_net": "0.25",
                "btc_baseline_equity": "1.05",
                "btc_return": "0.05",
                "authorized_return_net": "0.0",
                "authorized_return_gross": "0.0",
                "effective_market_exposure": "0.0",
                "actual_held_asset": "CASH",
                "current_asset": "CASH",
                "execution_target_asset": "CASH",
                "execution_target_exposure": "0.0",
                "trend_permission_active": False,
                "asset_transition_day": False,
            },
        ]

        chart_contract = materializer.build_dashboard_public_chart_timeseries_contract(
            production_timeseries_rows=rows,
            dashboard_public_status=status,
            live_strategy_start_date="2026-05-08",
        )

        self.assertEqual([row["model_index"] for row in chart_contract["rows"]], [1.0, 1.0])
        self.assertEqual([row["model_authorized_exposure_x"] for row in chart_contract["rows"]], [0.0, 0.0])
        self.assertEqual([row["model_authorized_return_net"] for row in chart_contract["rows"]], [0.0, 0.0])
        self.assertEqual([row["live_strategy_index"] for row in chart_contract["rows"]], [1.0, 1.0])
        self.assertEqual([row["live_strategy_exposure_x"] for row in chart_contract["rows"]], [0.0, 0.0])
        self.assertEqual(status["model_signal"]["preferred_asset"], "BTC")
        self.assertEqual(status["model_signal"]["exposure_x"], 1.0)

    def test_materializer_helper_writes_status_chart_quality_and_manifest(self):
        status = self.build_cash_blocked_status()
        runtime_snapshot = {
            "dashboard_public_status": status,
            "account_snapshot_summary": {
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
            },
        }
        production_rows = [
            {
                "date": "2026-05-09",
                "authorized_equity": "1.0",
                "btc_baseline_equity": "1.0",
                "authorized_return_net": "0.0",
                "authorized_return_gross": "0.0",
                "btc_return": "0.0",
                "effective_market_exposure": "0.0",
                "asset_transition_day": False,
            },
            {
                "date": "2026-05-10",
                "authorized_equity": "1.01",
                "btc_baseline_equity": "0.995",
                "authorized_return_net": "0.01",
                "authorized_return_gross": "0.01",
                "btc_return": "-0.005",
                "effective_market_exposure": "0.75",
                "asset_transition_day": False,
            },
        ]

        tmp = (
            ROOT
            / "outputs"
            / "_tmp_test_dashboard_public_contract_materializer"
            / f"case_{uuid.uuid4().hex}"
        )
        tmp.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, tmp, True)
        status_path = tmp / "dashboard_public_status.json"
        chart_path = tmp / "dashboard_public_chart_timeseries.csv"
        quality_path = tmp / "dashboard_public_status.quality.json"
        manifest_path = tmp / "dashboard_public_status.manifest.json"
        source_path = tmp / "production_timeseries.csv"
        source_path.write_text("date,authorized_equity\n2026-05-10,1.01\n", encoding="utf-8")

        with mock.patch.object(materializer, "DASHBOARD_PUBLIC_STATUS_PATH", status_path), mock.patch.object(
            materializer, "DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH", chart_path
        ), mock.patch.object(materializer, "DASHBOARD_PUBLIC_STATUS_QUALITY_PATH", quality_path), mock.patch.object(
            materializer, "DASHBOARD_PUBLIC_STATUS_MANIFEST_PATH", manifest_path
        ):
            result = materializer.materialize_dashboard_public_contract_bundle(
                runtime_snapshot=runtime_snapshot,
                production_timeseries_rows=production_rows,
                source_paths=[source_path],
            )

        self.assertEqual(result["status_path"], status_path)
        self.assertTrue(status_path.exists())
        self.assertTrue(chart_path.exists())
        self.assertTrue(quality_path.exists())
        self.assertTrue(manifest_path.exists())

        with quality_path.open("r", encoding="utf-8") as handle:
            quality_payload = json.load(handle)
        self.assertEqual(quality_payload["status"], "ok")
        self.assertTrue(quality_payload["checks"]["account_vs_btc_identity"])
        self.assertTrue(quality_payload["checks"]["live_strategy_contract_valid"])
        self.assertTrue(quality_payload["checks"]["strategy_execution_pair_aligned"])

        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest_payload = json.load(handle)
        self.assertEqual(manifest_payload["closed_day"], "2026-05-10")
        self.assertIn("dashboard_public_chart_timeseries.csv", " ".join(manifest_payload["output_files"]))
        self.assertEqual(
            manifest_payload["row_counts"][materializer.path_for_app(chart_path)],
            2,
        )

        with chart_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            written_rows = list(reader)
        self.assertEqual(len(written_rows), 2)
        self.assertEqual(written_rows[1]["live_strategy_index"], "1.01")
        self.assertEqual(written_rows[1]["live_strategy_exposure_x"], "0.75")
        self.assertEqual(written_rows[1]["real_account_index"], "1.0")
        self.assertEqual(written_rows[1]["real_account_exposure_x"], "0.0")


if __name__ == "__main__":
    unittest.main()
