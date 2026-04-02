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


class TestCanonicalUpstreamPathsExist(unittest.TestCase):
    def test_upstream_artifacts_exist_when_they_are_repo_relative_paths(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            upstream_artifacts = payload.get("upstream_artifacts", [])

            for upstream in upstream_artifacts:
                if not isinstance(upstream, str) or not upstream.strip():
                    failures.append(f"{path.relative_to(ROOT)} has invalid upstream entry: {upstream}")
                    continue

                repo_path = ROOT / Path(upstream)
                if repo_path.exists():
                    continue

                failures.append(
                    f"{path.relative_to(ROOT)} references missing upstream artifact: {upstream}"
                )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()