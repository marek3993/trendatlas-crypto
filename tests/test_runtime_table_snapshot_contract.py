import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_RUNTIME_SNAPSHOT_PATH = ROOT / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json"
APP_PY_PATH = ROOT / "app.py"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestRuntimeTableSnapshotContract(unittest.TestCase):
    def test_runtime_table_snapshot_has_required_fields(self):
        payload = load_json(APP_RUNTIME_SNAPSHOT_PATH)
        runtime_table = payload.get("runtime_table_snapshot")

        self.assertIsInstance(runtime_table, dict)
        self.assertEqual(payload.get("snapshot_type"), "app_runtime_snapshot")

        required_fields = {
            "last_pi_update_utc",
            "last_pc_refresh_utc",
            "last_refresh_status",
            "last_refresh_run_id",
            "last_wallet_sync_utc",
            "currentness_state",
            "currentness_reason",
            "source_metadata",
            "evaluated_at_utc",
        }
        self.assertTrue(required_fields.issubset(runtime_table.keys()))

        source_metadata = runtime_table.get("source_metadata")
        self.assertIsInstance(source_metadata, dict)
        self.assertTrue(
            {
                "last_pi_update_utc",
                "last_pc_refresh_utc",
                "last_refresh_status",
                "last_refresh_run_id",
                "last_wallet_sync_utc",
                "currentness_state",
                "currentness_reason",
            }.issubset(source_metadata.keys())
        )

    def test_refresh_fields_are_internally_consistent(self):
        payload = load_json(APP_RUNTIME_SNAPSHOT_PATH)
        runtime_table = payload["runtime_table_snapshot"]
        source_metadata = runtime_table["source_metadata"]

        refresh_status = runtime_table.get("last_refresh_status")
        refresh_run_id = runtime_table.get("last_refresh_run_id")
        refresh_pc_utc = runtime_table.get("last_pc_refresh_utc")

        if refresh_status == "not_run":
            self.assertIsNone(refresh_run_id)
            self.assertIsNone(refresh_pc_utc)
            return

        refresh_paths = {
            source_metadata["last_pc_refresh_utc"].get("path"),
            source_metadata["last_refresh_status"].get("path"),
            source_metadata["last_refresh_run_id"].get("path"),
        }
        self.assertEqual(len(refresh_paths), 1)
        self.assertNotIn(None, refresh_paths)

    def test_last_pi_update_uses_scheduler_manifest_not_runtime_health(self):
        payload = load_json(APP_RUNTIME_SNAPSHOT_PATH)
        runtime_table = payload["runtime_table_snapshot"]
        source_metadata = runtime_table["source_metadata"]["last_pi_update_utc"]

        self.assertEqual(
            source_metadata.get("path"),
            "outputs/execution/full_auto_scheduler/latest_scheduler_entry_manifest.json",
        )
        self.assertEqual(
            source_metadata.get("source_type"),
            "full_auto_scheduler_entry_manifest",
        )
        self.assertEqual(source_metadata.get("source_field"), "generated_at_utc")
        self.assertNotEqual(
            source_metadata.get("path"),
            "outputs/execution/runtime_health/latest_runtime_health.json",
        )
        self.assertNotEqual(source_metadata.get("source_field"), "last_success_utc")

    def test_app_refresh_rows_read_runtime_table_snapshot_only(self):
        source = APP_PY_PATH.read_text(encoding="utf-8")
        start_marker = 'pi_runtime_update_utc = runtime_table_payload.get("last_pi_update_utc")'
        end_marker = 'render_data_health_details(data_health_report, data_health_status_model, lang, refresh_rows)'
        start = source.index(start_marker)
        end = source.index(end_marker, start)
        refresh_block = source[start:end]

        self.assertIn(
            "runtime_table_payload = build_authority_runtime_table_snapshot(",
            source,
        )
        self.assertIn('runtime_table_payload.get("last_pi_update_utc")', refresh_block)
        self.assertIn('runtime_table_payload.get("last_wallet_sync_utc")', refresh_block)
        self.assertIn('runtime_table_payload.get("last_refresh_status")', refresh_block)
        self.assertIn('runtime_table_payload.get("last_refresh_run_id")', refresh_block)
        self.assertNotIn("strategy_freshness_payload.get(", refresh_block)
        self.assertNotIn("resolve_wallet_sync_utc(", refresh_block)
        self.assertNotIn("resolve_backup_refresh_finished_utc(", refresh_block)


if __name__ == "__main__":
    unittest.main()
