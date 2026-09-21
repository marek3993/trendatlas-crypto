"""Dependency-scoped diagnostics and finite, deterministic maintenance only."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.production import data_health_common as health
from services.shared import openai_responses

OUTPUT_DIR = ROOT / "outputs/execution/watchdog"
REPORT_PATH = OUTPUT_DIR / "latest_watchdog_report.json"
SUMMARY_PATH = OUTPUT_DIR / "latest_watchdog_summary.txt"
ACTIONS_PATH = OUTPUT_DIR / "latest_watchdog_actions.json"
CONFIG_PATH = ROOT / "configs/maintenance/watchdog_openai.json"
CACHE_DIR = OUTPUT_DIR / "data_health"
ACTION_ID = "refresh_dependency_health_cache"
ACTION_ALLOWLIST = frozenset({ACTION_ID})
HEALTHY = {"OK_CURRENT", "NOT_TIME_YET"}
INCIDENTS = HEALTHY | {"DEPENDENCY_UNHEALTHY", "DIAGNOSTIC_CACHE_STALE", "PRODUCTION_BUSY",
                       "SCHEDULER_ATTENTION", "UNKNOWN_NEEDS_HUMAN"}


def utc_now():
    return datetime.now(timezone.utc)


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError("Linked output path")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def acquire_watchdog_lock(*, remediation_enabled=False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "maintenance.lock"
    if path.is_symlink():
        raise ValueError("Linked lock")
    with path.open("a+b") as handle:
        if os.name == "posix":
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def production_state():
    """Fixed read-only systemctl calls; never accept a command from config or AI."""
    result = {"known": False, "inactive": False, "timer_ready": False, "pending": True}
    try:
        for unit, prefix in (("mrv1-production.service", "service"), ("mrv1-production.timer", "timer")):
            output = subprocess.check_output(
                ["systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState",
                 "-p", "SubState", "-p", "Result", "-p", "UnitFileState"],
                text=True, stderr=subprocess.DEVNULL, timeout=10)
            result[prefix] = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        jobs = subprocess.check_output(["systemctl", "list-jobs", "--no-legend", "--no-pager"],
                                       text=True, stderr=subprocess.DEVNULL, timeout=10)
        result["known"] = all(result[x].get("LoadState") == "loaded" for x in ("service", "timer"))
        result["pending"] = any("mrv1-production.service" in line.split() for line in jobs.splitlines())
        result["inactive"] = (result["service"].get("ActiveState") == "inactive" and
                              result["service"].get("Result") == "success" and not result["pending"])
        result["timer_ready"] = (result["timer"].get("ActiveState") == "active" and
                                 result["timer"].get("UnitFileState") == "enabled")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return result


def safe_sources(sources):
    result = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if source_id not in health.SOURCE_INDEX:
            source_id = "unknown"
        status = source.get("status")
        if status not in health.STATUS_VALUES:
            status = "failed"
        row = {"source_id": source_id, "status": status,
               "criticality": source.get("criticality") if source.get("criticality") in health.CRITICALITY_VALUES else "informational",
               "action": source.get("action") if source.get("action") in health.ACTION_VALUES else "warn_only"}
        for field in ("actual_last_date", "expected_last_date"):
            row[field] = health.parse_iso_day(source.get(field))
        row.update(health.dependency_impact(row))
        result.append(row)
    return result


def signature(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def collect_state():
    now = utc_now()
    production = production_state()
    errors = []
    try:
        bundle = health.build_report_bundle(root=ROOT, write_outputs=False)
        sources = safe_sources(bundle["report"]["sources"])
    except Exception:
        sources = []; errors.append("health_metadata_unreadable")
    cache_stale = True
    try:
        cache = json.loads((CACHE_DIR / "dependency_health_cache.json").read_text(encoding="utf-8"))
        age = (now - datetime.fromisoformat(cache["generated_at_utc"])).total_seconds()
        cache_stale = not (cache["source_sha256"] == signature(sources) and 0 <= age < 6 * 3600 and cache["schema_version"] == 2)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    bad = [s for s in sources if s["status"] != "ok"]
    trade_bad = [s for s in bad if "new_trade_transition" in s["blocked_action_ids"]]
    expected = (now.date() - timedelta(days=1)).isoformat()
    prior = (now.date() - timedelta(days=2)).isoformat()
    not_time_yet = bool(now.hour < 1 and trade_bad and all(
        s["status"] == "stale" and s["actual_last_date"] == prior for s in trade_bad))
    if errors or not production["known"]:
        incident = "UNKNOWN_NEEDS_HUMAN"
    elif not production["inactive"]:
        incident = "PRODUCTION_BUSY"
    elif not production["timer_ready"]:
        incident = "SCHEDULER_ATTENTION"
    elif not_time_yet:
        incident = "NOT_TIME_YET"
    elif bad:
        incident = "DEPENDENCY_UNHEALTHY"
    elif cache_stale:
        incident = "DIAGNOSTIC_CACHE_STALE"
    else:
        incident = "OK_CURRENT"
    return {"incident_class": incident, "production": production, "sources": sources,
            "cache_stale": cache_stale, "errors": errors, "expected_closed_utc_day": expected}


def choose_safe_action(incident_class, truths):
    production = truths.get("production", {})
    eligible = (incident_class in {"DIAGNOSTIC_CACHE_STALE", "DEPENDENCY_UNHEALTHY"} and
                truths.get("cache_stale") is True and not truths.get("errors") and
                production.get("known") is True and production.get("inactive") is True and
                production.get("timer_ready") is True and production.get("pending") is False)
    return {"eligible": eligible, "action": ACTION_ID if eligible else "none",
            "reason": "cache_needs_refresh" if eligible else "no_eligible_deterministic_action"}


def load_ai_config():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    fixed = {"model": "gpt-5.4", "reasoning_effort": "low", "api_key_env": "OPENAI_API_KEY",
             "responses_api": openai_responses.DEFAULT_RESPONSES_API_URL,
             "strict_schema_validation": True, "fail_closed": False}
    if any(config.get(k) != value for k, value in fixed.items()):
        raise ValueError("AI config violates maintenance contract")
    if not 1 <= config["timeout_seconds"] <= 60 or not 128 <= config["max_output_tokens"] <= 2048:
        raise ValueError("Unbounded AI request")
    return config


def ai_diagnose(state, action, *, enabled):
    result = {"requested": bool(enabled), "api_request_sent": False,
              "api_key_present": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
              "action_id": action["action"], "needs_human": False, "warning": None,
              "status": "not_requested", "model": "gpt-5.4", "reasoning_effort": "low"}
    if not enabled:
        return result
    if not result["api_key_present"]:
        result.update(status="deterministic_fallback", warning="missing_api_key")
        return result
    if state["incident_class"] in HEALTHY | {"PRODUCTION_BUSY", "DIAGNOSTIC_CACHE_STALE"}:
        result["status"] = "skipped_healthy_or_busy"
        return result
    try:
        config = load_ai_config()
        if not config.get("enabled"):
            result["status"] = "disabled_by_config"; return result
    except Exception:
        result.update(status="deterministic_fallback", warning="invalid_ai_config")
        return result
    allowed = ["none"] + ([action["action"]] if action["eligible"] else [])
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"action_id": {"type": "string", "enum": allowed},
                             "needs_human": {"type": "boolean"},
                             "reason_code": {"type": "string", "enum": ["eligible_repair", "no_safe_action", "human_review"]}},
              "required": ["action_id", "needs_human", "reason_code"]}
    payload = {"incident_class": state["incident_class"] if state["incident_class"] in INCIDENTS else "UNKNOWN_NEEDS_HUMAN",
               "system_available": True, "eligible_action_ids": allowed,
               "sources": [{k: s[k] for k in ("source_id", "status")} for s in safe_sources(state["sources"])]}
    try:
        result["api_request_sent"] = True
        response = openai_responses.invoke_structured_response(
            config, system_prompt="Analyze these sanitized maintenance enums. Choose only an eligible action ID or none. You cannot run commands, change trade permissions or request other actions.",
            user_payload=payload, schema_name="watchdog_maintenance_decision", schema=schema)
        parsed = response.parsed
        if (response.status != "completed" or set(parsed) != {"action_id", "needs_human", "reason_code"} or
                parsed["action_id"] not in allowed or type(parsed["needs_human"]) is not bool or
                parsed["reason_code"] not in schema["properties"]["reason_code"]["enum"]):
            raise ValueError("Invalid model decision")
        result.update(status="completed", action_id=parsed["action_id"], needs_human=parsed["needs_human"])
    except Exception as exc:
        code = getattr(exc, "code", "invalid_ai_decision")
        if code in {"api_failure", "timeout", "missing_api_key", "bootstrap_config_error"}:
            result.update(status="deterministic_fallback", warning="ai_api_unavailable")
        else:
            result.update(status="rejected", action_id="none", needs_human=True, warning="invalid_ai_decision")
    return result


def run_safe_action(action, state):
    current = collect_state()
    expected = choose_safe_action(current["incident_class"], current)
    if (not action.get("eligible") or action.get("action") not in ACTION_ALLOWLIST or
            action["action"] != expected["action"] or not expected["eligible"]):
        return {"status": "skipped", "action": "none", "reason": "eligibility_changed"}
    atomic_json(CACHE_DIR / "dependency_health_cache.json", {
        "schema_version": 2, "generated_at_utc": utc_now().isoformat(),
        "source_sha256": signature(current["sources"]), "sources": current["sources"],
        "system_available": True})
    return {"status": "completed", "action": ACTION_ID, "reason": "diagnostic_cache_refreshed"}


def build_report(*, remediation_enabled, ai_enabled=False):
    state = collect_state()
    initial_incident = state["incident_class"]
    action = choose_safe_action(initial_incident, state)
    ai = ai_diagnose(state, action, enabled=ai_enabled and remediation_enabled)
    selected = dict(action)
    if ai["action_id"] != action["action"] or ai["needs_human"]:
        selected.update(eligible=False, action="none")
    result = {"status": "skipped", "action": "none", "reason": "check_only" if not remediation_enabled else "not_eligible"}
    if remediation_enabled and selected["eligible"]:
        try:
            result = run_safe_action(selected, state)
            state = collect_state()
        except Exception:
            result = {"status": "failed", "action": selected["action"], "reason": "repair_failed"}
    impacts = [health.dependency_impact(s) for s in state["sources"]]
    affected = sorted({x for i in impacts for x in i["affected_capability_ids"]})
    blocked = sorted({x for i in impacts for x in i["blocked_action_ids"]})
    unknown = state["incident_class"] not in INCIDENTS or state["incident_class"] == "UNKNOWN_NEEDS_HUMAN"
    if unknown and "maintenance_diagnostics" not in affected:
        affected.append("maintenance_diagnostics")
    report = {"schema_version": 2, "generated_at_utc": utc_now().isoformat(),
              "mode": "remediate_safe" if remediation_enabled else "check_only",
              "incident_class": state["incident_class"] if not unknown else "UNKNOWN_NEEDS_HUMAN",
              "initial_incident_class": initial_incident, "system_available": True,
              "incident_level": "action_blocked" if "new_trade_transition" in blocked else ("degraded" if blocked else ("warning" if affected or unknown else "none")),
              "affected_capability_ids": affected, "blocked_action_ids": blocked,
              "block_app": False, "block_execution": "new_trade_transition" in blocked,
              "sources": state["sources"], "production": state["production"],
              "expected_closed_utc_day": state["expected_closed_utc_day"],
              "needs_human": unknown or ai["needs_human"] or bool(blocked) or result["status"] == "failed",
              "ai": ai, "warnings": ([ai["warning"]] if ai["warning"] else []) + state["errors"] + (["repair_failed"] if result["status"] == "failed" else []),
              "remediation_allowed": action["eligible"], "action_taken": result["action"],
              "action_result": result, "orders_sent": False, "live_order_chain": "NOT_INVOKED",
              "production_writes": False, "strategy_changed": False}
    return report, {"selected_action": selected, "action_result": result, "ai": ai}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-only", action="store_true")
    modes.add_argument("--remediate-safe", action="store_true")
    parser.add_argument("--ai-diagnose", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with acquire_watchdog_lock(remediation_enabled=args.remediate_safe):
        report, actions = build_report(remediation_enabled=args.remediate_safe, ai_enabled=args.ai_diagnose)
        atomic_json(REPORT_PATH, report); atomic_json(ACTIONS_PATH, actions)
        atomic_json(SUMMARY_PATH, {k: report[k] for k in ("incident_class", "system_available", "action_taken", "warnings", "orders_sent")})
    print(json.dumps(report, indent=2) if args.json else report["incident_class"])


if __name__ == "__main__":
    main()
