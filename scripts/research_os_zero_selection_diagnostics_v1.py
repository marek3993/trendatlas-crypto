from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LOOP_OUTPUT_DIR = ROOT / "outputs" / "research_os_autonomous_loop_v1"

LOOP_MANIFEST_NAME = "autonomous_loop_run_manifest.json"
LOOP_SUMMARY_JSON_NAME = "autonomous_loop_run_summary.json"
LOOP_SUMMARY_CSV_NAME = "autonomous_loop_run_summary.csv"

OUTPUT_JSON_NAME = "zero_selection_diagnostics.json"
OUTPUT_CSV_NAME = "zero_selection_diagnostics.csv"
TRACE_JSONL_NAME = "candidate_trace_log.jsonl"

RESEARCH_OS_RUNS_ROOT = ROOT / "research_os" / "runs"

EXPLICIT_REGISTRY_PATHS = [
    ROOT / "research_os" / "leaderboards" / "research_os_registry.csv",
    ROOT / "research_os" / "candidates_registry.csv",
]

EXPLICIT_RUN_FILES = {
    "run_manifest": "run_manifest.json",
    "run_status": "run_status.json",
    "quality_report": "quality_report.json",
    "precheck_inputs": "precheck_inputs.json",
    "precheck_result": "precheck_result.json",
    "selection_result": "selection_result.json",
    "promotion_decision": "promotion_decision.json",
    "governance_result": "governance_result.json",
    "artifacts_index": "artifacts_index.json",
    "lifecycle_audit": "lifecycle_audit.jsonl",
}

FAILISH_TOKENS = {
    "fail",
    "failed",
    "error",
    "blocked",
    "reject",
    "rejected",
    "deny",
    "denied",
    "invalid",
    "not_worthy",
    "not-worthy",
    "kill",
    "killed",
    "skip",
    "skipped",
}

PASSISH_TOKENS = {
    "ok",
    "pass",
    "passed",
    "success",
    "succeeded",
    "complete",
    "completed",
    "approved",
    "ready",
    "accepted",
    "written",
}

FORWARD_GOVERNANCE_TOKENS = {
    "forensic_ready",
    "master_pending",
    "governance_staged",
    "promotion_staged",
    "queued_for_governance",
    "queued",
}

STAGE_ORDER = [
    "orchestrator",
    "run_dir",
    "run_manifest",
    "scoring",
    "precheck",
    "selection",
    "governance",
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_optional(path: Path) -> Any | None:
    if not path.exists():
        return None
    return load_json(path)


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


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_csv_optional(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return load_csv(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS post-run zero-selection diagnostics v1")
    parser.add_argument("--loop-output-dir", required=True, help="Path to completed autonomous loop output dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise SystemExit("Choose exactly one of --dry-run or --execute.")
    return args


def print_kv(key: str, value: Any) -> None:
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, ensure_ascii=False)
    else:
        rendered = str(value)
    print(f"[ZEROSEL] {key}={rendered}", flush=True)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_lower(value: Any) -> str:
    return normalize_text(value).lower()


def parse_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        try:
            return int(float(str(value)))
        except Exception:
            return default


def parse_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


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


def status_from_payload(payload: Any, fallback: str = "missing") -> str:
    if payload is None:
        return fallback
    value = recursive_find_first(
        payload,
        [
            "status",
            "decision",
            "result",
            "recommendation",
            "verdict",
            "state",
        ],
    )
    if value is None:
        return "present_unknown"
    text = normalize_lower(value)
    return text or "present_unknown"


def recommendation_from_payload(payload: Any) -> str:
    value = recursive_find_first(
        payload,
        [
            "recommendation",
            "promotion_recommendation",
            "selection_recommendation",
            "governance_recommendation",
            "decision",
            "verdict",
        ],
    )
    return normalize_text(value)


def final_score_from_payload(payload: Any) -> float | None:
    value = recursive_find_first(
        payload,
        [
            "final_score",
            "score",
            "primary_score",
            "overall_score",
        ],
    )
    return parse_float(value)


def bool_failish(value: Any) -> bool:
    text = normalize_lower(value)
    if not text:
        return False
    return text in FAILISH_TOKENS or any(tok in text for tok in FAILISH_TOKENS)


def bool_passish(value: Any) -> bool:
    text = normalize_lower(value)
    if not text:
        return False
    return text in PASSISH_TOKENS or any(tok in text for tok in PASSISH_TOKENS)


def governance_forwardish(value: Any) -> bool:
    text = normalize_lower(value)
    if not text:
        return False
    return text in FORWARD_GOVERNANCE_TOKENS or any(tok in text for tok in FORWARD_GOVERNANCE_TOKENS)


def normalize_run_dirs(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_text(x) for x in value if normalize_text(x)]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [normalize_text(x) for x in parsed if normalize_text(x)]
            except Exception:
                pass
        if "|" in text:
            return [part.strip() for part in text.split("|") if part.strip()]
        return [text]
    return []


def load_loop_rows(loop_output_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest_path = loop_output_dir / LOOP_MANIFEST_NAME
    summary_json_path = loop_output_dir / LOOP_SUMMARY_JSON_NAME
    summary_csv_path = loop_output_dir / LOOP_SUMMARY_CSV_NAME

    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing loop manifest: {manifest_path}")
    if not summary_json_path.exists():
        raise FileNotFoundError(f"Missing loop summary json: {summary_json_path}")
    if not summary_csv_path.exists():
        raise FileNotFoundError(f"Missing loop summary csv: {summary_csv_path}")

    manifest = load_json(manifest_path)
    summary_json = load_json(summary_json_path)

    rows = summary_json.get("rows")
    if not isinstance(rows, list):
        rows = load_csv(summary_csv_path)

    if not isinstance(rows, list):
        raise ValueError("Loop summary rows are not readable.")

    return manifest, summary_json, rows


def load_registry_context() -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "paths": [],
        "rows": [],
    }
    for path in EXPLICIT_REGISTRY_PATHS:
        rows = load_csv_optional(path)
        ctx["paths"].append(str(path))
        for row in rows:
            out = dict(row)
            out["_registry_path"] = str(path)
            ctx["rows"].append(out)
    return ctx


def value_matches(candidate_values: set[str], row: dict[str, Any]) -> bool:
    for value in row.values():
        if normalize_text(value) in candidate_values:
            return True
    return False


def find_related_registry_rows(
    registry_rows: list[dict[str, Any]],
    candidate_id: str,
    experiment_id: str,
    spec_path: str,
    run_dir: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact_values = {
        v
        for v in [
            normalize_text(candidate_id),
            normalize_text(experiment_id),
            normalize_text(spec_path),
            normalize_text(run_dir),
            normalize_text(Path(run_dir).name) if run_dir else "",
        ]
        if v
    }

    fuzzy_values = {
        v
        for v in [
            normalize_text(experiment_id),
            normalize_text(Path(spec_path).stem) if spec_path else "",
            normalize_text(Path(run_dir).name) if run_dir else "",
        ]
        if v
    }

    exact_rows: list[dict[str, Any]] = []
    fuzzy_rows: list[dict[str, Any]] = []

    for row in registry_rows:
        if value_matches(exact_values, row):
            exact_rows.append(row)
        elif value_matches(fuzzy_values, row):
            fuzzy_rows.append(row)

    return exact_rows, fuzzy_rows


def derive_selection_status(
    selection_payload: Any,
    exact_registry_rows: list[dict[str, Any]],
    lifecycle_events: list[dict[str, Any]],
) -> str:
    if selection_payload is not None:
        return status_from_payload(selection_payload)

    if exact_registry_rows:
        statuses = {
            normalize_lower(row.get("status")) or normalize_lower(row.get("lifecycle_stage"))
            for row in exact_registry_rows
        }
        statuses.discard("")
        if statuses:
            if any(bool_failish(s) for s in statuses):
                return "registry_written_reject"
            return "registry_written"

    for event in lifecycle_events:
        event_text = normalize_lower(event.get("event"))
        if "selection" in event_text:
            return normalize_lower(event.get("status")) or "selection_event_present"

    return "missing"


def derive_governance_status(
    governance_payload: Any,
    promotion_payload: Any,
    exact_registry_rows: list[dict[str, Any]],
    lifecycle_events: list[dict[str, Any]],
) -> str:
    for payload in [governance_payload, promotion_payload]:
        if payload is not None:
            status = status_from_payload(payload)
            if status:
                return status

    for row in exact_registry_rows:
        status = normalize_lower(row.get("status"))
        lifecycle = normalize_lower(row.get("lifecycle_stage"))
        for candidate in [status, lifecycle]:
            if governance_forwardish(candidate):
                return candidate
            if candidate and ("governance" in candidate or "promotion" in candidate):
                return candidate

    for event in lifecycle_events:
        event_text = normalize_lower(event.get("event"))
        if "governance" in event_text or "promotion" in event_text:
            return normalize_lower(event.get("status")) or event_text

    return "missing"


def terminal_stage_reached(
    orchestrator_ok: bool,
    run_dir_exists: bool,
    run_manifest_exists: bool,
    scoring_status: str,
    precheck_status: str,
    selection_status: str,
    governance_status: str,
) -> str:
    reached = "orchestrator"
    if run_dir_exists:
        reached = "run_dir"
    if run_manifest_exists:
        reached = "run_manifest"
    if scoring_status != "missing":
        reached = "scoring"
    if precheck_status != "missing":
        reached = "precheck"
    if selection_status != "missing":
        reached = "selection"
    if governance_status != "missing":
        reached = "governance"
    if not orchestrator_ok:
        return "orchestrator"
    return reached


def build_failure_map(
    orchestrator_ok: bool,
    run_dir_exists: bool,
    run_manifest_exists: bool,
    scoring_status: str,
    scoring_recommendation: str,
    precheck_status: str,
    precheck_decision: str,
    selection_status: str,
    governance_status: str,
    exact_registry_rows: list[dict[str, Any]],
    fuzzy_registry_rows: list[dict[str, Any]],
    selection_payload: Any,
) -> tuple[str, str, str, str, str]:
    first_failure_stage = ""
    first_failure_reason_code = ""
    selection_block_reason = ""
    governance_block_reason = ""
    promotion_block_reason = ""

    if not orchestrator_ok:
        return (
            "orchestrator",
            "ORCHESTRATOR_DISPATCH_FAILED",
            "UPSTREAM_ORCHESTRATOR_FAILURE",
            "UPSTREAM_ORCHESTRATOR_FAILURE",
            "UPSTREAM_ORCHESTRATOR_FAILURE",
        )

    if not run_dir_exists:
        return (
            "run_dir",
            "RUN_DIR_NOT_CREATED",
            "UPSTREAM_RUN_CREATION_FAILURE",
            "UPSTREAM_RUN_CREATION_FAILURE",
            "UPSTREAM_RUN_CREATION_FAILURE",
        )

    if not run_manifest_exists:
        return (
            "run_manifest",
            "RUN_MANIFEST_MISSING",
            "UPSTREAM_RUN_MANIFEST_MISSING",
            "UPSTREAM_RUN_MANIFEST_MISSING",
            "UPSTREAM_RUN_MANIFEST_MISSING",
        )

    if scoring_status == "missing":
        return (
            "scoring",
            "MISSING_OUTPUT_ARTIFACT__QUALITY_REPORT",
            "UPSTREAM_SCORING_ARTIFACT_MISSING",
            "UPSTREAM_SCORING_ARTIFACT_MISSING",
            "UPSTREAM_SCORING_ARTIFACT_MISSING",
        )

    if bool_failish(scoring_status) or bool_failish(scoring_recommendation):
        return (
            "scoring",
            "LEGIT_LOW_QUALITY_REJECTION",
            "LEGIT_LOW_QUALITY_REJECTION",
            "UPSTREAM_SCORING_REJECT",
            "UPSTREAM_SCORING_REJECT",
        )

    if precheck_status == "missing":
        return (
            "precheck",
            "MISSING_PRECHECK_RESULT",
            "UPSTREAM_PRECHECK_ARTIFACT_MISSING",
            "UPSTREAM_PRECHECK_ARTIFACT_MISSING",
            "UPSTREAM_PRECHECK_ARTIFACT_MISSING",
        )

    if bool_failish(precheck_status) or bool_failish(precheck_decision):
        return (
            "precheck",
            "PRECHECK_POLICY_BLOCK",
            "UPSTREAM_PRECHECK_POLICY_BLOCK",
            "UPSTREAM_PRECHECK_POLICY_BLOCK",
            "UPSTREAM_PRECHECK_POLICY_BLOCK",
        )

    if selection_status == "missing":
        if fuzzy_registry_rows and not exact_registry_rows:
            return (
                "selection",
                "INCONSISTENT_CANDIDATE_LINKAGE",
                "INFRA_BUG__INCONSISTENT_CANDIDATE_LINKAGE",
                "SELECTION_NOT_REACHED_DUE_TO_LINKAGE_BUG",
                "PROMOTION_NOT_REACHED_DUE_TO_LINKAGE_BUG",
            )
        if exact_registry_rows:
            return (
                "selection",
                "SELECTION_ARTIFACT_MISSING",
                "MISSING_SELECTION_ARTIFACT",
                "SELECTION_NOT_REACHED",
                "PROMOTION_NOT_REACHED",
            )
        return (
            "selection",
            "MISSING_REGISTRY_WRITE",
            "MISSING_REGISTRY_WRITE",
            "SELECTION_NOT_REACHED",
            "PROMOTION_NOT_REACHED",
        )

    if bool_failish(selection_status):
        return (
            "selection",
            "SELECTION_POLICY_BLOCK",
            "SELECTION_POLICY_BLOCK",
            "SELECTION_POLICY_BLOCK",
            "PROMOTION_NOT_REACHED",
        )

    if governance_status == "missing":
        return (
            "governance",
            "GOVERNANCE_NOT_STAGED",
            "",
            "GOVERNANCE_NOT_STAGED",
            "GOVERNANCE_NOT_STAGED",
        )

    if bool_failish(governance_status):
        return (
            "governance",
            "GOVERNANCE_POLICY_BLOCK",
            "",
            "GOVERNANCE_POLICY_BLOCK",
            "GOVERNANCE_POLICY_BLOCK",
        )

    if not governance_forwardish(governance_status):
        return (
            "governance",
            "GOVERNANCE_NOT_STAGED",
            "",
            "GOVERNANCE_NOT_STAGED",
            "GOVERNANCE_NOT_STAGED",
        )

    return (
        first_failure_stage,
        first_failure_reason_code,
        selection_block_reason,
        governance_block_reason,
        promotion_block_reason,
    )


def build_trace_rows(
    loop_row: dict[str, Any],
    registry_ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    spec_path = normalize_text(loop_row.get("spec_path"))
    experiment_id = normalize_text(loop_row.get("experiment_id"))
    dispatch_returncode = parse_int(loop_row.get("dispatch_returncode"))
    orchestrator_ok = dispatch_returncode == 0

    spec_payload = load_json_optional(Path(spec_path)) if spec_path and Path(spec_path).exists() else None
    run_dirs = normalize_run_dirs(loop_row.get("new_run_dirs"))

    if not run_dirs:
        run_dirs = [""]

    out: list[dict[str, Any]] = []

    for run_dir_str in run_dirs:
        run_dir = Path(run_dir_str) if run_dir_str else None
        run_dir_exists = bool(run_dir and run_dir.exists() and run_dir.is_dir())

        files: dict[str, Any] = {}
        if run_dir_exists and run_dir is not None:
            for key, filename in EXPLICIT_RUN_FILES.items():
                path = run_dir / filename
                if filename.endswith(".json"):
                    files[key] = load_json_optional(path)
                elif filename.endswith(".jsonl"):
                    files[key] = load_jsonl_optional(path)
                else:
                    files[key] = None
        else:
            for key in EXPLICIT_RUN_FILES:
                files[key] = None

        run_manifest = files["run_manifest"]
        run_manifest_exists = run_manifest is not None

        candidate_id = normalize_text(
            recursive_find_first(run_manifest, ["candidate_id", "experiment_id"])
        ) or experiment_id

        scoring_status = status_from_payload(files["quality_report"])
        scoring_recommendation = recommendation_from_payload(files["quality_report"])
        final_score = final_score_from_payload(files["quality_report"])

        precheck_status = status_from_payload(
            files["precheck_result"] if files["precheck_result"] is not None else files["precheck_inputs"]
        )
        precheck_decision = recommendation_from_payload(
            files["precheck_result"] if files["precheck_result"] is not None else files["precheck_inputs"]
        )

        exact_registry_rows, fuzzy_registry_rows = find_related_registry_rows(
            registry_ctx["rows"],
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            spec_path=spec_path,
            run_dir=run_dir_str,
        )

        selection_status = derive_selection_status(
            selection_payload=files["selection_result"],
            exact_registry_rows=exact_registry_rows,
            lifecycle_events=files["lifecycle_audit"] or [],
        )

        governance_status = derive_governance_status(
            governance_payload=files["governance_result"],
            promotion_payload=files["promotion_decision"],
            exact_registry_rows=exact_registry_rows,
            lifecycle_events=files["lifecycle_audit"] or [],
        )

        promotion_recommendation = (
            recommendation_from_payload(files["promotion_decision"])
            or recommendation_from_payload(files["governance_result"])
            or recommendation_from_payload(files["selection_result"])
            or scoring_recommendation
        )

        term_stage = terminal_stage_reached(
            orchestrator_ok=orchestrator_ok,
            run_dir_exists=run_dir_exists,
            run_manifest_exists=run_manifest_exists,
            scoring_status=scoring_status,
            precheck_status=precheck_status,
            selection_status=selection_status,
            governance_status=governance_status,
        )

        (
            first_failure_stage,
            first_failure_reason_code,
            selection_block_reason,
            governance_block_reason,
            promotion_block_reason,
        ) = build_failure_map(
            orchestrator_ok=orchestrator_ok,
            run_dir_exists=run_dir_exists,
            run_manifest_exists=run_manifest_exists,
            scoring_status=scoring_status,
            scoring_recommendation=scoring_recommendation,
            precheck_status=precheck_status,
            precheck_decision=precheck_decision,
            selection_status=selection_status,
            governance_status=governance_status,
            exact_registry_rows=exact_registry_rows,
            fuzzy_registry_rows=fuzzy_registry_rows,
            selection_payload=files["selection_result"],
        )

        worthy_candidate_flag = False
        if governance_forwardish(governance_status):
            worthy_candidate_flag = True
        elif bool_passish(promotion_recommendation) and not first_failure_reason_code:
            worthy_candidate_flag = True

        trace_row = {
            "candidate_id": candidate_id,
            "spec_path": spec_path,
            "run_dir": run_dir_str,
            "orchestrator_status": "ok" if orchestrator_ok else "failed",
            "scoring_status": scoring_status,
            "scoring_recommendation": scoring_recommendation,
            "precheck_status": precheck_status,
            "selection_status": selection_status,
            "governance_status": governance_status,
            "terminal_stage_reached": term_stage,
            "first_failure_stage": first_failure_stage,
            "first_failure_reason_code": first_failure_reason_code,
            "selection_block_reason": selection_block_reason,
            "governance_block_reason": governance_block_reason,
            "final_score": final_score,
            "precheck_decision": precheck_decision,
            "promotion_recommendation": promotion_recommendation,
            "worthy_candidate_flag": worthy_candidate_flag,
            "experiment_id": experiment_id,
            "dispatch_returncode": dispatch_returncode,
            "run_manifest_status": status_from_payload(run_manifest),
            "registry_exact_match_count": len(exact_registry_rows),
            "registry_fuzzy_match_count": len(fuzzy_registry_rows),
            "promotion_block_reason": promotion_block_reason,
        }

        out.append(trace_row)

    return out


def main() -> None:
    args = parse_args()
    mode = "execute" if args.execute else "dry-run"

    loop_output_dir = Path(args.loop_output_dir)
    diagnostics_json_path = loop_output_dir / OUTPUT_JSON_NAME
    diagnostics_csv_path = loop_output_dir / OUTPUT_CSV_NAME
    trace_jsonl_path = loop_output_dir / TRACE_JSONL_NAME

    print_kv("mode", mode)
    print_kv("loop_output_dir", str(loop_output_dir))

    manifest, summary_json, loop_rows = load_loop_rows(loop_output_dir)
    registry_ctx = load_registry_context()

    print_kv("loop_rows_count", len(loop_rows))
    print_kv("registry_paths", registry_ctx["paths"])
    print_kv("registry_rows_count", len(registry_ctx["rows"]))

    if not loop_rows:
        raise RuntimeError("No loop rows found. Zero-selection batch cannot remain without trace map.")

    trace_rows: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}

    for loop_row in loop_rows:
        rows = build_trace_rows(loop_row, registry_ctx)
        if not rows:
            raise RuntimeError("A candidate dispatch produced zero trace rows, which is forbidden.")
        for row in rows:
            trace_rows.append(row)
            code = normalize_text(row["first_failure_reason_code"]) or "NO_FAILURE_CODE"
            reason_counts[code] = reason_counts.get(code, 0) + 1
            append_jsonl(
                trace_jsonl_path,
                {
                    "ts_utc": now_utc_iso(),
                    "mode": mode,
                    "candidate_trace": row,
                },
            )

    if len(trace_rows) < len(loop_rows):
        raise RuntimeError(
            "Every candidate dispatch must get explicit trace result. Trace rows are fewer than loop rows."
        )

    worthy_count = sum(1 for row in trace_rows if row["worthy_candidate_flag"])
    zero_selection_confirmed = worthy_count == 0

    diagnostics_payload = {
        "generated_at_utc": now_utc_iso(),
        "mode": mode,
        "loop_output_dir": str(loop_output_dir),
        "input_files": {
            "loop_manifest": str(loop_output_dir / LOOP_MANIFEST_NAME),
            "loop_summary_json": str(loop_output_dir / LOOP_SUMMARY_JSON_NAME),
            "loop_summary_csv": str(loop_output_dir / LOOP_SUMMARY_CSV_NAME),
            "registry_paths": registry_ctx["paths"],
        },
        "loop_manifest_status": manifest.get("status"),
        "loop_summary_status": summary_json.get("status"),
        "trace_rows_count": len(trace_rows),
        "worthy_candidates_count": worthy_count,
        "zero_selection_confirmed": zero_selection_confirmed,
        "reason_code_counts": reason_counts,
        "traces": trace_rows,
    }

    write_json(diagnostics_json_path, diagnostics_payload)
    write_csv(diagnostics_csv_path, trace_rows)

    print_kv("trace_rows_count", len(trace_rows))
    print_kv("worthy_candidates_count", worthy_count)
    print_kv("zero_selection_confirmed", zero_selection_confirmed)
    print_kv("reason_code_counts", reason_counts)
    print_kv("zero_selection_diagnostics_json", str(diagnostics_json_path))
    print_kv("zero_selection_diagnostics_csv", str(diagnostics_csv_path))
    print_kv("candidate_trace_log_jsonl", str(trace_jsonl_path))


if __name__ == "__main__":
    main()