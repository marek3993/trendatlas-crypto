from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_OS = ROOT / "research_os"
POLICY_PATH = RESEARCH_OS / "policies" / "research_os_spec_generator_policy_v1.json"
HYPOTHESES_PATH = ROOT / "outputs" / "research_os_ideation_v1" / "ideation_hypotheses.json"


class SpecGenerationError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    if not path.exists():
        raise SpecGenerationError(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def resolve_hypotheses(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("hypotheses"), list):
        return payload["hypotheses"]
    if isinstance(payload, list):
        return payload
    raise SpecGenerationError("unsupported hypotheses payload shape")


def validate_hypothesis(policy: dict[str, Any], hypothesis: dict[str, Any]) -> None:
    for field in policy["required_hypothesis_thesis_fields"]:
        if hypothesis.get(field) in (None, "", []):
            raise SpecGenerationError(f"hypothesis missing mandatory thesis field: {field}")

    family = hypothesis["mutation_family"]
    for field in policy["family_specific_required_fields"].get(family, []):
        if hypothesis.get(field) in (None, "", []):
            raise SpecGenerationError(f"hypothesis missing family-specific field: {field}")

    if hypothesis["primary_expected_metric_improvement"] not in policy["allowed_primary_expected_metric_improvement"]:
        raise SpecGenerationError("invalid primary_expected_metric_improvement")


def build_spec(policy: dict[str, Any], hypothesis: dict[str, Any]) -> dict[str, Any]:
    validate_hypothesis(policy, hypothesis)

    macro_path = Path(policy["input_resolution"]["macro_file_path"])
    ohlcv_dir = Path(policy["input_resolution"]["ohlcv_dir_path"])
    ohlcv_files = sorted(str(p) for p in ohlcv_dir.glob(policy["input_resolution"]["ohlcv_glob"]) if p.is_file())

    spec = {
        "experiment_id": hypothesis["hypothesis_label"],
        "branch": "core",
        "segment_owner": "MRV1 CORE STRATEGY",
        "hypothesis_label": hypothesis["hypothesis_label"],
        "experiment_family": hypothesis["mutation_family"],
        "baseline_model": policy["baseline_defaults"]["baseline_model"],
        "baseline_paper_path": policy["baseline_defaults"]["baseline_paper_path"],
        "input_paths": [str(macro_path)] + ohlcv_files,
        "script_path": policy["script_defaults"]["authoritative_script_path"],
        "script_args": [
            "--mode", "research",
            "--baseline-model", policy["baseline_defaults"]["baseline_model"],
            "--baseline-paper", policy["baseline_defaults"]["baseline_paper_path"],
            "--hypothesis-label", hypothesis["hypothesis_label"],
            "--compare-target", hypothesis["exact_compare_target"]
        ],
        "expected_outputs": policy["default_expected_outputs"],
        "scoring_profile": policy["default_scoring_profile"],
        "promotion_rule": policy["default_promotion_rule"],
        "invalidation_rule": policy["default_invalidation_rule"],
        "budget_class": policy["branch_defaults"]["core"]["budget_class"],
        "priority": policy["branch_defaults"]["core"]["priority"],
        "created_by": "research_os_experiment_spec_generator_v1",
        "created_at": utc_now_iso(),
        "status": "spec_ready"
    }

    for field in policy["required_spec_fields"]:
        if spec.get(field) in (None, "", []):
            raise SpecGenerationError(f"generated spec missing required fields: {field}")

    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise SpecGenerationError("choose exactly one of --dry-run or --execute")

    policy = load_json(POLICY_PATH)
    hypotheses = resolve_hypotheses(load_json(HYPOTHESES_PATH))

    output_dir = Path(policy["output_dir"])
    summary_json_path = Path(policy["summary_json_path"])
    summary_csv_path = Path(policy["summary_csv_path"])
    log_jsonl_path = Path(policy["log_jsonl_path"])

    generated = []
    summary_rows = []

    for hypothesis in hypotheses:
        spec = build_spec(policy, hypothesis)
        spec_path = output_dir / f"{spec['experiment_id']}.spec_ready.json"
        generated.append({"spec_path": str(spec_path), "spec": spec})
        summary_rows.append({
            "experiment_id": spec["experiment_id"],
            "hypothesis_label": spec["hypothesis_label"],
            "experiment_family": spec["experiment_family"],
            "status": spec["status"],
            "spec_path": str(spec_path)
        })

    if args.execute:
        for item in generated:
            write_json(Path(item["spec_path"]), item["spec"])
        write_json(summary_json_path, {"generated_specs": generated})
        write_csv(summary_csv_path, summary_rows, ["experiment_id", "hypothesis_label", "experiment_family", "status", "spec_path"])
        append_jsonl(log_jsonl_path, {
            "ts": utc_now_iso(),
            "event": "spec_generation_completed",
            "generated_count": len(generated),
            "policy_version": policy["policy_version"]
        })
        print(f"[SAVED] specs={len(generated)}")
        print(f"[SAVED] summary_json={summary_json_path}")
        print(f"[SAVED] summary_csv={summary_csv_path}")
    else:
        print(f"[DRY-RUN] would_generate_specs={len(generated)}")
        for row in summary_rows:
            print(f"[DRY-RUN] {row['hypothesis_label']} | {row['experiment_family']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)