import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_JSON_FILES = [
    ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_universe_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json",
    ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json",
    ROOT / "canonical" / "manifests" / "canonical_product_manifest.json",
    ROOT / "canonical" / "exports" / "canonical_product_export_contract.json",
    ROOT / "canonical" / "references" / "canonical_66g_reference.json",
    ROOT / "canonical" / "references" / "canonical_benchmark_reference.json",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalNotesBlocksPresent(unittest.TestCase):
    def test_all_canonical_json_files_have_non_empty_notes_or_truth_notes(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)

            notes = payload.get("notes")
            truth_notes = payload.get("truth_notes")

            has_notes = isinstance(notes, list) and len(notes) > 0
            has_truth_notes = isinstance(truth_notes, list) and len(truth_notes) > 0

            if not has_notes and not has_truth_notes:
                failures.append(
                    f"{path.relative_to(ROOT)} missing non-empty notes/truth_notes block"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_notes_blocks_contain_only_non_empty_strings(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)

            for key in ["notes", "truth_notes"]:
                if key not in payload:
                    continue

                value = payload[key]
                if not isinstance(value, list):
                    failures.append(f"{path.relative_to(ROOT)} {key} must be a list")
                    continue

                invalid = [item for item in value if not isinstance(item, str) or not item.strip()]
                if invalid:
                    failures.append(f"{path.relative_to(ROOT)} {key} contains invalid entries")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()