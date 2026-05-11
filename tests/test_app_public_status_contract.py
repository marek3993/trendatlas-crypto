import ast
import math
import unittest
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


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
                "production_chart_legend": "Strategia - kapital",
                "production_chart_btc_legend": "BTC baseline",
                "production_chart_exposure_legend": "Modelovy signal",
                "production_chart_exposure_axis": "Modelovy signal",
                "production_hover_date": "Datum",
                "production_hover_index": "Kapitalovy index",
                "production_hover_return_net": "Denny pohyb strategie",
                "production_hover_market_state": "Modelovy stav",
                "production_hover_authorized_exposure": "Modelovy signal",
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
            "filter_from_year",
            "rebase_series",
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
            "Strategia - kapital",
            "Vyvoj kapitalu strategie",
            real_account_exposure_state=state,
        )

        annotation_text = fig.layout.annotations[0].text
        hover_template = fig.data[0].hovertemplate
        self.assertIn("Realny ucet: Mimo trhu", annotation_text)
        self.assertIn("CASH", annotation_text)
        self.assertIn("Realna expozicia: 0.00x", annotation_text)
        self.assertIn("Model preferuje: BTC", annotation_text)
        self.assertIn("Modelovy signal: 0.75x", annotation_text)
        self.assertIn("Realny ucet: Mimo trhu / 0.00x | CASH", fig.data[0].customdata[-1])
        self.assertIn("Modelovy stav", hover_template)
        self.assertNotIn("Stav trhu", hover_template)
        self.assertNotIn("V TRHU", hover_template)


if __name__ == "__main__":
    unittest.main()
