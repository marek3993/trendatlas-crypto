from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

import phase66e_probation_governance as core


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

CORE_MODEL_KEY = "phase66g_production_soft_filters"
CORE_PAPER = (
    OUTPUTS
    / "phase66g_production_candidate_live"
    / f"{CORE_MODEL_KEY}_paper.csv"
)

PHASE63_MODEL_KEY = core.CURRENT_WINNER_KEY
PHASE63_PAPER = core.CURRENT_WINNER_PAPER

PHASE67B_SHORTLIST = (
    OUTPUTS
    / "phase67b_top100_forensic_prune_and_rerun"
    / "phase67b_asset_shortlist.csv"
)

PHASE67C_DIR = OUTPUTS / "phase67c_shortlist_challenger_overlay"


@dataclass
class ChallengerConfig:
    profile_name: str
    score_lb: int
    fast_ma: int
    slow_ma: int
    min_score: float
    edge_vs_core: float
    risk_ma: int
    risk_buffer: float
    vol_lb: int
    vol_cap: float
    rel_recent_lb: int
    rel_recent_min_edge: float
    cooldown_days: int


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def detect_position_column(df: pd.DataFrame) -> str | None:
    preferred = [
        "executed_position",
        "final_position",
        "signal_position",
        "position",
        "selected_symbol",
        "symbol",
        "asset",
    ]
    for col in preferred:
        if col in df.columns:
            return col
    for col in df.columns:
        lc = str(col).lower()
        if "position" in lc or "symbol" in lc or "asset" in lc:
            return col
    return None


def load_strategy_paper(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing paper: {path}")

    raw = pd.read_csv(path)
    raw = normalize_columns(raw)

    if "date" not in raw.columns:
        raise ValueError(f"{path.name}: missing date column")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    raw = raw.set_index("date")

    required_numeric = ["strategy_return", "equity"]
    for col in required_numeric:
        if col not in raw.columns:
            raise ValueError(f"{path.name}: missing {col}")

    regime_col = "executed_regime" if "executed_regime" in raw.columns else "final_regime"
    if regime_col not in raw.columns:
        raise ValueError(f"{path.name}: missing executed_regime/final_regime")

    pos_col = detect_position_column(raw)
    if pos_col is None:
        raise ValueError(f"{path.name}: missing position column")

    out = pd.DataFrame(index=raw.index.copy())
    out["strategy_return"] = pd.to_numeric(raw["strategy_return"], errors="coerce").fillna(0.0)
    out["equity"] = pd.to_numeric(raw["equity"], errors="coerce").ffill().bfill()
    out["executed_regime"] = raw[regime_col].astype(str).fillna("NA").str.upper()
    out["executed_position"] = raw[pos_col].astype(str).fillna("NA").str.upper().str.strip()
    return out


def load_local_daily_for_core(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path)
    df = normalize_columns(df)
    if "date" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{path.name}: missing date/close")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = (
        df.dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    daily = df[["date", "close"]].rename(columns={"date": "ts"}).copy()
    daily["day"] = pd.to_datetime(daily["ts"]).dt.normalize()
    daily = daily.groupby("day", as_index=True)["close"].last().to_frame("candidate_close").sort_index()

    q = {
        "history_days": int((daily.index.max() - daily.index.min()).days + 1) if len(daily) else 0,
        "start_date": daily.index.min().date().isoformat() if len(daily) else "",
        "end_date": daily.index.max().date().isoformat() if len(daily) else "",
        "daily_rows": int(len(daily)),
        "max_gap_days": 0,
        "non_na_close_ratio": float(daily["candidate_close"].notna().mean()) * 100.0 if len(daily) else 0.0,
    }
    if len(daily) >= 2:
        gaps = pd.Series(daily.index).diff().dt.days.dropna()
        q["max_gap_days"] = int(gaps.max()) if not gaps.empty else 0
    return daily, q


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


def calc_metrics(df: pd.DataFrame, model_name: str) -> dict:
    x = df.copy()
    x["strategy_return"] = pd.to_numeric(x["strategy_return"], errors="coerce").fillna(0.0)
    x["equity"] = (1.0 + x["strategy_return"]).cumprod()

    total_return = float(x["equity"].iloc[-1] / x["equity"].iloc[0] - 1.0) if len(x) > 1 else 0.0
    cagr = annualize_return(total_return, len(x))
    max_dd = max_drawdown_from_equity(x["equity"])
    sharpe = sharpe_ratio(x["strategy_return"])
    sortino = sortino_ratio(x["strategy_return"])

    out = {
        "model": model_name,
        "days": int(len(x)),
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "sharpe": sharpe,
        "sortino": sortino,
    }
    if "executed_regime" in x.columns:
        r = x["executed_regime"].astype(str).fillna("NA")
        out["cash_days_pct"] = float((r == "CASH").mean() * 100.0)
        out["btc_days_pct"] = float((r == "BTC").mean() * 100.0)
        out["base_days_pct"] = float((r == "BASE").mean() * 100.0)
        out["candidate_days_pct"] = float((r == "CANDIDATE").mean() * 100.0)
    if "executed_position" in x.columns:
        p = x["executed_position"].astype(str).fillna("NA")
        out["trade_count"] = int((p != p.shift(1)).sum() - 1) if len(p) else 0
    return out


def window_metrics(df: pd.DataFrame, start_date: str) -> dict:
    sub = df[df.index >= pd.Timestamp(start_date)].copy()
    if sub.empty:
        return {
            f"since{start_date[:4]}_total_return_pct": np.nan,
            f"since{start_date[:4]}_cagr_pct": np.nan,
            f"since{start_date[:4]}_max_drawdown_pct": np.nan,
        }
    m = calc_metrics(sub, f"since{start_date[:4]}")
    return {
        f"since{start_date[:4]}_total_return_pct": m["total_return_pct"],
        f"since{start_date[:4]}_cagr_pct": m["cagr_pct"],
        f"since{start_date[:4]}_max_drawdown_pct": m["max_drawdown_pct"],
    }


def rolling_compound_return(ret: pd.Series, lb: int) -> pd.Series:
    return (1.0 + ret).rolling(lb, min_periods=lb).apply(np.prod, raw=True) - 1.0


def align_candidate_to_core(core_df: pd.DataFrame, candidate_daily: pd.DataFrame) -> pd.DataFrame:
    x = core_df.copy()
    c = candidate_daily.copy().reindex(x.index)
    c["candidate_close"] = c["candidate_close"].ffill()
    x["candidate_close"] = c["candidate_close"]
    x["candidate_return"] = x["candidate_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x


def compute_candidate_signal(df: pd.DataFrame, cfg: ChallengerConfig) -> pd.DataFrame:
    x = df.copy()

    x["core_score"] = rolling_compound_return(x["strategy_return"], cfg.score_lb)
    x["cand_score"] = x["candidate_close"].pct_change(cfg.score_lb)
    x["cand_recent_rel"] = x["candidate_close"].pct_change(cfg.rel_recent_lb) - x["equity"].pct_change(cfg.rel_recent_lb)

    x["cand_fast_ma"] = x["candidate_close"].rolling(cfg.fast_ma, min_periods=cfg.fast_ma).mean()
    x["cand_slow_ma"] = x["candidate_close"].rolling(cfg.slow_ma, min_periods=cfg.slow_ma).mean()
    x["cand_risk_ma"] = x["candidate_close"].rolling(cfg.risk_ma, min_periods=cfg.risk_ma).mean()
    x["cand_vol"] = x["candidate_return"].rolling(cfg.vol_lb, min_periods=cfg.vol_lb).std(ddof=0)

    x["cand_trend_ok"] = (
        (x["candidate_close"] > x["cand_fast_ma"])
        & (x["cand_fast_ma"] > x["cand_slow_ma"])
        & (x["cand_score"] >= cfg.min_score)
    )

    x["cand_risk_off"] = (
        (x["candidate_close"] < (x["cand_risk_ma"] * (1.0 + cfg.risk_buffer)))
        | (x["cand_vol"] > cfg.vol_cap)
    )

    x["cand_beats_core"] = x["cand_score"] >= (x["core_score"] + cfg.edge_vs_core)
    x["cand_recent_rel_ok"] = x["cand_recent_rel"] >= cfg.rel_recent_min_edge

    x["candidate_signal_raw"] = (
        x["cand_trend_ok"].fillna(False)
        & (~x["cand_risk_off"].fillna(True))
        & x["cand_beats_core"].fillna(False)
        & x["cand_recent_rel_ok"].fillna(False)
        & x["candidate_close"].notna()
    )

    raw = x["candidate_signal_raw"].fillna(False).astype(bool).values
    if cfg.cooldown_days > 0:
        locked = np.zeros(len(raw), dtype=bool)
        hold = 0
        for i, flag in enumerate(raw):
            if flag:
                hold = cfg.cooldown_days
            elif hold > 0:
                hold -= 1
            locked[i] = flag or hold > 0
        x["candidate_signal"] = locked
    else:
        x["candidate_signal"] = raw

    x["candidate_execute"] = pd.Series(x["candidate_signal"], index=x.index).shift(1, fill_value=False)
    return x


def build_candidate_overlay(core_df: pd.DataFrame, candidate_daily: pd.DataFrame, cfg: ChallengerConfig, asset: str) -> pd.DataFrame:
    x = align_candidate_to_core(core_df, candidate_daily)
    x = compute_candidate_signal(x, cfg)

    out = x.copy()
    out["executed_regime"] = np.where(out["candidate_execute"], "CANDIDATE", out["executed_regime"])
    out["executed_position"] = np.where(out["candidate_execute"], asset, out["executed_position"])
    out["strategy_return"] = np.where(out["candidate_execute"], out["candidate_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
    return out


def add_delta_cols(row: dict, ref: dict, prefix: str) -> dict:
    out = row.copy()
    for metric in [
        "cagr_pct",
        "max_drawdown_pct",
        "since2021_cagr_pct",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
    ]:
        out[f"delta_vs_{prefix}_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(ref.get(metric), errors="coerce")
        )
    return out


def build_profiles() -> list[ChallengerConfig]:
    return [
        ChallengerConfig(
            profile_name="phase67c_shortlist_challenger_base",
            score_lb=30,
            fast_ma=20,
            slow_ma=100,
            min_score=0.12,
            edge_vs_core=0.03,
            risk_ma=150,
            risk_buffer=-0.03,
            vol_lb=30,
            vol_cap=0.045,
            rel_recent_lb=30,
            rel_recent_min_edge=0.00,
            cooldown_days=3,
        ),
        ChallengerConfig(
            profile_name="phase67c_shortlist_challenger_strict",
            score_lb=30,
            fast_ma=20,
            slow_ma=100,
            min_score=0.16,
            edge_vs_core=0.06,
            risk_ma=150,
            risk_buffer=-0.03,
            vol_lb=20,
            vol_cap=0.035,
            rel_recent_lb=30,
            rel_recent_min_edge=0.03,
            cooldown_days=3,
        ),
    ]


def choose_best_asset_each_day(asset_overlays: dict[str, pd.DataFrame], core_df: pd.DataFrame) -> pd.DataFrame:
    idx = core_df.index
    rows = []

    for dt in idx:
        best_asset = ""
        best_score = -1e18
        best_ret = np.nan

        for asset, df in asset_overlays.items():
            if dt not in df.index:
                continue
            execute = bool(df.at[dt, "candidate_execute"]) if "candidate_execute" in df.columns else False
            if not execute:
                continue

            cand_score = pd.to_numeric(df.at[dt, "cand_score"], errors="coerce")
            core_score = pd.to_numeric(df.at[dt, "core_score"], errors="coerce")
            rel = pd.to_numeric(df.at[dt, "cand_recent_rel"], errors="coerce")
            score = (0.0 if pd.isna(cand_score) else cand_score * 3.0) - (0.0 if pd.isna(core_score) else core_score * 1.0) + (0.0 if pd.isna(rel) else rel * 2.0)

            if score > best_score:
                best_score = score
                best_asset = asset
                best_ret = pd.to_numeric(df.at[dt, "candidate_return"], errors="coerce")

        rows.append(
            {
                "date": dt,
                "selected_asset": best_asset,
                "selected_score": best_score if best_asset else np.nan,
                "selected_return": best_ret if best_asset else np.nan,
            }
        )

    sel = pd.DataFrame(rows).set_index("date")
    out = core_df.copy()
    out["selected_asset"] = sel["selected_asset"]
    out["selected_score"] = sel["selected_score"]
    out["selected_return"] = pd.to_numeric(sel["selected_return"], errors="coerce")

    use_candidate = out["selected_asset"].astype(str) != ""
    out["executed_regime"] = np.where(use_candidate, "CANDIDATE", out["executed_regime"])
    out["executed_position"] = np.where(use_candidate, out["selected_asset"], out["executed_position"])
    out["strategy_return"] = np.where(use_candidate, out["selected_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()

    return out


def load_shortlist(shortlist_path: Path) -> list[dict]:
    if not shortlist_path.exists():
        raise FileNotFoundError(f"Missing shortlist: {shortlist_path}")
    df = pd.read_csv(shortlist_path)
    df.columns = [str(c).strip() for c in df.columns]
    if "asset" not in df.columns or "file" not in df.columns:
        raise ValueError("Shortlist file must contain asset and file columns")
    return df.to_dict("records")


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE67C shortlist challenger overlay over 66G core")
    parser.add_argument("--core-paper", type=str, default=str(CORE_PAPER))
    parser.add_argument("--phase63-paper", type=str, default=str(PHASE63_PAPER))
    parser.add_argument("--shortlist-file", type=str, default=str(PHASE67B_SHORTLIST))
    args = parser.parse_args()

    ensure_dir(PHASE67C_DIR)

    core_df = load_strategy_paper(Path(args.core_paper))
    phase63_df = load_strategy_paper(Path(args.phase63_paper))
    shortlist = load_shortlist(Path(args.shortlist_file))
    profiles = build_profiles()

    core_row = calc_metrics(core_df, CORE_MODEL_KEY)
    core_row.update(window_metrics(core_df, "2021-01-01"))
    core_row.update(window_metrics(core_df, "2023-01-01"))
    core_row.update(window_metrics(core_df, "2025-01-01"))

    phase63_row = calc_metrics(phase63_df, PHASE63_MODEL_KEY)
    phase63_row.update(window_metrics(phase63_df, "2021-01-01"))
    phase63_row.update(window_metrics(phase63_df, "2023-01-01"))
    phase63_row.update(window_metrics(phase63_df, "2025-01-01"))

    log("[PHASE67C] Start")
    log(f"[PHASE67C] Core paper: {args.core_paper}")
    log(f"[PHASE67C] Shortlist assets: {[x['asset'] for x in shortlist]}")

    summary_rows = [phase63_row, core_row]
    compare_rows = []
    decisions_all = []
    asset_quality_rows = []
    papers = {
        PHASE63_MODEL_KEY: phase63_df.copy(),
        CORE_MODEL_KEY: core_df.copy(),
    }

    for cfg in profiles:
        asset_overlays: dict[str, pd.DataFrame] = {}
        failed_assets = []

        for item in shortlist:
            asset = str(item["asset"]).strip().upper()
            file_path = Path(str(item["file"]))
            try:
                daily, q = load_local_daily_for_core(file_path)
                overlay = build_candidate_overlay(core_df, daily, cfg, asset)
                asset_overlays[asset] = overlay
                asset_quality_rows.append(
                    {
                        "profile": cfg.profile_name,
                        "asset": asset,
                        "file": str(file_path),
                        **q,
                    }
                )
            except Exception as e:
                failed_assets.append({"profile": cfg.profile_name, "asset": asset, "reason": str(e)})

        combined = choose_best_asset_each_day(asset_overlays, core_df)
        row = calc_metrics(combined, cfg.profile_name)
        row.update(window_metrics(combined, "2021-01-01"))
        row.update(window_metrics(combined, "2023-01-01"))
        row.update(window_metrics(combined, "2025-01-01"))
        row = add_delta_cols(row, core_row, "phase66g_core")
        row = add_delta_cols(row, phase63_row, "phase63")
        row["shortlist_size"] = len(asset_overlays)

        selected_nonempty = combined["selected_asset"].astype(str)
        row["selection_count"] = int((selected_nonempty != "").sum())
        row["switch_count"] = int((combined["executed_position"].astype(str) != combined["executed_position"].astype(str).shift(1)).sum() - 1)
        row["unique_selected_assets"] = int(selected_nonempty[selected_nonempty != ""].nunique())

        summary_rows.append(row)
        compare_rows.append(row)
        papers[cfg.profile_name] = combined.copy()

        decision = (
            combined[["selected_asset", "selected_score", "executed_position", "executed_regime", "strategy_return"]]
            .reset_index()
            .rename(columns={"index": "date"})
            .copy()
        )
        decision["profile"] = cfg.profile_name
        decisions_all.append(decision)

        for x in failed_assets:
            asset_quality_rows.append(x)

        log(f"[PHASE67C] done {cfg.profile_name}")

    summary = pd.DataFrame(summary_rows)
    compare = pd.DataFrame(compare_rows)
    if not compare.empty:
        compare = compare.sort_values(
            by=[
                "delta_vs_phase66g_core_since2023_cagr_pct",
                "delta_vs_phase66g_core_cagr_pct",
                "delta_vs_phase66g_core_since2025_cagr_pct",
                "delta_vs_phase66g_core_max_drawdown_pct",
            ],
            ascending=[False, False, False, False],
            na_position="last",
        ).reset_index(drop=True)

    decisions_out = pd.concat(decisions_all, ignore_index=True) if decisions_all else pd.DataFrame()
    asset_quality_df = pd.DataFrame(asset_quality_rows)

    best = compare.head(1)
    best_model = str(best.iloc[0]["model"]) if not best.empty else ""
    best_paper = papers.get(best_model)

    live_status = pd.DataFrame()
    latest_top10 = pd.DataFrame()
    if best_paper is not None:
        latest_available_date = best_paper.index.max().strftime("%Y-%m-%d") if len(best_paper) else ""
        current_asset = str(best_paper["executed_position"].astype(str).iloc[-1]) if len(best_paper) else "BASELINE"
        current_asset = current_asset if current_asset else "BASELINE"

        live_status = pd.DataFrame(
            [
                {
                    "model": best_model,
                    "latest_available_date": latest_available_date,
                    "current_asset": current_asset,
                }
            ]
        )

        last_rows = best_paper.reset_index().rename(columns={"index": "date"}).tail(10).copy()
        last_rows["date"] = pd.to_datetime(last_rows["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        latest_top10 = last_rows

    summary_path = PHASE67C_DIR / "phase67c_shortlist_challenger_summary.csv"
    compare_path = PHASE67C_DIR / "phase67c_shortlist_challenger_compare.csv"
    decisions_path = PHASE67C_DIR / "phase67c_shortlist_challenger_decisions.csv"
    asset_quality_path = PHASE67C_DIR / "phase67c_shortlist_challenger_asset_quality.csv"
    live_status_path = PHASE67C_DIR / "phase67c_live_status.csv"
    latest_top10_path = PHASE67C_DIR / "phase67c_latest_rows.csv"
    manifest_path = PHASE67C_DIR / "phase67c_manifest.json"

    summary.to_csv(summary_path, index=False)
    compare.to_csv(compare_path, index=False)
    decisions_out.to_csv(decisions_path, index=False)
    asset_quality_df.to_csv(asset_quality_path, index=False)
    live_status.to_csv(live_status_path, index=False)
    latest_top10.to_csv(latest_top10_path, index=False)

    for model, paper in papers.items():
        out_path = PHASE67C_DIR / f"{model}_paper.csv"
        paper.reset_index().rename(columns={paper.index.name or "index": "date"}).to_csv(out_path, index=False)

    manifest = {
        "phase": "phase67c_shortlist_challenger_overlay",
        "phase63_paper": str(args.phase63_paper),
        "core_paper": str(args.core_paper),
        "shortlist_file": str(args.shortlist_file),
        "profiles": [asdict(p) for p in profiles],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "decisions_file": str(decisions_path),
        "asset_quality_file": str(asset_quality_path),
        "live_status_file": str(live_status_path),
        "latest_rows_file": str(latest_top10_path),
        "best_model": best_model,
        "notes": [
            "66G narrow core ostáva baseline.",
            "Phase67B shortlist assety sú len challenger layer.",
            "Cieľ: zachovať kvalitu 66G a pridať edge z broad scan shortlistu len keď si ho zaslúži.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE67C TOP RESULT ===")
    if best.empty:
        log("No challenger profile processed.")
    else:
        row = best.iloc[0]
        log(f"model: {row['model']}")
        log(f"cagr_pct: {row['cagr_pct']:.2f}")
        log(f"max_drawdown_pct: {row['max_drawdown_pct']:.2f}")
        log(f"since2023_cagr_pct: {row['since2023_cagr_pct']:.2f}")
        log(f"since2025_cagr_pct: {row['since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_cagr_pct: {row['delta_vs_phase66g_core_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_since2023_cagr_pct: {row['delta_vs_phase66g_core_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_since2025_cagr_pct: {row['delta_vs_phase66g_core_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_max_drawdown_pct: {row['delta_vs_phase66g_core_max_drawdown_pct']:.2f}")
        log(f"delta_vs_phase63_cagr_pct: {row['delta_vs_phase63_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2023_cagr_pct: {row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2025_cagr_pct: {row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_max_drawdown_pct: {row['delta_vs_phase63_max_drawdown_pct']:.2f}")
        log(f"selection_count: {int(row['selection_count'])}")
        log(f"switch_count: {int(row['switch_count'])}")
        log(f"unique_selected_assets: {int(row['unique_selected_assets'])}")
        log("")

    if not live_status.empty:
        ls = live_status.iloc[0]
        log("=== PHASE67C LIVE STATUS ===")
        log(f"latest_available_date: {ls['latest_available_date']}")
        log(f"current_asset: {ls['current_asset']}")
        log("")

    log(f"[PHASE67C] Saved summary -> {summary_path}")
    log(f"[PHASE67C] Saved compare -> {compare_path}")
    log(f"[PHASE67C] Saved decisions -> {decisions_path}")
    log(f"[PHASE67C] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE67C] Saved live status -> {live_status_path}")
    log(f"[PHASE67C] Saved latest rows -> {latest_top10_path}")
    log(f"[PHASE67C] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()