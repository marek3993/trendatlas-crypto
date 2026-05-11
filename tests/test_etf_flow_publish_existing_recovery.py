import unittest

import pandas as pd

from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
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


if __name__ == "__main__":
    unittest.main()
