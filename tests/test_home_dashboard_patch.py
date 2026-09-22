import ast
import unittest
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path

from deployment.home_dashboard_patch import build_patched_sources, verify_installed_sources


ROOT = Path(__file__).resolve().parents[1]
SANITIZED_PY = ROOT / "tests" / "fixtures" / "home_dashboard_trendatlas_payload_v1.py"
SNAPSHOT_JS = ROOT / "tests" / "fixtures" / "home_dashboard_app_status_v1.js"


class TestHomeDashboardPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.python_new, cls.js_new = build_patched_sources(
            SANITIZED_PY.read_bytes(), SNAPSHOT_JS.read_bytes(), verify_hash=False
        )

    def test_read_only_pi_snapshot_still_matches_patch_anchors_when_available(self):
        local_py = ROOT / "tmp" / "pi_home_dashboard_sanitized.py"
        local_js = ROOT / "tmp" / "pi_home_app_snapshot.js"
        if local_py.exists() and local_js.exists():
            build_patched_sources(local_py.read_bytes(), local_js.read_bytes(), verify_hash=False)

    def test_patch_is_narrow_and_removes_forbidden_wallet_inference(self):
        verify_installed_sources(self.python_new, self.js_new)
        source = self.python_new.decode("utf-8")
        js = self.js_new.decode("utf-8")
        self.assertNotIn('real_account_asset = "CASH" if real_is_cash else (target_asset or "n/a")', source)
        self.assertNotIn('trade_submission_state = "Blokované" if real_is_cash', source)
        self.assertNotIn('status.real_account_asset || status.target_asset', js)
        self.assertNotIn('status.real_account_exposure ?? status.target_exposure', js)
        self.assertNotIn("canonical Hyperliquid PnL", js)
        self.assertIn('"next_rebalance_review_utc": next_rebalance_review_utc', source)

    def test_no_action_cash_is_waiting_and_unknown_wallet_is_not_model(self):
        module = ast.parse(self.python_new.decode("utf-8"))
        node = next(item for item in module.body if isinstance(item, ast.FunctionDef) and item.name == "trendatlas_payload")
        extracted = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(extracted)

        paths = {
            "STRATEGY_SNAPSHOT_PATH": "snapshot",
            "DATA_HEALTH_PATH": "health",
            "STRATEGY_DIAGNOSTICS_PATH": "diagnostics",
            "ACCOUNT_SNAPSHOT_PATH": "account",
            "APP_RUNTIME_SNAPSHOT_PATH": "runtime",
            "DASHBOARD_PUBLIC_STATUS_PATH": "public",
            "EXECUTION_INTENT_PATH": "intent",
            "REAL_ORDER_GATE_PATH": "gate",
            "DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH": "chart",
        }
        documents = {
            "snapshot": {
                "closed_day": "2026-09-21",
                "candidate_asset": "AVAX",
                "model_candidate_exposure": 1.0,
                "trend_permission_active": False,
                "next_rebalance_date": "2026-09-27",
                "provenance": {"wait_condition": {"code": "candidate_entry_not_authorized"}},
            },
            "health": {"summary": {"overall_status": "ok", "block_execution": False}},
            "diagnostics": {"current_trade_state": {}},
            "account": {"summary": {"positions_count": 0, "current_position": "CASH"}},
            "runtime": {},
            "public": {
                "real_account": {"asset": "CASH", "exposure_x": 0.0, "position_label_sk": "Mimo trhu"},
                "execution": {"target_asset": "CASH", "target_size_pct": 0.0, "gate_status": "no_action", "would_place_real_order": False},
                "model_signal": {"preferred_asset": "AVAX", "exposure_x": 1.0},
            },
            "intent": {"target_asset": "CASH", "target_exposure": 0.0},
            "gate": {"status": "no_action", "would_place_real_order": False, "block_reasons": ["no_market_entry_authorized"]},
        }

        def safe_float(value, default=None):
            try:
                return float(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        namespace = {
            "CONFIG": paths,
            "read_json_file": lambda path: (documents[path], None),
            "cached_file": lambda *_: ([], None),
            "load_timeseries": lambda *_: [],
            "row_date": lambda row: None,
            "find_row_days_before": lambda *_: None,
            "percent_change": lambda *_: None,
            "safe_float": safe_float,
            "safe_bool": bool,
            "get_live_btc_price": lambda *_: {"live": False},
            "downsample": lambda rows, _: rows,
            "get_btc_24h_sparkline": lambda _: {"points": []},
            "wallet_payload": lambda _: {},
            "human_strategy_text": lambda *_: "",
            "HTTPStatus": HTTPStatus,
            "utc_now_iso": lambda: "2026-09-22T12:00:00Z",
            "date": date,
            "datetime": datetime,
            "timedelta": timedelta,
            "timezone": timezone,
        }
        exec(compile(extracted, "home_dashboard.py", "exec"), namespace)
        _, result = namespace["trendatlas_payload"]()
        state = result["state"]
        self.assertEqual(state["trade_submission_state"], "Čaká na signál")
        self.assertEqual(state["real_account_asset"], "CASH")
        self.assertEqual(state["real_account_exposure"], 0.0)
        self.assertIn("AVAX", state["signal_status"])
        self.assertIn("nepotvrdil", state["wait_reason"])
        self.assertEqual(state["next_rebalance_review_utc"], "28.09.2026 00:10 UTC")
        self.assertIn("Žiadna bezpečnostná blokácia", state["blocking_gate"])

        documents["account"] = {"summary": {}}
        documents["public"] = {}
        documents["runtime"] = {}
        documents["intent"] = {"target_asset": "AVAX", "target_exposure": 1.0}
        documents["gate"] = {"status": "blocked", "would_place_real_order": False, "block_reasons": ["stale_signal"]}
        _, result = namespace["trendatlas_payload"]()
        state = result["state"]
        self.assertEqual(state["trade_submission_state"], "Blokované")
        self.assertEqual(state["real_account_asset"], "Nedostupné")
        self.assertIsNone(state["real_account_exposure"])
        self.assertIn("Neaktuálny signál", state["blocking_gate"])
        self.assertNotIn("stale_signal", state["blocking_gate"])

        documents["intent"] = {}
        documents["gate"] = {"status": "no_action", "would_place_real_order": False}
        _, result = namespace["trendatlas_payload"]()
        self.assertEqual(result["state"]["trade_submission_state"], "Čaká na kontrolu")


if __name__ == "__main__":
    unittest.main()
