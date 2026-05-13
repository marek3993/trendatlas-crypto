import argparse
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import phase60_selective_restore_robustness as phase60
from scripts import daily_refresh_app_pipeline as refresh_pipeline
from scripts import phase63_btc_participation_overlay as phase63


PINNED_PHASE60_MODEL = phase60.PINNED_PHASE60_DEPENDENCY_MODEL_KEY
PINNED_PHASE63_VARIANT = phase63.PINNED_PHASE63_DEPENDENCY_VARIANT_KEY


class TestPhase60FastDependencyRefresh(unittest.TestCase):
    def _make_case_dir(self) -> Path:
        root = ROOT / "tmp_test_artifacts" / f"phase60_fast_dependency_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def _write_ohlcv_csv(self, path: Path, dates: pd.DatetimeIndex, base_price: float, daily_step: float) -> None:
        price = pd.Series(range(len(dates)), index=dates, dtype="float64") * daily_step + base_price
        pd.DataFrame(
            {
                "date": dates,
                "open": price * 0.995,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1_000_000 + pd.Series(range(len(dates)), index=dates, dtype="float64"),
            }
        ).to_csv(path, index=False)

    def _write_phase60_input_files(self, case_dir: Path) -> tuple[Path, Path, Path, list[str], str]:
        data_dir = case_dir / "ohlcv"
        data_dir.mkdir(parents=True, exist_ok=True)
        macro_path = case_dir / "global_liquidity_weekly.csv"
        dates = pd.date_range("2025-01-01", periods=330, freq="D")
        symbols = ["BTCUSDT", "BNBUSDT", "TRXUSDT", "SOLUSDT"]
        slopes = {
            "BTCUSDT": 0.25,
            "BNBUSDT": 0.10,
            "TRXUSDT": 0.45,
            "SOLUSDT": 0.35,
        }
        base_prices = {
            "BTCUSDT": 100.0,
            "BNBUSDT": 50.0,
            "TRXUSDT": 10.0,
            "SOLUSDT": 20.0,
        }

        for symbol in symbols:
            self._write_ohlcv_csv(
                data_dir / f"{symbol}_1d.csv",
                dates,
                base_prices[symbol],
                slopes[symbol],
            )

        macro_dates = dates[::7]
        pd.DataFrame(
            {
                "date": macro_dates,
                "g7_m2_yoy": 2.0,
                "bis_gli_yoy": 1.0,
                "cb_balance_sheet_yoy": 0.5,
            }
        ).to_csv(macro_path, index=False)

        btc_path = data_dir / "BTCUSDT_1d.csv"
        return data_dir, macro_path, btc_path, symbols, str(dates[-1].date())

    def _run_phase60_fast_dependency(
        self,
        *,
        case_dir: Path,
    ) -> tuple[Path, Path, str]:
        phase60_output_dir = case_dir / "phase60_outputs"
        data_dir, macro_path, btc_path, symbols, expected_last_date = self._write_phase60_input_files(case_dir)
        argv = [
            "phase60_selective_restore_robustness.py",
            "--dependency-only",
            "--model-key",
            PINNED_PHASE60_MODEL,
        ]

        with (
            mock.patch.object(phase60, "OUT_DIR", phase60_output_dir),
            mock.patch.object(phase60, "DATA_DIR", data_dir),
            mock.patch.object(phase60, "MACRO_PATH", macro_path),
            mock.patch.object(phase60, "ALL_SYMBOLS", symbols),
            mock.patch.object(sys, "argv", argv),
        ):
            phase60.main()

        return phase60_output_dir / f"{PINNED_PHASE60_MODEL}_paper.csv", btc_path, expected_last_date

    def test_dependency_only_fast_path_does_not_build_full_model_grid(self):
        args = argparse.Namespace(
            dependency_only=True,
            model_key="",
            only_model="",
        )
        models, run_mode, targeted = phase60.resolve_requested_models(args)

        self.assertTrue(targeted)
        self.assertEqual(run_mode, "dependency_only_fast_refresh")
        self.assertEqual(models, [PINNED_PHASE60_MODEL])

    def test_explicit_model_key_uses_targeted_fast_path(self):
        args = argparse.Namespace(
            dependency_only=False,
            model_key=PINNED_PHASE60_MODEL,
            only_model="",
        )
        models, run_mode, targeted = phase60.resolve_requested_models(args)

        self.assertTrue(targeted)
        self.assertEqual(run_mode, "targeted_fast_refresh")
        self.assertEqual(models, [PINNED_PHASE60_MODEL])

    def test_refresh_pipeline_uses_documented_phase60_fast_dependency_command(self):
        self.assertEqual(
            refresh_pipeline.PHASE60_FAST_DEPENDENCY_ARGS,
            ["--dependency-only", "--model-key", refresh_pipeline.PHASE60_PINNED_MODEL],
        )
        self.assertEqual(refresh_pipeline.PHASE60_PINNED_MODEL, PINNED_PHASE60_MODEL)
        self.assertEqual(refresh_pipeline.PHASE60_PAPER.name, f"{PINNED_PHASE60_MODEL}_paper.csv")

    def test_help_and_registry_document_targeted_phase60_dependency_refresh(self):
        help_text = phase60.build_arg_parser().format_help().lower()
        self.assertIn("--dependency-only", help_text)
        self.assertIn("targeted fast dependency refresh", help_text)
        self.assertIn("not the full research grid", help_text)
        self.assertIn(PINNED_PHASE60_MODEL.lower(), help_text)

        script_registry_path = ROOT / "canonical" / "script_registry.json"
        script_registry = json.loads(script_registry_path.read_text(encoding="utf-8"))
        script_entry = next(
            (
                entry
                for entry in script_registry["scripts"]
                if entry.get("script_path") == "phase60_selective_restore_robustness.py"
            ),
            None,
        )
        self.assertIsNotNone(script_entry)
        self.assertIn("--dependency-only --model-key", str(script_entry["notes"]))

        output_registry_path = ROOT / "canonical" / "output_registry.json"
        output_registry = json.loads(output_registry_path.read_text(encoding="utf-8"))
        output_entry = next(
            (
                entry
                for entry in output_registry["outputs"]
                if entry.get("output_path") == "outputs/phase60_selective_restore_robustness/"
            ),
            None,
        )
        self.assertIsNotNone(output_entry)
        self.assertIn("--dependency-only --model-key", str(output_entry["notes"]))

    def test_fast_phase60_dependency_command_updates_required_paper_with_latest_ts(self):
        case_dir = self._make_case_dir()
        paper_path, _, expected_last_date = self._run_phase60_fast_dependency(case_dir=case_dir)

        self.assertTrue(paper_path.exists())
        exported = pd.read_csv(paper_path)
        self.assertEqual(exported.columns[0], "ts")
        self.assertEqual(str(exported["ts"].iloc[-1]).strip(), expected_last_date)

    def test_phase60_output_shape_remains_consumable_by_phase63(self):
        case_dir = self._make_case_dir()
        paper_path, _, expected_last_date = self._run_phase60_fast_dependency(case_dir=case_dir)

        raw = pd.read_csv(paper_path)
        loaded = phase63.load_base_strategy(paper_path)

        self.assertFalse(loaded.empty)
        self.assertEqual(str(loaded.index[-1].date()), expected_last_date)
        self.assertEqual(
            str(loaded["base_selected_symbol"].iloc[-1]).upper(),
            str(raw["selected"].iloc[-1]).upper(),
        )
        for column in ["base_return", "base_selected_symbol", "base_rolling_ret_30"]:
            self.assertIn(column, loaded.columns)

    def test_phase63_winner_only_fast_command_consumes_fresh_phase60_paper(self):
        case_dir = self._make_case_dir()
        paper_path, btc_path, expected_last_date = self._run_phase60_fast_dependency(case_dir=case_dir)
        phase63_output_dir = case_dir / "phase63_outputs"
        phase63_output_dir.mkdir(parents=True, exist_ok=True)
        required_phase63_paper = phase63_output_dir / f"{PINNED_PHASE63_VARIANT}_paper.csv"

        argv = [
            "phase63_btc_participation_overlay.py",
            "--winner-only",
            "--variant-key",
            PINNED_PHASE63_VARIANT,
            "--base-paper-path",
            str(paper_path),
        ]

        with (
            mock.patch.object(phase63, "PHASE63_DIR", phase63_output_dir),
            mock.patch.object(phase63, "discover_btc_price_file", return_value=btc_path),
            mock.patch.object(sys, "argv", argv),
        ):
            phase63.main()

        self.assertTrue(required_phase63_paper.exists())
        exported = pd.read_csv(required_phase63_paper)
        self.assertEqual(str(exported["date"].iloc[-1]).strip(), expected_last_date)

    def test_phase60_fast_dependency_tests_do_not_stage_outputs_or_data(self):
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", "outputs", "data"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
