import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "dev_only_build_btc_etf_flow_daily_panel.py"
ENV_EXAMPLE_PATH = ROOT / "configs" / "dev_only_btc_etf_flow.env.example"
CONTRACT_PATH = ROOT / "research_os" / "dev_only" / "contracts" / "dev_only_btc_etf_flow_daily_panel.contract.json"


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


if __name__ == "__main__":
    unittest.main()
