from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def timestamp_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


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
    parser = argparse.ArgumentParser(description="Research OS Forensic Precheck v1")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--candidate-id", default=None)
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


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: Path, label: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise RuntimeError(f"{label} is empty: {path}")
    return df


def first_existing(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def normalize_ts_column(df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[str]]:
    ts_col = first_existing(df, ["ts", "timestamp", "date", "datetime"])
    if ts_col is None:
        return df.copy(), None
    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).sort_values(ts_col).copy()
    out = out.rename(columns={ts_col: "ts"})
    return out, "ts"


def check_artifacts_complete(contract_required: List[str], run_dir: Path) -> Tuple[bool, List[str]]:
    missing = []
    for name in contract_required:
        if not (run_dir / name).exists():
            missing.append(name)
    return (len(missing) == 0, missing)


def check_manifest_artifact_index_consistent(
    manifest: Dict[str, Any],
    artifacts_index: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    problems: List[str] = []

    manifest_run_id = manifest.get("run_id")
    artifacts_run_id = artifacts_index.get("run_id")
    if manifest_run_id != artifacts_run_id:
        problems.append("run_id_mismatch")

    manifest_artifact_root = manifest.get("artifact_root")
    if not manifest_artifact_root:
        problems.append("manifest_missing_artifact_root")

    produced_files = artifacts_index.get("produced_files")
    if not isinstance(produced_files, list):
        problems.append("artifacts_index_produced_files_invalid")

    required = artifacts_index.get("required_run_artifacts")
    if not isinstance(required, list):
        problems.append("artifacts_index_required_run_artifacts_invalid")

    return (len(problems) == 0, problems)


def check_compare_complete(
    compare_df: Optional[pd.DataFrame],
    compare_path: Optional[Path],
    compare_required: bool,
) -> Tuple[bool, List[str]]:
    problems: List[str] = []
    if not compare_required:
        return True, problems

    if compare_path is None or compare_df is None:
        problems.append("compare_missing")
        return False, problems

    required_cols = {"score"}
    missing_cols = sorted(required_cols - set(compare_df.columns))
    if missing_cols:
        problems.append(f"compare_missing_cols:{missing_cols}")

    if len(compare_df) < 1:
        problems.append("compare_no_rows")

    return (len(problems) == 0, problems)


def compute_paper_metrics(paper_df: pd.DataFrame) -> Dict[str, Optional[float]]:
    work, _ = normalize_ts_column(paper_df)
    ret_col = first_existing(work, ["strategy_ret", "ret", "daily_ret", "return"])
    equity_col = first_existing(work, ["equity", "portfolio_value", "nav"])

    if ret_col is None and equity_col is None:
        return {
            "row_count": float(len(work)),
            "final_equity": None,
            "total_return_pct": None,
            "avg_daily_ret_pct": None,
            "worst_day_pct": None,
        }

    if ret_col is None and equity_col is not None:
        work[equity_col] = pd.to_numeric(work[equity_col], errors="coerce")
        work["strategy_ret"] = work[equity_col].pct_change().fillna(0.0)
        ret_col = "strategy_ret"

    work[ret_col] = pd.to_numeric(work[ret_col], errors="coerce")
    work = work.dropna(subset=[ret_col]).copy()

    final_equity = None
    total_return_pct = None
    if equity_col is not None:
        work[equity_col] = pd.to_numeric(work[equity_col], errors="coerce")
        work = work.dropna(subset=[equity_col]).copy()
        if len(work) >= 1:
            final_equity = float(work[equity_col].iloc[-1])
        if len(work) >= 2 and float(work[equity_col].iloc[0]) != 0.0:
            total_return_pct = float((work[equity_col].iloc[-1] / work[equity_col].iloc[0] - 1.0) * 100.0)
    else:
        compounded = float((1.0 + work[ret_col]).prod())
        final_equity = compounded
        total_return_pct = (compounded - 1.0) * 100.0

    avg_daily_ret_pct = float(work[ret_col].mean() * 100.0) if len(work) else None
    worst_day_pct = float(work[ret_col].min() * 100.0) if len(work) else None

    return {
        "row_count": float(len(work)),
        "final_equity": final_equity,
        "total_return_pct": total_return_pct,
        "avg_daily_ret_pct": avg_daily_ret_pct,
        "worst_day_pct": worst_day_pct,
    }


def compute_summary_metrics(summary_df: pd.DataFrame) -> Dict[str, Optional[float]]:
    row = summary_df.iloc[0].to_dict()

    score = to_float(row.get("score"))
    total_return_pct = (
        to_float(row.get("total_return_pct"))
        or to_float(row.get("primary_metric_value"))
        or to_float(row.get("cagr_pct"))
    )
    cagr_pct = to_float(row.get("cagr_pct"))
    max_drawdown_pct = to_float(row.get("max_drawdown_pct"))
    since2025_cagr_pct = to_float(row.get("since2025_cagr_pct"))

    return {
        "score": score,
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "since2025_cagr_pct": since2025_cagr_pct,
    }


def check_summary_paper_consistent(summary_df: pd.DataFrame, paper_df: pd.DataFrame) -> Tuple[bool, List[str], Dict[str, Any]]:
    problems: List[str] = []
    summary_metrics = compute_summary_metrics(summary_df)
    paper_metrics = compute_paper_metrics(paper_df)

    if paper_metrics["row_count"] is None or paper_metrics["row_count"] <= 0:
        problems.append("paper_no_rows")

    score = summary_metrics["score"]
    if score is None:
        problems.append("summary_missing_score")

    if summary_metrics["total_return_pct"] is not None and paper_metrics["total_return_pct"] is not None:
        delta = abs(summary_metrics["total_return_pct"] - paper_metrics["total_return_pct"])
        if delta > 10.0:
            problems.append(f"total_return_delta_too_large:{delta:.4f}")

    if summary_metrics["cagr_pct"] is not None:
        if math.isnan(summary_metrics["cagr_pct"]) or abs(summary_metrics["cagr_pct"]) > 100000:
            problems.append("summary_cagr_invalid")

    details = {
        "summary_metrics": summary_metrics,
        "paper_metrics": paper_metrics,
    }
    return (len(problems) == 0, problems, details)


def check_lag1_sensitivity(paper_df: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    work, _ = normalize_ts_column(paper_df)
    ret_col = first_existing(work, ["strategy_ret", "ret", "daily_ret", "return"])
    if ret_col is None:
        return False, {
            "available": False,
            "reason": "paper_missing_return_column",
            "lag1_sensitivity_ok": False,
        }

    work[ret_col] = pd.to_numeric(work[ret_col], errors="coerce")
    work = work.dropna(subset=[ret_col]).copy()
    if len(work) < 3:
        return False, {
            "available": False,
            "reason": "paper_too_short_for_lag1_check",
            "lag1_sensitivity_ok": False,
        }

    same_day_compounded = float((1.0 + work[ret_col]).prod() - 1.0)
    lag1_compounded = float((1.0 + work[ret_col].shift(1).fillna(0.0)).prod() - 1.0)
    delta_pct_pts = (same_day_compounded - lag1_compounded) * 100.0

    ok = delta_pct_pts <= 25.0
    return ok, {
        "available": True,
        "same_day_total_return_pct": same_day_compounded * 100.0,
        "lag1_total_return_pct": lag1_compounded * 100.0,
        "delta_pct_pts": delta_pct_pts,
        "lag1_sensitivity_ok": ok,
    }


def check_benchmark_sanity(compare_df: Optional[pd.DataFrame], summary_df: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    if compare_df is None:
        return False, {
            "benchmark_sanity_ok": False,
            "reason": "compare_missing",
        }

    compare_score_col = first_existing(compare_df, ["score", "candidate_score"])
    delta_col = first_existing(compare_df, ["delta_vs_baseline_pct", "delta_pct", "outperformance_pct"])

    if compare_score_col is None:
        return False, {
            "benchmark_sanity_ok": False,
            "reason": "compare_missing_score_column",
        }

    compare_score = to_float(compare_df.iloc[0].get(compare_score_col))
    if compare_score is None:
        return False, {
            "benchmark_sanity_ok": False,
            "reason": "compare_score_not_numeric",
        }

    summary_score = compute_summary_metrics(summary_df)["score"]
    if summary_score is None:
        return False, {
            "benchmark_sanity_ok": False,
            "reason": "summary_score_missing",
        }

    score_delta = abs(summary_score - compare_score)
    if score_delta > 0.0001:
        return False, {
            "benchmark_sanity_ok": False,
            "reason": f"summary_compare_score_mismatch:{score_delta:.6f}",
            "summary_score": summary_score,
            "compare_score": compare_score,
        }

    delta_vs_baseline = to_float(compare_df.iloc[0].get(delta_col)) if delta_col else None
    if delta_vs_baseline is not None and abs(delta_vs_baseline) > 1000.0:
        return False, {
            "benchmark_sanity_ok": False,
            "reason": "delta_vs_baseline_implausible",
            "delta_vs_baseline_pct": delta_vs_baseline,
        }

    return True, {
        "benchmark_sanity_ok": True,
        "summary_score": summary_score,
        "compare_score": compare_score,
        "delta_vs_baseline_pct": delta_vs_baseline,
    }


def check_suspicious_uplift(compare_df: Optional[pd.DataFrame], paper_df: pd.DataFrame) -> Dict[str, Any]:
    work, _ = normalize_ts_column(paper_df)
    ret_col = first_existing(work, ["strategy_ret", "ret", "daily_ret", "return"])
    if ret_col is None:
        return {
            "suspicious_uplift_flag": True,
            "reason": "paper_missing_return_column",
            "top3_share_pct": None,
        }

    work[ret_col] = pd.to_numeric(work[ret_col], errors="coerce")
    work = work.dropna(subset=[ret_col]).copy()
    if len(work) < 5:
        return {
            "suspicious_uplift_flag": True,
            "reason": "paper_too_short_for_uplift_concentration",
            "top3_share_pct": None,
        }

    positive = work.loc[work[ret_col] > 0.0, ret_col].sort_values(ascending=False)
    total_positive = float(positive.sum())
    if total_positive <= 0.0:
        return {
            "suspicious_uplift_flag": False,
            "reason": "no_positive_uplift",
            "top3_share_pct": 0.0,
        }

    top3_share_pct = float(positive.head(3).sum() / total_positive * 100.0)
    suspicious = top3_share_pct >= 85.0
    return {
        "suspicious_uplift_flag": suspicious,
        "reason": "top3_positive_days_concentration",
        "top3_share_pct": top3_share_pct,
    }


def load_optional_metrics(run_dir: Path) -> Dict[str, Any]:
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        return {}
    try:
        return read_json(metrics_path)
    except Exception:
        return {}


def build_precheck_result(
    *,
    run_dir: Path,
    candidate_id: Optional[str],
    decision: str,
    reason_codes: List[str],
    artifacts_complete: bool,
    missing_required_artifacts: List[str],
    summary_paper_consistent: bool,
    summary_paper_details: Dict[str, Any],
    compare_complete: bool,
    compare_problems: List[str],
    manifest_artifact_index_consistent: bool,
    manifest_index_problems: List[str],
    lag1_sensitivity_ok: bool,
    lag1_details: Dict[str, Any],
    benchmark_sanity_ok: bool,
    benchmark_details: Dict[str, Any],
    suspicious_uplift_flag: bool,
    suspicious_uplift_details: Dict[str, Any],
    suspicious_uplift_hard_fail: bool,
    synthetic_harness: bool,
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_dir": str(run_dir),
        "candidate_id": candidate_id,
        "executed_at": timestamp_utc(),
        "decision": decision,
        "reason_codes": reason_codes,
        "checks": {
            "artifacts_complete": {
                "ok": artifacts_complete,
                "missing_required_artifacts": missing_required_artifacts,
            },
            "summary_paper_consistent": {
                "ok": summary_paper_consistent,
                "details": summary_paper_details,
            },
            "compare_complete": {
                "ok": compare_complete,
                "problems": compare_problems,
            },
            "manifest_artifact_index_consistent": {
                "ok": manifest_artifact_index_consistent,
                "problems": manifest_index_problems,
            },
            "lag1_sensitivity_ok": {
                "ok": lag1_sensitivity_ok,
                "details": lag1_details,
            },
            "benchmark_sanity_ok": {
                "ok": benchmark_sanity_ok,
                "details": benchmark_details,
            },
            "suspicious_uplift_flag": {
                "value": suspicious_uplift_flag,
                "details": suspicious_uplift_details,
                "hard_fail": suspicious_uplift_hard_fail,
            },
        },
        "synthetic_harness": synthetic_harness,
        "forensic_handoff_ready": decision == "precheck_passed",
    }


def build_precheck_summary_row(
    *,
    batch_candidate_id: Optional[str],
    run_dir: Path,
    decision: str,
    reason_codes: List[str],
    artifacts_complete: bool,
    summary_paper_consistent: bool,
    compare_complete: bool,
    manifest_artifact_index_consistent: bool,
    lag1_sensitivity_ok: bool,
    benchmark_sanity_ok: bool,
    suspicious_uplift_flag: bool,
    suspicious_uplift_hard_fail: bool,
    synthetic_harness: bool,
) -> Dict[str, Any]:
    return {
        "candidate_id": batch_candidate_id or "",
        "run_dir": str(run_dir),
        "decision": decision,
        "reason_codes": "|".join(reason_codes),
        "artifacts_complete": int(artifacts_complete),
        "summary_paper_consistent": int(summary_paper_consistent),
        "compare_complete": int(compare_complete),
        "manifest_artifact_index_consistent": int(manifest_artifact_index_consistent),
        "lag1_sensitivity_ok": int(lag1_sensitivity_ok),
        "benchmark_sanity_ok": int(benchmark_sanity_ok),
        "suspicious_uplift_flag": int(suspicious_uplift_flag),
        "suspicious_uplift_hard_fail": int(suspicious_uplift_hard_fail),
        "synthetic_harness": int(synthetic_harness),
        "executed_at": timestamp_utc(),
    }


def main() -> None:
    args = parse_args()
    rt = Runtime.start("research_os_forensic_precheck_v1.py")

    try:
        run_dir = Path(args.run_dir)
        require_dir(rt, run_dir, "run_dir")

        run_manifest_path = require_file(rt, run_dir / "run_manifest.json", "run_manifest")
        run_status_path = require_file(rt, run_dir / "run_status.json", "run_status")
        artifacts_index_path = require_file(rt, run_dir / "artifacts_index.json", "artifacts_index")
        quality_report_path = require_file(rt, run_dir / "quality_report.json", "quality_report")
        precheck_inputs_path = require_file(rt, run_dir / "precheck_inputs.json", "precheck_inputs")

        precheck_result_path = run_dir / "precheck_result.json"
        precheck_summary_path = run_dir / "precheck_summary.csv"

        manifest = read_json(run_manifest_path)
        run_status = read_json(run_status_path)
        artifacts_index = read_json(artifacts_index_path)
        quality_report = read_json(quality_report_path)
        precheck_inputs = read_json(precheck_inputs_path)
        metrics_json = load_optional_metrics(run_dir)

        contract_required = artifacts_index.get("required_run_artifacts", [])
        if not isinstance(contract_required, list):
            rt.fail("artifacts_index.required_run_artifacts must be list")

        summary_path = run_dir / "summary.csv"
        paper_path = run_dir / "paper.csv"
        compare_path = run_dir / "compare.csv" if (run_dir / "compare.csv").exists() else None

        candidate_id = args.candidate_id or manifest.get("candidate_id") or manifest.get("experiment_id")
        synthetic_harness = bool(metrics_json.get("synthetic_harness", False))

        if args.dry_run:
            rt.set_counter("candidate_id", candidate_id)
            rt.set_counter("run_dir", str(run_dir))
            rt.finish_ok(
                {
                    "mode": "dry_run",
                    "precheck_result_path": str(precheck_result_path),
                    "precheck_summary_path": str(precheck_summary_path),
                }
            )
            return

        summary_df = load_csv(require_file(rt, summary_path, "summary_csv"), "summary_csv")
        paper_df = load_csv(require_file(rt, paper_path, "paper_csv"), "paper_csv")
        compare_df = load_csv(compare_path, "compare_csv") if compare_path is not None else None

        compare_required = True

        artifacts_complete, missing_required_artifacts = check_artifacts_complete(contract_required, run_dir)
        summary_paper_consistent, summary_paper_problems, summary_paper_details = check_summary_paper_consistent(summary_df, paper_df)
        compare_complete, compare_problems = check_compare_complete(compare_df, compare_path, compare_required)
        manifest_artifact_index_consistent, manifest_index_problems = check_manifest_artifact_index_consistent(manifest, artifacts_index)
        lag1_sensitivity_ok, lag1_details = check_lag1_sensitivity(paper_df)
        benchmark_sanity_ok, benchmark_details = check_benchmark_sanity(compare_df, summary_df)
        suspicious_uplift_details = check_suspicious_uplift(compare_df, paper_df)
        suspicious_uplift_flag = bool(suspicious_uplift_details["suspicious_uplift_flag"])

        suspicious_uplift_hard_fail = suspicious_uplift_flag and (not synthetic_harness)

        reason_codes: List[str] = []

        if not artifacts_complete:
            reason_codes.append("missing_required_artifact")
        if not summary_paper_consistent:
            reason_codes.append("summary_paper_mismatch")
        if not compare_complete:
            reason_codes.append("compare_incomplete")
        if not manifest_artifact_index_consistent:
            reason_codes.append("manifest_index_inconsistent")
        if not lag1_sensitivity_ok:
            reason_codes.append("lag1_sensitivity_fail")
        if not benchmark_sanity_ok:
            reason_codes.append("benchmark_sanity_fail")
        if suspicious_uplift_hard_fail:
            reason_codes.append("suspicious_uplift_flag")
        elif suspicious_uplift_flag:
            reason_codes.append("warning_suspicious_uplift_flag")

        decision = "precheck_passed"
        hard_fail_codes = {
            "missing_required_artifact",
            "summary_paper_mismatch",
            "compare_incomplete",
            "manifest_index_inconsistent",
            "lag1_sensitivity_fail",
            "benchmark_sanity_fail",
            "suspicious_uplift_flag",
        }
        if any(code in hard_fail_codes for code in reason_codes):
            decision = "precheck_failed"

        result_payload = build_precheck_result(
            run_dir=run_dir,
            candidate_id=candidate_id,
            decision=decision,
            reason_codes=reason_codes,
            artifacts_complete=artifacts_complete,
            missing_required_artifacts=missing_required_artifacts,
            summary_paper_consistent=summary_paper_consistent,
            summary_paper_details=summary_paper_details | {"problems": summary_paper_problems},
            compare_complete=compare_complete,
            compare_problems=compare_problems,
            manifest_artifact_index_consistent=manifest_artifact_index_consistent,
            manifest_index_problems=manifest_index_problems,
            lag1_sensitivity_ok=lag1_sensitivity_ok,
            lag1_details=lag1_details,
            benchmark_sanity_ok=benchmark_sanity_ok,
            benchmark_details=benchmark_details,
            suspicious_uplift_flag=suspicious_uplift_flag,
            suspicious_uplift_details=suspicious_uplift_details,
            suspicious_uplift_hard_fail=suspicious_uplift_hard_fail,
            synthetic_harness=synthetic_harness,
        )
        save_json(precheck_result_path, result_payload)
        rt.log(f"SAVED kind=json path={precheck_result_path} size_bytes={precheck_result_path.stat().st_size}")

        summary_row = build_precheck_summary_row(
            batch_candidate_id=candidate_id,
            run_dir=run_dir,
            decision=decision,
            reason_codes=reason_codes,
            artifacts_complete=artifacts_complete,
            summary_paper_consistent=summary_paper_consistent,
            compare_complete=compare_complete,
            manifest_artifact_index_consistent=manifest_artifact_index_consistent,
            lag1_sensitivity_ok=lag1_sensitivity_ok,
            benchmark_sanity_ok=benchmark_sanity_ok,
            suspicious_uplift_flag=suspicious_uplift_flag,
            suspicious_uplift_hard_fail=suspicious_uplift_hard_fail,
            synthetic_harness=synthetic_harness,
        )
        save_csv(
            precheck_summary_path,
            [summary_row],
            [
                "candidate_id",
                "run_dir",
                "decision",
                "reason_codes",
                "artifacts_complete",
                "summary_paper_consistent",
                "compare_complete",
                "manifest_artifact_index_consistent",
                "lag1_sensitivity_ok",
                "benchmark_sanity_ok",
                "suspicious_uplift_flag",
                "suspicious_uplift_hard_fail",
                "synthetic_harness",
                "executed_at",
            ],
        )
        rt.log(f"SAVED kind=csv path={precheck_summary_path} rows=1 cols=14 size_bytes={precheck_summary_path.stat().st_size}")

        rt.set_counter("candidate_id", candidate_id)
        rt.set_counter("decision", decision)
        rt.set_counter("artifacts_complete", int(artifacts_complete))
        rt.set_counter("summary_paper_consistent", int(summary_paper_consistent))
        rt.set_counter("compare_complete", int(compare_complete))
        rt.set_counter("manifest_artifact_index_consistent", int(manifest_artifact_index_consistent))
        rt.set_counter("lag1_sensitivity_ok", int(lag1_sensitivity_ok))
        rt.set_counter("benchmark_sanity_ok", int(benchmark_sanity_ok))
        rt.set_counter("suspicious_uplift_flag", int(suspicious_uplift_flag))
        rt.set_counter("suspicious_uplift_hard_fail", int(suspicious_uplift_hard_fail))
        rt.set_counter("synthetic_harness", int(synthetic_harness))
        rt.set_counter("reason_codes_count", len(reason_codes))

        rt.finish_ok(
            {
                "mode": "execute",
                "precheck_result_path": str(precheck_result_path),
                "precheck_summary_path": str(precheck_summary_path),
            }
        )

    except Exception as exc:
        for line in traceback.format_exc().rstrip().splitlines():
            rt.log(f"TRACE {line}")
        rt.finish_fail(str(exc))
        raise


if __name__ == "__main__":
    main()