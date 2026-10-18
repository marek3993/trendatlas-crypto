"""Reproduce frozen checkpoints and compare every historical signal with user code."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from trendatlas_clean.backtest import Costs, metrics, replay
from trendatlas_clean.core import explain_day, price_returns, target_weights, weights_dict
from trendatlas_clean.data import REFERENCE_SYMBOLS, load


def reference_module(path: Path):
    spec = importlib.util.spec_from_file_location("clean_user_reference", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate(data_dir: Path, end: str, output_dir: Path, *, prefix_tests: int = 25, reference_path: Path | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    panel = load(data_dir, end, REFERENCE_SYMBOLS)
    c, q = panel.close, panel.quote_volume
    actual = target_weights(c, q)
    reference = reference_module(reference_path or ROOT / "tests/fixtures/clean_5050_reference.py")
    rf = reference.features(c, q)
    rc = reference.decide(reference.Params(0.5, 10, 1, 0.25, 0.25), rf)
    rb = rc * 0
    rb["BTC"] = (rf["trend"]["BTC"] >= 0.5).astype(float)
    expected = 0.5 * rc + 0.5 * rb
    mismatches = actual.ne(expected).any(axis=1)
    checkpoints = json.loads((ROOT / "tests/fixtures/clean_5050_checkpoints.json").read_text())
    checkpoint_rows = []
    for day, weights in checkpoints.items():
        if pd.Timestamp(day) not in actual.index:
            checkpoint_rows.append({"day": day, "expected": weights, "status": "DATA_NOT_AVAILABLE"})
            continue
        got = weights_dict(actual.loc[day])
        row = {"day": day, "expected": weights, "actual": got, "matched": got == weights}
        if got != weights:
            row["diagnostics"] = explain_day(c, q, day)
            row["classification"] = "UNEXPLAINED_DATA_OR_UNIVERSE_DIFFERENCE_NOT_WAIVED"
        checkpoint_rows.append(row)
    days = actual.loc["2021-01-01":].index
    positions = np.unique(np.linspace(0, len(days) - 1, min(prefix_tests, len(days)), dtype=int))
    prefix_mismatches = []
    for i in positions:
        day = days[i]
        prefix = target_weights(c.loc[:day], q.loc[:day]).iloc[-1]
        if not prefix.equals(actual.loc[day]):
            prefix_mismatches.append(str(day.date()))
    # Mutate all prices/volumes AFTER one decision; preserve missingness and axes.
    split = days[len(days) // 2]
    mutated_c, mutated_q = c.copy(), q.copy()
    mutated_c.loc[mutated_c.index > split] *= 11.0
    mutated_q.loc[mutated_q.index > split] *= 0.013
    mutated = target_weights(mutated_c, mutated_q)
    future_mismatches = int(actual.loc[:split].ne(mutated.loc[:split]).any(axis=1).sum())
    ledger = replay(panel, actual)
    held = actual.shift(1).fillna(0)
    prices = price_returns(c)
    independent = pd.Series(0.0, index=c.index)
    for coin in c:
        independent += held[coin] * prices[coin].fillna(0)
    residual = float((independent - ledger["gross_return"]).abs().max())
    period = ledger.loc["2021-01-01":]
    weights_changed = actual.ne(actual.shift(1).fillna(0)).any(axis=1)
    report = {
        "strategy": "trendatlas_clean_5050_v1", "reference_symbols": len(c.columns),
        "input_sha256": panel.input_sha256, "input_files": panel.files,
        "history_start": str(c.index[0].date()), "history_end": end,
        "comparison_days_since_2021": len(days),
        "reference_signal_mismatches_full_history": int(mismatches.sum()),
        "reference_signal_mismatches_since_2021": int(mismatches.loc["2021-01-01":].sum()),
        "reference_mismatch_days": [str(d.date()) for d in mismatches[mismatches].index],
        "checkpoints": checkpoint_rows,
        "checkpoint_matches": sum(x.get("matched", False) for x in checkpoint_rows),
        "checkpoint_count": len(checkpoint_rows),
        "truncation_tests": len(positions), "truncation_mismatches": prefix_mismatches,
        "future_mutation_mismatches": future_mismatches,
        "gross_return_identity_max_abs_error": residual,
        "weight_changes_since_2021": int(weights_changed.loc["2021-01-01":].sum()),
        "state_observations_including_initial_since_2021": int(actual.loc["2021-01-01":].ne(actual.loc["2021-01-01":].shift(1)).any(axis=1).sum()),
        "reference_expected_state_observations_including_initial": 179,
        "metrics_since_2021": metrics(period),
        "metrics_last_365_days": metrics(ledger.iloc[-365:]),
        "costs": Costs().__dict__, "cost_timing": "weights[D-1] changes charged to holding day D",
        "claimed_83_5_percent_independently_verified": False,
        "full_universe_replay": "NOT_RUN_REFERENCE_59_ONLY",
        "oos_status": "HISTORY_ALREADY_INSPECTED_NOT_UNTOUCHED_OOS",
        "live_orders_sent": 0,
    }
    report["passed"] = (not mismatches.any() and report["checkpoint_matches"] == len(checkpoints)
                        and not prefix_mismatches and future_mismatches == 0 and residual <= 1e-14
                        and not period["invalid_return_or_nav"].any())
    actual.to_csv(output_dir / "decision_weights.csv", index_label="decision_closed_day_utc")
    ledger.to_csv(output_dir / "daily_ledger.csv", index_label="return_day_utc")
    (output_dir / "validation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--end", default="2026-10-17")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix-tests", type=int, default=25)
    args = parser.parse_args()
    report = validate(args.data_dir, args.end, args.output_dir, prefix_tests=args.prefix_tests)
    print(json.dumps({k: v for k, v in report.items() if k not in {"input_files", "checkpoints"}}, indent=2, allow_nan=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
