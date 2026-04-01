from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "research_os_ideation_policy_v1.json"
MUTATION_POLICY_PATH = ROOT / "research_os_mutation_space_policy_v1.json"
BOOTSTRAP_REGISTRY_PATH = ROOT / "research_os" / "leaderboards" / "research_os_registry.csv"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required json: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv_optional(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def ensure_bootstrap_registry(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fieldnames = [
            "candidate_id",
            "status",
            "lifecycle_stage",
            "branch",
            "segment_owner",
            "hypothesis_label",
            "model_key",
            "script_path",
            "created_at_utc",
            "updated_at_utc",
        ]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
    return path


def resolve_first_existing(candidates: list[str], required: bool, label: str) -> Path | None:
    checked: list[str] = []
    for raw in candidates:
        path = Path(raw)
        checked.append(str(path))
        if path.exists() and path.is_file():
            return path

    if label == "registry csv":
        return ensure_bootstrap_registry(BOOTSTRAP_REGISTRY_PATH)

    if required:
        joined = "\n".join(checked)
        raise FileNotFoundError(f"Missing required {label}. Checked:\n{joined}")
    return None


def safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def walk_values(obj: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    out: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_str = str(key)
            out.append((path + (key_str,), value))
            out.extend(walk_values(value, path + (key_str,)))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            idx_str = str(idx)
            out.append((path + (idx_str,), value))
            out.extend(walk_values(value, path + (idx_str,)))
    return out


def extract_baseline_model_key(truth_pack: dict[str, Any]) -> str:
    exact_candidates = [
        safe_get(truth_pack, "official_baseline", "model_key", default=""),
        safe_get(truth_pack, "official_baseline_model_key", default=""),
        safe_get(truth_pack, "baseline_model_key", default=""),
        safe_get(truth_pack, "baseline", "model_key", default=""),
        safe_get(truth_pack, "current_winner_key", default=""),
        safe_get(truth_pack, "official_truth", "model_key", default=""),
        safe_get(truth_pack, "single_truth", "model_key", default=""),
    ]
    for raw in exact_candidates:
        value = str(raw).strip()
        if value:
            return value

    for path, value in walk_values(truth_pack):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        last_key = path[-1].lower()
        full_path = ".".join(path).lower()
        if (
            last_key in {"model_key", "baseline_model_key", "official_baseline_model_key", "current_winner_key"}
            or "baseline" in full_path and "model_key" in full_path
        ):
            return text

    paper_path = extract_baseline_paper_path(truth_pack)
    if paper_path:
        stem = Path(paper_path).stem
        if stem.endswith("_paper"):
            stem = stem[:-6]
        if stem:
            return stem

    return "official_baseline_unresolved"


def extract_baseline_paper_path(truth_pack: dict[str, Any]) -> str:
    exact_candidates = [
        safe_get(truth_pack, "official_baseline", "paper_path", default=""),
        safe_get(truth_pack, "official_baseline_paper_path", default=""),
        safe_get(truth_pack, "baseline_paper_path", default=""),
        safe_get(truth_pack, "baseline", "paper_path", default=""),
        safe_get(truth_pack, "current_winner_paper", default=""),
        safe_get(truth_pack, "official_truth", "paper_path", default=""),
        safe_get(truth_pack, "single_truth", "paper_path", default=""),
    ]
    for raw in exact_candidates:
        value = str(raw).strip()
        if value:
            return value

    for path, value in walk_values(truth_pack):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        last_key = path[-1].lower()
        full_path = ".".join(path).lower()
        if text.lower().endswith(".csv") and (
            last_key in {"paper_path", "baseline_paper_path", "official_baseline_paper_path", "current_winner_paper"}
            or "paper_path" in full_path
            or "winner_paper" in full_path
        ):
            return text

    return ""


def build_context(policy: dict[str, Any]) -> dict[str, Any]:
    req = policy["required_inputs"]

    truth_pack_path = resolve_first_existing(req["truth_pack_candidates"], True, "truth pack")
    registry_path = resolve_first_existing(req["registry_csv_candidates"], True, "registry csv")
    lineage_path = resolve_first_existing(req["lineage_summary_csv_candidates"], False, "lineage summary csv")
    scoring_path = resolve_first_existing(req["scoring_history_candidates"], False, "scoring history csv")
    selection_path = resolve_first_existing(req["selection_history_candidates"], False, "selection history csv")

    truth_pack = load_json(truth_pack_path)
    registry_rows = load_csv_optional(registry_path)
    lineage_rows = load_csv_optional(lineage_path)
    scoring_rows = load_csv_optional(scoring_path)
    selection_rows = load_csv_optional(selection_path)

    official_baseline_model_key = extract_baseline_model_key(truth_pack)
    official_baseline_paper_path = extract_baseline_paper_path(truth_pack)

    return {
        "truth_pack_path": truth_pack_path,
        "registry_path": registry_path,
        "lineage_path": lineage_path,
        "scoring_path": scoring_path,
        "selection_path": selection_path,
        "truth_pack": truth_pack,
        "registry_rows": registry_rows,
        "lineage_rows": lineage_rows,
        "scoring_rows": scoring_rows,
        "selection_rows": selection_rows,
        "official_baseline_model_key": official_baseline_model_key,
        "official_baseline_paper_path": official_baseline_paper_path,
    }


def extract_branch_text(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("branch", "")),
        str(row.get("segment_owner", "")),
        str(row.get("candidate_id", "")),
        str(row.get("hypothesis_label", "")),
        str(row.get("model_key", "")),
        str(row.get("script_path", "")),
    ]
    return " ".join(parts).lower()


def extract_delta_value(row: dict[str, Any]) -> float:
    candidate_cols = [
        "delta_vs_official_cagr_pct",
        "delta_vs_official_baseline_cagr_pct",
        "delta_vs_phase66g_cagr_pct",
        "delta_vs_phase63_cagr_pct",
        "delta_cagr_pct",
    ]
    for col in candidate_cols:
        raw = str(row.get(col, "")).strip()
        if raw == "":
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return 0.0


def branch_saturation(branch: str, policy: dict[str, Any], ctx: dict[str, Any]) -> tuple[str, int, float]:
    rules = policy["saturation_rules"]
    recent_window = int(rules["recent_window_records"])
    minimum_records = int(rules["minimum_recent_records_for_warning"])
    max_positive_threshold = float(rules["max_positive_delta_threshold_pct"])
    action = str(rules["action"]).strip().lower()

    combined = ctx["scoring_rows"] + ctx["selection_rows"] + ctx["registry_rows"]
    branch_rows = [row for row in combined if branch in extract_branch_text(row)]
    recent_rows = branch_rows[-recent_window:]
    recent_count = len(recent_rows)
    best_delta = max((extract_delta_value(row) for row in recent_rows), default=0.0)

    if recent_count >= minimum_records and best_delta <= max_positive_threshold:
        return action, recent_count, best_delta
    return "none", recent_count, best_delta


def build_registry_signatures(rows: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in rows:
        text = "|".join(
            [
                str(row.get("candidate_id", "")).strip().lower(),
                str(row.get("hypothesis_label", "")).strip().lower(),
                str(row.get("script_path", "")).strip().lower(),
                str(row.get("model_key", "")).strip().lower(),
            ]
        )
        if text.replace("|", "").strip():
            out.add(text)
    return out


def normalize_tokens(text: str) -> set[str]:
    return {tok for tok in re.split(r"[^a-z0-9]+", text.lower()) if tok}


def near_duplicate_score(a: str, b: str) -> float:
    ta = normalize_tokens(a)
    tb = normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def build_duplicate_flag(
    candidate_text: str,
    registry_rows: list[dict[str, Any]],
    registry_signatures: set[str],
    min_overlap: float,
) -> tuple[bool, str]:
    normalized = candidate_text.lower().strip()
    if normalized in registry_signatures:
        return True, "exact_registry_signature_match"

    best_overlap = 0.0
    for row in registry_rows:
        compare_text = " ".join(
            [
                str(row.get("candidate_id", "")),
                str(row.get("hypothesis_label", "")),
                str(row.get("script_path", "")),
                str(row.get("model_key", "")),
            ]
        )
        score = near_duplicate_score(normalized, compare_text)
        best_overlap = max(best_overlap, score)
    if best_overlap >= min_overlap:
        return True, f"near_duplicate_overlap_{best_overlap:.2f}"
    return False, ""


def deterministic_hypothesis_id(branch: str, mutation_key: str, baseline_reference: str, ordinal: int) -> str:
    raw = f"{branch}|{mutation_key}|{baseline_reference}|{ordinal}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"hyp_{digest}"


def flatten_for_csv(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in records:
        flat = row.copy()
        flat["risk_flags"] = "|".join(row.get("risk_flags", []))
        flat["expected_outputs"] = "|".join(row.get("expected_outputs", []))
        flat["parameter_overrides_json"] = json.dumps(row.get("parameter_overrides", {}), ensure_ascii=False, sort_keys=True)
        out.append(flat)
    return out


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write("")
        return

    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_hypotheses(
    policy: dict[str, Any],
    mutation_policy: dict[str, Any],
    ctx: dict[str, Any],
    branch_filter: str | None,
    max_hypotheses: int,
    log_path: Path,
) -> list[dict[str, Any]]:
    allowed_branches = policy["allowed_branches"]
    per_branch_caps = policy["max_hypotheses_per_branch"]
    owners = policy["segment_owner_by_branch"]
    baseline_reference_map = policy["baseline_reference_by_branch"]
    duplicate_min_overlap = float(policy["duplicate_rules"]["near_duplicate_token_overlap_min"])

    if branch_filter is not None and branch_filter not in allowed_branches:
        raise ValueError(f"Unsupported branch: {branch_filter}")

    registry_signatures = build_registry_signatures(ctx["registry_rows"])
    registry_rows = ctx["registry_rows"]

    all_templates: list[dict[str, Any]] = []
    for branch in allowed_branches:
        if branch_filter and branch != branch_filter:
            continue
        for template in mutation_policy["branch_templates"].get(branch, []):
            merged = template.copy()
            merged["branch"] = branch
            all_templates.append(merged)

    all_templates.sort(key=lambda row: (-int(row["priority"]), row["branch"], row["mutation_key"]))

    branch_counts: dict[str, int] = {branch: 0 for branch in allowed_branches}
    hypotheses: list[dict[str, Any]] = []

    for ordinal, template in enumerate(all_templates, start=1):
        branch = str(template["branch"])
        if len(hypotheses) >= max_hypotheses:
            break
        if branch_counts[branch] >= int(per_branch_caps[branch]):
            continue

        saturation_action, recent_count, best_delta = branch_saturation(branch, policy, ctx)
        baseline_reference = str(baseline_reference_map[branch]).strip()
        if baseline_reference == "official_baseline":
            baseline_reference = ctx["official_baseline_model_key"]

        candidate_text = "|".join(
            [
                branch,
                str(template["mutation_key"]),
                baseline_reference,
                str(template["hypothesis_label_template"]),
                str(template["script_path"]),
            ]
        )
        duplicate_flag, duplicate_reason = build_duplicate_flag(
            candidate_text=candidate_text,
            registry_rows=registry_rows,
            registry_signatures=registry_signatures,
            min_overlap=duplicate_min_overlap,
        )

        saturated_value = saturation_action
        if saturation_action != "none":
            saturated_value = f"{saturation_action}:recent={recent_count}:best_delta={best_delta:.2f}"

        hypothesis = {
            "hypothesis_id": deterministic_hypothesis_id(branch, str(template["mutation_key"]), baseline_reference, ordinal),
            "branch": branch,
            "segment_owner": owners[branch],
            "hypothesis_label": str(template["hypothesis_label_template"]).strip(),
            "mutation_key": str(template["mutation_key"]).strip(),
            "rationale": str(template["rationale"]).strip(),
            "expected_direction_of_improvement": str(template["expected_direction_of_improvement"]).strip(),
            "baseline_reference": baseline_reference,
            "baseline_paper_path": ctx["official_baseline_paper_path"] if branch == "core" else "",
            "script_path": str(template["script_path"]).strip(),
            "risk_flags": list(template.get("risk_flags", [])),
            "duplicate_or_near_duplicate": bool(duplicate_flag),
            "duplicate_reason": duplicate_reason,
            "saturated_branch_block_or_warning": saturated_value,
            "saturation_recent_record_count": recent_count,
            "saturation_best_delta_pct": best_delta,
            "priority": int(template["priority"]),
            "parameter_overrides": dict(template.get("parameter_overrides", {})),
            "expected_outputs": list(template.get("expected_outputs", [])),
            "macro_frozen_mode": bool(policy["macro_frozen_mode"]),
            "machine_readable": True,
            "status": "candidate",
            "created_at_utc": now_utc(),
        }
        hypotheses.append(hypothesis)
        branch_counts[branch] += 1

        log_jsonl(
            log_path,
            {
                "ts_utc": now_utc(),
                "event": "hypothesis_generated",
                "hypothesis_id": hypothesis["hypothesis_id"],
                "branch": branch,
                "duplicate_or_near_duplicate": duplicate_flag,
                "duplicate_reason": duplicate_reason,
                "saturated_branch_block_or_warning": saturated_value,
            },
        )

    return hypotheses


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-hypotheses", type=int, default=None)
    parser.add_argument("--branch", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run and args.execute:
        raise ValueError("Use either --dry-run or --execute, not both.")
    mode = "execute" if args.execute else "dry-run"

    policy = load_json(POLICY_PATH)
    mutation_policy = load_json(MUTATION_POLICY_PATH)
    if policy.get("policy_version") != "research_os_ideation_policy_v1":
        raise ValueError("Unexpected ideation policy version.")
    if mutation_policy.get("policy_version") != "research_os_mutation_space_policy_v1":
        raise ValueError("Unexpected mutation policy version.")

    output_dir = Path(str(policy["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = policy["output_files"]
    log_path = output_dir / str(output_files["decision_log_jsonl"])

    ctx = build_context(policy)
    log_jsonl(
        log_path,
        {
            "ts_utc": now_utc(),
            "event": "context_loaded",
            "mode": mode,
            "truth_pack_path": str(ctx["truth_pack_path"]),
            "registry_path": str(ctx["registry_path"]),
            "official_baseline_model_key": ctx["official_baseline_model_key"],
            "macro_frozen_mode": bool(policy["macro_frozen_mode"]),
        },
    )

    max_hypotheses = int(args.max_hypotheses or policy["max_hypotheses_default"])
    hypotheses = generate_hypotheses(
        policy=policy,
        mutation_policy=mutation_policy,
        ctx=ctx,
        branch_filter=args.branch,
        max_hypotheses=max_hypotheses,
        log_path=log_path,
    )

    summary_rows = flatten_for_csv(hypotheses)
    write_json(output_dir / str(output_files["hypotheses_json"]), hypotheses)
    write_csv(output_dir / str(output_files["summary_csv"]), summary_rows)

    log_jsonl(
        log_path,
        {
            "ts_utc": now_utc(),
            "event": "ideation_complete",
            "mode": mode,
            "hypothesis_count": len(hypotheses),
            "branch_filter": args.branch,
        },
    )

    print(f"[IDEATION] mode={mode}")
    print(f"[IDEATION] macro_frozen_mode={policy['macro_frozen_mode']}")
    print(f"[IDEATION] hypotheses={len(hypotheses)}")
    print(f"[IDEATION] output_dir={output_dir}")


if __name__ == "__main__":
    main()