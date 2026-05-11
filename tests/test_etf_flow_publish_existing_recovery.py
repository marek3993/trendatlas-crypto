import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd

from scripts.production import data_health_common
from scripts.production import build_current_strategy_snapshot
from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import (
    Phase68g66g1p25xCandidateAdapter,
)
from scripts.production.strategy_adapters.phase68g_btc_persistence_10d_early_risk_075_adapter import (
    Phase68gBtcPersistence10dEarlyRisk075Adapter,
)
from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    _materialize_full_history_frame_to_closed_day,
    _validate_etf_panel_materialization,
)


class TestEtfFlowPublishExistingRecovery(unittest.TestCase):
    def _make_case_root(self) -> Path:
        tmp_base = Path.cwd() / "tmp_test_artifacts"
        tmp_base.mkdir(parents=True, exist_ok=True)
        root = tmp_base / f"etf_flow_recovery_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        return root

    def _write_rows(self, path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _seed_stale_phase68g_baseline_bundle(
        self,
        root: Path,
        *,
        source_day: str = "2026-04-30",
        next_rebalance_date: str = "2026-05-12",
    ) -> None:
        summary_path = (
            root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
        )
        paper_path = (
            root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase68g_66g_1p25x_candidate_paper.csv"
        )
        trend_status_path = root / "outputs" / "execution" / "app_exports" / "phase66g_live_status.csv"
        trend_history_path = (
            root / "outputs" / "execution" / "app_exports" / "phase66g_trend_barometer_history.csv"
        )
        freshness_path = root / "outputs" / "execution" / "freshness" / "app_freshness_report.json"
        benchmark_path = root / "data" / "ohlcv" / "BTCUSDT_1d.csv"

        summary_fields = [
            "model",
            "latest_available_date",
            "annual_borrow_cost_pct",
            "tradable_transition_slippage_bps",
            "fee_side_mode",
            "taker_fee_bps",
            "maker_fee_bps",
            "staking_discount_pct",
            "referral_discount_pct",
        ]
        self._write_rows(
            summary_path,
            summary_fields,
            [
                {
                    "model": "phase68g_66g_1p25x_candidate",
                    "latest_available_date": source_day,
                    "annual_borrow_cost_pct": 12.0,
                    "tradable_transition_slippage_bps": 10.0,
                    "fee_side_mode": "taker",
                    "taker_fee_bps": 4.5,
                    "maker_fee_bps": 1.5,
                    "staking_discount_pct": 0.0,
                    "referral_discount_pct": 0.0,
                }
            ],
        )

        paper_rows: list[dict[str, object]] = []
        for stamp in pd.date_range("2023-01-01", source_day, freq="D"):
            paper_rows.append(
                {
                    "date": stamp.strftime("%Y-%m-%d"),
                    "realistic_ret_gross": 0.0,
                    "portfolio_held_asset": "CASH",
                    "effective_leverage": 0.0,
                    "daily_borrow_cost": 0.0,
                    "tradable_slippage_cost": 0.0,
                    "trend_block_day": False,
                    "stress_block_day": False,
                    "trend_gate_pass": False,
                    "trend_state_label": "neutral",
                    "trend_score": -0.05,
                    "buy_threshold": 0.1,
                    "leverage_active": False,
                    "leverage_state_reason": "flat",
                    "trend_activation_threshold": 0.1,
                }
            )
        self._write_rows(
            paper_path,
            [
                "date",
                "realistic_ret_gross",
                "portfolio_held_asset",
                "effective_leverage",
                "daily_borrow_cost",
                "tradable_slippage_cost",
                "trend_block_day",
                "stress_block_day",
                "trend_gate_pass",
                "trend_state_label",
                "trend_score",
                "buy_threshold",
                "leverage_active",
                "leverage_state_reason",
                "trend_activation_threshold",
            ],
            paper_rows,
        )
        self._write_rows(
            trend_status_path,
            ["latest_available_date", "next_rebalance_date"],
            [{"latest_available_date": "2026-05-10", "next_rebalance_date": next_rebalance_date}],
        )
        self._write_rows(
            trend_history_path,
            ["trend_calc_date", "trend_score"],
            [{"trend_calc_date": "2026-05-10", "trend_score": -0.05}],
        )
        freshness_path.parent.mkdir(parents=True, exist_ok=True)
        freshness_path.write_text(
            json.dumps({"latest_closed_utc_date": "2026-05-10", "status": "ok", "errors": []}),
            encoding="utf-8",
        )
        benchmark_rows = []
        base_close = 90000.0
        for idx, stamp in enumerate(pd.date_range("2023-01-01", "2026-05-10", freq="D")):
            benchmark_rows.append({"date": stamp.strftime("%Y-%m-%d"), "close": base_close + idx * 100.0})
        self._write_rows(benchmark_path, ["date", "close"], benchmark_rows)

    def _seed_current_phase68g_baseline_bundle(self, root: Path) -> None:
        self._seed_stale_phase68g_baseline_bundle(
            root,
            source_day="2026-05-10",
            next_rebalance_date="2026-05-10",
        )

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

    def test_data_health_accepts_etf_weekend_carry_forward_without_fake_panel_row(self):
        root = self._make_case_root()
        try:
            snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
            panel_path = (
                root
                / "outputs"
                / "research_os"
                / "dev_only"
                / "non_authoritative_btc_etf_flow_daily_panel"
                / "btc_etf_flow_daily_panel.csv"
            )
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "current_strategy_snapshot",
                        "strategy_version": data_health_common.ETF_FLOW_LIVE_STRATEGY_VERSION,
                        "closed_day": "2026-05-10",
                        "source_inputs": {
                            "etf_flow_evidence_window": {
                                "start_date": "2024-01-12",
                                "end_date": "2026-05-10",
                            },
                            "etf_panel_materialization": {
                                "actual_latest_source_session_day": "2026-05-08",
                                "actual_latest_causal_available_day": "2026-05-09",
                                "active_source_session_day": "2026-05-08",
                                "active_source_causal_available_day": "2026-05-09",
                                "materialized_closed_day": "2026-05-10",
                                "carry_forward_days_applied": 1,
                                "evaluation_mode": "carry_forward_last_valid_etf_state",
                                "carry_forward_reason": "no_intermediate_us_trading_sessions",
                                "synthetic_source_rows_added": 0,
                                "d_plus_1_source_contract_ok": True,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            self._write_rows(
                panel_path,
                [
                    "date",
                    "us_trading_session_date",
                    "aggregate_net_flow_usd",
                    "daily_causal_ready",
                    "probe_input_ready_flag",
                ],
                [
                    {
                        "date": "2026-05-08",
                        "us_trading_session_date": "2026-05-07",
                        "aggregate_net_flow_usd": 1.0,
                        "daily_causal_ready": True,
                        "probe_input_ready_flag": True,
                    },
                    {
                        "date": "2026-05-09",
                        "us_trading_session_date": "2026-05-08",
                        "aggregate_net_flow_usd": 2.0,
                        "daily_causal_ready": True,
                        "probe_input_ready_flag": True,
                    },
                ],
            )
            csv_meta, csv_error = data_health_common.load_csv_meta(panel_path)
            self.assertIsNone(csv_error)
            self.assertEqual(
                data_health_common.resolve_actual_last_date_for_csv(
                    "research_btc_etf_flow_daily_panel_csv",
                    csv_meta or {},
                    root=root,
                ),
                "2026-05-10",
            )
            self.assertEqual(
                data_health_common.resolve_actual_last_date_for_json(
                    "research_btc_etf_flow_daily_panel_quality",
                    {
                        "status": "passed",
                        "panel_end_causal_btc_utc_day": "2026-05-09",
                    },
                    root=root,
                    path_overrides={},
                ),
                "2026-05-10",
            )
            with panel_path.open(newline="", encoding="utf-8") as handle:
                physical_rows = list(csv.DictReader(handle))
            self.assertEqual(physical_rows[-1]["date"], "2026-05-09")
            self.assertNotIn("2026-05-10", {row["date"] for row in physical_rows})
            snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(
                snapshot_payload["source_inputs"]["etf_flow_evidence_window"]["start_date"],
                "2024-01-12",
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

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

        root = self._make_case_root()
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
            ), mock.patch.object(
                build_current_strategy_snapshot,
                "_maybe_rebuild_phase68g_baseline_dependency_for_btc",
                return_value={"status": "current", "target_closed_day": "2026-05-10"},
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
            shutil.rmtree(root, ignore_errors=True)

    def test_phase68g_baseline_dependency_materialization_reaches_fresh_closed_day(self):
        root = self._make_case_root()
        try:
            self._seed_stale_phase68g_baseline_bundle(root)

            adapter = Phase68g66g1p25xCandidateAdapter()
            inputs = adapter.load_inputs(root=root, materialize_to_canonical_closed_day=True)
            timeseries = adapter.build_timeseries(inputs)

            self.assertEqual(inputs["source_closed_day"], "2026-04-30")
            self.assertEqual(inputs["closed_day"], "2026-05-10")
            self.assertEqual(inputs["paper_last_day"], "2026-04-30")
            self.assertEqual(inputs["paper_materialization"]["materialized_closed_day"], "2026-05-10")
            self.assertEqual(inputs["paper_materialization"]["carry_forward_rows_added"], 10)
            self.assertEqual(str(timeseries["date"].iloc[-1]), "2026-05-10")
            self.assertTrue(timeseries.tail(10)["cash_day"].astype(bool).all())
            self.assertTrue(timeseries.tail(10)["turnover"].eq(0.0).all())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_build_path_materializes_real_btc_persistence_dependency_from_stale_phase68g_bundle(self):
        root = self._make_case_root()
        try:
            self._seed_stale_phase68g_baseline_bundle(root)
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
            self._write_rows(
                paper_path,
                ["date", "strategy_version"],
                [{"date": "2026-04-30", "strategy_version": "phase68g_btc_persistence_10d_early_risk_075"}],
            )
            self._write_rows(
                summary_path,
                ["model", "latest_available_date", "total_return_pct"],
                [
                    {
                        "model": "phase68g_btc_persistence_10d_early_risk_075",
                        "latest_available_date": "2026-04-30",
                        "total_return_pct": "0.0",
                    }
                ],
            )

            with mock.patch.object(
                Phase68gBtcPersistence10dEarlyRisk075Adapter,
                "build_snapshot_metrics",
                return_value={
                    "total_return_pct_net": 0.0,
                    "latest_available_date": "2026-05-10",
                },
            ):
                result = build_current_strategy_snapshot._maybe_materialize_btc_persistence_dependency(
                    strategy_model=build_current_strategy_snapshot.ETF_FLOW_CANDIDATE_ID,
                    root=root,
                )

            self.assertEqual(result["status"], "materialized")
            self.assertEqual(result["target_closed_day"], "2026-05-10")
            self.assertEqual(result["previous_paper_last_day"], "2026-04-30")
            self.assertEqual(result["paper_last_day"], "2026-05-10")
            with paper_path.open(newline="", encoding="utf-8") as handle:
                paper_rows = list(csv.DictReader(handle))
            with summary_path.open(newline="", encoding="utf-8") as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertEqual(paper_rows[-1]["date"], "2026-05-10")
            self.assertEqual(summary_rows[-1]["latest_available_date"], "2026-05-10")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_build_path_rebuilds_phase68g_baseline_when_stale_source_reaches_rebalance_boundary(self):
        root = self._make_case_root()
        try:
            self._seed_stale_phase68g_baseline_bundle(root, next_rebalance_date="2026-05-10")
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
            self._write_rows(
                paper_path,
                ["date", "strategy_version"],
                [{"date": "2026-04-30", "strategy_version": "phase68g_btc_persistence_10d_early_risk_075"}],
            )
            self._write_rows(
                summary_path,
                ["model", "latest_available_date", "total_return_pct"],
                [
                    {
                        "model": "phase68g_btc_persistence_10d_early_risk_075",
                        "latest_available_date": "2026-04-30",
                        "total_return_pct": "0.0",
                    }
                ],
            )

            def fake_rebuild(*, root: Path, target_closed_day: str) -> dict[str, object]:
                self.assertEqual(target_closed_day, "2026-05-10")
                self._seed_current_phase68g_baseline_bundle(root)
                return {
                    "status": "rebuilt",
                    "target_closed_day": target_closed_day,
                    "paper_path": str(
                        root
                        / "outputs"
                        / "execution"
                        / "app_exports"
                        / "phase68g_66g_1p25x_candidate_paper.csv"
                    ),
                    "summary_path": str(
                        root
                        / "outputs"
                        / "execution"
                        / "app_exports"
                        / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
                    ),
                }

            with mock.patch.object(
                build_current_strategy_snapshot,
                "_rebuild_phase68g_baseline_dependency_from_canonical_inputs",
                fake_rebuild,
            ), mock.patch.object(
                Phase68gBtcPersistence10dEarlyRisk075Adapter,
                "build_snapshot_metrics",
                return_value={
                    "total_return_pct_net": 0.0,
                    "latest_available_date": "2026-05-10",
                },
            ):
                result = build_current_strategy_snapshot._maybe_materialize_btc_persistence_dependency(
                    strategy_model=build_current_strategy_snapshot.ETF_FLOW_CANDIDATE_ID,
                    root=root,
                )

            self.assertEqual(result["status"], "materialized")
            self.assertEqual(result["target_closed_day"], "2026-05-10")
            self.assertEqual(result["previous_paper_last_day"], "2026-04-30")
            self.assertEqual(result["paper_last_day"], "2026-05-10")
            self.assertEqual(
                result["phase68g_baseline_dependency"]["status"],
                "rebuilt",
            )
            self.assertEqual(
                result["phase68g_baseline_dependency"]["trigger"],
                "stale_baseline_crossed_rebalance_boundary",
            )
            with paper_path.open(newline="", encoding="utf-8") as handle:
                paper_rows = list(csv.DictReader(handle))
            with summary_path.open(newline="", encoding="utf-8") as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertEqual(paper_rows[-1]["date"], "2026-05-10")
            self.assertEqual(summary_rows[-1]["latest_available_date"], "2026-05-10")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
