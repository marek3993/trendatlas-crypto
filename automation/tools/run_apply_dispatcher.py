from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

TRUTH_APPROVED_DIR = AUTOMATION_ROOT / "truth_patches" / "approved"
CODE_APPROVED_DIR = AUTOMATION_ROOT / "code_patches" / "approved"
REPORTS_DIR = AUTOMATION_ROOT / "reports" / "dispatcher_runs"

APPLY_TRUTH_SCRIPT = AUTOMATION_ROOT / "tools" / "apply_truth_patch.py"
APPLY_CODE_SCRIPT = AUTOMATION_ROOT / "tools" / "apply_code_patch.py"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_patch_ids(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def main() -> None:
    applied_by = sys.argv[1].strip() if len(sys.argv) > 1 else "dispatcher"

    truth_patch_ids = list_patch_ids(TRUTH_APPROVED_DIR)
    code_patch_ids = list_patch_ids(CODE_APPROVED_DIR)

    report = {
        "dispatcher_id": f"dispatcher_{now_utc_compact()}",
        "started_at": now_utc_iso(),
        "applied_by": applied_by,
        "truth_patch_ids_found": truth_patch_ids,
        "code_patch_ids_found": code_patch_ids,
        "truth_results": [],
        "code_results": [],
        "status": "success",
    }

    # safer order: truth first, then code
    for patch_id in truth_patch_ids:
        rc, stdout, stderr = run_cmd([sys.executable, str(APPLY_TRUTH_SCRIPT), patch_id, applied_by])
        item = {
            "patch_id": patch_id,
            "returncode": rc,
            "stdout": stdout,
            "stderr": stderr,
            "kind": "truth",
        }
        report["truth_results"].append(item)
        if rc != 0:
            report["status"] = "failed"
            report["failed_at"] = f"truth:{patch_id}"
            report["ended_at"] = now_utc_iso()
            report_path = REPORTS_DIR / f"{report['dispatcher_id']}.json"
            write_json(report_path, report)
            print("FAIL: dispatcher stopped on truth patch failure")
            print(f"patch_id={patch_id}")
            print(f"report={report_path}")
            sys.exit(1)

    for patch_id in code_patch_ids:
        rc, stdout, stderr = run_cmd([sys.executable, str(APPLY_CODE_SCRIPT), patch_id, applied_by])
        item = {
            "patch_id": patch_id,
            "returncode": rc,
            "stdout": stdout,
            "stderr": stderr,
            "kind": "code",
        }
        report["code_results"].append(item)
        if rc != 0:
            report["status"] = "failed"
            report["failed_at"] = f"code:{patch_id}"
            report["ended_at"] = now_utc_iso()
            report_path = REPORTS_DIR / f"{report['dispatcher_id']}.json"
            write_json(report_path, report)
            print("FAIL: dispatcher stopped on code patch failure")
            print(f"patch_id={patch_id}")
            print(f"report={report_path}")
            sys.exit(1)

    report["ended_at"] = now_utc_iso()
    report_path = REPORTS_DIR / f"{report['dispatcher_id']}.json"
    write_json(report_path, report)

    print("OK: dispatcher finished")
    print(f"truth_patch_count={len(truth_patch_ids)}")
    print(f"code_patch_count={len(code_patch_ids)}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()