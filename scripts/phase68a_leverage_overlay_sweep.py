from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

PHASE66G_PAPER = (
    OUTPUTS
    / "phase66g_production_candidate_live"
    / "phase66g_production_soft_filters_paper.csv"
)

PHASE68A_DIR = OUTPUTS / "phase68a_leverage_overlay_sweep"


@dataclass(frozen=True)
class LeverageVariant:
    model: str
    leverage: float


VARIANTS: list[LeverageVariant] = [
    LeverageVariant(model="phase68a_66g_1p00x", leverage=1.00),
    LeverageVariant(model="phase68a_66g_1p10x", leverage=1.10),
    LeverageVariant(model="phase68a_66g_1p25x", leverage=1.25),
    LeverageVariant(model="phase68a_66g_1p35x", leverage=1.35),
    LeverageVariant(model="phase68a_66g_1p50x", leverage=1.50),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def pick_col(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    lower_map = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    raise KeyError(f"Chýba required column pre {label}. Kandidáti: {candidates}")


def normalize_paper(df: pd.DataFrame) -> pd.DataFrame:
    ts_col = pick_col(df, ["date", "ts", "datetime", "timestamp"], "date")
    ret_col = pick_col(
        df,
        ["strategy_ret", "daily_ret", "ret", "return", "strategy_return", "portfolio_ret", "equity_ret"],
        "strategy_ret",
    )

    asset_col = None
    asset_candidates = [
        "chosen_asset",
        "held_asset_public",
        "selected_asset",
        "asset",
        "weekly_authorized_asset",
        "current_asset",
    ]
    lower_map = {str(c).lower(): c for c in df.columns}
    for c in asset_candidates:
        if c.lower() in lower_map:
            asset_col = lower_map[c.lower()]
            break

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[ts_col], errors="coerce").dt.tz_localize(None)
    out["strategy_ret"] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)

    if asset_col is not None:
        out["asset"] = df[asset_col].astype(str).fillna("")
    else:
        out["asset"] = ""

    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return out


def normalize_asset_label(raw: str) -> str:
    s = str(raw).strip().upper()
    if s in {"", "NAN", "NONE", "NULL", "BASELINE", "CORE"}:
        return "CASH"
    return s


def add_exposure_flags(paper: pd.DataFrame) -> pd.DataFrame:
    out = paper.copy()
    out["held_asset"] = out["asset"].apply(normalize_asset_label)
    out["is_exposed"] = ~out["held_asset"].isin(["CASH", "USD", "USDT"])
    return out


def apply_leverage_overlay(
    paper: pd.DataFrame,
    leverage: float,
    annual_borrow_cost: float,
) -> pd.DataFrame:
    out = paper.copy()

    borrowed_fraction = max(leverage - 1.0, 0.0)
    daily_borrow_cost = annual_borrow_cost / 365.25

    out["leverage"] = float(leverage)
    out["borrowed_fraction"] = float(borrowed_fraction)
    out["daily_borrow_cost"] = np.where(
        out["is_exposed"],
        borrowed_fraction * daily_borrow_cost,
        0.0,
    )

    out["leveraged_ret_gross"] = out["strategy_ret"] * float(leverage)
    out["leveraged_ret"] = out["leveraged_ret_gross"] - out["daily_borrow_cost"]

    # ochrana proti nevalidnej equity sérii
    out["leveraged_ret"] = out["leveraged_ret"].clip(lower=-0.999999)

    out["equity_curve"] = (1.0 + out["leveraged_ret"]).cumprod()
    return out


def compute_cagr_pct(ret_series: pd.Series, date_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    start_dt = pd.to_datetime(date_series.iloc[0])
    end_dt = pd.to_datetime(date_series.iloc[-1])
    days = max((end_dt - start_dt).days, 1)
    years = days / 365.25
    if years <= 0:
        return np.nan
    cagr = (eq.iloc[-1] ** (1.0 / years)) - 1.0
    return float(cagr * 100.0)


def compute_max_drawdown_pct(ret_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min() * 100.0)


def subset_since(df: pd.DataFrame, start_date: str) -> pd.DataFrame:
    start_ts = pd.Timestamp(start_date)
    return df.loc[df["date"] >= start_ts].copy().reset_index(drop=True)


def summarize_variant(model: str, paper: pd.DataFrame) -> dict:
    since2023 = subset_since(paper, "2023-01-01")
    since2025 = subset_since(paper, "2025-01-01")

    held = paper["held_asset"].astype(str)
    exposed = paper["is_exposed"].astype(bool)

    switch_count = int((held != held.shift(1)).sum() - 1) if len(held) else 0

    return {
        "model": model,
        "leverage": float(paper["leverage"].iloc[0]),
        "annual_borrow_cost_pct": float(paper["daily_borrow_cost"].max() * 365.25 * 100.0),
        "cagr_pct": round(compute_cagr_pct(paper["leveraged_ret"], paper["date"]), 2),
        "max_drawdown_pct": round(compute_max_drawdown_pct(paper["leveraged_ret"]), 2),
        "since2023_cagr_pct": round(compute_cagr_pct(since2023["leveraged_ret"], since2023["date"]), 2)
        if not since2023.empty
        else np.nan,
        "since2025_cagr_pct": round(compute_cagr_pct(since2025["leveraged_ret"], since2025["date"]), 2)
        if not since2025.empty
        else np.nan,
        "selection_count": int(exposed.sum()),
        "switch_count": int(max(switch_count, 0)),
        "unique_selected_assets": int(held[held != "CASH"].nunique()),
        "latest_available_date": paper["date"].max().strftime("%Y-%m-%d") if not paper.empty else "",
        "held_asset_now": str(held.iloc[-1]) if not paper.empty else "",
    }


def add_delta_cols(row: dict, ref: dict) -> dict:
    out = row.copy()
    for metric in ["cagr_pct", "max_drawdown_pct", "since2023_cagr_pct", "since2025_cagr_pct"]:
        out[f"delta_vs_1p00x_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(ref.get(metric), errors="coerce")
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE68A leverage overlay sweep over current 66G paper")
    parser.add_argument("--paper", type=str, default=str(PHASE66G_PAPER))
    parser.add_argument("--annual-borrow-cost", type=float, default=0.0)
    args = parser.parse_args()

    ensure_dir(PHASE68A_DIR)
    papers_dir = PHASE68A_DIR / "papers"
    ensure_dir(papers_dir)

    paper_path = Path(args.paper)
    if not paper_path.exists():
        raise FileNotFoundError(f"Paper sa nenašiel: {paper_path}")

    log("[PHASE68A] Start")
    log(f"[PHASE68A] Input paper: {paper_path}")
    log(f"[PHASE68A] Annual borrow cost: {args.annual_borrow_cost:.4f}")

    base_raw = pd.read_csv(paper_path)
    base_paper = normalize_paper(base_raw)
    base_paper = add_exposure_flags(base_paper)

    summary_rows: list[dict] = []
    leveraged_papers: dict[str, pd.DataFrame] = {}

    for variant in VARIANTS:
        log(f"[PHASE68A] running {variant.model} | leverage={variant.leverage:.2f}x")

        lev_paper = apply_leverage_overlay(
            paper=base_paper,
            leverage=variant.leverage,
            annual_borrow_cost=float(args.annual_borrow_cost),
        )

        leveraged_papers[variant.model] = lev_paper
        summary_rows.append(summarize_variant(variant.model, lev_paper))

        save_df = lev_paper.copy()
        save_df.to_csv(papers_dir / f"{variant.model}_paper.csv", index=False)

        log(f"[PHASE68A] done {variant.model}")

    summary_df = pd.DataFrame(summary_rows)
    baseline_row = summary_df.loc[summary_df["model"] == "phase68a_66g_1p00x"]
    if baseline_row.empty:
        raise ValueError("Chýba baseline row phase68a_66g_1p00x")
    baseline = baseline_row.iloc[0].to_dict()

    compare_rows = [add_delta_cols(row, baseline) for row in summary_rows]
    compare_df = pd.DataFrame(compare_rows)

    compare_df = compare_df.sort_values(
        by=[
            "since2025_cagr_pct",
            "cagr_pct",
            "max_drawdown_pct",
        ],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    top = compare_df.iloc[0].to_dict()

    summary_path = PHASE68A_DIR / "phase68a_leverage_summary.csv"
    compare_path = PHASE68A_DIR / "phase68a_leverage_compare.csv"
    manifest_path = PHASE68A_DIR / "phase68a_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)

    manifest = {
        "phase": "phase68a_leverage_overlay_sweep",
        "input_paper": str(paper_path),
        "annual_borrow_cost": float(args.annual_borrow_cost),
        "variants": [asdict(v) for v in VARIANTS],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "papers_dir": str(papers_dir),
        "notes": [
            "Synthetic leverage overlay nad current 66G paperom.",
            "Nemení signal/logiku/universe/governance.",
            "Funding/liquidation/slippage nie sú v tomto v1 modele explicitne simulované.",
            "Cieľ je zistiť first-order effect 1.10x/1.25x/1.35x/1.50x na current 66G line.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE68A TOP RESULT ===")
    log(f"model: {top['model']}")
    log(f"leverage: {float(top['leverage']):.2f}x")
    log(f"cagr_pct: {float(top['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(top['max_drawdown_pct']):.2f}")
    log(f"since2023_cagr_pct: {float(top['since2023_cagr_pct']):.2f}")
    log(f"since2025_cagr_pct: {float(top['since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_cagr_pct: {float(top['delta_vs_1p00x_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_since2023_cagr_pct: {float(top['delta_vs_1p00x_since2023_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_since2025_cagr_pct: {float(top['delta_vs_1p00x_since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_max_drawdown_pct: {float(top['delta_vs_1p00x_max_drawdown_pct']):.2f}")
    log(f"selection_count: {int(pd.to_numeric(top.get('selection_count'), errors='coerce'))}")
    log(f"switch_count: {int(pd.to_numeric(top.get('switch_count'), errors='coerce'))}")
    log(f"held_asset_now: {top['held_asset_now']}")
    log("")

    log(f"[PHASE68A] Saved summary -> {summary_path}")
    log(f"[PHASE68A] Saved compare -> {compare_path}")
    log(f"[PHASE68A] Saved manifest -> {manifest_path}")
    log(f"[PHASE68A] Saved papers -> {papers_dir}")


if __name__ == "__main__":
    main()