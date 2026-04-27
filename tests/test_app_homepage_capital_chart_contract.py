import ast
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_PY_PATH = ROOT / "app.py"


def load_functions(*function_names: str) -> dict[str, object]:
    source = APP_PY_PATH.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(APP_PY_PATH))
    selected_nodes = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    namespace = {
        "pd": pd,
    }
    exec(compile(extracted_module, str(APP_PY_PATH), "exec"), namespace)
    return {name: namespace[name] for name in function_names}


class TestAppHomepageCapitalChartContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        loaded = load_functions(
            "filter_from_year",
            "clip_homepage_chart_frames",
        )
        cls.filter_from_year = loaded["filter_from_year"]
        cls.clip_homepage_chart_frames = loaded["clip_homepage_chart_frames"]

    def test_chart_frames_clip_to_shared_visible_window(self):
        main_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-04-17", "2026-04-18", "2026-04-19", "2026-04-20", "2026-04-21"]),
                "equity": [100.0, 101.0, 102.0, 102.0, 102.0],
            }
        )
        btc_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-04-18", "2026-04-19"]),
                "close": [70000.0, 71000.0],
            }
        )

        main_plot, btc_plot, visible_window = self.__class__.clip_homepage_chart_frames(
            main_df,
            btc_df,
            2026,
        )

        self.assertEqual(
            main_plot["ts"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-04-18", "2026-04-19"],
        )
        self.assertEqual(
            btc_plot["ts"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-04-18", "2026-04-19"],
        )
        self.assertEqual(str(visible_window["start"].date()), "2026-04-18")
        self.assertEqual(str(visible_window["end"].date()), "2026-04-19")

    def test_chart_frames_fail_when_year_filter_has_no_overlap(self):
        main_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-04-20", "2026-04-21"]),
                "equity": [100.0, 101.0],
            }
        )
        btc_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2026-04-18", "2026-04-19"]),
                "close": [70000.0, 71000.0],
            }
        )

        with self.assertRaisesRegex(ValueError, "no overlapping visible date window"):
            self.__class__.clip_homepage_chart_frames(main_df, btc_df, 2026)


if __name__ == "__main__":
    unittest.main()
