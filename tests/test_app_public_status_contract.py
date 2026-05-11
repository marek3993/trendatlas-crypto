import ast
import math
import unittest
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


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
        "math": math,
        "t": lambda lang, key: {
            "sk": {
                "na": "Nedostupne",
                "production_state_in_market": "V trhu",
                "production_state_out_of_market": "Mimo trhu",
            },
            "en": {
                "na": "Unavailable",
                "production_state_in_market": "In market",
                "production_state_out_of_market": "Out of market",
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


if __name__ == "__main__":
    unittest.main()
