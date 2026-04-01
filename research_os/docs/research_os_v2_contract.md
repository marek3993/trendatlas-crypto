# Research OS v2 Contract

## Required fields

### experiment_spec.template.json
Required fields:
- experiment_id
- branch
- segment_owner
- hypothesis_label
- experiment_family
- baseline_model
- baseline_paper_path
- input_paths
- script_path
- script_args
- expected_outputs
- scoring_profile
- promotion_rule
- invalidation_rule
- budget_class
- priority
- created_by
- created_at
- status

### promotion_decision.template.json
Required fields:
- decision_id
- candidate_id
- source_run_id
- decision
- decision_reason
- decided_by
- decided_at
- evidence_refs

### run_status.template.json
Required fields:
- schema_version
- run_id
- experiment_id
- candidate_id
- status
- allowed_status_values
- started_at
- ended_at
- status_reason
- current_step
- promotion_decision
- updated_at

## Allowed status values

Strict allowed lifecycle statuses:
- proposed
- spec_ready
- queued
- running
- run_failed
- ran
- scored
- precheck_failed
- precheck_passed
- forensic_ready
- forensic_failed
- forensic_passed
- master_pending
- promoted
- archived

No custom statuses allowed.

## Required run artifacts

Every run folder under `research_os/runs/<run_id>/` must contain:
- run_manifest.json
- run_status.json
- stdout.log
- stderr.log
- artifacts_index.json
- quality_report.json
- precheck_inputs.json

Plus summary/paper/compare artifacts when applicable:
- summary.csv
- paper.csv
- compare.csv

## Promotion decision types

Strict allowed decisions:
- kill
- hold
- rerun
- promote_to_precheck
- promote_to_forensic
- promote_to_master
- promote_to_official

No custom promotion decisions allowed.

## Naming conventions

- experiment_id: lowercase snake_case or phase-style identifier, e.g. `phase70_ai_lab_example`
- run_id: deterministic unique ID per run, e.g. `run_20260330_0001`
- decision_id: deterministic unique ID per decision, e.g. `decision_20260330_0001`
- all JSON templates/schemas live under `research_os/` only
- no broad autodiscovery for contracts
- orchestrator must use strict file paths from manifests/contracts
