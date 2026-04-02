from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LOOP_OUTPUT_DIR = ROOT / "outputs" / "research_os_autonomous_loop_v1"

INPUT_FILES = {
    "loop_manifest": "autonomous_loop_run_manifest.json",
    "loop_summary_json": "autonomous_loop_run_summary.json",
    "loop_summary_csv": "autonomous_loop_run_summary.csv",
    "zero_selection_diagnostics_json": "zero_selection_diagnostics.json",
    "zero_selection_diagnostics_csv": "zero_selection_diagnostics.csv",
    "candidate_trace_log_jsonl": "candidate_trace_log.jsonl",
}

OUTPUT_FILES = {
    "bundle_json": "autonomous_quality_audit_bundle.json",
    "bundle_txt": "autonomous_quality_audit_bundle.txt",
    "bundle_manifest": "autonomous_quality_audit_bundle_manifest.json",
}

EXPLICIT_IDEATION_PATHS = [
    ROOT / "outputs" / "research_os_ideation_v1" / "ideation_hypotheses.json",
    ROOT / "research_os" / "ideation" / "ideation_hypotheses.json",
]

EXPLICIT_GENERATED_SPECS_JSON_PATHS = [
    ROOT / "research_os" / "experiment_specs" / "generated" / "generated_experiment_specs.json",
    ROOT / "outputs" / "research_os_spec_generation_v1" / "generated_experiment_specs.json",
]

EXPLICIT_GENERATED_SPECS_SUMMARY_PATHS = [
    ROOT / "research_os" / "experiment_specs" / "generated" / "generated_experiment_specs_summary.csv",
    ROOT / "outputs" / "research_os_spec_generation_v1" / "generated_experiment_specs_summary.csv",
]

EXPLICIT_REGISTRY_PATHS = [
    ROOT / "research_os" / "leaderboards" / "research_os_registry.csv",
    ROOT / "research_os" / "candidates_registry.csv",
]

RUN_ARTIFACTS = {
    "run_manifest": "run_manifest.json",
    "run_status": "run_status.json",
    "quality_report": "quality_report.json",
    "scoring_result": "scoring_result.json",
    "precheck_inputs": "precheck_inputs.json",
    "precheck_result": "precheck_result.json",
    "selection_result": "selection_result.json",
    "promotion_decision": "promotion_decision.json",
    "governance_result": "governance_result.json",
    "artifacts_index": "artifacts_index.json",
    "lifecycle_audit": "lifecycle_audit.jsonl",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def print_kv(key: str, value: Any) -> None:
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False)
    else:
        rendered = str(value)
    print(f"[AUDITBUNDLE] {key}={rendered}", flush=True)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_lower(value: Any) -> str:
    return normalize_text(value).lower()


def parse_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_optional(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return load_json(path)
    except Exception:
        return None


def load_csv_optional(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def load_jsonl_optional(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                out.append(payload)
        except Exception:
            continue
    return out


def resolve_first_existing(paths: list[Path], label: str) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    print_kv(f"{label}_path_status", "MISSING_IN_OUTPUT")
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS audit bundle export v1")
    parser.add_argument("--loop-output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.dry_run == args.execute:
        raise SystemExit("Choose exactly one of --dry-run or --execute.")
    return args


def recursive_find_first(obj: Any, keys: list[str]) -> Any | None:
    wanted = {k.lower() for k in keys}

    def _walk(node: Any) -> Any | None:
        if isinstance(node, dict):
            for k, v in node.items():
                if str(k).lower() in wanted:
                    return v
            for v in node.values():
                found = _walk(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found is not None:
                    return found
        return None

    return _walk(obj)


def parse_json_list_or_pipe(value: Any) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                return [normalize_text(x) for x in payload if normalize_text(x)]
        except Exception:
            pass
    if "|" in text:
        return [part.strip() for part in text.split("|") if part.strip()]
    return [text]


def path_status(path: Path | None) -> tuple[str, str]:
    if path is None:
        return "MISSING_IN_OUTPUT", "missing artifact"
    if not path.exists():
        return "MISSING_IN_OUTPUT", "not generated by pipeline"
    return str(path), ""


def artifact_or_missing(path: Path | None) -> tuple[str, str, Any | None]:
    if path is None:
        return "MISSING_IN_OUTPUT", "missing artifact", None
    if not path.exists():
        return "MISSING_IN_OUTPUT", "not generated by pipeline", None
    if path.suffix.lower() == ".json":
        return str(path), "", load_json_optional(path)
    if path.suffix.lower() == ".jsonl":
        return str(path), "", load_jsonl_optional(path)
    return str(path), "", None


def safe_reason_list(*values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = normalize_text(item)
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
        else:
            text = normalize_text(value)
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out


def build_run_artifact_paths(run_dir: str) -> dict[str, Path | None]:
    if not run_dir:
        return {k: None for k in RUN_ARTIFACTS.keys()}
    base = Path(run_dir)
    return {k: base / filename for k, filename in RUN_ARTIFACTS.items()}


def load_loop_inputs(loop_output_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest_path = loop_output_dir / INPUT_FILES["loop_manifest"]
    summary_json_path = loop_output_dir / INPUT_FILES["loop_summary_json"]
    summary_csv_path = loop_output_dir / INPUT_FILES["loop_summary_csv"]
    diagnostics_json_path = loop_output_dir / INPUT_FILES["zero_selection_diagnostics_json"]

    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing required loop manifest: {manifest_path}")
    if not summary_json_path.exists():
        raise FileNotFoundError(f"Missing required loop summary json: {summary_json_path}")
    if not summary_csv_path.exists():
        raise FileNotFoundError(f"Missing required loop summary csv: {summary_csv_path}")
    if not diagnostics_json_path.exists():
        raise FileNotFoundError(f"Missing required diagnostics json: {diagnostics_json_path}")

    manifest = load_json(manifest_path)
    summary_json = load_json(summary_json_path)
    summary_rows = summary_json.get("rows")
    if not isinstance(summary_rows, list):
        summary_rows = load_csv_optional(summary_csv_path)

    diagnostics_json = load_json(diagnostics_json_path)
    return manifest, summary_json, summary_rows, diagnostics_json


def build_summary_row_map(summary_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in summary_rows:
        spec_path = normalize_text(row.get("spec_path"))
        run_dirs = parse_json_list_or_pipe(row.get("new_run_dirs"))
        if run_dirs:
            for run_dir in run_dirs:
                out[(spec_path, run_dir)] = row
        else:
            out[(spec_path, "")] = row
    return out


def build_ideation_maps(ideation_payload: Any) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}

    if isinstance(ideation_payload, list):
        rows = ideation_payload
    elif isinstance(ideation_payload, dict) and isinstance(ideation_payload.get("hypotheses"), list):
        rows = ideation_payload["hypotheses"]
    else:
        rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        hyp_id = normalize_text(row.get("hypothesis_id"))
        label = normalize_text(row.get("hypothesis_label"))
        if hyp_id:
            by_id[hyp_id] = row
        if label:
            by_label[label] = row

    return by_id, by_label


def build_generated_spec_map(payload: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    if isinstance(payload, dict) and isinstance(payload.get("generated_specs"), list):
        rows = payload["generated_specs"]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        spec_path = normalize_text(row.get("spec_path"))
        spec_obj = row.get("spec")
        if spec_path and isinstance(spec_obj, dict):
            out[spec_path] = spec_obj
        elif isinstance(row, dict) and normalize_text(row.get("spec_id")) and normalize_text(row.get("spec_file")):
            out[normalize_text(row["spec_file"])] = row

    return out


def derive_baseline_from_spec(spec_json: dict[str, Any]) -> str:
    baseline_model = spec_json.get("baseline_model")
    if isinstance(baseline_model, dict):
        value = normalize_text(baseline_model.get("model_key"))
        if value:
            return value
    if isinstance(baseline_model, str):
        value = normalize_text(baseline_model)
        if value:
            return value
    value = normalize_text(spec_json.get("baseline_reference"))
    return value or "MISSING_IN_OUTPUT"


def derive_mutation_family(spec_json: dict[str, Any]) -> str:
    value = normalize_text(spec_json.get("experiment_family"))
    if value:
        return value
    overrides = spec_json.get("parameter_overrides")
    if isinstance(overrides, dict):
        value = normalize_text(overrides.get("profile_family"))
        if value:
            return value
    return "MISSING_IN_OUTPUT"


def render_bundle_txt(payload: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append("AUTONOMOUS QUALITY AUDIT BUNDLE")
    lines.append("")
    lines.append("A) BUNDLE SUMMARY")
    lines.append(f"- generated_at_utc = {payload['generated_at_utc']}")
    lines.append(f"- loop_output_dir = {payload['loop_output_dir']}")
    lines.append(f"- trace_rows_count = {payload['trace_rows_count']}")
    lines.append(f"- worthy_candidates_count = {payload['worthy_candidates_count']}")
    lines.append(f"- zero_selection_confirmed = {payload['zero_selection_confirmed']}")
    lines.append(f"- reason_code_counts = {json.dumps(payload['reason_code_counts'], ensure_ascii=False)}")
    lines.append("")
    lines.append("B) CANDIDATE DUMP")

    for item in payload["candidates"]:
        lines.append("")
        lines.append(f"bundle_entry_id: {item['bundle_entry_id']}")
        lines.append(f"candidate_id: {item['candidate_id']}")
        lines.append(f"mutation_family: {item['mutation_family']}")
        lines.append(f"branch: {item['branch']}")
        lines.append(f"segment_owner: {item['segment_owner']}")
        lines.append(f"hypothesis_label: {item['hypothesis_label']}")
        lines.append(f"hypothesis_text: {item['hypothesis_text']}")
        lines.append(f"target_baseline: {item['target_baseline']}")
        lines.append(f"experiment_spec_path: {item['experiment_spec_path']}")
        lines.append("experiment_spec_json:")
        lines.append(json.dumps(item["experiment_spec_json"], indent=2, ensure_ascii=False))
        lines.append("")
        lines.append(f"scoring_result_path: {item['scoring_result_path']}")
        lines.append(f"final_score: {item['final_score']}")
        lines.append(f"promotion_recommendation: {item['promotion_recommendation']}")
        lines.append(f"reason_codes: {json.dumps(item['reason_codes'], ensure_ascii=False)}")
        lines.append(f"precheck_decision: {item['precheck_decision']}")
        lines.append(f"first_failure_stage: {item['first_failure_stage']}")
        lines.append(f"first_failure_reason_code: {item['first_failure_reason_code']}")
        lines.append(f"selection_block_reason: {item['selection_block_reason']}")
        lines.append(f"governance_block_reason: {item['governance_block_reason']}")
        lines.append("")
        lines.append("notes_or_diagnostics:")
        for note in item["notes_or_diagnostics"]:
            lines.append(f"- {note}")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    mode = "execute" if args.execute else "dry-run"

    loop_output_dir = Path(args.loop_output_dir)

    print_kv("mode", mode)
    print_kv("loop_output_dir", str(loop_output_dir))

    manifest, summary_json, summary_rows, diagnostics_json = load_loop_inputs(loop_output_dir)
    diagnostics_traces = diagnostics_json.get("traces")
    if not isinstance(diagnostics_traces, list):
        raise ValueError("zero_selection_diagnostics.json does not contain trace list.")

    if not diagnostics_traces:
        raise RuntimeError("No diagnostics traces found. Audit bundle cannot be empty.")

    summary_row_map = build_summary_row_map(summary_rows)

    ideation_path = resolve_first_existing(EXPLICIT_IDEATION_PATHS, "ideation_hypotheses")
    ideation_payload = load_json_optional(ideation_path) if ideation_path else None
    ideation_by_id, ideation_by_label = build_ideation_maps(ideation_payload)

    generated_specs_json_path = resolve_first_existing(EXPLICIT_GENERATED_SPECS_JSON_PATHS, "generated_experiment_specs_json")
    generated_specs_payload = load_json_optional(generated_specs_json_path) if generated_specs_json_path else None
    generated_spec_map = build_generated_spec_map(generated_specs_payload)

    generated_specs_summary_path = resolve_first_existing(EXPLICIT_GENERATED_SPECS_SUMMARY_PATHS, "generated_experiment_specs_summary_csv")

    registry_paths_present = [str(path) for path in EXPLICIT_REGISTRY_PATHS if path.exists()]

    print_kv("trace_rows_count", len(diagnostics_traces))
    print_kv("summary_rows_count", len(summary_rows))
    print_kv("ideation_path", str(ideation_path) if ideation_path else "MISSING_IN_OUTPUT")
    print_kv("generated_specs_json_path", str(generated_specs_json_path) if generated_specs_json_path else "MISSING_IN_OUTPUT")
    print_kv("generated_specs_summary_path", str(generated_specs_summary_path) if generated_specs_summary_path else "MISSING_IN_OUTPUT")
    print_kv("registry_paths_present", registry_paths_present)

    bundle_rows: list[dict[str, Any]] = []
    reason_code_counts: dict[str, int] = {}
    scoring_paths: list[str] = []
    precheck_paths: list[str] = []

    for idx, trace in enumerate(diagnostics_traces, start=1):
        if not isinstance(trace, dict):
            continue

        candidate_id = normalize_text(trace.get("candidate_id"))
        spec_path = normalize_text(trace.get("spec_path"))
        run_dir = normalize_text(trace.get("run_dir"))
        hypothesis_label_from_trace = normalize_text(trace.get("hypothesis_label"))

        spec_json = None
        if spec_path and Path(spec_path).exists():
            spec_json = load_json_optional(Path(spec_path))
        if spec_json is None and spec_path in generated_spec_map:
            candidate_spec = generated_spec_map[spec_path]
            if isinstance(candidate_spec, dict):
                spec_json = candidate_spec
        if not isinstance(spec_json, dict):
            spec_json = {
                "status": "MISSING_IN_OUTPUT",
                "reason": "missing artifact",
            }

        source_hypothesis_id = normalize_text(spec_json.get("source_hypothesis_id"))
        hypothesis_label = normalize_text(spec_json.get("hypothesis_label")) or hypothesis_label_from_trace or "MISSING_IN_OUTPUT"

        ideation_row = None
        if source_hypothesis_id and source_hypothesis_id in ideation_by_id:
            ideation_row = ideation_by_id[source_hypothesis_id]
        elif hypothesis_label and hypothesis_label in ideation_by_label:
            ideation_row = ideation_by_label[hypothesis_label]

        mutation_family = derive_mutation_family(spec_json)
        branch = normalize_text(spec_json.get("branch")) or normalize_text(trace.get("branch")) or "MISSING_IN_OUTPUT"
        segment_owner = normalize_text(spec_json.get("segment_owner")) or "MISSING_IN_OUTPUT"
        target_baseline = derive_baseline_from_spec(spec_json)

        hypothesis_text = "MISSING_IN_OUTPUT"
        hypothesis_text_reason = "missing artifact"
        hypothesis_rationale = "MISSING_IN_OUTPUT"

        if isinstance(ideation_row, dict):
            raw_hyp_text = normalize_text(ideation_row.get("hypothesis_text"))
            raw_rationale = normalize_text(ideation_row.get("rationale"))
            if raw_hyp_text:
                hypothesis_text = raw_hyp_text
                hypothesis_text_reason = ""
            else:
                hypothesis_text = "MISSING_IN_OUTPUT"
                hypothesis_text_reason = "not generated by pipeline"
            if raw_rationale:
                hypothesis_rationale = raw_rationale

        summary_row = summary_row_map.get((spec_path, run_dir)) or summary_row_map.get((spec_path, ""))
        cycle = normalize_text(summary_row.get("cycle")) if isinstance(summary_row, dict) else ""
        dispatch_returncode = normalize_text(summary_row.get("dispatch_returncode")) if isinstance(summary_row, dict) else ""

        run_artifact_paths = build_run_artifact_paths(run_dir)

        scoring_path = None
        if run_artifact_paths["scoring_result"] and run_artifact_paths["scoring_result"].exists():
            scoring_path = run_artifact_paths["scoring_result"]
        elif run_artifact_paths["quality_report"] and run_artifact_paths["quality_report"].exists():
            scoring_path = run_artifact_paths["quality_report"]

        scoring_result_path, scoring_result_reason, scoring_payload = artifact_or_missing(scoring_path)
        if scoring_result_path != "MISSING_IN_OUTPUT":
            scoring_paths.append(scoring_result_path)

        precheck_path = None
        if run_artifact_paths["precheck_result"] and run_artifact_paths["precheck_result"].exists():
            precheck_path = run_artifact_paths["precheck_result"]
        precheck_result_path, precheck_result_reason, precheck_payload = artifact_or_missing(precheck_path)
        if precheck_result_path != "MISSING_IN_OUTPUT":
            precheck_paths.append(precheck_result_path)

        promotion_decision_path, _, promotion_payload = artifact_or_missing(run_artifact_paths["promotion_decision"])
        selection_result_path, _, selection_payload = artifact_or_missing(run_artifact_paths["selection_result"])
        governance_result_path, _, governance_payload = artifact_or_missing(run_artifact_paths["governance_result"])

        final_score = trace.get("final_score")
        if final_score in (None, "") and isinstance(scoring_payload, dict):
            final_score = recursive_find_first(scoring_payload, ["final_score", "score", "primary_score", "overall_score"])
        final_score = parse_float(final_score)
        if final_score is None:
            final_score_export: Any = "MISSING_IN_OUTPUT"
        else:
            final_score_export = final_score

        promotion_recommendation = normalize_text(trace.get("promotion_recommendation"))
        if not promotion_recommendation and isinstance(scoring_payload, dict):
            promotion_recommendation = normalize_text(
                recursive_find_first(scoring_payload, ["promotion_recommendation", "recommendation", "verdict"])
            )
        if not promotion_recommendation and isinstance(promotion_payload, dict):
            promotion_recommendation = normalize_text(
                recursive_find_first(promotion_payload, ["promotion_recommendation", "recommendation", "decision"])
            )
        if not promotion_recommendation:
            promotion_recommendation = "MISSING_IN_OUTPUT"

        precheck_decision = normalize_text(trace.get("precheck_decision"))
        if not precheck_decision and isinstance(precheck_payload, dict):
            precheck_decision = normalize_text(
                recursive_find_first(precheck_payload, ["decision", "precheck_decision", "status", "verdict"])
            )
        if not precheck_decision:
            precheck_decision = "MISSING_IN_OUTPUT"

        first_failure_stage = normalize_text(trace.get("first_failure_stage")) or "MISSING_IN_OUTPUT"
        first_failure_reason_code = normalize_text(trace.get("first_failure_reason_code")) or "MISSING_IN_OUTPUT"
        selection_block_reason = normalize_text(trace.get("selection_block_reason")) or "MISSING_IN_OUTPUT"
        governance_block_reason = normalize_text(trace.get("governance_block_reason")) or "MISSING_IN_OUTPUT"

        reason_codes = safe_reason_list(
            first_failure_reason_code,
            selection_block_reason if selection_block_reason != first_failure_reason_code else "",
            governance_block_reason if governance_block_reason not in {first_failure_reason_code, selection_block_reason} else "",
        )
        if not reason_codes:
            reason_codes = ["MISSING_IN_OUTPUT"]

        for code in reason_codes:
            reason_code_counts[code] = reason_code_counts.get(code, 0) + 1

        notes: list[str] = []
        if hypothesis_text == "MISSING_IN_OUTPUT":
            notes.append(f"MISSING_IN_OUTPUT::hypothesis_text::{hypothesis_text_reason}")
        if scoring_result_path == "MISSING_IN_OUTPUT":
            notes.append(f"MISSING_IN_OUTPUT::scoring_result_path::{scoring_result_reason}")
        if precheck_result_path == "MISSING_IN_OUTPUT":
            notes.append(f"MISSING_IN_OUTPUT::precheck_result_path::{precheck_result_reason}")
        if not run_dir:
            notes.append("MISSING_IN_OUTPUT::run_dir::missing artifact")
        if isinstance(spec_json, dict) and spec_json.get("status") == "MISSING_IN_OUTPUT":
            notes.append("MISSING_IN_OUTPUT::experiment_spec_json::missing artifact")
        if not notes:
            notes.append("artifacts_linked_from_explicit_loop_spec_run_outputs")

        row = {
            "bundle_entry_id": f"bundle_entry_{idx:03d}",
            "candidate_id": candidate_id or "MISSING_IN_OUTPUT",
            "mutation_family": mutation_family,
            "branch": branch,
            "segment_owner": segment_owner,
            "hypothesis_label": hypothesis_label,
            "hypothesis_text": hypothesis_text,
            "hypothesis_rationale": hypothesis_rationale,
            "target_baseline": target_baseline,
            "experiment_spec_path": spec_path or "MISSING_IN_OUTPUT",
            "experiment_spec_json": spec_json,
            "scoring_result_path": scoring_result_path,
            "final_score": final_score_export,
            "promotion_recommendation": promotion_recommendation,
            "reason_codes": reason_codes,
            "precheck_decision": precheck_decision,
            "first_failure_stage": first_failure_stage,
            "first_failure_reason_code": first_failure_reason_code,
            "selection_block_reason": selection_block_reason,
            "governance_block_reason": governance_block_reason,
            "notes_or_diagnostics": notes,
            "source_hypothesis_id": source_hypothesis_id or "MISSING_IN_OUTPUT",
            "run_dir": run_dir or "MISSING_IN_OUTPUT",
            "cycle": cycle or "MISSING_IN_OUTPUT",
            "dispatch_returncode": dispatch_returncode or "MISSING_IN_OUTPUT",
            "precheck_result_path": precheck_result_path,
            "selection_result_path": selection_result_path,
            "promotion_decision_path": promotion_decision_path,
            "governance_result_path": governance_result_path,
        }
        bundle_rows.append(row)

    if not bundle_rows:
        raise RuntimeError("Bundle export produced zero candidate rows.")

    worthy_candidates_count = 0
    for row in bundle_rows:
        if normalize_lower(row["governance_block_reason"]) not in {"missing_in_output", ""}:
            continue
        if normalize_lower(row["first_failure_reason_code"]) == "missing_in_output":
            continue
        if "LEGIT_LOW_QUALITY_REJECTION" not in row["reason_codes"]:
            worthy_candidates_count += 1

    zero_selection_confirmed = all("LEGIT_LOW_QUALITY_REJECTION" in row["reason_codes"] for row in bundle_rows)

    bundle_payload = {
        "generated_at_utc": now_utc_iso(),
        "mode": mode,
        "loop_output_dir": str(loop_output_dir),
        "trace_rows_count": len(bundle_rows),
        "worthy_candidates_count": worthy_candidates_count,
        "zero_selection_confirmed": zero_selection_confirmed,
        "reason_code_counts": reason_code_counts,
        "source_files": {
            "loop_manifest_path": str(loop_output_dir / INPUT_FILES["loop_manifest"]),
            "loop_summary_json_path": str(loop_output_dir / INPUT_FILES["loop_summary_json"]),
            "loop_summary_csv_path": str(loop_output_dir / INPUT_FILES["loop_summary_csv"]),
            "zero_selection_diagnostics_json_path": str(loop_output_dir / INPUT_FILES["zero_selection_diagnostics_json"]),
            "zero_selection_diagnostics_csv_path": str(loop_output_dir / INPUT_FILES["zero_selection_diagnostics_csv"]),
            "candidate_trace_log_jsonl_path": str(loop_output_dir / INPUT_FILES["candidate_trace_log_jsonl"]),
            "ideation_hypotheses_json_path": str(ideation_path) if ideation_path else "MISSING_IN_OUTPUT",
            "generated_experiment_specs_json_path": str(generated_specs_json_path) if generated_specs_json_path else "MISSING_IN_OUTPUT",
            "generated_experiment_specs_summary_csv_path": str(generated_specs_summary_path) if generated_specs_summary_path else "MISSING_IN_OUTPUT",
            "registry_paths": registry_paths_present,
            "per_candidate_scoring_result_paths": scoring_paths if scoring_paths else ["MISSING_IN_OUTPUT"],
            "per_candidate_precheck_result_paths": precheck_paths if precheck_paths else ["MISSING_IN_OUTPUT"],
        },
        "candidates": bundle_rows,
    }

    bundle_manifest = {
        "generated_at_utc": now_utc_iso(),
        "mode": mode,
        "loop_output_dir": str(loop_output_dir),
        "candidate_count": len(bundle_rows),
        "source_file_count": len(bundle_payload["source_files"]),
        "output_files": {
            "bundle_json": str(loop_output_dir / OUTPUT_FILES["bundle_json"]),
            "bundle_txt": str(loop_output_dir / OUTPUT_FILES["bundle_txt"]),
            "bundle_manifest": str(loop_output_dir / OUTPUT_FILES["bundle_manifest"]),
        },
        "source_files": bundle_payload["source_files"],
        "reason_code_counts": reason_code_counts,
    }

    print_kv("candidate_count", len(bundle_rows))
    print_kv("worthy_candidates_count", worthy_candidates_count)
    print_kv("zero_selection_confirmed", zero_selection_confirmed)
    print_kv("reason_code_counts", reason_code_counts)

    if mode == "dry-run":
        print_kv("bundle_json", str(loop_output_dir / OUTPUT_FILES["bundle_json"]))
        print_kv("bundle_txt", str(loop_output_dir / OUTPUT_FILES["bundle_txt"]))
        print_kv("bundle_manifest", str(loop_output_dir / OUTPUT_FILES["bundle_manifest"]))
        return

    bundle_json_path = loop_output_dir / OUTPUT_FILES["bundle_json"]
    bundle_txt_path = loop_output_dir / OUTPUT_FILES["bundle_txt"]
    bundle_manifest_path = loop_output_dir / OUTPUT_FILES["bundle_manifest"]

    write_json(bundle_json_path, bundle_payload)
    bundle_txt_path.write_text(render_bundle_txt(bundle_payload), encoding="utf-8")
    write_json(bundle_manifest_path, bundle_manifest)

    if not bundle_json_path.exists() or not bundle_txt_path.exists() or not bundle_manifest_path.exists():
        raise RuntimeError("Required audit bundle outputs were not written.")

    print_kv("status", "OK")
    print_kv("autonomous_quality_audit_bundle_json", str(bundle_json_path))
    print_kv("autonomous_quality_audit_bundle_txt", str(bundle_txt_path))
    print_kv("autonomous_quality_audit_bundle_manifest_json", str(bundle_manifest_path))


if __name__ == "__main__":
    main()