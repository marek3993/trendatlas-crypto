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

from scripts import daily_refresh_app_pipeline as refresh_pipeline
from scripts import phase63_btc_participation_overlay as phase63
from scripts import phase66e_probation_governance as phase66_core


PINNED_VARIANT = phase63.PINNED_PHASE63_DEPENDENCY_VARIANT_KEY


class TestPhase63FastDependencyRefresh(unittest.TestCase):
    def _make_case_dir(self) -> Path:
        root = ROOT / "tmp_test_artifacts" / f"phase63_fast_dependency_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def _write_phase63_input_files(self, case_dir: Path) -> tuple[Path, Path, str]:
        dates = pd.date_range("2025-01-01", periods=220, freq="D")
        base_path = case_dir / "phase60_restore_trx_sol_base_paper.csv"
        btc_path = case_dir / "BTCUSDT_1d.csv"

        pd.DataFrame(
            {
                "date": dates,
                "strategy_return": 0.0,
                "executed_position": "ALT",
            }
        ).to_csv(base_path, index=False)

        btc_close = pd.Series(range(100, 320), index=dates, dtype="float64")
        pd.DataFrame({"date": dates, "close": btc_close.values}).to_csv(btc_path, index=False)
        return base_path, btc_path, str(dates[-1].date())

    def test_pinned_variant_key_parses_without_grid_lookup(self):
        cfg = phase63.parse_variant_key(PINNED_VARIANT)

        self.assertEqual(cfg.name, PINNED_VARIANT)
        self.assertEqual(cfg.btc_fast_ma, 20)
        self.assertEqual(cfg.btc_slow_ma, 100)
        self.assertEqual(cfg.btc_ret_lb, 30)
        self.assertEqual(cfg.btc_ret_min, 0.12)
        self.assertEqual(cfg.btc_risk_ma, 150)
        self.assertEqual(cfg.btc_risk_buffer, -0.03)
        self.assertEqual(cfg.btc_vol_lb, 30)
        self.assertEqual(cfg.btc_vol_cap, 0.045)
        self.assertEqual(cfg.weak_base_lb, 30)
        self.assertEqual(cfg.weak_base_threshold, 0.02)
        self.assertEqual(cfg.cooldown_days, 3)

    def test_winner_only_fast_path_does_not_build_full_variant_grid(self):
        args = phase63.build_arg_parser().parse_args(["--winner-only"])

        with mock.patch.object(
            phase63,
            "build_variant_grid",
            side_effect=AssertionError("winner-only must not build full grid"),
        ):
            variants, run_mode, targeted = phase63.resolve_requested_variants(args)

        self.assertTrue(targeted)
        self.assertEqual(run_mode, "winner_only_fast_dependency_refresh")
        self.assertEqual([variant.name for variant in variants], [PINNED_VARIANT])

    def test_only_model_parseable_key_uses_fast_path_for_legacy_pipeline_compatibility(self):
        args = argparse.Namespace(
            winner_only=False,
            variant_key="",
            only_model=PINNED_VARIANT,
        )

        with mock.patch.object(
            phase63,
            "build_variant_grid",
            side_effect=AssertionError("parseable --only-model must not build full grid"),
        ):
            variants, run_mode, targeted = phase63.resolve_requested_variants(args)

        self.assertTrue(targeted)
        self.assertEqual(run_mode, "targeted_fast_dependency_refresh")
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].name, PINNED_VARIANT)

    def test_refresh_pipeline_uses_documented_phase63_fast_dependency_command(self):
        self.assertEqual(
            refresh_pipeline.PHASE63_FAST_DEPENDENCY_ARGS,
            ["--winner-only", "--variant-key", refresh_pipeline.PHASE63_PINNED_MODEL],
        )
        self.assertEqual(refresh_pipeline.PHASE63_PINNED_MODEL, PINNED_VARIANT)
        self.assertEqual(
            refresh_pipeline.PHASE63_PAPER,
            phase66_core.CURRENT_WINNER_PAPER,
        )

    def test_help_documents_targeted_fast_dependency_refresh_not_full_grid(self):
        help_text = phase63.build_arg_parser().format_help().lower()

        self.assertIn("--winner-only", help_text)
        self.assertIn("targeted fast dependency refresh", help_text)
        self.assertIn("not the full research grid", help_text)
        self.assertIn(PINNED_VARIANT.lower(), help_text)

    def test_winner_only_main_writes_required_paper_with_latest_btc_date_and_phase66g_shape(self):
        case_dir = self._make_case_dir()
        phase63_output_dir = case_dir / "phase63_outputs"
        phase63_output_dir.mkdir(parents=True, exist_ok=True)
        base_path, btc_path, expected_last_date = self._write_phase63_input_files(case_dir)
        required_paper_path = phase63_output_dir / f"{PINNED_VARIANT}_paper.csv"
        manifest_path = phase63_output_dir / "phase63_manifest.json"

        argv = [
            "phase63_btc_participation_overlay.py",
            "--winner-only",
            "--variant-key",
            PINNED_VARIANT,
            "--base-paper-path",
            str(base_path),
        ]

        with (
            mock.patch.object(phase63, "PHASE63_DIR", phase63_output_dir),
            mock.patch.object(phase63, "discover_btc_price_file", return_value=btc_path),
            mock.patch.object(sys, "argv", argv),
        ):
            phase63.main()

        self.assertTrue(required_paper_path.exists())
        exported = pd.read_csv(required_paper_path)
        self.assertEqual(str(exported["date"].iloc[-1]).strip(), expected_last_date)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_mode"], "winner_only_fast_dependency_refresh")
        self.assertEqual(manifest["requested_variant_key"], PINNED_VARIANT)
        self.assertEqual(manifest["requested_variant_output_status"], "written")
        self.assertEqual(
            Path(manifest["requested_variant_output_file"]).name,
            required_paper_path.name,
        )

        loaded = phase66_core.load_baseline_paper(required_paper_path, phase66_core.OverlayConfig())
        self.assertFalse(loaded.empty)
        self.assertEqual(str(loaded.index[-1].date()), expected_last_date)
        for column in ["strategy_return", "base_return", "btc_return", "equity", "executed_regime"]:
            self.assertIn(column, loaded.columns)

    def test_winner_only_main_fails_if_required_paper_dataframe_is_missing(self):
        case_dir = self._make_case_dir()
        phase63_output_dir = case_dir / "phase63_outputs"
        phase63_output_dir.mkdir(parents=True, exist_ok=True)
        base_path, btc_path, _ = self._write_phase63_input_files(case_dir)
        required_paper_path = phase63_output_dir / f"{PINNED_VARIANT}_paper.csv"
        summary_path = phase63_output_dir / "phase63_overlay_summary.csv"
        compare_path = phase63_output_dir / "phase63_overlay_top_compare.csv"
        manifest_path = phase63_output_dir / "phase63_manifest.json"

        argv = [
            "phase63_btc_participation_overlay.py",
            "--winner-only",
            "--variant-key",
            PINNED_VARIANT,
            "--base-paper-path",
            str(base_path),
        ]

        with (
            mock.patch.object(phase63, "PHASE63_DIR", phase63_output_dir),
            mock.patch.object(phase63, "discover_btc_price_file", return_value=btc_path),
            mock.patch.object(
                phase63,
                "simulate_variant",
                side_effect=ValueError("forced targeted paper failure"),
            ),
            mock.patch.object(sys, "argv", argv),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "did not materialize the required paper DataFrame",
            ):
                phase63.main()

        self.assertFalse(required_paper_path.exists())
        self.assertTrue(summary_path.exists())
        self.assertTrue(compare_path.exists())
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["requested_variant_output_status"], "missing_required_paper")
        self.assertIn("did not materialize the required paper DataFrame", manifest["requested_variant_output_error"])

    def test_fast_path_paper_shape_is_consumable_by_phase66g_baseline_loader(self):
        case_dir = self._make_case_dir()
        cfg = phase63.parse_variant_key(PINNED_VARIANT)
        dates = pd.date_range("2025-01-01", periods=220, freq="D")
        btc_close = pd.Series(range(100, 320), index=dates, dtype="float64")
        base_input = pd.DataFrame(
            {
                "base_return": 0.0,
                "base_selected_symbol": "ALT",
                "base_rolling_ret_10": 0.0,
                "base_rolling_ret_20": 0.0,
                "base_rolling_ret_30": 0.0,
                "btc_close": btc_close,
                "btc_return": btc_close.pct_change().fillna(0.0),
            },
            index=dates,
        )

        paper = phase63.simulate_variant(base_input, cfg)
        paper_path = case_dir / f"{PINNED_VARIANT}_paper.csv"
        paper.reset_index().rename(columns={"index": "date"}).to_csv(paper_path, index=False)

        loaded = phase66_core.load_baseline_paper(paper_path, phase66_core.OverlayConfig())

        self.assertFalse(loaded.empty)
        self.assertEqual(str(loaded.index[-1].date()), "2025-08-08")
        for column in ["strategy_return", "base_return", "btc_return", "equity", "executed_regime"]:
            self.assertIn(column, loaded.columns)

    def test_phase63_fast_dependency_tests_do_not_stage_outputs_or_data(self):
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
