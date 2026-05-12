import ast
import math
import unittest
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from scripts.execution.materialize_execution_app_exports import (
    build_dashboard_public_chart_timeseries_contract,
    build_dashboard_public_status_contract,
    build_dashboard_public_status_quality,
    build_runtime_public_status_contract,
)


ROOT = Path(__file__).resolve().parents[1]
APP_PY_PATH = ROOT / "app.py"


def load_app_symbols(*function_names: str) -> dict[str, object]:
    source = APP_PY_PATH.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(APP_PY_PATH))
    selected_nodes = []
    wanted_assignments = {
        "ETF_FLOW_PUBLIC_STRATEGY_VERSION",
        "ETF_FLOW_PUBLIC_EVIDENCE_START_DATE",
    }
    for node in module.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id in wanted_assignments
                for target in node.targets
            ):
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in function_names:
            selected_nodes.append(node)

    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    namespace: dict[str, object] = {
        "Any": Any,
        "date": date,
        "pd": pd,
        "go": go,
        "make_subplots": make_subplots,
        "math": math,
        "t": lambda lang, key: {
            "sk": {
                "na": "Nedostupne",
                "production_state_in_market": "V trhu",
                "production_state_out_of_market": "Mimo trhu",
                "production_chart_legend": "Model",
                "production_chart_btc_legend": "BTC baseline",
                "production_chart_exposure_legend": "Modelový signál",
                "production_chart_exposure_axis": "Modelový signál",
                "production_hover_date": "Datum",
                "production_hover_index": "Kapitalovy index",
                "production_hover_return_net": "Denny pohyb strategie",
                "production_hover_market_state": "Modelovy stav",
                "production_hover_authorized_exposure": "Modelový signál",
                "production_hover_candidate_asset": "Preferovane aktivum",
                "production_hover_btc_index": "BTC index",
                "production_hover_btc_return": "Denny pohyb BTC",
                "production_hover_btc_close": "BTC close",
                "production_hover_market_state_in": "SIGNAL AKTIVNY",
                "production_hover_market_state_out": "SIGNAL CASH",
                "production_chart_current_prefix": "Aktualne",
                "chart_performance_axis": "Index",
            },
            "en": {
                "na": "Unavailable",
                "production_state_in_market": "In market",
                "production_state_out_of_market": "Out of market",
                "production_chart_legend": "Strategy capital",
                "production_chart_btc_legend": "BTC baseline",
                "production_chart_exposure_legend": "Model signal",
                "production_chart_exposure_axis": "Model signal",
                "production_hover_date": "Date",
                "production_hover_index": "Capital index",
                "production_hover_return_net": "Strategy daily move",
                "production_hover_market_state": "Model state",
                "production_hover_authorized_exposure": "Model signal",
                "production_hover_candidate_asset": "Preferred asset",
                "production_hover_btc_index": "BTC index",
                "production_hover_btc_return": "BTC daily move",
                "production_hover_btc_close": "BTC close",
                "production_hover_market_state_in": "SIGNAL IN MARKET",
                "production_hover_market_state_out": "SIGNAL OUT OF MARKET",
                "production_chart_current_prefix": "Current",
                "chart_performance_axis": "Index",
            },
        }[lang][key],
    }
    exec(compile(extracted_module, str(APP_PY_PATH), "exec"), namespace)
    return namespace


class TestAppPublicStatusContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = load_app_symbols(
            "as_float",
            "as_bool",
            "resolve_main_metrics_for_display",
            "_to_bool_series",
            "_compute_total_return_pct",
            "_compute_cagr_pct",
            "_compute_cagr_since",
            "_compute_average_annual_period_return_pct",
            "_compute_max_drawdown_pct",
            "_annualized_sharpe_from_daily_returns",
            "_annualized_sortino_from_daily_returns",
            "normalize_iso_day_optional",
            "resolve_etf_public_evidence_start_day",
            "build_public_homepage_performance_context",
            "first_present_value",
            "get_nested_value",
            "_first_numeric_value",
            "resolve_real_account_exposure_state",
            "resolve_dashboard_public_status_state",
            "filter_from_year",
            "rebase_series",
            "production_chart_authorized_equity_series",
            "production_chart_authorized_gross_return_series",
            "production_chart_authorized_return_series",
            "production_chart_authorized_exposure_series",
            "production_chart_real_account_equity_series",
            "production_chart_real_account_return_series",
            "production_chart_real_account_exposure_series",
            "production_chart_transition_cost_series",
            "production_chart_btc_index_series",
            "production_chart_btc_return_series",
            "production_chart_source_alignment_issues",
            "product_asset_label_nominative",
            "production_market_state_label_from_values",
            "make_production_equity_chart",
        )

    def test_etf_public_performance_window_starts_at_etf_evidence_start(self):
        build_context = self.__class__.ns["build_public_homepage_performance_context"]
        frame = pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    [
                        "2023-01-01",
                        "2024-01-11",
                        "2024-01-12",
                        "2024-12-31",
                        "2025-01-01",
                        "2025-12-31",
                        "2026-01-01",
                    ]
                ),
                "authorized_return_net": [0.50, 0.20, 0.10, 0.20, 0.50, 0.00, 0.00],
                "cash_day": [True, True, False, False, False, False, False],
                "btc_day": [False, False, True, True, True, True, True],
                "asset_transition_day": [False, False, True, False, False, False, False],
            }
        )
        snapshot = {
            "strategy_version": "phase68g_etf_flow_impulse_early_risk_cooldown_15",
            "metrics": {"model": "phase68g_etf_flow_impulse_early_risk_cooldown_15"},
            "source_inputs": {
                "etf_flow_evidence_window": {
                    "start_date": "2024-01-12",
                    "end_date": "2026-05-10",
                }
            },
        }

        context = build_context(snapshot, frame)

        self.assertEqual(context["start_day"], "2024-01-12")
        self.assertEqual(context["public_window_label_key"], "since_etf_start")
        self.assertEqual(context["public_window_metric_key"], "public_window_cagr_pct")
        self.assertEqual(
            context["timeseries_df"]["ts"].dt.strftime("%Y-%m-%d").tolist(),
            ["2024-01-12", "2024-12-31", "2025-01-01", "2025-12-31", "2026-01-01"],
        )
        self.assertAlmostEqual(context["top_performance_metrics"]["cagr_pct"], 20.5, places=4)
        self.assertNotEqual(
            context["top_performance_metrics"]["cagr_pct"],
            context["top_performance_metrics"]["public_window_cagr_pct"],
        )
        self.assertEqual(
            context["top_performance_metrics"]["public_window_cagr_pct"],
            context["top_performance_metrics"]["since2023_cagr_pct"],
        )

    def test_real_account_card_stays_cash_when_intent_and_gate_are_cash_blocked(self):
        resolve_state = self.__class__.ns["resolve_real_account_exposure_state"]

        state = resolve_state(
            account_snapshot_view={"positions_count": 0, "open_position": None},
            dry_run_decision_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            real_order_gate_payload={
                "target_asset": "CASH",
                "status": "blocked",
                "would_place_real_order": False,
                "production_signal_context": {
                    "candidate_asset": "BTC",
                    "model_candidate_exposure": 0.75,
                    "target_exposure": 0.0,
                },
            },
            production_snapshot={
                "candidate_asset": "BTC",
                "model_candidate_exposure": 0.75,
                "execution_intent": {"target_asset": "CASH", "target_exposure": 0.0},
            },
            lang="sk",
        )

        self.assertTrue(state["is_out_of_market"])
        self.assertEqual(state["asset"], "CASH")
        self.assertEqual(state["exposure"], 0.0)
        self.assertEqual(state["value"], "Mimo trhu / 0.00x")
        self.assertEqual(state["target_asset"], "CASH")
        self.assertFalse(state["would_place_real_order"])

    def test_production_chart_separates_real_cash_account_from_model_signal(self):
        resolve_state = self.__class__.ns["resolve_real_account_exposure_state"]
        make_chart = self.__class__.ns["make_production_equity_chart"]
        state = resolve_state(
            account_snapshot_view={"positions_count": 0, "open_position": None},
            dry_run_decision_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            real_order_gate_payload={
                "target_asset": "CASH",
                "status": "blocked",
                "would_place_real_order": False,
                "production_signal_context": {
                    "candidate_asset": "BTC",
                    "model_candidate_exposure": 0.75,
                    "target_exposure": 0.0,
                },
            },
            production_snapshot={
                "candidate_asset": "BTC",
                "model_candidate_exposure": 0.75,
                "execution_intent": {"target_asset": "CASH", "target_exposure": 0.0},
            },
            lang="sk",
        )
        frame = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-05-09", "2026-05-10"]),
                "authorized_equity": [100.0, 101.0],
                "btc_baseline_equity": [100.0, 102.0],
                "authorized_return_net": [0.0, 0.01],
                "btc_return": [0.0, 0.02],
                "btc_close": [100000.0, 102000.0],
                "effective_market_exposure": [0.75, 0.75],
                "trend_permission_active": [True, True],
                "candidate_asset": ["BTC", "BTC"],
            }
        )

        fig = make_chart(
            frame,
            2026,
            "sk",
            "Model",
            "Modelový vývoj vs BTC",
            real_account_exposure_state=state,
            chart_view="model",
        )

        annotation_text = fig.layout.annotations[0].text
        hover_template = fig.data[0].hovertemplate
        self.assertEqual(fig.layout.title.text, "Modelový vývoj vs BTC")
        self.assertEqual(fig.data[0].name, "Model")
        self.assertIn("Reálny účet: CASH / Mimo trhu / 0.00x", annotation_text)
        self.assertIn("Modelový signál: BTC / 0.75x", annotation_text)
        self.assertIn("Reálny účet: CASH / Mimo trhu / 0.00x", fig.data[0].customdata[-1][4])
        self.assertIn("Modelový signál: BTC / 0.75x", fig.data[0].customdata[-1][5])
        self.assertIn("Modelovy stav", hover_template)
        self.assertIn("%{customdata[5]}", hover_template)
        self.assertIn("%{customdata[4]}", hover_template)
        self.assertNotIn("Stav trhu", hover_template)
        self.assertNotIn("V TRHU", hover_template)
        self.assertEqual(len(fig.data), 3)
        self.assertEqual(fig.data[2].name, "Modelový signál")
        self.assertEqual(list(fig.data[2].y), [0.75, 0.75])

    def test_production_chart_strip_uses_authorized_exposure_not_candidate_signal(self):
        make_chart = self.__class__.ns["make_production_equity_chart"]
        frame = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-05-09", "2026-05-10"]),
                "authorized_equity": [100.0, 99.85],
                "btc_baseline_equity": [100.0, 101.0],
                "authorized_return_net": [0.0, -0.0015],
                "authorized_return_gross": [0.0, 0.0],
                "btc_return": [0.0, 0.01],
                "btc_close": [100000.0, 101000.0],
                "effective_market_exposure": [0.0, 0.0],
                "model_candidate_exposure": [1.0, 0.75],
                "trend_permission_active": [False, False],
                "candidate_asset": ["BASE", "BTC"],
                "fees_daily": [0.0, 0.00045],
                "funding_daily": [0.0, 0.00025],
                "borrow_cost_daily": [0.0, 0.00030],
                "slippage_cost_daily": [0.0, 0.00050],
                "asset_transition_day": [False, True],
            }
        )

        fig = make_chart(
            frame,
            2026,
            "en",
            "Model",
            "Model vs BTC",
            chart_view="model",
        )

        self.assertEqual(fig.data[2].name, "Model signal")
        self.assertEqual(list(fig.data[2].y), [0.0, 0.0])

    def test_production_chart_source_alignment_accepts_zero_exposure_cost_only_move(self):
        issues_fn = self.__class__.ns["production_chart_source_alignment_issues"]
        frame = pd.DataFrame(
            {
                "date": ["2026-05-09", "2026-05-10"],
                "authorized_equity": [1.0, 0.9985],
                "authorized_return_gross": [0.0, 0.0],
                "authorized_return_net": [0.0, -0.0015],
                "effective_market_exposure": [0.0, 0.0],
                "asset_transition_day": [False, True],
                "fees_daily": [0.0, 0.00045],
                "funding_daily": [0.0, 0.00025],
                "borrow_cost_daily": [0.0, 0.00030],
                "slippage_cost_daily": [0.0, 0.00050],
            }
        )

        self.assertEqual(issues_fn(frame), [])

    def test_production_chart_source_alignment_rejects_positive_market_return_while_zero_exposure(self):
        issues_fn = self.__class__.ns["production_chart_source_alignment_issues"]
        frame = pd.DataFrame(
            {
                "date": ["2026-05-10"],
                "authorized_equity": [1.01],
                "authorized_return_gross": [0.01],
                "authorized_return_net": [0.01],
                "effective_market_exposure": [0.0],
                "asset_transition_day": [False],
                "fees_daily": [0.0],
                "funding_daily": [0.0],
                "borrow_cost_daily": [0.0],
                "slippage_cost_daily": [0.0],
            }
        )

        issues = issues_fn(frame)
        self.assertTrue(
            any("non-zero authorized_return_gross" in issue for issue in issues),
            issues,
        )
        self.assertTrue(
            any("positive authorized_return_net" in issue for issue in issues),
            issues,
        )

    def test_production_chart_source_alignment_rejects_unexplained_zero_exposure_net_move(self):
        issues_fn = self.__class__.ns["production_chart_source_alignment_issues"]
        frame = pd.DataFrame(
            {
                "date": ["2026-05-10"],
                "authorized_equity": [0.998],
                "authorized_return_gross": [0.0],
                "authorized_return_net": [-0.002],
                "effective_market_exposure": [0.0],
                "asset_transition_day": [True],
                "fees_daily": [0.0],
                "funding_daily": [0.0],
                "borrow_cost_daily": [0.0],
                "slippage_cost_daily": [0.001],
            }
        )

        issues = issues_fn(frame)
        self.assertTrue(
            any("move without matching explicit transition cost" in issue for issue in issues),
            issues,
        )

    def test_dashboard_public_status_contract_exact_schema_for_cash_blocked_account(self):
        contract = build_dashboard_public_status_contract(
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
            generated_at_utc="2026-05-11T08:15:00Z",
        )

        self.assertEqual(
            set(contract.keys()),
            {
                "schema_version",
                "generated_at_utc",
                "closed_day",
                "real_account",
                "execution",
                "model_signal",
                "model_performance",
                "data_health",
                "live_market_state",
                "public_labels_sk",
            },
        )
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(contract["generated_at_utc"], "2026-05-11T08:15:00Z")
        self.assertEqual(contract["closed_day"], "2026-05-10")
        self.assertEqual(
            contract["real_account"],
            {
                "asset": "CASH",
                "position_label_sk": "Mimo trhu",
                "exposure_x": 0.0,
                "in_market": False,
                "account_equity_usd": 39.475466,
                "available_balance_usd": 39.475466,
            },
        )
        self.assertEqual(
            contract["execution"],
            {
                "target_asset": "CASH",
                "target_size_pct": 0.0,
                "gate_status": "blocked",
                "would_place_real_order": False,
                "live_order_sent": False,
            },
        )
        self.assertEqual(
            contract["model_signal"],
            {
                "preferred_asset": "BTC",
                "exposure_x": 0.75,
                "label_sk": "Modelový signál",
                "not_real_wallet_exposure": True,
            },
        )
        self.assertEqual(contract["model_performance"]["account_24h_pct"], 0.0)
        self.assertEqual(contract["model_performance"]["btc_24h_pct"], -0.5)
        self.assertEqual(contract["model_performance"]["account_vs_btc_24h_pct"], 0.5)
        self.assertEqual(contract["model_performance"]["public_average_annual_growth_pct"], 216.86)
        self.assertEqual(contract["model_performance"]["since_etf_start_cagr_pct"], 322.34)
        self.assertEqual(contract["model_performance"]["since2025_cagr_pct"], 251.64)
        self.assertEqual(
            contract["data_health"],
            {
                "reference_closed_day": None,
                "overall_status": "unknown",
                "block_app": False,
                "block_execution": False,
            },
        )
        self.assertEqual(
            contract["live_market_state"],
            {
                "btc_24h_pct": -0.5,
                "btc_24h_pct_source": "published_snapshot",
                "btc_24h_pct_expected_live_source": "live_ticker",
                "btc_24h_pct_snapshot_is_not_live": True,
                "published_snapshot_btc_24h_pct": -0.5,
                "account_24h_pct": 0.0,
                "account_vs_btc_24h_pct": 0.5,
            },
        )
        self.assertEqual(
            contract["public_labels_sk"],
            {
                "account_24h": "Účet 24h",
                "account_vs_btc": "Účet vs BTC",
                "real_account": "Reálny účet",
                "model_signal": "Modelový signál",
            },
        )

    def test_live_market_state_prefers_live_btc_input_without_overwriting_snapshot_performance(self):
        contract = build_dashboard_public_status_contract(
            account_summary={
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
            },
            intent_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            dry_run_payload={"target_asset": "BTC", "target_size_pct": 0.75},
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
            },
            production_timeseries_last_row={
                "date": "2026-05-10",
                "btc_return": -0.005,
            },
            live_market_payload={
                "btc_24h_pct": 1.9,
                "btc_24h_pct_source": "live_ticker",
            },
        )

        self.assertEqual(contract["model_performance"]["btc_24h_pct"], -0.5)
        self.assertEqual(contract["model_performance"]["account_24h_pct"], 0.0)
        self.assertEqual(contract["model_performance"]["account_vs_btc_24h_pct"], 0.5)
        self.assertEqual(contract["live_market_state"]["btc_24h_pct"], 1.9)
        self.assertEqual(contract["live_market_state"]["btc_24h_pct_source"], "live_ticker")
        self.assertFalse(contract["live_market_state"]["btc_24h_pct_snapshot_is_not_live"])
        self.assertEqual(contract["live_market_state"]["published_snapshot_btc_24h_pct"], -0.5)
        self.assertEqual(contract["live_market_state"]["account_24h_pct"], 0.0)
        self.assertEqual(contract["live_market_state"]["account_vs_btc_24h_pct"], -1.9)

    def test_dashboard_public_status_state_resolver_uses_contract_only(self):
        resolve_public_state = self.__class__.ns["resolve_dashboard_public_status_state"]
        state = resolve_public_state(
            {
                "schema_version": 1,
                "generated_at_utc": "2026-05-11T08:15:00Z",
                "closed_day": "2026-05-10",
                "real_account": {
                    "asset": "CASH",
                    "position_label_sk": "Mimo trhu",
                    "exposure_x": 0.0,
                    "in_market": False,
                    "account_equity_usd": 39.475466,
                    "available_balance_usd": 39.475466,
                },
                "execution": {
                    "target_asset": "CASH",
                    "target_size_pct": 0.0,
                    "gate_status": "blocked",
                    "would_place_real_order": False,
                    "live_order_sent": False,
                },
                "model_signal": {
                    "preferred_asset": "BTC",
                    "exposure_x": 0.75,
                    "label_sk": "Modelový signál",
                    "not_real_wallet_exposure": True,
                },
                "model_performance": {
                    "account_24h_pct": 0.0,
                    "btc_24h_pct": -0.5,
                    "account_vs_btc_24h_pct": 0.5,
                    "public_average_annual_growth_pct": 216.86,
                    "since_etf_start_cagr_pct": 322.34,
                    "since2025_cagr_pct": 251.64,
                },
                "data_health": {
                    "reference_closed_day": "2026-05-10",
                    "overall_status": "ok",
                    "block_app": False,
                    "block_execution": False,
                },
                "live_market_state": {
                    "btc_24h_pct": -0.5,
                    "btc_24h_pct_source": "published_snapshot",
                    "btc_24h_pct_expected_live_source": "live_ticker",
                    "btc_24h_pct_snapshot_is_not_live": True,
                    "published_snapshot_btc_24h_pct": -0.5,
                    "account_24h_pct": 0.0,
                    "account_vs_btc_24h_pct": 0.5,
                },
                "public_labels_sk": {
                    "account_24h": "Účet 24h",
                    "account_vs_btc": "Účet vs BTC",
                    "real_account": "Reálny účet",
                    "model_signal": "Modelový signál",
                },
            },
            "sk",
        )

        real_state = state["real_account_exposure_state"]
        model_state = state["model_signal_state"]
        performance_state = state["model_performance_state"]
        self.assertEqual(real_state["asset"], "CASH")
        self.assertEqual(real_state["value"], "Mimo trhu / 0.00x")
        self.assertEqual(real_state["label_sk"], "Reálny účet")
        self.assertEqual(model_state["preferred_asset"], "BTC")
        self.assertEqual(model_state["exposure_x"], 0.75)
        self.assertEqual(model_state["label_sk"], "Modelový signál")
        self.assertEqual(performance_state["account_24h_pct"], 0.0)
        self.assertEqual(performance_state["btc_24h_pct"], -0.5)
        self.assertEqual(performance_state["account_vs_btc_24h_pct"], 0.5)
        self.assertEqual(performance_state["btc_24h_pct_source_label"], "closed_day_snapshot")

    def test_dashboard_public_chart_keeps_cash_account_flat_without_real_history(self):
        contract = build_dashboard_public_status_contract(
            account_summary={
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
            },
            intent_payload={"target_asset": "CASH", "target_size_pct": 0.0},
            dry_run_payload={"target_asset": "BTC", "target_size_pct": 0.75},
            gate_payload={
                "target_asset": "CASH",
                "status": "blocked",
                "would_place_real_order": False,
            },
            production_snapshot_payload={
                "closed_day": "2026-05-10",
                "candidate_asset": "BTC",
                "model_candidate_exposure": 0.75,
            },
            production_timeseries_last_row={
                "date": "2026-05-10",
                "btc_return": 0.02,
                "authorized_return_net": 0.0,
            },
            data_health_payload={
                "reference_closed_day_utc": "2026-05-10",
                "summary": {
                    "overall_status": "ok",
                    "block_app": False,
                    "block_execution": False,
                },
            },
        )
        production_rows = [
            {
                "date": "2026-05-09",
                "authorized_equity": "1.0",
                "btc_baseline_equity": "1.0",
                "authorized_return_net": "0.0",
                "authorized_return_gross": "0.0",
                "btc_return": "0.0",
                "effective_market_exposure": "0.75",
            },
            {
                "date": "2026-05-10",
                "authorized_equity": "1.01",
                "btc_baseline_equity": "1.02",
                "authorized_return_net": "0.01",
                "authorized_return_gross": "0.01",
                "btc_return": "0.02",
                "effective_market_exposure": "0.75",
            },
        ]

        chart_contract = build_dashboard_public_chart_timeseries_contract(
            production_timeseries_rows=production_rows,
            dashboard_public_status=contract,
        )
        quality = build_dashboard_public_status_quality(
            dashboard_public_status=contract,
            chart_rows=chart_contract["rows"],
            production_timeseries_rows=production_rows,
            account_summary={
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
            },
        )

        self.assertEqual(chart_contract["chart_scope"], "real_account_flat_no_history")
        self.assertEqual([row["real_account_index"] for row in chart_contract["rows"]], [1.0, 1.0])
        self.assertEqual([row["real_account_exposure_x"] for row in chart_contract["rows"]], [0.0, 0.0])
        self.assertEqual([row["real_account_return_net"] for row in chart_contract["rows"]], [0.0, 0.0])
        self.assertEqual([row["model_authorized_exposure_x"] for row in chart_contract["rows"]], [0.75, 0.75])
        self.assertEqual(quality["status"], "ok")

    def test_homepage_prefers_dashboard_public_status_before_real_account_fallback(self):
        source = APP_PY_PATH.read_text(encoding="utf-8")
        start_marker = 'dashboard_public_status = load_dashboard_public_status_for_app('
        end_marker = 'strategy_signal_exposure = _first_numeric_value('
        start = source.index(start_marker)
        end = source.index(end_marker, start)
        block = source[start:end]

        self.assertIn('resolve_dashboard_public_status_state(', block)
        self.assertIn('dashboard_public_state.get("real_account_exposure_state")', block)
        self.assertIn('if not real_account_exposure_state:', block)
        self.assertNotIn('production_snapshot.get("actual_held_asset")', block)
        self.assertNotIn('production_snapshot.get("current_asset")', block)
        self.assertNotIn('production_snapshot.get("effective_market_exposure")', block)

    def test_homepage_model_signal_uses_cis_without_raw_exposure_fallbacks(self):
        source = APP_PY_PATH.read_text(encoding="utf-8")
        start_marker = 'strategy_signal_exposure = _first_numeric_value('
        end_marker = 'state_story = build_homepage_state_story('
        start = source.index(start_marker)
        end = source.index(end_marker, start)
        block = source[start:end]

        self.assertIn('runtime_model_signal_state.get("exposure_x")', block)
        self.assertNotIn('production_snapshot.get("model_candidate_exposure")', block)
        self.assertNotIn('production_snapshot.get("effective_market_exposure")', block)
        self.assertNotIn('production_signal_context", "model_candidate_exposure"', block)

    def test_homepage_default_chart_reads_cis_real_account_timeseries_and_keeps_model_view(self):
        source = APP_PY_PATH.read_text(encoding="utf-8")
        start_marker = 'dashboard_public_chart_timeseries_df = load_dashboard_public_chart_timeseries_frame('
        end_marker = 'st.markdown(f"### {t(lang, \'performance_title\')}")'
        start = source.index(start_marker)
        end = source.index(end_marker, start)
        block = source[start:end]

        self.assertIn("LOCAL_DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH", block)
        self.assertIn("years = available_years_from_frames([dashboard_public_chart_timeseries_df])", block)
        self.assertIn("timeseries_df=dashboard_public_chart_timeseries_df", block)
        self.assertIn("main_label=real_account_card_label", block)
        self.assertIn('chart_view="real_account"', block)
        self.assertIn("with st.expander(model_chart_title", block)
        self.assertIn('chart_view="model"', block)
        default_block = block[: block.index("with st.expander(model_chart_title")]
        self.assertNotIn("build_production_chart_current_state_note", default_block)

    def test_homepage_account_card_does_not_show_model_equity_as_real_pnl(self):
        source = APP_PY_PATH.read_text(encoding="utf-8")
        start_marker = "home_cards = ["
        end_marker = "home_cols = st.columns(len(home_cards))"
        start = source.index(start_marker)
        end = source.index(end_marker, start)
        block = source[start:end]

        self.assertIn('real_account_exposure_state["value"]', block)
        self.assertNotIn("model_equity", block)
        self.assertNotIn("paper_equity", block)
        self.assertNotIn("account_equity_usd", block)

    def test_dashboard_public_chart_defaults_to_cis_real_account_columns_and_keeps_lower_strip(self):
        make_chart = self.__class__.ns["make_production_equity_chart"]
        frame = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-05-09", "2026-05-10"]),
                "model_index": [10.0, 11.0],
                "btc_index": [20.0, 21.0],
                "model_authorized_exposure_x": [0.75, 0.75],
                "model_authorized_return_net": [0.0, 0.10],
                "model_authorized_return_gross": [0.0, 0.10],
                "model_transition_cost": [0.0, 0.0],
                "real_account_index": [1.0, 1.0],
                "real_account_exposure_x": [0.0, 0.0],
                "real_account_return_net": [0.0, 0.0],
                "real_account_vs_btc_return": [0.0, -0.05],
                "chart_scope": ["real_account_flat_no_history", "real_account_flat_no_history"],
                "authorized_equity": [999.0, 999.0],
                "btc_baseline_equity": [888.0, 888.0],
                "effective_market_exposure": [9.0, 9.0],
                "actual_held_asset": ["BTC", "BTC"],
                "current_asset": ["BTC", "BTC"],
            }
        )

        fig = make_chart(
            frame,
            2026,
            "en",
            "Real account",
            "Real account vs BTC",
            real_account_exposure_state={
                "asset": "CASH",
                "is_out_of_market": True,
                "state_text": "Out of market",
                "exposure_text": "0.00x",
            },
            model_signal_state={
                "preferred_asset": "BTC",
                "exposure_x": 0.75,
                "label_sk": "Modelovy signal",
            },
        )

        self.assertEqual(fig.data[0].name, "Real account")
        self.assertEqual(list(fig.data[0].y), [1.0, 1.0])
        self.assertEqual(list(fig.data[1].y), [1.0, 1.05])
        self.assertEqual(len(fig.data), 3)
        self.assertEqual(fig.data[2].name, "Real account")
        self.assertEqual(list(fig.data[2].y), [0.0, 0.0])
        self.assertIn("Real account: CASH / Out of market / 0.00x", fig.layout.annotations[0].text)
        self.assertNotIn("Model signal", fig.layout.annotations[0].text)

        model_fig = make_chart(
            frame,
            2026,
            "en",
            "Model",
            "Model vs BTC",
            model_signal_state={
                "preferred_asset": "BTC",
                "exposure_x": 0.75,
                "label_sk": "Modelovy signal",
            },
            chart_view="model",
        )

        self.assertEqual(list(model_fig.data[0].y), [1.0, 1.1])
        self.assertEqual(list(model_fig.data[1].y), [1.0, 1.05])
        self.assertEqual(len(model_fig.data), 3)
        self.assertEqual(model_fig.data[2].name, "Model signal")
        self.assertEqual(list(model_fig.data[2].y), [0.75, 0.75])

    def test_runtime_contract_separates_wallet_cash_from_model_btc_signal(self):
        contract = build_runtime_public_status_contract(
            account_summary={
                "current_position": "CASH",
                "positions_count": 0,
                "open_position": None,
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
                "candidate_asset": "BTC",
                "model_candidate_exposure": 0.75,
                "effective_market_exposure": 0.75,
                "actual_held_asset": "BTC",
                "current_asset": "BTC",
            },
        )

        real_state = contract["real_account_state"]
        model_state = contract["model_signal_state"]
        performance_state = contract["model_performance_state"]
        data_health_state = contract["data_health_state"]
        live_market_state = contract["live_market_state"]
        self.assertFalse(real_state["in_market"])
        self.assertEqual(real_state["asset"], "CASH")
        self.assertEqual(real_state["exposure_x"], 0.0)
        self.assertEqual(real_state["position_label_sk"], "Mimo trhu")
        self.assertEqual(real_state["gate_status"], "blocked")
        self.assertFalse(real_state["would_place_real_order"])
        self.assertEqual(real_state["source"], "wallet/intent/gate")
        self.assertEqual(real_state["intent_target_asset"], "CASH")
        self.assertEqual(real_state["intent_target_size_pct"], 0.0)
        self.assertEqual(model_state["preferred_asset"], "BTC")
        self.assertEqual(model_state["exposure_x"], 0.75)
        self.assertTrue(model_state["not_real_wallet_exposure"])
        self.assertEqual(model_state["label_sk"], "Modelový signál")
        self.assertEqual(performance_state["equity_curve_semantics"], "model/paper, never real account PnL")
        self.assertEqual(data_health_state["overall_status"], "unknown")
        self.assertFalse(data_health_state["block_app"])
        self.assertEqual(live_market_state["btc_24h_pct_source"], "published_snapshot")
        self.assertTrue(live_market_state["btc_24h_pct_snapshot_is_not_live"])


if __name__ == "__main__":
    unittest.main()
