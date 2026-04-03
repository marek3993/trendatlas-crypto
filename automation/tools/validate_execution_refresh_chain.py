from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"
DEFAULT_RUNBOOK = AUTOMATION_ROOT / "config" / "execution_refresh_runbook.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / value


def validate_required_files(stage: dict) -> tuple[bool, list[str]]:
    missing: list[str] = []

    for rel in stage.get("required_outputs", []):
        p = resolve_path(str(rel))
        if not p.exists():
            missing.append(str(p))

    for rel in stage.get("required_manifests", []):
        p = resolve_path(str(rel))
        if not p.exists():
            missing.append(str(p))

    for rel in stage.get("required_quality_files", []):
        p = resolve_path(str(rel))
        if not p.exists():
            missing.append(str(p))

    return len(missing) == 0, missing


def validate_json_file(path_str: str) -> tuple[bool, str]:
    path = resolve_path(path_str)
    if not path.exists():
        return False, f"Missing JSON file: {path}"

    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True, f"Readable JSON: {path}"
    except Exception as exc:
        return False, f"Broken JSON {path}: {exc}"


def validate_jsonl_file(path_str: str) -> tuple[bool, str]:
    path = resolve_path(path_str)
    if not path.exists():
        return False, f"Missing JSONL file: {path}"

    try:
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            json.loads(line)
        return True, f"Readable JSONL: {path}"
    except Exception as exc:
        return False, f"Broken JSONL {path}: {exc}"


def validate_manifest_status(path_str: str) -> tuple[bool, str]:
    path = resolve_path(path_str)
    if not path.exists():
        return False, f"Missing manifest: {path}"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Unreadable manifest {path}: {exc}"

    status = str(data.get("status", "")).strip().lower()
    if status and status not in {"ok", "success", "healthy", "passed"}:
        return False, f"Manifest status not healthy: {path} status={status}"

    return True, f"Manifest status acceptable: {path}"


def validate_quality_file(path_str: str) -> tuple[bool, str]:
    path = resolve_path(path_str)
    if not path.exists():
        return False, f"Missing quality file: {path}"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Unreadable quality file {path}: {exc}"

    text = json.dumps(data, ensure_ascii=False).lower()
    bad_tokens = ["fail", "failed", "error", "broken"]

    for token in bad_tokens:
        if token in text:
            return False, f"Quality file indicates failure token '{token}': {path}"

    return True, f"Quality file looks healthy: {path}"


def validate_cross_file_logic() -> tuple[list[str], list[str]]:
    findings: list[str] = []
    errors: list[str] = []

    intent_path = PROJECT_ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent.json"
    dry_run_path = PROJECT_ROOT / "outputs" / "execution" / "dry_run" / "latest_dry_run_decision.json"
    status_path = PROJECT_ROOT / "outputs" / "execution" / "live_status" / "execution_status.json"

    intent = None
    dry = None
    live = None

    if intent_path.exists():
        try:
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Unable to parse latest_execution_intent.json: {exc}")

    if dry_run_path.exists():
        try:
            dry = json.loads(dry_run_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Unable to parse latest_dry_run_decision.json: {exc}")

    if status_path.exists():
        try:
            live = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Unable to parse execution_status.json: {exc}")

    if dry is not None:
        duplicate_order_risk = dry.get("duplicate_order_risk")
        stale_signal = dry.get("stale_signal")
        would_place_order = dry.get("would_place_order")
        recommended_action = dry.get("recommended_action")
        current_state = dry.get("current_state")
        target_asset = dry.get("target_asset")

        findings.append(
            "dry_run decision summary: "
            f"recommended_action={recommended_action} | "
            f"would_place_order={would_place_order} | "
            f"current_state={current_state} | "
            f"target_asset={target_asset}"
        )

        if duplicate_order_risk is True:
            errors.append("dry_run.latest_dry_run_decision.json duplicate_order_risk=true")

        if stale_signal is True:
            errors.append("dry_run.latest_dry_run_decision.json stale_signal=true")

        if would_place_order not in {True, False, None}:
            errors.append(f"dry_run.latest_dry_run_decision.json invalid would_place_order={would_place_order}")

    if intent is not None and dry is not None:
        intent_target_asset = intent.get("target_asset")
        dry_target_asset = dry.get("target_asset")
        if intent_target_asset is not None and dry_target_asset is not None and intent_target_asset != dry_target_asset:
            errors.append(
                "Intent and dry-run decision disagree on target_asset: "
                f"intent={intent_target_asset} dry_run={dry_target_asset}"
            )

        intent_signal_id = intent.get("signal_id")
        dry_signal_id = dry.get("signal_id")
        if intent_signal_id is not None and dry_signal_id is not None and intent_signal_id != dry_signal_id:
            errors.append(
                "Intent and dry-run decision disagree on signal_id: "
                f"intent={intent_signal_id} dry_run={dry_signal_id}"
            )

    if live is not None and dry is not None:
        live_current_state = live.get("current_state")
        dry_current_state = dry.get("current_state")
        if live_current_state is not None and dry_current_state is not None and live_current_state != dry_current_state:
            findings.append(
                "execution_status.current_state differs from dry_run.current_state: "
                f"live={live_current_state} dry_run={dry_current_state}"
            )

    return findings, errors


def validate_chain(runbook: dict) -> tuple[str, list[str], list[str]]:
    findings: list[str] = []
    errors: list[str] = []

    for stage in runbook.get("stages", []):
        stage_name = str(stage["name"])

        ok_required, missing = validate_required_files(stage)
        if not ok_required:
            errors.append(f"{stage_name}: missing required files -> {missing}")
            continue

        for item in stage.get("required_outputs", []):
            if str(item).lower().endswith(".json"):
                ok, note = validate_json_file(str(item))
                (findings if ok else errors).append(f"{stage_name}: {note}")

        for item in stage.get("required_manifests", []):
            ok_json, note_json = validate_json_file(str(item))
            (findings if ok_json else errors).append(f"{stage_name}: {note_json}")

            ok_manifest, note_manifest = validate_manifest_status(str(item))
            (findings if ok_manifest else errors).append(f"{stage_name}: {note_manifest}")

        for item in stage.get("required_quality_files", []):
            ok_json, note_json = validate_json_file(str(item))
            (findings if ok_json else errors).append(f"{stage_name}: {note_json}")

            ok_quality, note_quality = validate_quality_file(str(item))
            (findings if ok_quality else errors).append(f"{stage_name}: {note_quality}")

    for path_str in runbook.get("global_jsonl_files", []):
        ok_jsonl, note = validate_jsonl_file(str(path_str))
        (findings if ok_jsonl else errors).append(note)

    cross_findings, cross_errors = validate_cross_file_logic()
    findings.extend(cross_findings)
    errors.extend(cross_errors)

    if errors:
        return "broken", findings, errors
    return "healthy", findings, errors


def main() -> None:
    runbook_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_RUNBOOK

    if not runbook_path.exists():
        raise FileNotFoundError(f"Runbook not found: {runbook_path}")

    runbook = read_json(runbook_path)
    chain_status, findings, errors = validate_chain(runbook)

    print(f"runbook={runbook_path}")
    print(f"chain_status={chain_status}")

    for finding in findings:
        print(f"finding={finding}")

    for error in errors:
        print(f"error={error}")

    if chain_status != "healthy":
        sys.exit(1)


if __name__ == "__main__":
    main()