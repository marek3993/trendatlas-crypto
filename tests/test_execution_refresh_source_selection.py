import json
import shutil
import unittest
from pathlib import Path

from scripts.execution import materialize_execution_app_exports as materializer

ROOT = Path(__file__).resolve().parents[1]


class TestExecutionRefreshSourceSelection(unittest.TestCase):
    def write_manifest(self, root: Path, run_id: str, payload: dict) -> None:
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "app_refresh_pipeline_manifest.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def test_current_refresh_source_status_wins_over_previous_failed_run(self):
        manifest_root = ROOT / "tmp_test_execution_refresh_source_selection"
        if manifest_root.exists():
            shutil.rmtree(manifest_root)
        manifest_root.mkdir(parents=True, exist_ok=True)
        try:
            self.write_manifest(
                manifest_root,
                "20260418_102800",
                {
                    "started_at_utc": "2026-04-18T10:28:00+00:00",
                    "main_refresh_chain_status": "FAIL",
                    "main_refresh_chain_finished_at_utc": "2026-04-18T10:28:00+00:00",
                    "status": "FAIL",
                },
            )
            self.write_manifest(
                manifest_root,
                "20260418_103458",
                {
                    "started_at_utc": "2026-04-18T10:34:58+00:00",
                    "main_refresh_chain_status": "RUNNING",
                    "refresh_source_status": "OK",
                    "refresh_source_finished_at_utc": "2026-04-18T10:35:44+00:00",
                },
            )

            original_dir = materializer.APP_REFRESH_PIPELINE_DIR
            try:
                materializer.APP_REFRESH_PIPELINE_DIR = manifest_root
                summary = materializer.build_strategy_freshness_summary(
                    latest_strategy_artifact_date="2026-04-17",
                    latest_trend_calculation_date="2026-04-17",
                    latest_wallet_sync_utc="2026-04-18T10:35:51Z",
                    latest_available_closed_utc_date="2026-04-17",
                )
            finally:
                materializer.APP_REFRESH_PIPELINE_DIR = original_dir
        finally:
            shutil.rmtree(manifest_root)

        self.assertEqual(summary["latest_refresh_run_id"], "20260418_103458")
        self.assertEqual(summary["latest_refresh_run_status"], "OK")
        self.assertEqual(summary["refresh_status"], "OK")
        self.assertEqual(summary["refresh_currentness_state"], "current")
        self.assertEqual(
            summary["refresh_finished_at_utc"],
            "2026-04-18T10:35:44+00:00",
        )


if __name__ == "__main__":
    unittest.main()
