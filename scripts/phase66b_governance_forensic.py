from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

PHASE66_DIR = OUTPUTS / "phase66_weekly_asset_governance"
BASELINE_PAPER = PHASE66_DIR / "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3_paper.csv"
GOVERNANCE_PAPER = PHASE66_DIR / "phase66_weekly_asset_governance_paper.csv"

OUT_DIR = OUTPUTS / "phase66b_governance_forensic"


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def load_paper(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path)
    df = normalize_columns(df)

    if "date" not in df.columns:
        raise ValueError(f"{path.name}: missing date column")
    if "strategy_return" not in df.columns:
        raise ValueError(f"{path.name}: missing strategy_return column")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["strategy_return"] = pd.to_numeric(df["strategy_return"], errors="coerce").fillna(0.0)

    for col in ["chosen_asset", "weekly_authorized_asset", "executed_position", "executed_regime"]:
        if col in df.columns:
            df[col] = df[col].astype(str).fillna("")

    df = (
        df.dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
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
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def calc_return_metrics(returns: pd.Series) -> dict:
    x = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if len(x) == 0:
        return {
            "days": 0,
            "total_return_pct": np.nan,
            "cagr_pct": np.nan,
            "max_drawdown_pct": np.nan,
        }
    eq = (1.0 + x).cumprod()
    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    cagr = annualize_return(total_return, len(eq))
    max_dd = max_drawdown_from_equity(eq)
    return {
        "days": int(len(eq)),
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
    }


def merge_papers(baseline: pd.DataFrame, governance: pd.DataFrame) -> pd.DataFrame:
    keep_cols = ["date", "strategy_return"]
    base = baseline[keep_cols].rename(columns={"strategy_return": "baseline_return"}).copy()

    gov_cols = ["date", "strategy_return"]
    optional_cols = ["chosen_asset", "weekly_authorized_asset", "executed_position", "executed_regime"]
    for col in optional_cols:
        if col in governance.columns:
            gov_cols.append(col)

    gov = governance[gov_cols].rename(columns={"strategy_return": "governance_return"}).copy()

    df = base.merge(gov, on="date", how="inner")
    df["baseline_return"] = pd.to_numeric(df["baseline_return"], errors="coerce").fillna(0.0)
    df["governance_return"] = pd.to_numeric(df["governance_return"], errors="coerce").fillna(0.0)
    df["delta_return"] = df["governance_return"] - df["baseline_return"]

    if "chosen_asset" not in df.columns:
        df["chosen_asset"] = ""
    if "weekly_authorized_asset" not in df.columns:
        df["weekly_authorized_asset"] = ""

    df["chosen_asset"] = df["chosen_asset"].astype(str).replace("nan", "")
    df["weekly_authorized_asset"] = df["weekly_authorized_asset"].astype(str).replace("nan", "")
    return df


def get_asset_column(df: pd.DataFrame) -> str:
    if "chosen_asset" in df.columns and (df["chosen_asset"].astype(str) != "").any():
        return "chosen_asset"
    if "weekly_authorized_asset" in df.columns and (df["weekly_authorized_asset"].astype(str) != "").any():
        return "weekly_authorized_asset"
    raise ValueError("Governance paper nemá usable chosen asset column.")


def subset_metrics(df: pd.DataFrame, mask: pd.Series) -> dict:
    sub = df.loc[mask].copy()
    gov = calc_return_metrics(sub["governance_return"])
    base = calc_return_metrics(sub["baseline_return"])

    return {
        "days": int(len(sub)),
        "gov_total_return_pct": gov["total_return_pct"],
        "gov_cagr_pct": gov["cagr_pct"],
        "gov_max_drawdown_pct": gov["max_drawdown_pct"],
        "base_total_return_pct": base["total_return_pct"],
        "base_cagr_pct": base["cagr_pct"],
        "base_max_drawdown_pct": base["max_drawdown_pct"],
        "delta_total_return_pct": (
            pd.to_numeric(gov["total_return_pct"], errors="coerce")
            - pd.to_numeric(base["total_return_pct"], errors="coerce")
        ),
        "delta_cagr_pct": (
            pd.to_numeric(gov["cagr_pct"], errors="coerce")
            - pd.to_numeric(base["cagr_pct"], errors="coerce")
        ),
        "delta_max_drawdown_pct": (
            pd.to_numeric(gov["max_drawdown_pct"], errors="coerce")
            - pd.to_numeric(base["max_drawdown_pct"], errors="coerce")
        ),
    }


def split_asset_windows(df: pd.DataFrame, asset_col: str) -> pd.DataFrame:
    x = df.copy()
    x["asset_active"] = x[asset_col].astype(str).fillna("")
    active = x["asset_active"] != ""
    x["group_break"] = (x["asset_active"] != x["asset_active"].shift(1)) | (~active)
    x["window_id"] = x["group_break"].cumsum()

    rows = []
    for _, sub in x[active].groupby(["asset_active", "window_id"], sort=False):
        asset = str(sub["asset_active"].iloc[0])
        gov = calc_return_metrics(sub["governance_return"])
        base = calc_return_metrics(sub["baseline_return"])

        rows.append(
            {
                "asset": asset,
                "start_date": sub["date"].iloc[0].strftime("%Y-%m-%d"),
                "end_date": sub["date"].iloc[-1].strftime("%Y-%m-%d"),
                "days": int(len(sub)),
                "gov_total_return_pct": gov["total_return_pct"],
                "base_total_return_pct": base["total_return_pct"],
                "delta_total_return_pct": (
                    pd.to_numeric(gov["total_return_pct"], errors="coerce")
                    - pd.to_numeric(base["total_return_pct"], errors="coerce")
                ),
                "avg_daily_delta_pct": float(sub["delta_return"].mean() * 100.0),
                "sum_daily_delta_pct": float(sub["delta_return"].sum() * 100.0),
            }
        )

    return pd.DataFrame(rows)


def classify_asset(row: pd.Series) -> str:
    s23 = pd.to_numeric(row.get("since2023_delta_total_return_pct"), errors="coerce")
    s25 = pd.to_numeric(row.get("since2025_delta_total_return_pct"), errors="coerce")
    pos_windows = pd.to_numeric(row.get("positive_window_pct"), errors="coerce")
    days = pd.to_numeric(row.get("selected_days"), errors="coerce")

    if pd.isna(days) or days <= 0:
        return "NO_DATA"
    if pd.notna(s23) and pd.notna(s25) and s23 > 0 and s25 >= 0 and (pd.isna(pos_windows) or pos_windows >= 50):
        return "KEEP"
    if pd.notna(s23) and s23 > 0 and (pd.isna(s25) or s25 < 0):
        return "WATCH_2025"
    if pd.notna(s23) and s23 <= 0 and pd.notna(s25) and s25 <= 0:
        return "REMOVE"
    return "WATCH"


def main() -> None:
    ensure_dir(OUT_DIR)

    log("[PHASE66B] Start")

    baseline = load_paper(BASELINE_PAPER)
    governance = load_paper(GOVERNANCE_PAPER)
    df = merge_papers(baseline, governance)
    asset_col = get_asset_column(df)

    log(f"[PHASE66B] Using asset column: {asset_col}")

    overall_mask = df[asset_col].astype(str) != ""
    since2023_mask = overall_mask & (df["date"] >= pd.Timestamp("2023-01-01"))
    since2025_mask = overall_mask & (df["date"] >= pd.Timestamp("2025-01-01"))

    overall_selected = subset_metrics(df, overall_mask)
    since2023_selected = subset_metrics(df, since2023_mask)
    since2025_selected = subset_metrics(df, since2025_mask)

    asset_rows = []
    active_assets = sorted([x for x in df[asset_col].astype(str).unique().tolist() if x])

    for asset in active_assets:
        mask_all = df[asset_col].astype(str) == asset
        mask_2023 = mask_all & (df["date"] >= pd.Timestamp("2023-01-01"))
        mask_2025 = mask_all & (df["date"] >= pd.Timestamp("2025-01-01"))

        row = {"asset": asset, "selected_days": int(mask_all.sum()), "selected_days_pct": float(mask_all.mean() * 100.0)}
        row.update({f"all_{k}": v for k, v in subset_metrics(df, mask_all).items()})
        row["since2023_days"] = int(mask_2023.sum())
        row["since2025_days"] = int(mask_2025.sum())

        m2023 = subset_metrics(df, mask_2023)
        m2025 = subset_metrics(df, mask_2025)

        row["since2023_delta_total_return_pct"] = m2023["delta_total_return_pct"]
        row["since2023_delta_cagr_pct"] = m2023["delta_cagr_pct"]
        row["since2023_delta_max_drawdown_pct"] = m2023["delta_max_drawdown_pct"]

        row["since2025_delta_total_return_pct"] = m2025["delta_total_return_pct"]
        row["since2025_delta_cagr_pct"] = m2025["delta_cagr_pct"]
        row["since2025_delta_max_drawdown_pct"] = m2025["delta_max_drawdown_pct"]

        asset_rows.append(row)

    asset_summary = pd.DataFrame(asset_rows)

    windows = split_asset_windows(df, asset_col)
    if not windows.empty:
        win_stats = (
            windows.groupby("asset", as_index=False)
            .agg(
                window_count=("asset", "size"),
                avg_window_delta_total_return_pct=("delta_total_return_pct", "mean"),
                median_window_delta_total_return_pct=("delta_total_return_pct", "median"),
                positive_window_count=("delta_total_return_pct", lambda s: int((pd.to_numeric(s, errors="coerce") > 0).sum())),
                negative_window_count=("delta_total_return_pct", lambda s: int((pd.to_numeric(s, errors="coerce") < 0).sum())),
                best_window_delta_total_return_pct=("delta_total_return_pct", "max"),
                worst_window_delta_total_return_pct=("delta_total_return_pct", "min"),
            )
        )
        win_stats["positive_window_pct"] = np.where(
            win_stats["window_count"] > 0,
            win_stats["positive_window_count"] / win_stats["window_count"] * 100.0,
            np.nan,
        )
        asset_summary = asset_summary.merge(win_stats, on="asset", how="left")

    if not asset_summary.empty:
        asset_summary["verdict"] = asset_summary.apply(classify_asset, axis=1)
        asset_summary = asset_summary.sort_values(
            by=[
                "since2023_delta_total_return_pct",
                "all_delta_total_return_pct",
                "since2025_delta_total_return_pct",
                "positive_window_pct",
            ],
            ascending=[False, False, False, False],
            na_position="last",
        ).reset_index(drop=True)

    top_keep_watch = asset_summary[asset_summary["verdict"].isin(["KEEP", "WATCH_2025", "WATCH"])].copy() if not asset_summary.empty else pd.DataFrame()
    drop_candidates = asset_summary[asset_summary["verdict"] == "REMOVE"].copy() if not asset_summary.empty else pd.DataFrame()

    summary_rows = [
        {
            "scope": "selected_days_all_assets",
            **overall_selected,
        },
        {
            "scope": "selected_days_since2023",
            **since2023_selected,
        },
        {
            "scope": "selected_days_since2025",
            **since2025_selected,
        },
    ]
    high_level = pd.DataFrame(summary_rows)

    high_level_path = OUT_DIR / "phase66b_governance_forensic_summary.csv"
    asset_summary_path = OUT_DIR / "phase66b_governance_asset_summary.csv"
    windows_path = OUT_DIR / "phase66b_governance_asset_windows.csv"
    keep_watch_path = OUT_DIR / "phase66b_governance_keep_watch.csv"
    drop_path = OUT_DIR / "phase66b_governance_drop_candidates.csv"
    manifest_path = OUT_DIR / "phase66b_manifest.json"

    high_level.to_csv(high_level_path, index=False)
    asset_summary.to_csv(asset_summary_path, index=False)
    windows.to_csv(windows_path, index=False)
    top_keep_watch.to_csv(keep_watch_path, index=False)
    drop_candidates.to_csv(drop_path, index=False)

    manifest = {
        "phase": "phase66b_governance_forensic",
        "baseline_paper": str(BASELINE_PAPER),
        "governance_paper": str(GOVERNANCE_PAPER),
        "asset_column_used": asset_col,
        "summary_file": str(high_level_path),
        "asset_summary_file": str(asset_summary_path),
        "windows_file": str(windows_path),
        "keep_watch_file": str(keep_watch_path),
        "drop_candidates_file": str(drop_path),
        "notes": [
            "Forenzná analýza governance výberov.",
            "Cieľ: zistiť ktoré assety reálne pomáhali a ktoré škodili.",
            "Výstup je určený ako vstup pre ďalší pruned governance phase.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE66B TOP RESULT ===")
    if asset_summary.empty:
        log("No active governance assets found.")
    else:
        best = asset_summary.iloc[0]
        log(f"asset: {best['asset']}")
        log(f"selected_days: {int(best['selected_days'])}")
        log(f"since2023_delta_total_return_pct: {best['since2023_delta_total_return_pct']:.2f}")
        log(f"since2025_delta_total_return_pct: {best['since2025_delta_total_return_pct']:.2f}")
        log(f"avg_window_delta_total_return_pct: {best.get('avg_window_delta_total_return_pct', np.nan):.2f}")
        log(f"positive_window_pct: {best.get('positive_window_pct', np.nan):.2f}")
        log(f"verdict: {best['verdict']}")
        log("")

    if not drop_candidates.empty:
        log("=== PHASE66B DROP CANDIDATES ===")
        for _, row in drop_candidates.head(5).iterrows():
            log(
                f"{row['asset']}: s2023={row['since2023_delta_total_return_pct']:.2f}, "
                f"s2025={row['since2025_delta_total_return_pct']:.2f}, verdict={row['verdict']}"
            )
        log("")

    log(f"[PHASE66B] Saved summary -> {high_level_path}")
    log(f"[PHASE66B] Saved asset summary -> {asset_summary_path}")
    log(f"[PHASE66B] Saved windows -> {windows_path}")
    log(f"[PHASE66B] Saved keep/watch -> {keep_watch_path}")
    log(f"[PHASE66B] Saved drop candidates -> {drop_path}")
    log(f"[PHASE66B] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()