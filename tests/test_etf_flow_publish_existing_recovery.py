import csv
import json
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd

from scripts.production import build_current_strategy_snapshot
from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    _materialize_full_history_frame_to_closed_day,
    _validate_etf_panel_materialization,
)


class TestEtfFlowPublishExistingRecovery(unittest.TestCase):
    def test_weekend_carry_forward_uses_last_valid_etf_source_without_synthetic_rows(self):
        etf_df = pd.DataFrame(
            [
                {
                    "us_trading_session_date": "2026-05-07",
                    "causal_available_for_btc_utc_day": "2026-05-08",
                    "aggregate_net_flow_usd": 1.0,
                },
                {
                    "us_trading_session_date": "2026-05-08",
                    "causal_available_for_btc_utc_day": "2026-05-09",
                    "aggregate_net_flow_usd": 2.0,
                },
            ],
            index=pd.to_datetime(["2026-05-08", "2026-05-09"]),
        )

        materialization = _validate_etf_panel_materialization(
            etf_df=etf_df,
            target_closed_day="2026-05-10",
        )

        self.assertEqual(materialization["actual_latest_source_session_day"], "2026-05-08")
        self.assertEqual(materialization["actual_latest_causal_available_day"], "2026-05-09")
        self.assertEqual(materialization["active_source_session_day"], "2026-05-08")
        self.assertEqual(materialization["active_source_causal_available_day"], "2026-05-09")
        self.assertEqual(materialization["materialized_closed_day"], "2026-05-10")
        self.assertEqual(materialization["carry_forward_days_applied"], 1)
        self.assertEqual(
            materialization["evaluation_mode"],
            "carry_forward_last_valid_etf_state",
        )
        self.assertEqual(
            materialization["carry_forward_reason"],
            "no_intermediate_us_trading_sessions",
        )
        self.assertEqual(materialization["synthetic_source_rows_added"], 0)
        self.assertEqual(
            materialization["carry_forward_non_session_days"],
            [{"date": "2026-05-09", "reason": "weekend"}],
        )

    def test_full_history_materialization_extends_to_closed_day_without_synthetic_etf_source_rows(self):
        index = pd.to_datetime(["2026-05-08", "2026-05-09"])
        full_history_frame = pd.DataFrame(
            {
                "cash_day": [True, True],
                "stress_block_active": [False, False],
                "btc_price_filter_pass": [True, True],
                "flow_3d_sum_usd": [100.0, 200.0],
                "flow_2_of_last_3_positive_flag": [True, True],
                "probe_input_ready_flag": [True, True],
                "dev_only": [True, True],
                "non_authoritative": [True, True],
                "official_truth": [False, False],
                "strategy_advancement": [False, False],
                "causal_available_for_btc_utc_day": pd.to_datetime(["2026-05-08", "2026-05-09"]),
                "us_trading_session_date": pd.to_datetime(["2026-05-07", "2026-05-08"]),
                "etf_flow_feature_available": [True, True],
                "etf_flow_evidence_window": [True, True],
            },
            index=index,
        )
        baseline_probe_frame = pd.DataFrame(
            {
                "cash_day": [True, True, True],
                "stress_block_active": [False, False, False],
            },
            index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]),
        )
        btc_df = pd.DataFrame(
            {
                "btc_close": [100.0, 101.0, 102.0],
                "btc_return": [0.0, 0.01, 0.009900990099],
                "btc_ema10": [99.0, 100.0, 101.0],
                "btc_price_filter_pass": [True, True, True],
            },
            index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]),
        )

        materialized = _materialize_full_history_frame_to_closed_day(
            full_history_frame=full_history_frame,
            baseline_probe_frame=baseline_probe_frame,
            btc_df=btc_df,
            target_closed_day="2026-05-10",
        )

        self.assertEqual(pd.Timestamp(materialized.index[-1]).strftime("%Y-%m-%d"), "2026-05-10")
        self.assertEqual(len(materialized), 3)
        self.assertFalse(bool(materialized.loc[pd.Timestamp("2026-05-10"), "etf_flow_feature_available"]))
        self.assertTrue(bool(materialized.loc[pd.Timestamp("2026-05-10"), "etf_flow_evidence_window"]))
        self.assertTrue(pd.isna(materialized.loc[pd.Timestamp("2026-05-10"), "causal_available_for_btc_utc_day"]))

    def test_build_path_materializes_stale_btc_persistence_dependency_before_etf_flow(self):
        class FakeBtcPersistenceAdapter:
            def load_inputs(self, *, root):
                return {"closed_day": "2026-05-10"}

            def build_timeseries(self, inputs):
                return pd.DataFrame(
                    [
                        {"date": "2026-05-08", "strategy_version": "phase68g_btc_persistence_10d_early_risk_075"},
                        {"date": "2026-05-09", "strategy_version": "phase68g_btc_persistence_10d_early_risk_075"},
                        {"date": "2026-05-10", "strategy_version": "phase68g_btc_persistence_10d_early_risk_075"},
                    ]
                )

            def build_snapshot_metrics(self, inputs, timeseries):
                return {
                    "model": "phase68g_btc_persistence_10d_early_risk_075",
                    "latest_available_date": "2026-05-10",
                    "total_return_pct": "1.0",
                }

        tmp_base = Path.cwd() / "outputs" / "_tmp_test_etf_flow_publish_existing_recovery"
        tmp_base.mkdir(parents=True, exist_ok=True)
        root = tmp_base / f"case_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            freshness_path = root / "outputs" / "execution" / "freshness" / "app_freshness_report.json"
            paper_path = (
                root
                / "outputs"
                / "execution"
                / "app_exports"
                / "phase68g_btc_persistence_10d_early_risk_075_paper.csv"
            )
            summary_path = (
                root
                / "outputs"
                / "execution"
                / "app_exports"
                / "phase68g_btc_persistence_10d_early_risk_075_authoritative_net_compare_export.csv"
            )
            freshness_path.parent.mkdir(parents=True, exist_ok=True)
            paper_path.parent.mkdir(parents=True, exist_ok=True)
            freshness_path.write_text(
                json.dumps({"latest_closed_utc_date": "2026-05-10", "status": "ok"}),
                encoding="utf-8",
            )
            paper_path.write_text("date\n2026-05-08\n", encoding="utf-8")
            summary_path.write_text(
                "model,latest_available_date,total_return_pct\n"
                "phase68g_btc_persistence_10d_early_risk_075,2026-05-08,0.5\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                build_current_strategy_snapshot,
                "Phase68gBtcPersistence10dEarlyRisk075Adapter",
                FakeBtcPersistenceAdapter,
            ):
                result = build_current_strategy_snapshot._maybe_materialize_btc_persistence_dependency(
                    strategy_model=build_current_strategy_snapshot.ETF_FLOW_CANDIDATE_ID,
                    root=root,
                )

            self.assertEqual(result["status"], "materialized")
            self.assertEqual(result["previous_paper_last_day"], "2026-05-08")
            self.assertEqual(result["paper_last_day"], "2026-05-10")
            with paper_path.open(newline="", encoding="utf-8") as f:
                paper_rows = list(csv.DictReader(f))
            with summary_path.open(newline="", encoding="utf-8") as f:
                summary_rows = list(csv.DictReader(f))
            self.assertEqual(paper_rows[-1]["date"], "2026-05-10")
            self.assertEqual(summary_rows[-1]["latest_available_date"], "2026-05-10")
        finally:
            # Best-effort cleanup; sandboxed Windows temp ACLs can make this non-critical.
            try:
                import shutil

                shutil.rmtree(root, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
