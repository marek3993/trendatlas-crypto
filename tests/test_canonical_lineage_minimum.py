import json
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

REQUIRED_FIELDS = [
    "artifact_name",
    "artifact_type",
    "truth_domain",
    "truth_status",
    "generated_at",
    "effective_date",
    "producer_script",
    "source_run_id",
    "upstream_artifacts",
    "supersedes",
    "consumer_scope",
]

ALLOWED_ARTIFACT_TYPES = {
    "decision",
    "snapshot",
    "manifest",
    "export",
    "reference",
}

ALLOWED_TRUTH_DOMAINS = {
    "strategy",
    "universe",
    "leverage",
    "product",
    "benchmark",
    "artifacts",
    "lineage",
}

ALLOWED_TRUTH_STATUSES = {
    "exploratory",
    "candidate",
    "reference",
    "official",
    "deprecated",
    "superseded",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_all_canonical_json_files_exist():
    missing = [str(path.relative_to(ROOT)) for path in CANONICAL_JSON_FILES if not path.exists()]
    assert not missing, f"Missing canonical JSON files: {missing}"


def test_canonical_json_files_have_required_fields():
    failures = []

    for path in CANONICAL_JSON_FILES:
        payload = load_json(path)
        missing_fields = [field for field in REQUIRED_FIELDS if field not in payload]
        if missing_fields:
            failures.append(
                f"{path.relative_to(ROOT)} missing required fields: {missing_fields}"
            )

    assert not failures, " | ".join(failures)


def test_canonical_json_fields_have_valid_basic_types():
    failures = []

    for path in CANONICAL_JSON_FILES:
        payload = load_json(path)

        if not isinstance(payload["artifact_name"], str) or not payload["artifact_name"].strip():
            failures.append(f"{path.relative_to(ROOT)} invalid artifact_name")

        if payload["artifact_type"] not in ALLOWED_ARTIFACT_TYPES:
            failures.append(f"{path.relative_to(ROOT)} invalid artifact_type={payload['artifact_type']}")

        if payload["truth_domain"] not in ALLOWED_TRUTH_DOMAINS:
            failures.append(f"{path.relative_to(ROOT)} invalid truth_domain={payload['truth_domain']}")

        if payload["truth_status"] not in ALLOWED_TRUTH_STATUSES:
            failures.append(f"{path.relative_to(ROOT)} invalid truth_status={payload['truth_status']}")

        if not isinstance(payload["generated_at"], str) or not payload["generated_at"].strip():
            failures.append(f"{path.relative_to(ROOT)} invalid generated_at")

        if not isinstance(payload["effective_date"], str) or not payload["effective_date"].strip():
            failures.append(f"{path.relative_to(ROOT)} invalid effective_date")

        if not isinstance(payload["producer_script"], str) or not payload["producer_script"].strip():
            failures.append(f"{path.relative_to(ROOT)} invalid producer_script")

        if not isinstance(payload["upstream_artifacts"], list):
            failures.append(f"{path.relative_to(ROOT)} upstream_artifacts must be a list")

        if not isinstance(payload["supersedes"], list):
            failures.append(f"{path.relative_to(ROOT)} supersedes must be a list")

        if not isinstance(payload["consumer_scope"], list) or not payload["consumer_scope"]:
            failures.append(f"{path.relative_to(ROOT)} consumer_scope must be a non-empty list")

    assert not failures, " | ".join(failures)


def test_canonical_json_names_start_with_canonical_prefix():
    failures = []

    for path in CANONICAL_JSON_FILES:
        payload = load_json(path)
        artifact_name = payload["artifact_name"]
        if not artifact_name.startswith("canonical_"):
            failures.append(f"{path.relative_to(ROOT)} artifact_name must start with canonical_")

    assert not failures, " | ".join(failures)


def test_canonical_json_filename_matches_artifact_name():
    failures = []

    for path in CANONICAL_JSON_FILES:
        payload = load_json(path)
        expected_filename = f"{payload['artifact_name']}.json"
        if path.name != expected_filename:
            failures.append(
                f"{path.relative_to(ROOT)} filename mismatch: expected {expected_filename}"
            )

    assert not failures, " | ".join(failures)