from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


def load_precedence_symbols() -> dict[str, object]:
    wanted = {
        "parse_iso_datetime_optional",
        "build_missing_runtime_snapshot",
        "load_runtime_snapshot_for_app",
        "select_preferred_account_runtime_snapshot",
        "load_dashboard_public_status_for_app",
    }
    module = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    extracted = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(extracted)
    namespace: dict[str, object] = {
        "Path": Path,
        "datetime": datetime,
        "timezone": timezone,
        "Any": Any,
        "FRESHNESS_SUMMARY_TEXT": {"missing_authority_artifact": "missing"},
        "LOCAL_APP_RUNTIME_SNAPSHOT_PATH": Path("local_runtime.json"),
        "LOCAL_DASHBOARD_PUBLIC_STATUS_PATH": Path("local_status.json"),
    }
    exec(compile(extracted, str(APP_PATH), "exec"), namespace)
    return namespace


def runtime_snapshot(*, account_as_of: str, generated_at: str, exposure: float) -> dict:
    status = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "closed_day": "2026-09-01",
        "real_account": {"asset": "BTC", "exposure_x": exposure},
        "execution": {},
        "model_signal": {},
        "model_performance": {},
        "data_health": {},
        "live_market_state": {},
        "public_labels_sk": {},
    }
    return {
        "snapshot_type": "app_runtime_snapshot",
        "schema_version": 2,
        "account_snapshot_as_of_utc": account_as_of,
        "app_runtime_snapshot_generated_at_utc": generated_at,
        "account_snapshot_summary": {"current_position": "BTC"},
        "dashboard_public_status": status,
    }


class TestAppRuntimeSnapshotPrecedence(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = load_precedence_symbols()

    def install_local(self, runtime: dict, standalone_status: dict | None = None) -> None:
        def load_json(path: Path) -> dict:
            if Path(path) == Path("local_runtime.json"):
                return runtime
            if Path(path) == Path("local_status.json"):
                return standalone_status or dict(runtime["dashboard_public_status"])
            return {}

        self.ns["load_json_optional"] = load_json

    def test_stale_local_runtime_cannot_override_newer_authority(self):
        authority = runtime_snapshot(
            account_as_of="2026-09-02T11:30:32Z",
            generated_at="2026-09-02T11:31:07Z",
            exposure=0.484539,
        )
        local = runtime_snapshot(
            account_as_of="2026-09-02T11:20:00Z",
            generated_at="2026-09-02T12:00:00Z",
            exposure=0.5,
        )
        self.install_local(local)

        selected = self.ns["select_preferred_account_runtime_snapshot"](authority)
        status = self.ns["load_dashboard_public_status_for_app"](
            selected,
            {"closed_day": "2026-09-01"},
        )

        self.assertIs(selected, authority)
        self.assertEqual(status["real_account"]["exposure_x"], 0.484539)

    def test_objectively_newer_local_runtime_can_override_authority(self):
        authority = runtime_snapshot(
            account_as_of="2026-09-02T11:30:32Z",
            generated_at="2026-09-02T11:31:07Z",
            exposure=0.484539,
        )
        local = runtime_snapshot(
            account_as_of="2026-09-02T11:40:00Z",
            generated_at="2026-09-02T11:41:00Z",
            exposure=0.49,
        )
        self.install_local(local)

        selected = self.ns["select_preferred_account_runtime_snapshot"](authority)
        status = self.ns["load_dashboard_public_status_for_app"](
            selected,
            {"closed_day": "2026-09-01"},
        )

        self.assertIs(selected, local)
        self.assertEqual(status["real_account"]["exposure_x"], 0.49)


if __name__ == "__main__":
    unittest.main()
