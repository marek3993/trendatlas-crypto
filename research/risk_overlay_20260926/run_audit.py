"""Offline baseline prerequisite audit. Never calls an execution entrypoint.

Exit 2 means research stopped at a failed scientific prerequisite, not a failed
runtime execution gate. Outputs are confined to this research directory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
ADAPTER_MODULE = "scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def compare_frames(reference: pd.DataFrame, rebuilt: pd.DataFrame) -> dict:
    if len(reference) != len(rebuilt):
        return {"passed": False, "reason": "row_count", "reference": len(reference), "rebuilt": len(rebuilt)}
    missing = sorted(set(reference) - set(rebuilt))
    differences = {}
    for col in reference.columns.intersection(rebuilt.columns):
        left, right = reference[col], rebuilt[col]
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            same = np.isclose(left.astype(float), right.astype(float), atol=1e-9, rtol=1e-12, equal_nan=True)
        else:
            same = left.fillna("").astype(str).to_numpy() == right.fillna("").astype(str).to_numpy()
        if not same.all():
            differences[col] = int((~same).sum())
    return {"passed": not missing and not differences, "missing_columns": missing,
            "differences": differences, "rows": len(reference), "columns_compared": len(reference.columns.intersection(rebuilt.columns))}


def close_returns(path: Path) -> pd.Series:
    frame = pd.read_csv(path)
    if frame.date.duplicated().any():
        raise ValueError(f"Duplicate OHLC days: {path.name}")
    return frame.set_index("date").close.pct_change()


def asset_identity(frame: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Diagnostic only: no replacement strategy and no net-PnL interpretation."""
    rows = []
    for asset, part in frame.loc[frame.effective_market_exposure > 0].groupby("actual_held_asset"):
        path = root / "data" / "ohlcv" / f"{asset}USDT_1d.csv"
        returns = close_returns(path) if path.exists() else pd.Series(dtype=float)
        for row in part.itertuples():
            market_return = returns.get(row.date, np.nan)
            expected = market_return * row.effective_market_exposure
            rows.append({"date": row.date, "model_asset": asset,
                         "model_exposure": row.effective_market_exposure,
                         "canonical_gross_return": row.authorized_return_gross,
                         "same_day_asset_return": market_return,
                         "asset_times_exposure": expected,
                         "residual": row.authorized_return_gross - expected,
                         "covered": bool(pd.notna(expected))})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def metrics(frame: pd.DataFrame) -> dict:
    r = frame.authorized_return_net.to_numpy(float)
    eq = np.r_[1.0, np.cumprod(1 + r)]
    dd = eq / np.maximum.accumulate(eq) - 1
    years = (pd.Timestamp(frame.date.iloc[-1]) - pd.Timestamp(frame.date.iloc[0])).days / 365.25
    cagr = eq[-1] ** (1 / years) - 1
    vol = np.std(r, ddof=0) * np.sqrt(365.25)
    down = np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * np.sqrt(365.25)
    return {"cagr_pct": float(cagr * 100), "total_return_pct": float((eq[-1] - 1) * 100),
            "max_drawdown_pct": float(dd.min() * 100), "calmar": float(cagr / -dd.min()),
            "sharpe_population_365_25": float(np.mean(r) * 365.25 / vol),
            "sortino_all_days_downside_365_25": float(np.mean(r) * 365.25 / down),
            "volatility_pct": float(vol * 100), "worst_day_pct": float(r.min() * 100),
            "worst_day_date": str(frame.date.iloc[int(r.argmin())]),
            "time_in_market_pct": float((frame.effective_market_exposure > 0).mean() * 100),
            "turnover_sum_nav_units": float(frame.turnover.sum()),
            "trade_level_metrics": None,
            "trade_level_metrics_unavailable_reason": "No economically reconciled fill ledger: asset/return identity and signal timing fail.",
            "cost_units": "sum of daily NAV cost fractions, not cash paid or percentage of initial equity",
            "trading_fees_sum_pct": float(frame.fees_daily.sum() * 100),
            "funding_sum_pct": float(frame.funding_daily.sum() * 100),
            "borrow_sum_pct": float(frame.borrow_cost_daily.sum() * 100),
            "slippage_sum_pct": float(frame.slippage_cost_daily.sum() * 100)}


def freeze(adapter) -> None:
    """Explicit one-time capture of public market/model inputs, no wallet data."""
    if (HERE / "frozen_inputs.zip").exists():
        raise FileExistsError("Frozen bundle already exists; refusing to replace research evidence")
    paths = set(adapter.resolve_source_paths(root=ROOT).values())
    paths.update((ROOT / "data" / "ohlcv").glob("*USDT_1d.csv"))
    paths.update(ROOT / p for p in [
        "outputs/phase66g_production_candidate_live/phase66g_manifest.json",
        "outputs/phase66g_production_candidate_live/phase66g_production_candidate_asset_quality.csv",
        "outputs/execution/app_exports/phase68g_etf_flow_impulse_early_risk_cooldown_15_authoritative_net_compare_export.csv",
    ])
    hashes = {}
    with zipfile.ZipFile(HERE / "frozen_inputs.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(paths):
            name = path.relative_to(ROOT).as_posix()
            hashes[name] = sha(path)
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    # Inventory intraday/funding without presenting them as venue mark/funding.
    inventory = []
    for folder in ["data/ohlcv_4h", "data/funding"]:
        for path in sorted((ROOT / folder).glob("*.csv")):
            f = pd.read_csv(path)
            inventory.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path),
                              "rows": len(f), "columns": list(f.columns),
                              "first_time_value": str(f.iloc[0, 0]), "last_time_value": str(f.iloc[-1, 0]),
                              "used_for_overlay": False})
    write_json(HERE / "input_manifest.json", {
        "code_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "frozen_inputs_sha256": sha(HERE / "frozen_inputs.zip"), "files": hashes,
        "contract_sha256": sha(HERE / "contract.json"), "seed": 20260926,
        "intraday_and_funding_inventory": inventory,
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "venue_mark_history": "not_present_in_supplied_dataset", "venue_funding_history": "not_present_in_supplied_dataset"})


def verify_bundle(bundle: Path, manifest: dict, target: Path) -> None:
    if sha(bundle) != manifest["frozen_inputs_sha256"]:
        raise ValueError("Frozen bundle hash mismatch")
    with zipfile.ZipFile(bundle) as z:
        if set(z.namelist()) != set(manifest["files"]):
            raise ValueError("Frozen member list mismatch")
        for name, expected in manifest["files"].items():
            dst = (target / name).resolve()
            if not dst.is_relative_to(target.resolve()):
                raise ValueError("Unsafe archive member")
            payload = z.read(name)
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError(f"Input hash mismatch: {name}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(payload)


def scientific_verdict(reproduction: dict, return_identity_ok: bool, timing_ok: bool, venue_ok: bool) -> dict:
    issues = []
    if not reproduction["passed"]:
        issues.append("canonical_reproduction_mismatch")
    if not return_identity_ok:
        issues.append("asset_return_identity_failure")
    if not timing_ok:
        issues.append("same_day_close_signal_applied_to_same_day_return")
    if not venue_ok:
        issues.append("hyperliquid_mark_and_hourly_funding_history_missing")
    return {"research_status": "STOPPED_AT_BASELINE_PREREQUISITES" if issues else "READY_FOR_SEPARATE_RESEARCH_RUN",
            "issues": issues, "recommendation": "NENASADZOVAT", "variants_executed": 0,
            "top_three": None, "walk_forward": None, "holdout": None,
            "holdout_status": "NOT_RUN", "production_changes": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true", help="Capture once from current local public inputs")
    parser.add_argument("--source", choices=["current", "local"], default="current")
    args = parser.parse_args()
    prefix = "local_" if args.source == "local" else ""
    contract = json.loads((HERE / "contract.json").read_text())
    if contract["research_rules"]["production_writes"] or contract["research_rules"]["orders_or_leverage_updates"]:
        raise ValueError("Invalid research-only contract")
    module = importlib.import_module(ADAPTER_MODULE)
    adapter = module.Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter()
    if args.freeze:
        freeze(adapter)
    manifest = json.loads((HERE / f"{prefix}input_manifest.json").read_text())
    if sha(HERE / "contract.json") != manifest["contract_sha256"]:
        raise ValueError("Research contract changed after input freeze")
    previous_manifest = HERE / f"{prefix}run_manifest.json"
    if previous_manifest.exists():
        previous = json.loads(previous_manifest.read_text())
        pinned = previous["source_hashes"]
        for name, expected in pinned.items():
            if name.startswith(("scripts/", "src/")) and sha(ROOT / name) != expected:
                normalized = hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                if normalized != previous.get("source_hashes_lf", {}).get(name):
                    raise ValueError(f"Production source changed since reproduction: {name}")
    with tempfile.TemporaryDirectory(prefix="trendatlas-risk-audit-") as temp:
        root = Path(temp)
        verify_bundle(HERE / f"{prefix}frozen_inputs.zip", manifest, root)
        reference = pd.read_csv(root / "outputs/production/current_strategy_timeseries.csv")
        snapshot = json.loads((root / "outputs/production/current_strategy_snapshot.json").read_text())
        # Call read-only methods; do not run a builder main or refresh chain.
        try:
            inputs = adapter.load_inputs(root=root)
        except (ValueError, FileNotFoundError) as exc:
            mismatches = []
            for name, meta in snapshot.get("source_inputs", {}).get("files", {}).items():
                path = root / meta.get("path", "")
                if meta.get("sha256") and path.is_file() and sha(path) != meta["sha256"]:
                    lf_hash = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                    mismatches.append({"source": name, "path": meta["path"], "expected": meta["sha256"], "available": sha(path),
                                       "explained_by_crlf_only": lf_hash == meta["sha256"]})
            result = {
                **scientific_verdict({"passed": False}, True, True, True),
                "baseline_reproduction": {"passed": False, "stage": "unchanged_adapter_load_inputs", "error_type": type(exc).__name__, "error": str(exc)},
                "frozen_source_commit": manifest["code_base_commit"],
                "canonical_snapshot_metrics_NOT_REPRODUCED": snapshot["metrics"],
                "canonical_snapshot_closed_day": snapshot["closed_day"],
                "canonical_timeseries_start": str(reference.date.iloc[0]),
                "canonical_timeseries_end": str(reference.date.iloc[-1]),
                "canonical_timeseries_rows": len(reference),
                "declared_source_hash_mismatches": mismatches,
                "reason": "Published current model artifacts and repository-tracked raw/durable input bundle are from different vintages; no fallback, data refresh, or strategy patch was applied.",
                "economic_overlay_analysis": "NOT_RUN_AFTER_REPRODUCTION_FAILURE",
            }
            write_json(HERE / f"{prefix}results.json", result)
            save_run_manifest(prefix, contract)
            print(json.dumps(result, indent=2))
            return 2
        rebuilt = adapter.build_timeseries(inputs)
        second_inputs = adapter.load_inputs(root=root)
        second = adapter.build_timeseries(second_inputs)
        reproduction = compare_frames(reference, rebuilt)
        repeat = compare_frames(rebuilt, second)
        reproduced_metrics = adapter.build_snapshot_metrics(inputs, rebuilt)
        metric_match = reproduced_metrics == snapshot["metrics"]
        reproduction["passed"] &= repeat["passed"] and metric_match
        reproduction["second_run"] = repeat
        reproduction["snapshot_metrics_exact_match"] = metric_match
        # Explicit counterexamples, re-derived from frozen raw data.
        identity = asset_identity(rebuilt, root)
        ex = identity.loc[identity.date.eq("2024-12-03")].iloc[0].to_dict()
        ex["TRX_same_day_return"] = float(close_returns(root / "data/ohlcv/TRXUSDT_1d.csv").loc[ex["date"]])
        btc = pd.read_csv(root / "data/ohlcv/BTCUSDT_1d.csv").set_index("date")
        ema = btc.close.ewm(span=10, adjust=False, min_periods=10).mean()
        byday = rebuilt.set_index("date")
        timing = {
            "date": "2025-01-07", "previous_model_asset": byday.loc["2025-01-06", "actual_held_asset"],
            "previous_model_exposure": float(byday.loc["2025-01-06", "effective_market_exposure"]),
            "new_model_asset": byday.loc["2025-01-07", "actual_held_asset"],
            "btc_close": float(btc.loc["2025-01-07", "close"]),
            "btc_ema10": float(ema.loc["2025-01-07"]),
            "btc_close_to_close_return": float(btc.close.pct_change().loc["2025-01-07"]),
            "canonical_gross_return": float(byday.loc["2025-01-07", "authorized_return_gross"]),
            "canonical_net_return": float(byday.loc["2025-01-07", "authorized_return_net"]),
            "prior_exposure_times_return_diagnostic_only": float(0.5 * btc.close.pct_change().loc["2025-01-07"]),
        }
        identity_ok = abs(ex["residual"]) < 1e-9
        timing_ok = not (timing["previous_model_exposure"] > 0 and timing["btc_close"] < timing["btc_ema10"]
                         and timing["canonical_gross_return"] == 0)
        verdict = scientific_verdict(reproduction, identity_ok, timing_ok, False)
        reference_metrics = metrics(rebuilt)
        core_manifest = json.loads((root / "outputs/phase66g_production_candidate_live/phase66g_manifest.json").read_text())
        quality = pd.read_csv(root / "outputs/phase66g_production_candidate_live/phase66g_production_candidate_asset_quality.csv")
        result = {**verdict, "baseline_reproduction": reproduction,
                  "reproduction_scope": "unchanged active adapter and ETF state machine from durable canonical BTC-persistence inputs; not a fresh upstream selector grid or independent execution backtest",
                  "date_start": rebuilt.date.iloc[0], "date_end": rebuilt.date.iloc[-1], "row_count": len(rebuilt),
                  "official_snapshot_metrics": snapshot["metrics"], "reproduced_snapshot_metrics": reproduced_metrics,
                  "independent_model_curve_metrics": reference_metrics,
                  "active_adapter_cost_config": inputs["cost_config_meta"],
                  "core_winner_parameters": core_manifest["winner_profile"],
                  "core_overlay_candidate_universe": sorted(quality.asset.astype(str).unique()),
                  "core_removed_assets": core_manifest["removed_assets"],
                  "observed_authorized_model_assets": sorted(rebuilt.actual_held_asset.unique()),
                  "observed_model_exposures": sorted(rebuilt.effective_market_exposure.unique()),
                  "trade_count_semantics": "snapshot trade_count equals asset_transition_day sum; not closed round trips or exchange fills",
                  "asset_identity_counterexample": ex, "timing_counterexample": timing,
                  "identity_diagnostic_rows": len(identity),
                  "identity_residual_over_1bp_rows": int((identity.residual.abs() > 0.0001).sum()),
                  "identity_missing_ohlc_rows": int((~identity.covered).sum()),
                  "identity_diagnostic_caveat": "same-row price consistency diagnostic; neither a repaired strategy nor a causal return replay; investigate transitions separately",
                  "holdout_caveat": "Prior local studies already analyzed this historical sample; no new overlay holdout was evaluated."}
        write_json(HERE / f"{prefix}results.json", result)
        rebuilt.to_csv(HERE / f"{prefix}baseline_reproduced.csv", index=False, lineterminator="\n")
        identity.to_csv(HERE / f"{prefix}asset_return_diagnostics.csv", index=False, lineterminator="\n")
    save_run_manifest(prefix, contract)
    print(json.dumps({"reproduction_passed": reproduction["passed"], **verdict}, indent=2))
    return 2 if verdict["issues"] else 0


def save_run_manifest(prefix: str, contract: dict) -> None:
    # Pin every local Python module actually imported, including dynamically loaded helpers.
    code_hashes = {}
    for mod in list(sys.modules.values()):
        file = getattr(mod, "__file__", None)
        if file:
            path = Path(file).resolve()
            if path.is_relative_to(ROOT) and path.suffix == ".py":
                code_hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    code_hashes_lf = {name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in code_hashes}
    write_json(HERE / f"{prefix}run_manifest.json", {"source_hashes": code_hashes, "source_hashes_lf": code_hashes_lf,
               "contract_sha256": sha(HERE / "contract.json"),
               "input_manifest_sha256": sha(HERE / f"{prefix}input_manifest.json"),
               "result_sha256": sha(HERE / f"{prefix}results.json"), "seed": contract["seed"],
               "command": "python research/risk_overlay_20260926/run_audit.py" + (" --source local" if prefix else ""), "expected_exit_code": 2,
               "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
               "heavy_refresh_steps": "skipped", "live_order_chain": "not_invoked"})


if __name__ == "__main__":
    raise SystemExit(main())
