from __future__ import annotations

import argparse
import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase69_research_only_runner_common import get_supported_mechanism_family_ids


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
DEV_ONLY_REPORTS_ROOT = (
    PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_preflight"
)

PRIMARY_COMPARE_TARGET = "phase67j_no_neo_main"
SECONDARY_COMPARE_TARGET = "phase68i_dynamic_ladder_candidate"
SECONDARY_COMPARE_USAGE = "overlay_context_suitability_only"
SECONDARY_COMPARE_CONTRACT_TOKEN = f"{SECONDARY_COMPARE_TARGET}_{SECONDARY_COMPARE_USAGE}"
SECONDARY_COMPARE_CONTRACT_ALIASES = {
    SECONDARY_COMPARE_CONTRACT_TOKEN,
    f"{SECONDARY_COMPARE_TARGET}_overlay_context_only",
}


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI LAB dev-only preflight compatibility gate")
    parser.add_argument("--spec", required=True, help="Path to a spec_ready experiment JSON artifact.")
    parser.add_argument(
        "--output",
        default="",
        help="Optional explicit JSON report path. Default is a dev-only non-authoritative output path.",
    )
    return parser.parse_args()


def resolve_report_path(spec_path: Path, spec: Optional[Dict[str, Any]]) -> Path:
    experiment_id = ""
    if isinstance(spec, dict):
        experiment_id = str(spec.get("experiment_id", "")).strip()

    if not experiment_id:
        stem = spec_path.name
        if stem.endswith(".spec_ready.json"):
            experiment_id = stem[: -len(".spec_ready.json")]
        else:
            experiment_id = spec_path.stem

    safe_name = experiment_id.replace(" ", "_")
    return DEV_ONLY_REPORTS_ROOT / f"{safe_name}.compatibility_gate.json"


def build_check(name: str, ok: bool, detail: str) -> Dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
    }


def parse_script_contract(script_args: Any) -> Dict[str, Any]:
    parsed = {
        "primary_compare_target": "",
        "primary_compare_paper": "",
        "secondary_compare_target": "",
        "secondary_compare_usage": "",
        "failure_criteria": "",
        "stop_conditions": [],
    }

    if not isinstance(script_args, list):
        return parsed

    idx = 0
    while idx < len(script_args):
        token = str(script_args[idx])
        next_value = str(script_args[idx + 1]) if idx + 1 < len(script_args) else ""

        if token == "--primary-compare-target":
            parsed["primary_compare_target"] = next_value
            idx += 2
            continue
        if token == "--primary-compare-paper":
            parsed["primary_compare_paper"] = next_value
            idx += 2
            continue
        if token == "--secondary-compare-target":
            parsed["secondary_compare_target"] = next_value
            idx += 2
            continue
        if token == "--secondary-compare-usage":
            parsed["secondary_compare_usage"] = next_value
            idx += 2
            continue
        if token == "--failure-criteria":
            parsed["failure_criteria"] = next_value
            idx += 2
            continue
        if token == "--stop-condition":
            if next_value:
                parsed["stop_conditions"].append(next_value)
            idx += 2
            continue

        idx += 1

    return parsed


def resolve_contract_spec_path(spec_path: Path, spec: Dict[str, Any]) -> Optional[Path]:
    for raw_path in spec.get("input_paths", []):
        candidate = Path(str(raw_path))
        if candidate.name.endswith(".contract_spec.json"):
            return candidate

    if spec_path.name.endswith(".spec_ready.json"):
        sibling = spec_path.with_name(spec_path.name.replace(".spec_ready.json", ".contract_spec.json"))
        if sibling.exists():
            return sibling

    return None


def inspect_shared_runner_usage(script_path: Path) -> Dict[str, Any]:
    details = {
        "uses_shared_runner": False,
        "family_ids": [],
        "inspection_error": "",
    }

    if not script_path.exists() or not script_path.is_file():
        details["inspection_error"] = f"script_missing:{script_path}"
        return details

    try:
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script_path))
    except Exception as exc:
        details["inspection_error"] = f"script_parse_error:{exc}"
        return details

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "phase69_research_only_runner_common":
            details["uses_shared_runner"] = True
        if isinstance(node, ast.Call):
            func = node.func
            func_name = ""
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if func_name != "FamilyConfig":
                continue
            for keyword in node.keywords:
                if keyword.arg != "family_id":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    details["family_ids"].append(keyword.value.value)

    unique_family_ids = sorted(set(details["family_ids"]))
    details["family_ids"] = unique_family_ids
    return details


def validate_script_path(spec: Dict[str, Any]) -> Dict[str, Any]:
    raw_path = str(spec.get("script_path", "")).strip()
    if not raw_path:
        return build_check("script_path_exists", False, "spec.script_path is empty")

    script_path = Path(raw_path)
    if not script_path.exists() or not script_path.is_file():
        return build_check("script_path_exists", False, f"missing script_path: {script_path}")

    return build_check("script_path_exists", True, f"script_path exists: {script_path}")


def validate_input_paths(spec: Dict[str, Any]) -> Dict[str, Any]:
    raw_paths = spec.get("input_paths", [])
    if not isinstance(raw_paths, list) or not raw_paths:
        return build_check("input_paths_exist", False, "spec.input_paths missing or empty")

    missing_paths = [str(Path(str(raw_path))) for raw_path in raw_paths if not Path(str(raw_path)).exists()]
    if missing_paths:
        return build_check("input_paths_exist", False, f"missing input_paths: {missing_paths}")

    return build_check("input_paths_exist", True, f"all input_paths exist: {len(raw_paths)}")


def validate_primary_compare(
    spec: Dict[str, Any],
    parsed_contract: Dict[str, Any],
    contract_spec: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    reasons: List[str] = []

    if str(spec.get("baseline_model", "")).strip() != PRIMARY_COMPARE_TARGET:
        reasons.append(f"baseline_model={spec.get('baseline_model')}")

    if parsed_contract["primary_compare_target"] != PRIMARY_COMPARE_TARGET:
        reasons.append(f"script_args.primary_compare_target={parsed_contract['primary_compare_target']}")

    if contract_spec is not None and str(contract_spec.get("exact_compare_target", "")).strip() != PRIMARY_COMPARE_TARGET:
        reasons.append(f"contract_spec.exact_compare_target={contract_spec.get('exact_compare_target')}")

    if reasons:
        return build_check(
            "primary_compare_phase67j_no_neo_main",
            False,
            "primary compare mismatch: " + " | ".join(reasons),
        )

    return build_check(
        "primary_compare_phase67j_no_neo_main",
        True,
        f"primary compare locked to {PRIMARY_COMPARE_TARGET}",
    )


def validate_secondary_compare(
    parsed_contract: Dict[str, Any],
    contract_spec: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    reasons: List[str] = []

    target = parsed_contract["secondary_compare_target"]
    usage = parsed_contract["secondary_compare_usage"]

    if bool(target) != bool(usage):
        reasons.append("script_args secondary target/usage are not paired")

    if target or usage:
        if target != SECONDARY_COMPARE_TARGET:
            reasons.append(f"script_args.secondary_compare_target={target}")
        if usage != SECONDARY_COMPARE_USAGE:
            reasons.append(f"script_args.secondary_compare_usage={usage}")

    if contract_spec is not None:
        context = contract_spec.get("optional_secondary_compare_context")
        if context is not None:
            model = str(context.get("model", "")).strip()
            contract_usage = str(context.get("usage", "")).strip()
            if model != SECONDARY_COMPARE_TARGET:
                reasons.append(f"contract_spec.optional_secondary_compare_context.model={model}")
            if contract_usage != SECONDARY_COMPARE_USAGE:
                reasons.append(f"contract_spec.optional_secondary_compare_context.usage={contract_usage}")

        raw_token = str(contract_spec.get("optional_secondary_compare_target", "")).strip()
        if raw_token and raw_token not in SECONDARY_COMPARE_CONTRACT_ALIASES:
            reasons.append(f"contract_spec.optional_secondary_compare_target={raw_token}")

    if reasons:
        return build_check(
            "secondary_compare_overlay_context_only",
            False,
            "secondary compare mismatch: " + " | ".join(reasons),
        )

    if not target and contract_spec is None:
        detail = "no secondary compare declared in script_args"
    elif not target:
        detail = "secondary compare omitted in script_args; contract remains compatible"
    else:
        detail = (
            f"secondary compare limited to {SECONDARY_COMPARE_TARGET} with "
            f"{SECONDARY_COMPARE_USAGE}"
        )

    return build_check("secondary_compare_overlay_context_only", True, detail)


def validate_failure_and_stop_conditions(
    spec: Dict[str, Any],
    parsed_contract: Dict[str, Any],
    contract_spec: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    reasons: List[str] = []

    if not str(parsed_contract["failure_criteria"]).strip():
        reasons.append("missing script_args failure criteria")

    if not parsed_contract["stop_conditions"]:
        reasons.append("missing script_args stop conditions")

    if not str(spec.get("invalidation_rule", "")).strip():
        reasons.append("missing spec invalidation_rule")

    if contract_spec is not None and not contract_spec.get("stop_conditions"):
        reasons.append("missing contract_spec stop_conditions")

    if reasons:
        return build_check(
            "failure_and_stop_conditions_exist",
            False,
            " | ".join(reasons),
        )

    return build_check(
        "failure_and_stop_conditions_exist",
        True,
        f"failure criteria present and stop conditions count={len(parsed_contract['stop_conditions'])}",
    )


def validate_shared_runner_support(spec: Dict[str, Any]) -> Dict[str, Any]:
    raw_script_path = str(spec.get("script_path", "")).strip()
    if not raw_script_path:
        return build_check(
            "phase69_shared_runner_family_supported",
            False,
            "script_path missing so shared-runner compatibility cannot be verified",
        )

    script_path = Path(raw_script_path)
    inspection = inspect_shared_runner_usage(script_path)
    if inspection["inspection_error"]:
        return build_check(
            "phase69_shared_runner_family_supported",
            False,
            inspection["inspection_error"],
        )

    if not inspection["uses_shared_runner"]:
        return build_check(
            "phase69_shared_runner_family_supported",
            True,
            "script does not use phase69 shared runner; family support check not required",
        )

    family_ids = inspection["family_ids"]
    if len(family_ids) != 1:
        return build_check(
            "phase69_shared_runner_family_supported",
            False,
            f"expected exactly one FamilyConfig.family_id, got {family_ids}",
        )

    supported_family_ids = set(get_supported_mechanism_family_ids())
    family_id = family_ids[0]
    if family_id not in supported_family_ids:
        return build_check(
            "phase69_shared_runner_family_supported",
            False,
            f"unsupported shared-runner family_id={family_id}; supported={sorted(supported_family_ids)}",
        )

    return build_check(
        "phase69_shared_runner_family_supported",
        True,
        f"shared runner supports family_id={family_id}",
    )


def run_preflight_gate(
    spec_path: Path,
    *,
    spec: Optional[Dict[str, Any]] = None,
    output_path: Optional[Path] = None,
    write_report: bool = True,
) -> Dict[str, Any]:
    spec_payload = spec
    load_error = ""
    if spec_payload is None:
        try:
            spec_payload = read_json(spec_path)
        except Exception as exc:
            spec_payload = None
            load_error = str(exc)

    report_path = output_path or resolve_report_path(spec_path, spec_payload)
    checks: List[Dict[str, Any]] = []
    contract_spec_path: Optional[Path] = None
    contract_spec: Optional[Dict[str, Any]] = None
    parsed_contract = parse_script_contract([])

    if spec_payload is None:
        checks.append(build_check("spec_json_loadable", False, f"unable to load spec json: {load_error}"))
    else:
        checks.append(build_check("spec_json_loadable", True, f"spec json loaded: {spec_path}"))
        parsed_contract = parse_script_contract(spec_payload.get("script_args"))
        contract_spec_path = resolve_contract_spec_path(spec_path, spec_payload)

        if contract_spec_path is not None:
            try:
                contract_spec = read_json(contract_spec_path)
            except Exception as exc:
                checks.append(
                    build_check(
                        "contract_spec_loadable",
                        False,
                        f"unable to load contract spec {contract_spec_path}: {exc}",
                    )
                )
            else:
                checks.append(
                    build_check(
                        "contract_spec_loadable",
                        True,
                        f"contract spec loaded: {contract_spec_path}",
                    )
                )

        checks.extend(
            [
                validate_script_path(spec_payload),
                validate_input_paths(spec_payload),
                validate_primary_compare(spec_payload, parsed_contract, contract_spec),
                validate_secondary_compare(parsed_contract, contract_spec),
                validate_failure_and_stop_conditions(spec_payload, parsed_contract, contract_spec),
                validate_shared_runner_support(spec_payload),
            ]
        )

    failed_check_names = [item["name"] for item in checks if not item["ok"]]
    status = "passed" if not failed_check_names else "failed"

    report = {
        "artifact_type": "ai_lab_dev_only_preflight_compatibility_gate",
        "gate_name": "phase69_ai_lab_compatibility_gate",
        "generated_at_utc": timestamp_utc(),
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "validation_scope": "dev_only_readiness_validation_only",
        "spec_path": str(spec_path),
        "report_path": str(report_path),
        "experiment_id": "" if spec_payload is None else str(spec_payload.get("experiment_id", "")),
        "status": status,
        "failed_check_names": failed_check_names,
        "checks": checks,
        "contract_spec_path": "" if contract_spec_path is None else str(contract_spec_path),
        "expected_primary_compare_target": PRIMARY_COMPARE_TARGET,
        "allowed_secondary_compare_target": SECONDARY_COMPARE_TARGET,
        "allowed_secondary_compare_usage": SECONDARY_COMPARE_USAGE,
        "supported_phase69_shared_runner_family_ids": list(get_supported_mechanism_family_ids()),
        "notes": [
            "Dev-only compatibility gate output.",
            "Non-authoritative validation artifact.",
            "Not source_of_truth and not an execution/runtime decision artifact.",
        ],
    }

    if write_report:
        save_json(report_path, report)

    return report


def main() -> None:
    args = parse_args()
    spec_path = Path(args.spec)
    output_path = Path(args.output) if args.output else None

    report = run_preflight_gate(spec_path, output_path=output_path, write_report=True)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_path": report["report_path"],
                "failed_check_names": report["failed_check_names"],
            },
            ensure_ascii=False,
        )
    )

    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
