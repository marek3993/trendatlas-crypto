from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.staged_candidate_promotion_support import (
    PROMOTED_CANDIDATE_ID,
    ROOT,
    build_promoted_diagnostics,
    build_promoted_manifest,
    build_promoted_snapshot,
    load_promoted_candidate_inputs,
    transform_candidate_timeseries_to_active,
    utc_now_iso,
)
from scripts.production.validate_current_strategy_snapshot import (
    build_quality_payload,
    validate_active_production_payloads,
)


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "production"
SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.json"
TIMESERIES_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_timeseries.csv"
DIAGNOSTICS_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_diagnostics.json"
QUALITY_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.quality.json"
MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.manifest.json"

ACTIVE_OUTPUT_PATHS = {
    "snapshot": SNAPSHOT_PATH,
    "timeseries": TIMESERIES_PATH,
    "diagnostics": DIAGNOSTICS_PATH,
}


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _path_for_manifest(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = (result.stdout or "").strip()
    return commit or None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp_path, index=False)
    temp_path.replace(path)


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Missing active Production Core file for backup: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _backup_current_active_bundle(
    *,
    backup_dir: Path,
    active_output_paths: dict[str, Path],
) -> list[str]:
    backed_up: list[str] = []
    for path in active_output_paths.values():
        backup_target = backup_dir / path.name
        _copy_file(path, backup_target)
        backed_up.append(_path_for_manifest(backup_target, root=ROOT))
    return backed_up


def _build_backup_dir(*, output_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return output_dir / "history" / f"pre_etf_flow_impulse_cutover_{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a validated staged Production Core candidate into active current_strategy outputs.")
    parser.add_argument("--candidate", default=PROMOTED_CANDIDATE_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.candidate != PROMOTED_CANDIDATE_ID:
        raise SystemExit(f"Unsupported candidate: {args.candidate!r}")

    output_dir = args.output_dir.resolve()
    snapshot_path = output_dir / SNAPSHOT_PATH.name
    timeseries_path = output_dir / TIMESERIES_PATH.name
    diagnostics_path = output_dir / DIAGNOSTICS_PATH.name
    quality_path = output_dir / QUALITY_PATH.name
    manifest_path = output_dir / MANIFEST_PATH.name

    candidate_inputs = load_promoted_candidate_inputs(root=ROOT, candidate_id=args.candidate)
    previous_snapshot = _read_json_required(snapshot_path)
    generated_at_utc = utc_now_iso()
    build_command = " ".join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    git_commit = _git_commit(ROOT)
    backup_dir = _build_backup_dir(output_dir=output_dir)
    backup_path = _path_for_manifest(backup_dir, root=ROOT)

    active_timeseries = transform_candidate_timeseries_to_active(candidate_inputs["timeseries"])
    snapshot = build_promoted_snapshot(
        generated_at_utc=generated_at_utc,
        build_command=build_command,
        git_commit=git_commit,
        candidate_inputs=candidate_inputs,
        active_timeseries=active_timeseries,
        previous_snapshot=previous_snapshot,
        backup_path=backup_path,
    )
    provisional_validation = {
        "status": "pending",
        "errors": [],
        "warnings": [],
        "checks": {},
    }
    diagnostics = build_promoted_diagnostics(
        generated_at_utc=generated_at_utc,
        candidate_inputs=candidate_inputs,
        active_timeseries=active_timeseries,
        validation=provisional_validation,
    )
    snapshot["validation"] = {
        "status": "passed",
        "errors": [],
        "warnings": [],
    }
    diagnostics["validation"] = {
        "status": "passed",
        "errors": [],
        "warnings": [],
    }

    validation = validate_active_production_payloads(
        snapshot=snapshot,
        timeseries=active_timeseries,
        diagnostics=diagnostics,
    )
    if validation["status"] != "passed":
        raise SystemExit(
            "Active Production Core promotion blocked fail-closed:\n- " + "\n- ".join(validation["errors"])
        )

    snapshot["validation"] = {
        "status": validation["status"],
        "errors": list(validation["errors"]),
        "warnings": list(validation["warnings"]),
    }
    diagnostics["validation"] = {
        "status": validation["status"],
        "errors": list(validation["errors"]),
        "warnings": list(validation["warnings"]),
    }
    quality = build_quality_payload(
        validation=validation,
        snapshot_path=snapshot_path,
        timeseries_path=timeseries_path,
        diagnostics_path=diagnostics_path,
    )

    backed_up_files = _backup_current_active_bundle(
        backup_dir=backup_dir,
        active_output_paths=ACTIVE_OUTPUT_PATHS,
    )
    manifest = build_promoted_manifest(
        generated_at_utc=generated_at_utc,
        build_command=build_command,
        git_commit=git_commit,
        candidate_inputs=candidate_inputs,
        validation=validation,
        backup_path=backup_path,
        backup_files=backed_up_files,
        snapshot_path=snapshot_path,
        timeseries_path=timeseries_path,
        diagnostics_path=diagnostics_path,
        quality_path=quality_path,
        manifest_path=manifest_path,
    )

    _atomic_write_json(snapshot_path, snapshot)
    _atomic_write_csv(timeseries_path, active_timeseries)
    _atomic_write_json(diagnostics_path, diagnostics)
    _atomic_write_json(quality_path, quality)
    _atomic_write_json(manifest_path, manifest)

    print(
        json.dumps(
            {
                "candidate_id": args.candidate,
                "closed_day": snapshot["closed_day"],
                "backup_path": backup_path,
                "backed_up_files": backed_up_files,
                "replaced_output_files": [
                    _path_for_manifest(snapshot_path, root=ROOT),
                    _path_for_manifest(timeseries_path, root=ROOT),
                    _path_for_manifest(diagnostics_path, root=ROOT),
                    _path_for_manifest(quality_path, root=ROOT),
                    _path_for_manifest(manifest_path, root=ROOT),
                ],
                "validation_status": validation["status"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
