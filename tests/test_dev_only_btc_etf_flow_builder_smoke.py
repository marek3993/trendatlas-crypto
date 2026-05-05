import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "dev_only_build_btc_etf_flow_daily_panel.py"
ENV_EXAMPLE_PATH = ROOT / "configs" / "dev_only_btc_etf_flow.env.example"
CONTRACT_PATH = ROOT / "research_os" / "dev_only" / "contracts" / "dev_only_btc_etf_flow_daily_panel.contract.json"
SCRIPTS_DIR = ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SPEC = importlib.util.spec_from_file_location("dev_only_btc_etf_flow_builder", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)

FARSIDE_SAMPLE_HTML = """
<html>
  <body>
    <table class="etf">
      <tr>
        <th>Date</th><th>IBIT</th><th>FBTC</th><th>BITB</th><th>ARKB</th>
        <th>BTCO</th><th>EZBC</th><th>BRRR</th><th>HODL</th><th>BTCW</th>
        <th>MSBT</th><th>GBTC</th><th>BTC</th><th>Total</th>
      </tr>
      <tr>
        <td>11 Jan 2024</td><td>111.7</td><td>227.0</td><td>237.9</td><td>65.3</td>
        <td>17.4</td><td>50.1</td><td>29.4</td><td>10.6</td><td>1.0</td>
        <td>-</td><td>(95.1)</td><td>-</td><td>655.3</td>
      </tr>
      <tr>
        <td>12 Jan 2024</td><td>386.0</td><td>195.3</td><td>17.4</td><td>39.8</td>
        <td>28.4</td><td>0.0</td><td>20.2</td><td>0.0</td><td>0.0</td>
        <td>-</td><td>(484.1)</td><td>-</td><td>203.0</td>
      </tr>
      <tr>
        <td>15 Jan 2024</td><td>-</td><td>-</td><td>-</td><td>-</td>
        <td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
        <td>-</td><td>-</td><td>-</td><td>0.0</td>
      </tr>
      <tr>
        <td>Total</td><td>497.7</td><td>422.3</td><td>255.3</td><td>105.1</td>
        <td>45.8</td><td>50.1</td><td>49.6</td><td>10.6</td><td>1.0</td>
        <td>-</td><td>(579.2)</td><td>-</td><td>858.3</td>
      </tr>
      <tr>
        <td>Average</td><td>248.8</td><td>211.2</td><td>127.6</td><td>52.6</td>
        <td>22.9</td><td>25.1</td><td>24.8</td><td>5.3</td><td>0.5</td>
        <td>-</td><td>(289.6)</td><td>-</td><td>286.1</td>
      </tr>
    </table>
  </body>
</html>
"""


class TestDevOnlyBtcEtfFlowBuilderSmoke(unittest.TestCase):
    def test_builder_script_exists(self):
        self.assertTrue(SCRIPT_PATH.exists())

    def test_builder_help_runs(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("BTC ETF-flow daily panel", result.stdout)

    def test_contract_and_env_example_exist(self):
        self.assertTrue(ENV_EXAMPLE_PATH.exists())
        self.assertTrue(CONTRACT_PATH.exists())

    def test_check_config_only_passes_for_farside_without_coinglass_key(self):
        env = os.environ.copy()
        env.pop("MRV1_COINGLASS_API_KEY", None)
        env["MRV1_BTC_ETF_FLOW_PRIMARY_PROVIDER"] = "farside"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--check-config-only"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn('"selected_primary_provider": "farside"', result.stdout)

    def test_farside_parser_extracts_aggregate_and_per_etf_flows(self):
        panel, child, discovered_tickers, meta = BUILDER.parse_farside_flow_html(
            FARSIDE_SAMPLE_HTML,
            retrieved_at_utc="2026-05-05 00:00:00 UTC",
        )
        self.assertEqual(discovered_tickers[:3], ["IBIT", "FBTC", "BITB"])
        self.assertEqual(meta["primary_source_url"], BUILDER.FARSIDE_FLOW_ALL_DATA_URL)
        self.assertEqual(meta["primary_source_parser_version"], BUILDER.FARSIDE_PARSER_VERSION)
        self.assertEqual(meta["summary_rows_seen"], ["Total", "Average"])
        self.assertEqual(panel["us_trading_session_date"].dt.strftime("%Y-%m-%d").tolist(), ["2024-01-11", "2024-01-12", "2024-01-15"])
        self.assertEqual(panel.loc[0, "aggregate_net_flow_usd"], 655_300_000.0)
        self.assertEqual(panel.loc[1, "aggregate_net_flow_usd"], 203_000_000.0)
        self.assertTrue(pd.isna(panel.loc[0, "aggregate_net_flow_btc"]))
        gbtc_row = child[
            (child["us_trading_session_date"] == "2024-01-11")
            & (child["etf_ticker"] == "GBTC")
        ].iloc[0]
        self.assertEqual(gbtc_row["net_flow_usd"], -95_100_000.0)
        self.assertEqual(gbtc_row["source_parser_version"], BUILDER.FARSIDE_PARSER_VERSION)
        self.assertFalse(
            ((child["us_trading_session_date"] == "2024-01-15") & (child["etf_ticker"] == "IBIT")).any()
        )

    def test_build_panel_with_farside_has_explicit_causal_alignment(self):
        spot_close = pd.Series(
            [46000.0, 47000.0, 43000.0],
            index=pd.to_datetime(["2024-01-11", "2024-01-12", "2024-01-15"]),
        )
        with (
            mock.patch.object(BUILDER, "fetch_farside_flow_html", return_value=FARSIDE_SAMPLE_HTML),
            mock.patch.object(BUILDER, "load_spot_daily", return_value=spot_close),
        ):
            panel, child, manifest_meta, quality = BUILDER.build_panel(
                primary_provider="farside",
                start_date_text="2024-01-11",
                timeout_seconds=30,
                coinglass_api_key=None,
                sosovalue_api_key=None,
                build_soso_enrichment=False,
                build_coinglass_aum=False,
            )

        self.assertEqual(panel["us_trading_session_date"].tolist(), ["2024-01-11", "2024-01-12"])
        self.assertEqual(panel["date"].tolist(), ["2024-01-12", "2024-01-13"])
        self.assertEqual(panel["causal_available_for_btc_utc_day"].tolist(), ["2024-01-12", "2024-01-13"])
        self.assertEqual(panel["btc_spot_close"].tolist(), [46000.0, 47000.0])
        self.assertEqual(panel["source_provider"].tolist(), ["farside", "farside"])
        self.assertEqual(panel["source_url"].tolist(), [BUILDER.FARSIDE_FLOW_ALL_DATA_URL, BUILDER.FARSIDE_FLOW_ALL_DATA_URL])
        self.assertEqual(
            panel["source_parser_version"].tolist(),
            [BUILDER.FARSIDE_PARSER_VERSION, BUILDER.FARSIDE_PARSER_VERSION],
        )
        self.assertEqual(panel["flow_positive_flag"].tolist(), [True, True])
        self.assertEqual(manifest_meta["primary_provider"], "farside")
        self.assertEqual(manifest_meta["primary_provider_non_trading_rows_dropped"], ["2024-01-15"])
        self.assertEqual(quality["verdict"], "READY_FOR_DEV_ONLY_PROBE")
        self.assertEqual(child["source_provider"].dropna().unique().tolist(), ["farside"])


if __name__ == "__main__":
    unittest.main()
