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
TRUTH_PACK_PATH = ROOT / "source_of_truth" / "project_truth.json"


class SpecGenerationError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    if not path.exists():
        raise SpecGenerationError(f"missing required file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def slugify(value: str) -> str:
    out: list[str] = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    text = "".join(out).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text[:120] if text else "unnamed_experiment"


def resolve_hypotheses(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("hypotheses"), list):
            return payload["hypotheses"]
        if isinstance(payload.get("items"), list):
            return payload["items"]
    raise SpecGenerationError("unsupported hypotheses payload shape")


def resolve_baseline_paper_path(policy: dict[str, Any]) -> str:
    path = Path(policy["baseline_defaults"]["baseline_paper_path"])
    if not path.exists():
        raise SpecGenerationError(f"baseline paper path does not exist: {path}")
    return str(path)


def resolve_script_path(policy: dict[str, Any]) -> str:
    path = Path(policy["script_defaults"]["authoritative_script_path"])
    if not path.exists():
        raise SpecGenerationError(f"authoritative script_path does not exist: {path}")
    return str(path)


def expand_input_paths(policy: dict[str, Any]) -> list[str]:
    macro_path = Path(policy["input_resolution"]["macro_file_path"])
    ohlcv_dir = Path(policy["input_resolution"]["ohlcv_dir_path"])
    glob_pattern = policy["input_resolution"]["ohlcv_glob"]

    if not macro_path.exists() or not macro_path.is_file():
        raise SpecGenerationError(f"macro input file does not exist: {macro_path}")
    if not ohlcv_dir.exists() or not ohlcv_dir.is_dir():
        raise SpecGenerationError(f"ohlcv input directory does not exist: {ohlcv_dir}")

    ohlcv_files = sorted(p for p in ohlcv_dir.glob(glob_pattern) if p.is_file())
    if policy["input_resolution"].get("require_nonempty_ohlcv_expansion", False) and not ohlcv_files:
        raise SpecGenerationError("ohlcv expansion produced zero files")

    return [str(macro_path)] + [str(p) for p in ohlcv_files]


def render_script_args(policy: dict[str, Any], hypothesis: dict[str, Any], baseline_model: str, baseline_paper_path: str) -> list[str]:
    template = policy["script_args_defaults"]["core"]
    mapping = {
        "baseline_model": baseline_model,
        "baseline_paper_path": baseline_paper_path,
        "hypothesis_label": hypothesis["hypothesis_label"],
        "exact_compare_target": hypothesis["exact_compare_target"]
    }
    return [str(x).format(**mapping) for x in template]


def validate_hypothesis_for_spec(hypothesis: dict[str, Any], policy: dict[str, Any]) -> None:
    for field in policy["required_hypothesis_thesis_fields"]:
        if hypothesis.get(field) in (None, "", []):
            raise SpecGenerationError(f"hypothesis missing mandatory thesis field: {field}")

    family = hypothesis["mutation_family"]
    for field in policy["family_specific_required_fields"].get(family, []):
        if hypothesis.get(field) in (None, "", []):
            raise SpecGenerationError(f"hypothesis missing family-specific field: {field}")


def build_spec(policy: dict[str, Any], truth_pack: dict[str, Any], hypothesis: dict[str, Any]) -> dict[str, Any]:
    validate_hypothesis_for_spec(hypothesis, policy)

    baseline_model = hypothesis.get("baseline_reference") or policy["baseline_defaults"]["baseline_model"]
    baseline_paper_path = resolve_baseline_paper_path(policy)
    script_path = resolve_script_path(policy)
    input_paths = expand_input_paths(policy)
    script_args = render_script_args(policy, hypothesis, baseline_model, baseline_paper_path)

    experiment_id = hypothesis.get("experiment_id") or slugify(hypothesis["hypothesis_label"])

    # IMPORTANT:
    # thesis/template fields are validated here but NOT emitted as top-level spec fields,
    # because experiment_spec.schema.json rejects unknown top-level fields.
    spec = {
        "experiment_id": experiment_id,
        "branch": hypothesis["branch"],
        "segment_owner": hypothesis["segment_owner"],
        "hypothesis_label": hypothesis["hypothesis_label"],
        "experiment_family": hypothesis["mutation_family"],
        "baseline_model": baseline_model,
        "baseline_paper_path": baseline_paper_path,
        "input_paths": input_paths,
        "script_path": script_path,
        "script_args": script_args,
        "expected_outputs": policy["default_expected_outputs"],
        "scoring_profile": policy["default_scoring_profile"],
        "promotion_rule": policy["default_promotion_rule"],
        "invalidation_rule": policy["default_invalidation_rule"],
        "budget_class": policy["branch_defaults"]["core"]["budget_class"],
        "priority": policy["branch_defaults"]["core"]["priority"],
        "created_by": policy["default_created_by"],
        "created_at": utc_now_iso(),
        "status": "spec_ready"
    }

    missing = [field for field in policy["required_spec_fields"] if spec.get(field) in (None, "", [])]
    if missing:
        raise SpecGenerationError(f"generated spec missing required fields: {missing}")

    return spec


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    fieldnames = [
        "experiment_id",
        "branch",
        "segment_owner",
        "hypothesis_label",
        "experiment_family",
        "baseline_model",
        "baseline_paper_path",
        "script_path",
        "budget_class",
        "priority",
        "status",
        "spec_path"
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate contract-compliant orchestrator-compatible experiment specs.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise SpecGenerationError("choose exactly one of --dry-run or --execute")

    print("[START] research_os_experiment_spec_generator_v1")

    policy = load_json(POLICY_PATH)
    truth_pack = load_json(TRUTH_PACK_PATH)
    hypotheses_payload = load_json(HYPOTHESES_PATH)
    hypotheses = resolve_hypotheses(hypotheses_payload)

    output_dir = Path(policy["output_dir"])
    summary_csv_path = Path(policy["summary_csv_path"])
    summary_json_path = Path(policy["summary_json_path"])
    log_jsonl_path = Path(policy["log_jsonl_path"])

    generated_specs_payload: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for hypothesis in hypotheses:
        spec = build_spec(policy, truth_pack, hypothesis)
        spec_path = output_dir / f"{spec['experiment_id']}.spec_ready.json"

        generated_specs_payload.append({"spec_path": str(spec_path), "spec": spec})
        summary_rows.append({
            "experiment_id": spec["experiment_id"],
            "branch": spec["branch"],
            "segment_owner": spec["segment_owner"],
            "hypothesis_label": spec["hypothesis_label"],
            "experiment_family": spec["experiment_family"],
            "baseline_model": spec["baseline_model"],
            "baseline_paper_path": spec["baseline_paper_path"],
            "script_path": spec["script_path"],
            "budget_class": spec["budget_class"],
            "priority": spec["priority"],
            "status": spec["status"],
            "spec_path": str(spec_path)
        })

    if args.execute:
        for item in generated_specs_payload:
            write_json(Path(item["spec_path"]), item["spec"])

        write_json(summary_json_path, {"generated_specs": generated_specs_payload})
        write_summary_csv(summary_csv_path, summary_rows)
        append_jsonl(log_jsonl_path, {
            "ts": utc_now_iso(),
            "event": "spec_generation_completed",
            "policy_name": policy["policy_name"],
            "policy_version": policy["policy_version"],
            "generated_count": len(generated_specs_payload)
        })
        print(f"[SAVED] specs={len(generated_specs_payload)}")
        print(f"[SAVED] summary_json={summary_json_path}")
        print(f"[SAVED] summary_csv={summary_csv_path}")
    else:
        print(f"[DRY-RUN] would_generate_specs={len(generated_specs_payload)}")
        for row in summary_rows:
            print(f"[DRY-RUN] {row['experiment_id']} | {row['experiment_family']} | {row['status']}")

    print("[END] research_os_experiment_spec_generator_v1")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)