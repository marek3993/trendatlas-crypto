import ast
import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_PY_PATH = ROOT / "app.py"


def load_functions(*function_names: str) -> dict[str, object]:
    source = APP_PY_PATH.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(APP_PY_PATH))

    selected_nodes = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_DISPLAY_TIMEZONE":
                    selected_nodes.append(node)
                    break
        elif isinstance(node, ast.FunctionDef) and node.name in function_names:
            selected_nodes.append(node)

    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(extracted_module)

    namespace = {
        "pd": pd,
        "re": re,
        "date": date,
        "datetime": datetime,
        "timezone": timezone,
        "ZoneInfo": ZoneInfo,
        "t": lambda lang, key: {"sk": {"na": "Nedostupné"}, "en": {"na": "N/A"}}[lang][key],
    }
    exec(compile(extracted_module, str(APP_PY_PATH), "exec"), namespace)
    return namespace


class TestAppOperationalTimestampDisplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        namespace = load_functions("format_date_text", "format_local_time_text")
        cls.format_local_time_text = namespace["format_local_time_text"]

    def test_operational_timestamp_displays_in_bratislava_timezone(self):
        rendered = self.__class__.format_local_time_text("2026-04-12T22:05:00Z", "sk")
        self.assertEqual(rendered, "13.4.2026 00:05 CEST")

    def test_operational_timestamp_uses_winter_timezone_label(self):
        rendered = self.__class__.format_local_time_text("2026-01-13T23:05:00Z", "sk")
        self.assertEqual(rendered, "14.1.2026 00:05 CET")

    def test_app_operational_sections_use_local_time_formatter(self):
        source = APP_PY_PATH.read_text(encoding="utf-8")
        self.assertIn('format_local_time_text(', source)
        self.assertIn('refresh_value_column: format_local_time_text(', source)
        self.assertIn('"value": format_local_time_text(account_snapshot_as_of_utc, lang),', source)
        self.assertNotIn('refresh_value_column: format_utc_text(', source)
        self.assertNotIn('"value": format_utc_text(account_snapshot_as_of_utc, lang),', source)


if __name__ == "__main__":
    unittest.main()
