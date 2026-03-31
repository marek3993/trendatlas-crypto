from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_SCORE = 1.25


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def timestamp_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


class Runtime:
    def __init__(self, script_name: str) -> None:
        self.script_name = script_name
        self.started = time.monotonic()
        self.saved: List[str] = []

    def log(self, message: str) -> None:
        print(f"[{timestamp_local()}] [{self.script_name}] {message}", flush=True)

    def save_csv(self, path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self.saved.append(str(path))
        self.log(f"SAVED kind=csv path={path} rows={len(rows)} cols={len(fieldnames)} size_bytes={path.stat().st_size}")

    def save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.saved.append(str(path))
        self.log(f"SAVED kind=json path={path} size_bytes={path.stat().st_size}")

    def finish(self) -> None:
        elapsed = time.monotonic() - self.started
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        self.log(f"SUMMARY saved_files_count={len(self.saved)}")
        for idx, path in enumerate(self.saved, start=1):
            self.log(f"SAVED_FILE[{idx}] path={path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research OS golden-path synthetic producer")
    parser.add_argument("--run-dir", default=None, help="Explicit run directory. If omitted, uses RESEARCH_OS_RUN_DIR env.")
    parser.add_argument("--score", type=float, default=DEFAULT_SCORE, help="Synthetic positive score.")
    return parser.parse_args()


def resolve_run_dir(rt: Runtime, args: argparse.Namespace) -> Path:
    raw = args.run_dir or os.environ.get("RESEARCH_OS_RUN_DIR")
    if not raw:
        raise RuntimeError("Missing run dir. Use --run-dir or RESEARCH_OS_RUN_DIR.")
    run_dir = Path(raw)
    rt.log(f"CHECK dir run_dir: {run_dir}")
    if not run_dir.exists() or not run_dir.is_dir():
        raise RuntimeError(f"Run dir does not exist: {run_dir}")
    rt.log("OK dir run_dir")
    return run_dir


def read_existing_json_if_present(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> None:
    rt = Runtime("research_os_golden_path_producer.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    args = parse_args()
    run_dir = resolve_run_dir(rt, args)

    experiment_id = os.environ.get("RESEARCH_OS_EXPERIMENT_ID", "phase70_golden_path_harness")
    score = float(args.score)

    summary_path = run_dir / "summary.csv"
    paper_path = run_dir / "paper.csv"
    compare_path = run_dir / "compare.csv"
    metrics_path = run_dir / "metrics.json"

    summary_rows = [
        {
            "model": experiment_id,
            "score": score,
            "primary_metric_value": score,
            "cagr_pct": 12.5,
            "max_drawdown_pct": -3.2,
            "since2025_cagr_pct": 10.1,
            "status": "valid",
        }
    ]
    rt.save_csv(
        summary_path,
        summary_rows,
        ["model", "score", "primary_metric_value", "cagr_pct", "max_drawdown_pct", "since2025_cagr_pct", "status"],
    )

    paper_rows = [
        {
            "ts": "2026-03-01",
            "selected": "BTCUSDT",
            "gross_exposure": 1.0,
            "strategy_ret": 0.0120,
            "equity": 1.0120,
        },
        {
            "ts": "2026-03-02",
            "selected": "ETHUSDT",
            "gross_exposure": 1.0,
            "strategy_ret": 0.0080,
            "equity": 1.020096,
        },
        {
            "ts": "2026-03-03",
            "selected": "BTCUSDT",
            "gross_exposure": 1.0,
            "strategy_ret": 0.0060,
            "equity": 1.026216576,
        },
    ]
    rt.save_csv(
        paper_path,
        paper_rows,
        ["ts", "selected", "gross_exposure", "strategy_ret", "equity"],
    )

    compare_rows = [
        {
            "candidate_model": experiment_id,
            "baseline_model": "phase66g_production_soft_filters",
            "score": score,
            "delta_vs_baseline_pct": 1.75,
            "compare_valid": 1,
            "verdict": "above_threshold",
        }
    ]
    rt.save_csv(
        compare_path,
        compare_rows,
        ["candidate_model", "baseline_model", "score", "delta_vs_baseline_pct", "compare_valid", "verdict"],
    )

    rt.save_json(
        metrics_path,
        {
            "score": score,
            "primary_metric_value": score,
            "cagr_pct": 12.5,
            "since2025_cagr_pct": 10.1,
            "compare_valid": True,
            "synthetic_harness": True,
            "created_at": timestamp_utc(),
        },
    )

    # Optional courtesy update if orchestrator pre-created these files.
    artifacts_index_path = run_dir / "artifacts_index.json"
    quality_report_path = run_dir / "quality_report.json"

    artifacts_index = read_existing_json_if_present(artifacts_index_path)
    if artifacts_index is not None:
        produced_files = artifacts_index.get("produced_files", [])
        for path in [str(summary_path), str(paper_path), str(compare_path), str(metrics_path)]:
            if path not in produced_files:
                produced_files.append(path)
        artifacts_index["produced_files"] = produced_files
        artifacts_index["producer_status"] = "golden_path_outputs_written"
        rt.save_json(artifacts_index_path, artifacts_index)

    quality_report = read_existing_json_if_present(quality_report_path)
    if quality_report is not None:
        quality_report["producer_status"] = "pass"
        quality_report["producer_checks"] = [
            {"name": "summary_csv_written", "ok": True},
            {"name": "paper_csv_written", "ok": True},
            {"name": "compare_csv_written", "ok": True},
            {"name": "positive_score", "ok": score > 0.0, "value": score},
        ]
        rt.save_json(quality_report_path, quality_report)

    rt.log(f"experiment_id={experiment_id}")
    rt.log(f"run_dir={run_dir}")
    rt.log(f"score={score}")
    rt.log("golden_path_ready=1")
    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{timestamp_local()}] [research_os_golden_path_producer.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{timestamp_local()}] [research_os_golden_path_producer.py] TRACE {line}", flush=True)
        raise