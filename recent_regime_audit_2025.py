from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"

SUMMARY_PATH = OUTPUTS / "phase46_final_compare_pruned_summary.csv"
EQUITY_PATH = OUTPUTS / "phase46_final_compare_pruned_equity_curves.csv"
AUDIT_DIR = OUTPUTS / "recent_regime_audit_2025"

AUDIT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = "2025-01-01"
TRADING_DAYS_PER_YEAR = 365.25

MODEL_ORDER = [
    "old_baseline",
    "phase42_full12",
    "phase45_without_BNBUSDT",
    "phase45_without_BNBUSDT_and_DOGEUSDT",
]

MODEL_LABELS = {
    "old_baseline": "Starsia verzia",
    "phase42_full12": "Predosly lider",
    "phase45_without_BNBUSDT": "Hlavna strategia",
    "phase45_without_BNBUSDT_and_DOGEUSDT": "Alternativna verzia",
}


def compute_metrics_from_equity(ts: pd.Series, eq: pd.Series) -> dict:
    df = pd.DataFrame({"ts": pd.to_datetime(ts), "equity": pd.to_numeric(eq, errors="coerce")})
    df = df.dropna().sort_values("ts").copy()
    if df.empty or len(df) < 2:
        return {
            "total_return_pct": None,
            "cagr_pct": None,
            "max_drawdown_pct": None,
            "worst_day_pct": None,
            "worst_3d_pct": None,
            "worst_5d_pct": None,
            "days": 0,
        }

    df["ret"] = df["equity"].pct_change().fillna(0.0)

    total_return = float(df["equity"].iloc[-1] / df["equity"].iloc[0] - 1.0)

    span_days = max((df["ts"].iloc[-1] - df["ts"].iloc[0]).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float((df["equity"].iloc[-1] / df["equity"].iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = df["equity"] / df["equity"].cummax() - 1.0
    max_dd = float(dd.min())

    r = df["ret"].copy()
    worst_day = float(r.min())

    if len(r) >= 3:
        worst_3d = float(((1.0 + r).rolling(3).apply(lambda x: x.prod(), raw=True) - 1.0).min())
    else:
        worst_3d = None

    if len(r) >= 5:
        worst_5d = float(((1.0 + r).rolling(5).apply(lambda x: x.prod(), raw=True) - 1.0).min())
    else:
        worst_5d = None

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "worst_day_pct": round(worst_day * 100.0, 2) if worst_day is not None else None,
        "worst_3d_pct": round(worst_3d * 100.0, 2) if worst_3d is not None else None,
        "worst_5d_pct": round(worst_5d * 100.0, 2) if worst_5d is not None else None,
        "days": int(len(df)),
    }


def main() -> None:
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {SUMMARY_PATH}")
    if not EQUITY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {EQUITY_PATH}")

    summary_df = pd.read_csv(SUMMARY_PATH)
    equity_df = pd.read_csv(EQUITY_PATH)
    equity_df["ts"] = pd.to_datetime(equity_df["ts"], errors="coerce")
    equity_df = equity_df.dropna(subset=["ts"]).sort_values("ts").copy()

    recent_df = equity_df.loc[equity_df["ts"] >= pd.Timestamp(START_DATE)].copy()
    if recent_df.empty:
        raise ValueError(f"No equity data found from {START_DATE}")

    rows = []
    for model in MODEL_ORDER:
        if model not in recent_df.columns:
            continue

        metrics = compute_metrics_from_equity(recent_df["ts"], recent_df[model])

        full_row = summary_df.loc[summary_df["model"] == model]
        full_cagr = float(full_row["cagr_pct"].iloc[0]) if not full_row.empty else None
        full_dd = float(full_row["max_drawdown_pct"].iloc[0]) if not full_row.empty else None

        rows.append(
            {
                "model": model,
                "label": MODEL_LABELS.get(model, model),
                **metrics,
                "full_history_cagr_pct": round(full_cagr, 2) if full_cagr is not None else None,
                "full_history_max_drawdown_pct": round(full_dd, 2) if full_dd is not None else None,
            }
        )

    out_df = pd.DataFrame(rows)

    if not out_df.empty:
        out_df["rank_total_return"] = out_df["total_return_pct"].rank(ascending=False, method="min")
        out_df["rank_cagr"] = out_df["cagr_pct"].rank(ascending=False, method="min")
        out_df["rank_max_dd"] = out_df["max_drawdown_pct"].rank(ascending=False, method="min")
        out_df = out_df.sort_values(["rank_total_return", "rank_cagr", "rank_max_dd", "label"])

    out_csv = AUDIT_DIR / "recent_regime_audit_2025_summary.csv"
    out_df.to_csv(out_csv, index=False)

    equity_export_cols = ["ts"] + [m for m in MODEL_ORDER if m in recent_df.columns]
    recent_equity_csv = AUDIT_DIR / "recent_regime_audit_2025_equity_curves.csv"
    recent_df[equity_export_cols].to_csv(recent_equity_csv, index=False)

    print("\n=== RECENT REGIME AUDIT FROM 2025-01-01 ===\n")
    print(out_df.to_string(index=False))
    print(f"\nSaved summary: {out_csv}")
    print(f"Saved recent equity curves: {recent_equity_csv}")

    main_row = out_df.loc[out_df["model"] == "phase45_without_BNBUSDT"]
    leader_row = out_df.loc[out_df["model"] == "phase42_full12"]

    if not main_row.empty and not leader_row.empty:
        main_ret = float(main_row["total_return_pct"].iloc[0])
        leader_ret = float(leader_row["total_return_pct"].iloc[0])
        main_cagr = float(main_row["cagr_pct"].iloc[0])
        leader_cagr = float(leader_row["cagr_pct"].iloc[0])
        main_dd = float(main_row["max_drawdown_pct"].iloc[0])
        leader_dd = float(leader_row["max_drawdown_pct"].iloc[0])

        print("\n=== QUICK READ ===\n")
        print(f"Hlavna strategia total return od 2025: {main_ret:.2f}%")
        print(f"Predosly lider total return od 2025: {leader_ret:.2f}%")
        print(f"Rozdiel total return: {main_ret - leader_ret:+.2f} p.b.")
        print(f"Hlavna strategia CAGR od 2025: {main_cagr:.2f}%")
        print(f"Predosly lider CAGR od 2025: {leader_cagr:.2f}%")
        print(f"Rozdiel CAGR: {main_cagr - leader_cagr:+.2f} p.b.")
        print(f"Hlavna strategia Max DD od 2025: {main_dd:.2f}%")
        print(f"Predosly lider Max DD od 2025: {leader_dd:.2f}%")
        print(f"Rozdiel Max DD: {main_dd - leader_dd:+.2f} p.b.")


if __name__ == "__main__":
    main()