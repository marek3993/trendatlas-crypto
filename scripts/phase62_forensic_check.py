from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
PHASE62_DIR = OUTPUTS / "phase62_btc_overlay"

PHASE61_WINNER = "phase61_restore_trx_sol_base"
LATEST_BASELINE = "phase42 core"


def log(msg: str) -> None:
    print(msg, flush=True)


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_equity(equity: pd.Series) -> float:
    eq = pd.to_numeric(equity, errors="coerce").ffill().bfill()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def sharpe_ratio(daily_ret: pd.Series) -> float:
    x = pd.to_numeric(daily_ret, errors="coerce").dropna()
    if len(x) < 2:
        return 0.0
    vol = x.std(ddof=0)
    if vol == 0 or np.isnan(vol):
        return 0.0
    return float((x.mean() / vol) * np.sqrt(365.25))


def sortino_ratio(daily_ret: pd.Series) -> float:
    x = pd.to_numeric(daily_ret, errors="coerce").dropna()
    if len(x) < 2:
        return 0.0
    downside = x[x < 0]
    if len(downside) == 0:
        return 0.0
    dd = downside.std(ddof=0)
    if dd == 0 or np.isnan(dd):
        return 0.0
    return float((x.mean() / dd) * np.sqrt(365.25))


def calc_metrics_from_returns(df: pd.DataFrame, ret_col: str, regime_col: str | None = None) -> dict:
    x = df.copy()
    x[ret_col] = pd.to_numeric(x[ret_col], errors="coerce").fillna(0.0)
    x["equity"] = (1.0 + x[ret_col]).cumprod()

    total_return = float(x["equity"].iloc[-1] / x["equity"].iloc[0] - 1.0) if len(x) > 1 else 0.0
    cagr = annualize_return(total_return, len(x))
    max_dd = max_drawdown_from_equity(x["equity"])
    sharpe = sharpe_ratio(x[ret_col])
    sortino = sortino_ratio(x[ret_col])

    out = {
        "days": int(len(x)),
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "sharpe": sharpe,
        "sortino": sortino,
    }

    if regime_col and regime_col in x.columns:
        r = x[regime_col].astype(str).fillna("NA")
        out["cash_days_pct"] = float((r == "CASH").mean() * 100.0)
        out["btc_days_pct"] = float((r == "BTC").mean() * 100.0)
        out["base_days_pct"] = float((r == "BASE").mean() * 100.0)

    return out


def window_metrics(df: pd.DataFrame, ret_col: str, regime_col: str | None, start_date: str) -> dict:
    sub = df[df["date"] >= pd.Timestamp(start_date)].copy()
    if sub.empty:
        return {
            f"since{start_date[:4]}_total_return_pct": np.nan,
            f"since{start_date[:4]}_cagr_pct": np.nan,
            f"since{start_date[:4]}_max_drawdown_pct": np.nan,
        }
    m = calc_metrics_from_returns(sub, ret_col, regime_col)
    return {
        f"since{start_date[:4]}_total_return_pct": m["total_return_pct"],
        f"since{start_date[:4]}_cagr_pct": m["cagr_pct"],
        f"since{start_date[:4]}_max_drawdown_pct": m["max_drawdown_pct"],
    }


def load_manifest() -> dict:
    path = PHASE62_DIR / "phase62_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing manifest file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_summary() -> pd.DataFrame:
    path = PHASE62_DIR / "phase62_overlay_summary.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing summary file: {path}")
    return read_csv(path)


def load_compare() -> pd.DataFrame:
    path = PHASE62_DIR / "phase62_overlay_top_compare.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing compare file: {path}")
    return read_csv(path)


def get_row_by_model(df: pd.DataFrame, model: str) -> dict | None:
    if "model" not in df.columns:
        return None
    hit = df[df["model"].astype(str).str.lower() == model.lower()]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def model_paper_path(model: str) -> Path:
    return PHASE62_DIR / f"{model}_paper.csv"


def load_paper(model: str) -> pd.DataFrame:
    path = model_paper_path(model)
    if not path.exists():
        raise FileNotFoundError(f"Missing paper file: {path}")

    df = read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"{model} paper nemá date stĺpec.")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    required = ["strategy_return", "base_return", "btc_return", "executed_regime", "executed_position"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        legacy_required = ["strategy_return", "base_return", "btc_return", "final_regime", "final_position"]
        legacy_missing = [c for c in legacy_required if c not in df.columns]
        if legacy_missing:
            raise ValueError(f"{model} paper nemá required stĺpce: {missing}")
        df["executed_regime"] = df["final_regime"]
        df["executed_position"] = df["final_position"]

    for c in ["strategy_return", "base_return", "btc_return"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["executed_regime"] = df["executed_regime"].astype(str).fillna("NA")
    df["executed_position"] = df["executed_position"].astype(str).fillna("NA")
    return df


def build_lagged_returns(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["lag1_regime"] = x["executed_regime"].shift(1).fillna("CASH")
    x["lag1_position"] = x["executed_position"].shift(1).fillna("CASH")

    x["lag1_strategy_return"] = np.where(
        x["lag1_regime"].eq("BTC"),
        x["btc_return"],
        np.where(
            x["lag1_regime"].eq("CASH"),
            0.0,
            x["base_return"],
        ),
    )
    x["lag1_strategy_return"] = pd.to_numeric(x["lag1_strategy_return"], errors="coerce").fillna(0.0)
    return x


def detect_switch_alignment(df: pd.DataFrame) -> dict:
    x = df.copy()
    x["switch"] = x["executed_regime"].ne(x["executed_regime"].shift(1)).fillna(False)
    sw = x[x["switch"]].copy()

    if sw.empty:
        return {
            "switch_days": np.nan,
            "avg_same_day_return_on_switch_pct": np.nan,
            "median_same_day_return_on_switch_pct": np.nan,
            "avg_next_day_return_after_switch_pct": np.nan,
            "median_next_day_return_after_switch_pct": np.nan,
        }

    next_day = x["strategy_return"].shift(-1)
    return {
        "switch_days": int(len(sw)),
        "avg_same_day_return_on_switch_pct": float(sw["strategy_return"].mean() * 100.0),
        "median_same_day_return_on_switch_pct": float(sw["strategy_return"].median() * 100.0),
        "avg_next_day_return_after_switch_pct": float(next_day.loc[sw.index].mean() * 100.0),
        "median_next_day_return_after_switch_pct": float(next_day.loc[sw.index].median() * 100.0),
    }


def pick_models(summary: pd.DataFrame, top_n: int = 3) -> list[str]:
    if "model" not in summary.columns:
        raise ValueError("Summary nemá model stĺpec.")
    ordered = summary["model"].astype(str).tolist()

    out: list[str] = []
    for model in ordered:
        if model not in out:
            out.append(model)
        if len(out) >= top_n:
            break

    if PHASE61_WINNER not in out:
        out.append(PHASE61_WINNER)

    return out


def ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out


def summarize_model(model: str, summary_row: dict | None) -> dict:
    out = {
        "model": model,
        "paper_file": str(model_paper_path(model)),
        "error": "",
        "rows": np.nan,
        "start_date": "",
        "end_date": "",
        "lag1_total_return_pct": np.nan,
        "lag1_cagr_pct": np.nan,
        "lag1_max_drawdown_pct": np.nan,
        "lag1_sharpe": np.nan,
        "lag1_sortino": np.nan,
        "lag1_cash_days_pct": np.nan,
        "lag1_btc_days_pct": np.nan,
        "lag1_base_days_pct": np.nan,
        "lag1_since2021_cagr_pct": np.nan,
        "lag1_since2023_cagr_pct": np.nan,
        "lag1_since2025_cagr_pct": np.nan,
        "lag_penalty_cagr_pct": np.nan,
        "lag_penalty_since2023_cagr_pct": np.nan,
        "lag_penalty_since2025_cagr_pct": np.nan,
        "max_abs_strategy_return_pct": np.nan,
        "max_abs_base_return_pct": np.nan,
        "max_abs_btc_return_pct": np.nan,
        "missing_strategy_return": np.nan,
        "missing_base_return": np.nan,
        "missing_btc_return": np.nan,
        "switch_days": np.nan,
        "avg_same_day_return_on_switch_pct": np.nan,
        "avg_next_day_return_after_switch_pct": np.nan,
    }

    if summary_row is not None:
        for src, dst in [
            ("cagr_pct", "same_day_cagr_pct"),
            ("max_drawdown_pct", "same_day_max_drawdown_pct"),
            ("since2021_cagr_pct", "same_day_since2021_cagr_pct"),
            ("since2023_cagr_pct", "same_day_since2023_cagr_pct"),
            ("since2025_cagr_pct", "same_day_since2025_cagr_pct"),
            ("cash_days_pct", "same_day_cash_days_pct"),
            ("btc_days_pct", "same_day_btc_days_pct"),
            ("base_days_pct", "same_day_base_days_pct"),
            ("sharpe", "same_day_sharpe"),
            ("sortino", "same_day_sortino"),
            ("total_return_pct", "same_day_total_return_pct"),
            ("trade_count", "same_day_trade_count"),
        ]:
            out[dst] = summary_row.get(src, np.nan)
    else:
        for dst in [
            "same_day_cagr_pct",
            "same_day_max_drawdown_pct",
            "same_day_since2021_cagr_pct",
            "same_day_since2023_cagr_pct",
            "same_day_since2025_cagr_pct",
            "same_day_cash_days_pct",
            "same_day_btc_days_pct",
            "same_day_base_days_pct",
            "same_day_sharpe",
            "same_day_sortino",
            "same_day_total_return_pct",
            "same_day_trade_count",
        ]:
            out[dst] = np.nan

    try:
        paper = load_paper(model)
        lagged = build_lagged_returns(paper)

        lag1 = calc_metrics_from_returns(lagged, "lag1_strategy_return", "lag1_regime")
        lag1.update(window_metrics(lagged, "lag1_strategy_return", "lag1_regime", "2021-01-01"))
        lag1.update(window_metrics(lagged, "lag1_strategy_return", "lag1_regime", "2023-01-01"))
        lag1.update(window_metrics(lagged, "lag1_strategy_return", "lag1_regime", "2025-01-01"))

        align = detect_switch_alignment(paper)

        out.update({
            "rows": int(len(paper)),
            "start_date": paper["date"].min().date().isoformat(),
            "end_date": paper["date"].max().date().isoformat(),
            "lag1_total_return_pct": lag1["total_return_pct"],
            "lag1_cagr_pct": lag1["cagr_pct"],
            "lag1_max_drawdown_pct": lag1["max_drawdown_pct"],
            "lag1_sharpe": lag1["sharpe"],
            "lag1_sortino": lag1["sortino"],
            "lag1_cash_days_pct": lag1.get("cash_days_pct"),
            "lag1_btc_days_pct": lag1.get("btc_days_pct"),
            "lag1_base_days_pct": lag1.get("base_days_pct"),
            "lag1_since2021_cagr_pct": lag1.get("since2021_cagr_pct"),
            "lag1_since2023_cagr_pct": lag1.get("since2023_cagr_pct"),
            "lag1_since2025_cagr_pct": lag1.get("since2025_cagr_pct"),
            "lag_penalty_cagr_pct": pd.to_numeric(lag1["cagr_pct"], errors="coerce") - pd.to_numeric(out.get("same_day_cagr_pct"), errors="coerce"),
            "lag_penalty_since2023_cagr_pct": pd.to_numeric(lag1.get("since2023_cagr_pct"), errors="coerce") - pd.to_numeric(out.get("same_day_since2023_cagr_pct"), errors="coerce"),
            "lag_penalty_since2025_cagr_pct": pd.to_numeric(lag1.get("since2025_cagr_pct"), errors="coerce") - pd.to_numeric(out.get("same_day_since2025_cagr_pct"), errors="coerce"),
            "max_abs_strategy_return_pct": float(paper["strategy_return"].abs().max() * 100.0),
            "max_abs_base_return_pct": float(paper["base_return"].abs().max() * 100.0),
            "max_abs_btc_return_pct": float(paper["btc_return"].abs().max() * 100.0),
            "missing_strategy_return": int(paper["strategy_return"].isna().sum()),
            "missing_base_return": int(paper["base_return"].isna().sum()),
            "missing_btc_return": int(paper["btc_return"].isna().sum()),
            **align,
        })
    except Exception as e:
        out["error"] = str(e)

    return out


def add_delta_cols(df: pd.DataFrame, ref_row: dict | None, prefix: str) -> pd.DataFrame:
    out = df.copy()

    required = [
        "same_day_cagr_pct",
        "lag1_cagr_pct",
        "same_day_since2023_cagr_pct",
        "lag1_since2023_cagr_pct",
        "same_day_since2025_cagr_pct",
        "lag1_since2025_cagr_pct",
    ]
    out = ensure_columns(out, required)

    if ref_row is None:
        for c in [
            f"delta_vs_{prefix}_same_day_cagr_pct",
            f"delta_vs_{prefix}_lag1_cagr_pct",
            f"delta_vs_{prefix}_same_day_since2023_cagr_pct",
            f"delta_vs_{prefix}_lag1_since2023_cagr_pct",
            f"delta_vs_{prefix}_same_day_since2025_cagr_pct",
            f"delta_vs_{prefix}_lag1_since2025_cagr_pct",
        ]:
            out[c] = np.nan
        return out

    ref_cagr = pd.to_numeric(ref_row.get("cagr_pct"), errors="coerce")
    ref_since2023 = pd.to_numeric(ref_row.get("since2023_cagr_pct"), errors="coerce")
    ref_since2025 = pd.to_numeric(ref_row.get("since2025_cagr_pct"), errors="coerce")

    out[f"delta_vs_{prefix}_same_day_cagr_pct"] = pd.to_numeric(out["same_day_cagr_pct"], errors="coerce") - ref_cagr
    out[f"delta_vs_{prefix}_lag1_cagr_pct"] = pd.to_numeric(out["lag1_cagr_pct"], errors="coerce") - ref_cagr
    out[f"delta_vs_{prefix}_same_day_since2023_cagr_pct"] = pd.to_numeric(out["same_day_since2023_cagr_pct"], errors="coerce") - ref_since2023
    out[f"delta_vs_{prefix}_lag1_since2023_cagr_pct"] = pd.to_numeric(out["lag1_since2023_cagr_pct"], errors="coerce") - ref_since2023
    out[f"delta_vs_{prefix}_same_day_since2025_cagr_pct"] = pd.to_numeric(out["same_day_since2025_cagr_pct"], errors="coerce") - ref_since2025
    out[f"delta_vs_{prefix}_lag1_since2025_cagr_pct"] = pd.to_numeric(out["lag1_since2025_cagr_pct"], errors="coerce") - ref_since2025
    return out


def main() -> None:
    log("[PHASE62 FORENSIC] Start")

    manifest = load_manifest()
    summary = load_summary()
    compare = load_compare()

    models = pick_models(summary, top_n=3)
    log(f"[PHASE62 FORENSIC] Models: {models}")

    rows = []
    for model in models:
        summary_row = get_row_by_model(summary, model)
        rows.append(summarize_model(model, summary_row))

    forensic = pd.DataFrame(rows)

    forensic = ensure_columns(
        forensic,
        [
            "same_day_cagr_pct",
            "lag1_cagr_pct",
            "same_day_since2023_cagr_pct",
            "lag1_since2023_cagr_pct",
            "same_day_since2025_cagr_pct",
            "lag1_since2025_cagr_pct",
            "same_day_max_drawdown_pct",
            "lag1_max_drawdown_pct",
            "same_day_btc_days_pct",
            "same_day_cash_days_pct",
            "switch_days",
            "avg_same_day_return_on_switch_pct",
            "avg_next_day_return_after_switch_pct",
            "error",
        ],
    )

    baseline_row = get_row_by_model(compare, LATEST_BASELINE)
    phase61_row = get_row_by_model(compare, PHASE61_WINNER)

    forensic = add_delta_cols(forensic, baseline_row, "phase42_core")
    forensic = add_delta_cols(forensic, phase61_row, "phase61")

    forensic_path = PHASE62_DIR / "phase62_forensic_check.csv"
    forensic.to_csv(forensic_path, index=False)

    out_manifest = {
        "phase": "phase62_forensic_check",
        "winner_input_key": manifest.get("winner_input_key"),
        "baseline_key": manifest.get("baseline_key"),
        "checked_models": models,
        "forensic_file": str(forensic_path),
    }
    out_manifest_path = PHASE62_DIR / "phase62_forensic_manifest.json"
    out_manifest_path.write_text(json.dumps(out_manifest, indent=2), encoding="utf-8")

    cols = [
        "model",
        "same_day_cagr_pct",
        "lag1_cagr_pct",
        "lag_penalty_cagr_pct",
        "same_day_since2023_cagr_pct",
        "lag1_since2023_cagr_pct",
        "lag_penalty_since2023_cagr_pct",
        "same_day_since2025_cagr_pct",
        "lag1_since2025_cagr_pct",
        "lag_penalty_since2025_cagr_pct",
        "same_day_max_drawdown_pct",
        "lag1_max_drawdown_pct",
        "same_day_btc_days_pct",
        "same_day_cash_days_pct",
        "switch_days",
        "avg_same_day_return_on_switch_pct",
        "avg_next_day_return_after_switch_pct",
        "delta_vs_phase42_core_same_day_cagr_pct",
        "delta_vs_phase42_core_lag1_cagr_pct",
        "delta_vs_phase61_same_day_cagr_pct",
        "delta_vs_phase61_lag1_cagr_pct",
        "error",
    ]
    cols = [c for c in cols if c in forensic.columns]

    log("")
    log("=== PHASE62 FORENSIC TOP VIEW ===")
    print(forensic[cols].to_string(index=False))

    bad = forensic[forensic["error"].astype(str).str.len() > 0].copy()
    if not bad.empty:
        log("")
        log("=== PHASE62 FORENSIC ERRORS ===")
        print(bad[["model", "error"]].to_string(index=False))

    log("")
    log(f"[PHASE62 FORENSIC] Saved -> {forensic_path}")
    log(f"[PHASE62 FORENSIC] Saved -> {out_manifest_path}")


if __name__ == "__main__":
    main()