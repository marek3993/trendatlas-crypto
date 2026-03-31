from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"
POLICIES_DIR = RESEARCH_OS_ROOT / "policies"
DEFAULT_SCORING_POLICY_PATH = POLICIES_DIR / "research_os_scoring_policy_v1.json"
DEFAULT_PROMOTION_POLICY_PATH = POLICIES_DIR / "research_os_promotion_policy_v1.json"


def timestamp_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass
class Runtime:
    script_name: str
    started_mono: float
    counters: Dict[str, Any]

    @classmethod
    def start(cls, script_name: str) -> "Runtime":
        rt = cls(script_name=script_name, started_mono=time.monotonic(), counters={})
        rt.log("START")
        rt.log(f"cwd={Path.cwd()}")
        rt.log(f"python={sys.executable}")
        rt.log(f"argv={' '.join(sys.argv)}")
        return rt

    def log(self, message: str) -> None:
        print(f"[{timestamp_local()}] [{self.script_name}] {message}", flush=True)

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value
        self.log(f"{key}={value}")

    def fail(self, message: str) -> None:
        self.log(f"FAIL {message}")
        raise RuntimeError(message)

    def finish_ok(self, extra: Optional[Dict[str, Any]] = None) -> None:
        elapsed = time.monotonic() - self.started_mono
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")
        if extra:
            for k, v in extra.items():
                self.log(f"SUMMARY {k}={v}")

    def finish_fail(self, message: str) -> None:
        elapsed = time.monotonic() - self.started_mono
        self.log(f"ERROR {message}")
        self.log(f"END status=FAIL elapsed_sec={elapsed:.3f}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS Scoring Engine v1")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--scoring-policy", default=str(DEFAULT_SCORING_POLICY_PATH))
    parser.add_argument("--promotion-policy", default=str(DEFAULT_PROMOTION_POLICY_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.execute:
        raise SystemExit("Choose exactly one of --dry-run or --execute.")
    return args


def require_file(rt: Runtime, path: Path, label: str) -> Path:
    rt.log(f"CHECK file {label}: {path}")
    if not path.exists() or not path.is_file():
        rt.fail(f"missing required file: {path}")
    rt.log(f"OK file {label}: size_bytes={path.stat().st_size}")
    return path


def require_dir(rt: Runtime, path: Path, label: str) -> Path:
    rt.log(f"CHECK dir {label}: {path}")
    if not path.exists() or not path.is_dir():
        rt.fail(f"missing required directory: {path}")
    rt.log(f"OK dir {label}")
    return path


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def load_optional_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def read_first_row_csv(path: Path) -> Dict[str, Any]:
    df = pd.read_csv(path)
    if df.empty:
        raise RuntimeError(f"empty csv: {path}")
    return df.iloc[0].to_dict()


def extract_candidate_metrics(run_dir: Path) -> Dict[str, float]:
    summary_row = read_first_row_csv(run_dir / "summary.csv")
    compare_row = read_first_row_csv(run_dir / "compare.csv")

    return {
        "score": to_float(summary_row.get("score"), 0.0) or 0.0,
        "cagr_pct": to_float(summary_row.get("cagr_pct"), 0.0) or 0.0,
        "since2023_cagr_pct": to_float(summary_row.get("since2023_cagr_pct"), 0.0) or 0.0,
        "since2025_cagr_pct": to_float(summary_row.get("since2025_cagr_pct"), 0.0) or 0.0,
        "max_drawdown_pct": to_float(summary_row.get("max_drawdown_pct"), 0.0) or 0.0,
        "switch_count": to_float(summary_row.get("switch_count"), 0.0) or 0.0,
        "delta_vs_baseline_pct": to_float(compare_row.get("delta_vs_baseline_pct"), 0.0) or 0.0
    }


def detect_complexity_level(run_manifest: Dict[str, Any], precheck_result: Dict[str, Any]) -> str:
    branch = str(run_manifest.get("branch", "")).lower()
    script_path = str(run_manifest.get("script_path", "")).lower()

    if "golden_path" in branch or "golden_path" in script_path or precheck_result.get("synthetic_harness", False):
        return "low"
    if "phase66g" in branch or "production" in branch:
        return "medium"
    if "dynamic" in branch or "top100" in branch or "admission" in branch:
        return "high"
    return "medium"


def detect_robustness_level(run_dir: Path, precheck_result: Dict[str, Any]) -> str:
    if precheck_result.get("decision") != "precheck_passed":
        return "weak"

    summary_path = run_dir / "summary.csv"
    compare_path = run_dir / "compare.csv"
    paper_path = run_dir / "paper.csv"

    if summary_path.exists() and compare_path.exists() and paper_path.exists():
        if precheck_result.get("synthetic_harness", False):
            return "medium"
        return "strong"

    return "unknown"


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def context_tokens(run_manifest: Dict[str, Any], precheck_result: Dict[str, Any], candidate_id: Optional[str], run_dir: Path) -> List[str]:
    tokens = []
    for raw in [
        candidate_id or "",
        run_manifest.get("candidate_id", ""),
        run_manifest.get("experiment_id", ""),
        run_manifest.get("branch", ""),
        run_manifest.get("script_path", ""),
        str(run_dir),
    ]:
        text = str(raw).lower()
        if text:
            tokens.append(text)
    if precheck_result.get("synthetic_harness", False):
        tokens.append("synthetic_harness")
    return tokens


def apply_scoring_branch_override(
    scoring_policy: Dict[str, Any],
    run_manifest: Dict[str, Any],
    precheck_result: Dict[str, Any],
    candidate_id: Optional[str],
    run_dir: Path,
) -> Dict[str, Any]:
    out = copy.deepcopy(scoring_policy)
    tokens = context_tokens(run_manifest, precheck_result, candidate_id, run_dir)
    overrides = scoring_policy.get("branch_overrides", {})
    applied = []

    for override_name, override in overrides.items():
        match_contains = [str(x).lower() for x in override.get("match_contains", [])]
        if match_contains and any(any(needle in token for token in tokens) for needle in match_contains):
            applied.append(override_name)

            if "replace_baseline_metrics" in override:
                out["official_baseline"]["summary_metrics"] = deep_merge(
                    out["official_baseline"]["summary_metrics"],
                    override["replace_baseline_metrics"],
                )
            if "replace_thresholds" in override:
                out["thresholds"] = deep_merge(out["thresholds"], override["replace_thresholds"])
            if "replace_component_weights" in override:
                out["component_weights"] = deep_merge(out["component_weights"], override["replace_component_weights"])
            if "replace_penalties" in override:
                out["penalties"] = deep_merge(out["penalties"], override["replace_penalties"])
            if "force_complexity_level" in override:
                out["_force_complexity_level"] = override["force_complexity_level"]
            if "force_robustness_level" in override:
                out["_force_robustness_level"] = override["force_robustness_level"]

    out["_applied_branch_overrides"] = applied
    return out


def apply_promotion_branch_override(
    promotion_policy: Dict[str, Any],
    run_manifest: Dict[str, Any],
    precheck_result: Dict[str, Any],
    candidate_id: Optional[str],
    run_dir: Path,
) -> Dict[str, Any]:
    out = copy.deepcopy(promotion_policy)
    tokens = context_tokens(run_manifest, precheck_result, candidate_id, run_dir)
    overrides = promotion_policy.get("branch_overrides", {})
    applied = []

    for override_name, override in overrides.items():
        match_contains = [str(x).lower() for x in override.get("match_contains", [])]
        if match_contains and any(any(needle in token for token in tokens) for needle in match_contains):
            applied.append(override_name)

            if "replace_score_thresholds" in override:
                out["score_thresholds"] = deep_merge(out["score_thresholds"], override["replace_score_thresholds"])
            if "replace_recent_performance_thresholds" in override:
                out["recent_performance_thresholds"] = deep_merge(
                    out["recent_performance_thresholds"],
                    override["replace_recent_performance_thresholds"],
                )
            if "replace_warning_treatment" in override:
                out["warning_treatment"] = deep_merge(out["warning_treatment"], override["replace_warning_treatment"])
            if "replace_explicit_policy_flags" in override:
                out["explicit_policy_flags"] = deep_merge(
                    out["explicit_policy_flags"],
                    override["replace_explicit_policy_flags"],
                )

    out["_applied_branch_overrides"] = applied
    return out


def build_reason_codes(
    *,
    promotion_recommendation: str,
    compare_missing: bool,
    precheck_failed: bool,
    micro_uplift_without_robustness: bool,
    weak_since2025_block: bool,
    suspicious_instability_hard: bool,
    suspicious_instability_warning: bool,
) -> List[str]:
    reasons: List[str] = []

    if compare_missing:
        reasons.append("compare_context_missing")
    if precheck_failed:
        reasons.append("precheck_failed")
    if micro_uplift_without_robustness:
        reasons.append("micro_uplift_without_robustness")
    if weak_since2025_block:
        reasons.append("weak_since2025_block")
    if suspicious_instability_hard:
        reasons.append("suspicious_instability_hard")
    elif suspicious_instability_warning:
        reasons.append("warning_suspicious_instability")

    reasons.append(f"promotion_recommendation:{promotion_recommendation}")
    return reasons


def main() -> None:
    args = parse_args()
    rt = Runtime.start("research_os_scoring_engine_v1.py")

    try:
        run_dir = Path(args.run_dir)
        scoring_policy_path = Path(args.scoring_policy)
        promotion_policy_path = Path(args.promotion_policy)

        require_dir(rt, run_dir, "run_dir")
        require_file(rt, scoring_policy_path, "scoring_policy")
        require_file(rt, promotion_policy_path, "promotion_policy")
        require_file(rt, run_dir / "run_manifest.json", "run_manifest")
        require_file(rt, run_dir / "artifacts_index.json", "artifacts_index")
        require_file(rt, run_dir / "quality_report.json", "quality_report")
        require_file(rt, run_dir / "summary.csv", "summary_csv")
        require_file(rt, run_dir / "paper.csv", "paper_csv")

        compare_path = run_dir / "compare.csv"
        precheck_result_path = run_dir / "precheck_result.json"
        scoring_result_path = run_dir / "scoring_result.json"
        scoring_summary_path = run_dir / "scoring_summary.csv"

        scoring_policy_raw = read_json(scoring_policy_path)
        promotion_policy_raw = read_json(promotion_policy_path)
        run_manifest = read_json(run_dir / "run_manifest.json")
        artifacts_index = read_json(run_dir / "artifacts_index.json")
        quality_report = read_json(run_dir / "quality_report.json")
        precheck_result = load_optional_json(precheck_result_path)

        candidate_id = args.candidate_id or run_manifest.get("candidate_id") or run_manifest.get("experiment_id")

        scoring_policy = apply_scoring_branch_override(
            scoring_policy_raw, run_manifest, precheck_result, candidate_id, run_dir
        )
        promotion_policy = apply_promotion_branch_override(
            promotion_policy_raw, run_manifest, precheck_result, candidate_id, run_dir
        )

        compare_missing = not compare_path.exists()
        precheck_failed = precheck_result.get("decision") not in ("precheck_passed",)

        baseline = scoring_policy["official_baseline"]["summary_metrics"]
        candidate = extract_candidate_metrics(run_dir)

        complexity_level = scoring_policy.get("_force_complexity_level") or detect_complexity_level(run_manifest, precheck_result)
        robustness_level = scoring_policy.get("_force_robustness_level") or detect_robustness_level(run_dir, precheck_result)

        suspicious_uplift_flag = bool(precheck_result.get("checks", {}).get("suspicious_uplift_flag", {}).get("value", False))
        suspicious_uplift_hard_fail = bool(precheck_result.get("checks", {}).get("suspicious_uplift_flag", {}).get("hard_fail", False))

        cagr_uplift = candidate["cagr_pct"] - float(baseline["cagr_pct"])
        since2023_uplift = candidate["since2023_cagr_pct"] - float(baseline["since2023_cagr_pct"])
        since2025_uplift = candidate["since2025_cagr_pct"] - float(baseline["since2025_cagr_pct"])
        max_dd_worsening = abs(candidate["max_drawdown_pct"]) - abs(float(baseline["max_drawdown_pct"]))
        switch_count_over_baseline = candidate["switch_count"] - float(baseline.get("switch_count", 0.0))

        weights = scoring_policy["component_weights"]
        penalties = scoring_policy["penalties"]
        thresholds = scoring_policy["thresholds"]
        recency_rules = scoring_policy["recency_multiplier_rules"]

        cagr_component = cagr_uplift * weights["cagr_uplift_vs_baseline"]
        since2023_component = since2023_uplift * weights["since2023_uplift_vs_baseline"]
        since2025_component = since2025_uplift * weights["since2025_uplift_vs_baseline"]

        max_dd_penalty_raw = max(0.0, max_dd_worsening) * penalties["max_drawdown_penalty_per_pct_point"]
        max_dd_penalty_component = -max_dd_penalty_raw * weights["max_drawdown_penalty"]

        switch_penalty_raw = max(0.0, switch_count_over_baseline) * penalties["switch_count_penalty_per_switch"]
        switch_penalty_component = -switch_penalty_raw * weights["switch_count_penalty"]

        complexity_penalty_raw = penalties["complexity_penalty_per_level"].get(complexity_level, 0.0)
        complexity_penalty_component = -complexity_penalty_raw * weights["complexity_penalty"]

        robustness_penalty_raw = penalties["robustness_penalty_values"].get(
            robustness_level,
            penalties["robustness_penalty_values"]["unknown"],
        )
        robustness_penalty_component = -robustness_penalty_raw * weights["robustness_penalty"]

        recency_multiplier = 1.0
        recency_multiplier *= recency_rules["since2025_positive_multiplier"] if since2025_uplift > 0 else recency_rules["since2025_negative_multiplier"]
        recency_multiplier *= recency_rules["since2023_positive_multiplier"] if since2023_uplift > 0 else recency_rules["since2023_negative_multiplier"]

        recency_bonus_component = (max(0.0, since2025_uplift) * (recency_multiplier - 1.0)) * weights["recency_weighting_bonus"]

        instability_level = "none"
        if suspicious_uplift_hard_fail:
            instability_level = "hard"
        elif suspicious_uplift_flag:
            instability_level = "warning"

        instability_penalty_raw = penalties["instability_penalty"][instability_level]
        instability_penalty_component = -instability_penalty_raw

        raw_score_before_recency = (
            cagr_component
            + since2023_component
            + since2025_component
            + max_dd_penalty_component
            + switch_penalty_component
            + complexity_penalty_component
            + robustness_penalty_component
            + instability_penalty_component
        )
        final_score = raw_score_before_recency + recency_bonus_component

        micro_uplift_without_robustness = (
            cagr_uplift <= thresholds["micro_uplift_cagr_pct"]
            and cagr_uplift > 0
            and robustness_level != thresholds["minimum_robustness_for_micro_uplift"]
        )

        weak_since2025_block = (
            promotion_policy["hard_fail_rules"]["block_if_weak_since2025_and_not_explicitly_allowed"]
            and since2025_uplift < promotion_policy["recent_performance_thresholds"]["minimum_since2025_uplift_pct"]
            and not promotion_policy["explicit_policy_flags"]["allow_weak_since2025_override"]
        )

        if compare_missing and promotion_policy["hard_fail_rules"]["require_compare_context"]:
            promotion_recommendation = "kill"
        elif precheck_failed and promotion_policy["hard_fail_rules"]["block_if_precheck_failed"]:
            promotion_recommendation = "kill"
        elif suspicious_uplift_hard_fail and promotion_policy["hard_fail_rules"]["block_if_suspicious_instability_hard"]:
            promotion_recommendation = "kill"
        elif weak_since2025_block:
            promotion_recommendation = "kill"
        elif micro_uplift_without_robustness:
            promotion_recommendation = promotion_policy["micro_uplift_policy"]["action_if_missing_robustness"]
        elif final_score >= promotion_policy["score_thresholds"]["promote_to_precheck_min_score"]:
            promotion_recommendation = "promote_to_precheck"
        elif final_score >= promotion_policy["score_thresholds"]["hold_min_score"]:
            promotion_recommendation = "hold"
        elif final_score >= promotion_policy["score_thresholds"]["rerun_min_score"]:
            promotion_recommendation = "rerun"
        else:
            promotion_recommendation = "kill"

        if suspicious_uplift_flag and not suspicious_uplift_hard_fail:
            warning_treatment = promotion_policy["warning_treatment"].get("warning_suspicious_uplift_flag")
            if promotion_recommendation == "promote_to_precheck" and warning_treatment in ("hold", "rerun", "kill"):
                promotion_recommendation = warning_treatment

        reason_codes = build_reason_codes(
            promotion_recommendation=promotion_recommendation,
            compare_missing=compare_missing,
            precheck_failed=precheck_failed,
            micro_uplift_without_robustness=micro_uplift_without_robustness,
            weak_since2025_block=weak_since2025_block,
            suspicious_instability_hard=suspicious_uplift_hard_fail,
            suspicious_instability_warning=(suspicious_uplift_flag and not suspicious_uplift_hard_fail),
        )

        result = {
            "schema_version": "1.1",
            "candidate_id": candidate_id,
            "run_dir": str(run_dir),
            "executed_at": timestamp_utc(),
            "policy_paths": {
                "scoring_policy": str(scoring_policy_path),
                "promotion_policy": str(promotion_policy_path)
            },
            "applied_overrides": {
                "scoring_policy": scoring_policy.get("_applied_branch_overrides", []),
                "promotion_policy": promotion_policy.get("_applied_branch_overrides", [])
            },
            "inputs": {
                "compare_context_missing": compare_missing,
                "precheck_failed": precheck_failed,
                "complexity_level": complexity_level,
                "robustness_level": robustness_level,
                "suspicious_uplift_flag": suspicious_uplift_flag,
                "suspicious_uplift_hard_fail": suspicious_uplift_hard_fail
            },
            "baseline_metrics": baseline,
            "candidate_metrics": candidate,
            "uplifts": {
                "cagr_uplift_pct": cagr_uplift,
                "since2023_uplift_pct": since2023_uplift,
                "since2025_uplift_pct": since2025_uplift,
                "max_drawdown_worsening_pct": max_dd_worsening,
                "switch_count_over_baseline": switch_count_over_baseline
            },
            "score_breakdown": {
                "cagr_component": cagr_component,
                "since2023_component": since2023_component,
                "since2025_component": since2025_component,
                "max_drawdown_penalty_component": max_dd_penalty_component,
                "switch_count_penalty_component": switch_penalty_component,
                "complexity_penalty_component": complexity_penalty_component,
                "robustness_penalty_component": robustness_penalty_component,
                "instability_penalty_component": instability_penalty_component,
                "recency_bonus_component": recency_bonus_component,
                "recency_multiplier": recency_multiplier,
                "final_score": final_score
            },
            "promotion_recommendation": promotion_recommendation,
            "reason_codes": reason_codes
        }

        summary_row = {
            "candidate_id": candidate_id,
            "run_dir": str(run_dir),
            "final_score": round(final_score, 6),
            "promotion_recommendation": promotion_recommendation,
            "cagr_uplift_pct": round(cagr_uplift, 6),
            "since2023_uplift_pct": round(since2023_uplift, 6),
            "since2025_uplift_pct": round(since2025_uplift, 6),
            "max_drawdown_worsening_pct": round(max_dd_worsening, 6),
            "switch_count_over_baseline": round(switch_count_over_baseline, 6),
            "complexity_level": complexity_level,
            "robustness_level": robustness_level,
            "suspicious_uplift_flag": int(suspicious_uplift_flag),
            "suspicious_uplift_hard_fail": int(suspicious_uplift_hard_fail),
            "reason_codes": "|".join(reason_codes),
            "applied_scoring_overrides": "|".join(scoring_policy.get("_applied_branch_overrides", [])),
            "applied_promotion_overrides": "|".join(promotion_policy.get("_applied_branch_overrides", [])),
            "executed_at": timestamp_utc()
        }

        if args.dry_run:
            rt.set_counter("candidate_id", candidate_id)
            rt.set_counter("mode", "dry_run")
            rt.finish_ok(
                {
                    "scoring_result_path": str(scoring_result_path),
                    "scoring_summary_path": str(scoring_summary_path)
                }
            )
            return

        write_json(scoring_result_path, result)
        rt.log(f"SAVED kind=json path={scoring_result_path} size_bytes={scoring_result_path.stat().st_size}")

        write_csv(
            scoring_summary_path,
            [summary_row],
            [
                "candidate_id",
                "run_dir",
                "final_score",
                "promotion_recommendation",
                "cagr_uplift_pct",
                "since2023_uplift_pct",
                "since2025_uplift_pct",
                "max_drawdown_worsening_pct",
                "switch_count_over_baseline",
                "complexity_level",
                "robustness_level",
                "suspicious_uplift_flag",
                "suspicious_uplift_hard_fail",
                "reason_codes",
                "applied_scoring_overrides",
                "applied_promotion_overrides",
                "executed_at"
            ]
        )
        rt.log(f"SAVED kind=csv path={scoring_summary_path} rows=1 cols=17 size_bytes={scoring_summary_path.stat().st_size}")

        rt.set_counter("candidate_id", candidate_id)
        rt.set_counter("promotion_recommendation", promotion_recommendation)
        rt.set_counter("final_score", round(final_score, 6))
        rt.set_counter("compare_context_missing", int(compare_missing))
        rt.set_counter("precheck_failed", int(precheck_failed))
        rt.set_counter("micro_uplift_without_robustness", int(micro_uplift_without_robustness))
        rt.set_counter("weak_since2025_block", int(weak_since2025_block))
        rt.set_counter("suspicious_uplift_flag", int(suspicious_uplift_flag))
        rt.set_counter("suspicious_uplift_hard_fail", int(suspicious_uplift_hard_fail))
        rt.set_counter("applied_scoring_overrides_count", len(scoring_policy.get("_applied_branch_overrides", [])))
        rt.set_counter("applied_promotion_overrides_count", len(promotion_policy.get("_applied_branch_overrides", [])))
        rt.set_counter("reason_codes_count", len(reason_codes))

        rt.finish_ok(
            {
                "mode": "execute",
                "scoring_result_path": str(scoring_result_path),
                "scoring_summary_path": str(scoring_summary_path)
            }
        )

    except Exception as exc:
        for line in traceback.format_exc().rstrip().splitlines():
            rt.log(f"TRACE {line}")
        rt.finish_fail(str(exc))
        raise


if __name__ == "__main__":
    main()