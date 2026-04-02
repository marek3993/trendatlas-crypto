from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"


DIRS = [
    "config",
    "schemas",
    "tasks",
    "tasks/specs",
    "tasks/queue",
    "tasks/completed",
    "runs",
    "reports",
    "screenshots",
    "truth_patches",
    "truth_patches/pending",
    "truth_patches/approved",
    "truth_patches/rejected",
    "approvals",
    "tools",
    "templates",
]


AUTOMATION_README = """# MRV1 Automation

Safe automation layer pre Market Regime v1.

## Scope
Rieši:
- browser automation workflow
- task specs
- run logging
- reports
- screenshots
- pending truth patches
- safe approval-gated updates do source_of_truth

Nerieši:
- winner decisions
- strategy ideation
- forensic validation
- app wording
- repo hygiene
- tokenomiku

## Safe mode
Automation nesmie priamo prepisovať source_of_truth.
Automation môže len:
- vykonať task
- uložiť log
- uložiť report
- pripraviť pending truth patch

Apply truth patchu je oddelený krok.
"""


AUTOMATION_CONFIG = {
    "project_name": "Market Regime v1",
    "layer_name": "MRV1 AUTOMATION",
    "safe_mode": True,
    "allow_direct_source_of_truth_write": False,
    "default_executor": "manual_orchestrator",
    "artifacts": {
        "runs_dir": "automation/runs",
        "reports_dir": "automation/reports",
        "screenshots_dir": "automation/screenshots",
        "truth_patches_pending_dir": "automation/truth_patches/pending",
        "truth_patches_approved_dir": "automation/truth_patches/approved",
        "truth_patches_rejected_dir": "automation/truth_patches/rejected",
        "approvals_dir": "automation/approvals"
    }
}


TASK_REGISTRY = {
    "version": 1,
    "task_types": [
        "browser_check",
        "browser_capture",
        "workflow_run",
        "report_only",
        "truth_patch_prep"
    ],
    "status_enum": [
        "draft",
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled"
    ]
}


TASK_SPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "TaskSpec",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "task_id",
        "task_type",
        "created_at",
        "requested_by",
        "status",
        "inputs",
        "constraints",
        "expected_outputs",
        "approval_gate",
        "source_refs"
    ],
    "properties": {
        "task_id": {"type": "string"},
        "task_type": {"type": "string"},
        "created_at": {"type": "string"},
        "requested_by": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["draft", "queued", "running", "completed", "failed", "cancelled"]
        },
        "inputs": {"type": "object"},
        "constraints": {"type": "object"},
        "expected_outputs": {
            "type": "array",
            "items": {"type": "string"}
        },
        "approval_gate": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required_for_truth_apply"],
            "properties": {
                "required_for_truth_apply": {"type": "boolean"},
                "approver_role": {"type": "string"}
            }
        },
        "source_refs": {
            "type": "array",
            "items": {"type": "string"}
        }
    }
}


RUN_LOG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RunLog",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "run_id",
        "task_id",
        "started_at",
        "ended_at",
        "status",
        "executor",
        "steps",
        "artifacts",
        "errors",
        "warnings"
    ],
    "properties": {
        "run_id": {"type": "string"},
        "task_id": {"type": "string"},
        "started_at": {"type": "string"},
        "ended_at": {"type": ["string", "null"]},
        "status": {
            "type": "string",
            "enum": ["started", "success", "partial", "failed"]
        },
        "executor": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["step_index", "timestamp", "action", "result"],
                "properties": {
                    "step_index": {"type": "integer"},
                    "timestamp": {"type": "string"},
                    "action": {"type": "string"},
                    "result": {"type": "string"},
                    "note": {"type": "string"}
                }
            }
        },
        "artifacts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["report_paths", "screenshot_manifest_paths", "pending_truth_patch_paths"],
            "properties": {
                "report_paths": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "screenshot_manifest_paths": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "pending_truth_patch_paths": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "errors": {
            "type": "array",
            "items": {"type": "string"}
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"}
        }
    }
}


REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Report",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "report_id",
        "run_id",
        "task_id",
        "summary",
        "findings",
        "artifacts",
        "pending_truth_patch_ids",
        "next_action"
    ],
    "properties": {
        "report_id": {"type": "string"},
        "run_id": {"type": "string"},
        "task_id": {"type": "string"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {"type": "string"}
        },
        "artifacts": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "run_log_path": {"type": "string"},
                "screenshot_manifest_paths": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "report_path": {"type": "string"}
            }
        },
        "pending_truth_patch_ids": {
            "type": "array",
            "items": {"type": "string"}
        },
        "next_action": {"type": "string"}
    }
}


SCREENSHOT_MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ScreenshotManifest",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "manifest_id",
        "run_id",
        "screenshots"
    ],
    "properties": {
        "manifest_id": {"type": "string"},
        "run_id": {"type": "string"},
        "screenshots": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["shot_id", "timestamp", "file_path", "page_hint", "note"],
                "properties": {
                    "shot_id": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "file_path": {"type": "string"},
                    "page_hint": {"type": "string"},
                    "note": {"type": "string"}
                }
            }
        }
    }
}


PENDING_TRUTH_PATCH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PendingTruthPatch",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "patch_id",
        "created_at",
        "task_id",
        "run_id",
        "target_files",
        "reason",
        "proposed_changes",
        "evidence_refs",
        "status"
    ],
    "properties": {
        "patch_id": {"type": "string"},
        "created_at": {"type": "string"},
        "task_id": {"type": "string"},
        "run_id": {"type": "string"},
        "target_files": {
            "type": "array",
            "items": {"type": "string"}
        },
        "reason": {"type": "string"},
        "proposed_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["change_type", "target", "payload"],
                "properties": {
                    "change_type": {"type": "string"},
                    "target": {"type": "string"},
                    "payload": {}
                }
            }
        },
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"}
        },
        "status": {
            "type": "string",
            "enum": ["pending", "approved", "rejected", "applied"]
        }
    }
}


APPROVAL_RECORD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ApprovalRecord",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "approval_id",
        "patch_id",
        "decision",
        "approved_by",
        "decided_at",
        "note"
    ],
    "properties": {
        "approval_id": {"type": "string"},
        "patch_id": {"type": "string"},
        "decision": {
            "type": "string",
            "enum": ["approved", "rejected"]
        },
        "approved_by": {"type": "string"},
        "decided_at": {"type": "string"},
        "note": {"type": "string"}
    }
}


TASK_SPEC_TEMPLATE = {
    "task_id": "task_YYYYMMDD_HHMMSS_slug",
    "task_type": "browser_check",
    "created_at": "2026-04-02T12:00:00Z",
    "requested_by": "user",
    "status": "draft",
    "inputs": {},
    "constraints": {
        "safe_mode": True,
        "allow_direct_source_of_truth_write": False
    },
    "expected_outputs": [
        "run_log",
        "report"
    ],
    "approval_gate": {
        "required_for_truth_apply": True,
        "approver_role": "human"
    },
    "source_refs": [
        "source_of_truth/README.md",
        "source_of_truth/master_state.md"
    ]
}


RUN_LOG_TEMPLATE = {
    "run_id": "run_YYYYMMDD_HHMMSS_slug",
    "task_id": "task_YYYYMMDD_HHMMSS_slug",
    "started_at": "2026-04-02T12:00:00Z",
    "ended_at": None,
    "status": "started",
    "executor": "manual_orchestrator",
    "steps": [],
    "artifacts": {
        "report_paths": [],
        "screenshot_manifest_paths": [],
        "pending_truth_patch_paths": []
    },
    "errors": [],
    "warnings": []
}


REPORT_TEMPLATE = {
    "report_id": "report_YYYYMMDD_HHMMSS_slug",
    "run_id": "run_YYYYMMDD_HHMMSS_slug",
    "task_id": "task_YYYYMMDD_HHMMSS_slug",
    "summary": "",
    "findings": [],
    "artifacts": {
        "run_log_path": "",
        "screenshot_manifest_paths": [],
        "report_path": ""
    },
    "pending_truth_patch_ids": [],
    "next_action": "review"
}


SCREENSHOT_MANIFEST_TEMPLATE = {
    "manifest_id": "manifest_YYYYMMDD_HHMMSS_slug",
    "run_id": "run_YYYYMMDD_HHMMSS_slug",
    "screenshots": []
}


PENDING_TRUTH_PATCH_TEMPLATE = {
    "patch_id": "patch_YYYYMMDD_HHMMSS_slug",
    "created_at": "2026-04-02T12:00:00Z",
    "task_id": "task_YYYYMMDD_HHMMSS_slug",
    "run_id": "run_YYYYMMDD_HHMMSS_slug",
    "target_files": [],
    "reason": "",
    "proposed_changes": [],
    "evidence_refs": [],
    "status": "pending"
}


APPROVAL_RECORD_TEMPLATE = {
    "approval_id": "approval_YYYYMMDD_HHMMSS_slug",
    "patch_id": "patch_YYYYMMDD_HHMMSS_slug",
    "decision": "approved",
    "approved_by": "human",
    "decided_at": "2026-04-02T12:00:00Z",
    "note": ""
}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_gitkeep(dir_path: Path) -> None:
    gitkeep = dir_path / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")


def main() -> None:
    AUTOMATION_ROOT.mkdir(parents=True, exist_ok=True)

    for rel_dir in DIRS:
        d = AUTOMATION_ROOT / rel_dir
        d.mkdir(parents=True, exist_ok=True)

    for rel_dir in [
        "tasks/specs",
        "tasks/queue",
        "tasks/completed",
        "runs",
        "reports",
        "screenshots",
        "truth_patches/pending",
        "truth_patches/approved",
        "truth_patches/rejected",
        "approvals",
    ]:
        ensure_gitkeep(AUTOMATION_ROOT / rel_dir)

    write_text(AUTOMATION_ROOT / "README.md", AUTOMATION_README)

    write_json(AUTOMATION_ROOT / "config" / "automation_config.json", AUTOMATION_CONFIG)
    write_json(AUTOMATION_ROOT / "config" / "task_registry.json", TASK_REGISTRY)

    write_json(AUTOMATION_ROOT / "schemas" / "task_spec.schema.json", TASK_SPEC_SCHEMA)
    write_json(AUTOMATION_ROOT / "schemas" / "run_log.schema.json", RUN_LOG_SCHEMA)
    write_json(AUTOMATION_ROOT / "schemas" / "report.schema.json", REPORT_SCHEMA)
    write_json(AUTOMATION_ROOT / "schemas" / "screenshot_manifest.schema.json", SCREENSHOT_MANIFEST_SCHEMA)
    write_json(AUTOMATION_ROOT / "schemas" / "pending_truth_patch.schema.json", PENDING_TRUTH_PATCH_SCHEMA)
    write_json(AUTOMATION_ROOT / "schemas" / "approval_record.schema.json", APPROVAL_RECORD_SCHEMA)

    write_json(AUTOMATION_ROOT / "templates" / "task_spec.template.json", TASK_SPEC_TEMPLATE)
    write_json(AUTOMATION_ROOT / "templates" / "run_log.template.json", RUN_LOG_TEMPLATE)
    write_json(AUTOMATION_ROOT / "templates" / "report.template.json", REPORT_TEMPLATE)
    write_json(AUTOMATION_ROOT / "templates" / "screenshot_manifest.template.json", SCREENSHOT_MANIFEST_TEMPLATE)
    write_json(AUTOMATION_ROOT / "templates" / "pending_truth_patch.template.json", PENDING_TRUTH_PATCH_TEMPLATE)
    write_json(AUTOMATION_ROOT / "templates" / "approval_record.template.json", APPROVAL_RECORD_TEMPLATE)

    print("OK: automation scaffold created")
    print(f"Root: {AUTOMATION_ROOT}")


if __name__ == "__main__":
    main()