from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import phase66e_probation_governance as core
from freshness_lineage import to_portable_path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DATA_DIR_DEFAULT = ROOT / "data" / "ohlcv_phase67_top100"

CURRENT_WINNER_KEY = core.CURRENT_WINNER_KEY
CURRENT_WINNER_PAPER = core.CURRENT_WINNER_PAPER

PHASE66G_SUMMARY = (
    OUTPUTS
    / "phase66g_production_candidate_live"
    / "phase66g_production_candidate_summary.csv"
)

PHASE67_DIR = OUTPUTS / "phase67_top100_build_and_governance"

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EURC", "PYUSD", "USDE", "USD0"}
WRAPPED_OR_SYNTHETIC_IDS = {
    "wrapped-bitcoin",
    "wrapped-steth",
    "wrapped-eeth",
    "staked-ether",
    "rocket-pool-eth",
}
EXCLUDE_SYMBOLS = {"WBTC", "WETH", "STETH", "WSTETH", "RETH", "WEETH", "CBETH"}


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def portable_path(path: str | Path) -> str:
    return to_portable_path(path, ROOT)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "market_regime_v1_phase67/1.0",
            "Accept": "application/json",
        }
    )
    return s


def get_json(session: requests.Session, url: str, params: dict | None = None, timeout: int = 30, retries: int = 4):
    last_err = None
    for i in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                time.sleep(1.5 + i)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(1.0 + i)
    raise RuntimeError(f"GET failed: {url} | params={params} | err={last_err}")


def normalize_symbol(sym: str) -> str:
    if not sym:
        return ""
    sym = str(sym).upper().strip()
    if sym == "HYPERLIQUID":
        return "HYPE"
    return sym


def is_excluded_cg_asset(item: dict) -> bool:
    sym = normalize_symbol(item.get("symbol", ""))
    name = str(item.get("name", "")).upper()
    cg_id = str(item.get("id", "")).lower()

    if not sym:
        return True
    if sym in STABLES or sym in EXCLUDE_SYMBOLS:
        return True
    if "WRAPPED" in name or cg_id in WRAPPED_OR_SYNTHETIC_IDS or "wrapped" in cg_id:
        return True
    if "STAKED" in name and "ETHER" in name:
        return True
    if sym.startswith("USD"):
        return True
    if sym.startswith("WBTC") or sym.startswith("WETH"):
        return True
    return False


def fetch_coingecko_top_assets(session: requests.Session, target_max_rank: int = 150) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while len(rows) < target_max_rank and page <= 3:
        data = get_json(
            session,
            COINGECKO_MARKETS_URL,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
            timeout=40,
        )
        if not isinstance(data, list) or not data:
            break
        for item in data:
            if is_excluded_cg_asset(item):
                continue
            rows.append(
                {
                    "cg_rank": item.get("market_cap_rank"),
                    "cg_id": item.get("id"),
                    "symbol": normalize_symbol(item.get("symbol", "")),
                    "name": item.get("name"),
                    "market_cap": item.get("market_cap"),
                }
            )
            if len(rows) >= target_max_rank:
                break
        page += 1
        time.sleep(0.4)

    df = pd.DataFrame(rows).drop_duplicates(subset=["symbol"], keep="first")
    df = df.sort_values(by=["cg_rank", "market_cap"], ascending=[True, False], na_position="last").reset_index(drop=True)
    return df.to_dict("records")


def fetch_binance_usdt_pairs(session: requests.Session) -> pd.DataFrame:
    data = get_json(session, BINANCE_EXCHANGE_INFO_URL, timeout=40)
    symbols = data.get("symbols", [])
    rows = []
    for x in symbols:
        if x.get("status") != "TRADING":
            continue
        if x.get("isSpotTradingAllowed") is False:
            continue
        if x.get("quoteAsset") != "USDT":
            continue
        base = normalize_symbol(x.get("baseAsset", ""))
        if not base or base in STABLES or base == "BTC":
            continue
        rows.append(
            {
                "binance_symbol": x.get("symbol"),
                "base_asset": base,
                "quote_asset": x.get("quoteAsset"),
            }
        )
    df = pd.DataFrame(rows).drop_duplicates(subset=["base_asset"], keep="first")
    return df


def map_top_assets_to_binance(cg_assets: list[dict], binance_pairs: pd.DataFrame, max_assets: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_map = {str(r["base_asset"]): r for _, r in binance_pairs.iterrows()}
    mapped = []
    unmatched = []
    used_bases = set()

    for item in cg_assets:
        sym = str(item["symbol"])
        pair = pair_map.get(sym)
        if pair is None:
            unmatched.append(item)
            continue
        if sym in used_bases:
            continue
        used_bases.add(sym)
        mapped.append(
            {
                **item,
                "binance_symbol": pair["binance_symbol"],
                "base_asset": pair["base_asset"],
                "quote_asset": pair["quote_asset"],
            }
        )
        if len(mapped) >= max_assets:
            break

    return pd.DataFrame(mapped), pd.DataFrame(unmatched)


def read_existing_daily_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    if "date" not in df.columns:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


def fetch_binance_daily_klines(
    session: requests.Session,
    symbol: str,
    start_date: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_date).timestamp() * 1000) if end_date else None

    rows = []
    current = start_ts

    while True:
        params = {
            "symbol": symbol,
            "interval": "1d",
            "limit": 1000,
            "startTime": current,
        }
        if end_ts is not None:
            params["endTime"] = end_ts

        data = get_json(session, BINANCE_KLINES_URL, params=params, timeout=40)
        if not isinstance(data, list) or not data:
            break

        for k in data:
            rows.append(
                {
                    "date": pd.to_datetime(int(k[0]), unit="ms").normalize(),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            )

        if len(data) < 1000:
            break

        last_open_ms = int(data[-1][0])
        next_open = pd.to_datetime(last_open_ms, unit="ms").normalize() + pd.Timedelta(days=1)
        next_ms = int(next_open.timestamp() * 1000)
        if next_ms <= current:
            break
        current = next_ms
        time.sleep(0.15)

    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    return df


def update_or_download_asset_daily(
    session: requests.Session,
    symbol: str,
    base_asset: str,
    data_dir: Path,
    full_start_date: str,
    force_refresh: bool,
) -> tuple[Path, dict]:
    ensure_dir(data_dir)
    out_path = data_dir / f"{base_asset}USDT_1d.csv"

    existing = read_existing_daily_csv(out_path)
    if force_refresh or existing.empty:
        fetch_start = full_start_date
    else:
        fetch_start = (existing["date"].max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    new_df = fetch_binance_daily_klines(session, symbol=symbol, start_date=fetch_start)
    merged = pd.concat([existing, new_df], ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)

    if not merged.empty:
        merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    merged.to_csv(out_path, index=False)

    q = {
        "file": portable_path(out_path),
        "rows": int(len(merged)),
        "start_date": str(merged["date"].iloc[0]) if len(merged) else "",
        "end_date": str(merged["date"].iloc[-1]) if len(merged) else "",
    }
    return out_path, q


def load_local_daily_for_core(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    if "date" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{path.name}: missing date/close")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

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


def build_winner_config(min_history_days: int) -> core.GovernanceConfig:
    return core.GovernanceConfig(
        profile_name="phase67_top100_production_soft_filters",
        trailing_train_days=365,
        recent_days=60,
        rebalance_every_days=7,
        min_history_days=min_history_days,
        min_triggers_in_train=4,
        min_total_delta_pct=0.5,
        min_recent_delta_pct=0.25,
        max_allowed_dd_worsen_pct=3.0,
        switch_score_margin=3.0,
        min_hold_periods=3,
        probation_lookback_days=45,
        probation_min_delta_pct=0.0,
        probation_ban_periods=6,
    )


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


def load_phase66g_reference(summary_path: Path) -> dict | None:
    if not summary_path.exists():
        return None
    df = pd.read_csv(summary_path)
    df.columns = [str(c).strip() for c in df.columns]
    match = df[df["model"].astype(str) == "phase66g_production_soft_filters"]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def compute_next_rebalance_date(decisions_df: pd.DataFrame, rebalance_days: int) -> str:
    if decisions_df.empty or "decision_date" not in decisions_df.columns:
        return ""
    last_decision = pd.to_datetime(decisions_df["decision_date"], errors="coerce").dropna()
    if last_decision.empty:
        return ""
    next_dt = last_decision.iloc[-1] + pd.Timedelta(days=rebalance_days)
    return next_dt.strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE67 top100 build + governance in one step")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--max-assets", type=int, default=100)
    parser.add_argument("--target-max-rank", type=int, default=180)
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR_DEFAULT))
    parser.add_argument("--full-start-date", type=str, default="2019-01-01")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--min-history-days", type=int, default=180)
    args = parser.parse_args()

    ensure_dir(PHASE67_DIR)
    data_dir = Path(args.data_dir)
    ensure_dir(data_dir)

    overlay_cfg = core.OverlayConfig()
    gov_cfg = build_winner_config(args.min_history_days)
    phase66g_ref = load_phase66g_reference(PHASE66G_SUMMARY)

    log("[PHASE67] Start")
    log(f"[PHASE67] Baseline paper: {args.baseline_paper}")
    log(f"[PHASE67] Data dir: {data_dir}")

    baseline = core.load_baseline_paper(Path(args.baseline_paper), overlay_cfg)
    phase63_row = core.calc_metrics(baseline, CURRENT_WINNER_KEY)
    phase63_row.update(core.window_metrics(baseline, "2021-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2023-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2025-01-01"))
    phase63_row["mode"] = "baseline"

    session = make_session()

    cg_assets = fetch_coingecko_top_assets(session, target_max_rank=args.target_max_rank)
    binance_pairs = fetch_binance_usdt_pairs(session)
    mapping_df, unmatched_df = map_top_assets_to_binance(cg_assets, binance_pairs, max_assets=args.max_assets)

    log(f"[PHASE67] CoinGecko filtered assets: {len(cg_assets)}")
    log(f"[PHASE67] Binance matched top assets: {len(mapping_df)}")

    downloaded_rows = []
    download_fail_rows = []
    asset_strategies: dict[str, pd.DataFrame] = {}
    asset_quality_rows = []

    for _, row in mapping_df.iterrows():
        asset = str(row["base_asset"])
        symbol = str(row["binance_symbol"])
        try:
            out_path, dl_q = update_or_download_asset_daily(
                session=session,
                symbol=symbol,
                base_asset=asset,
                data_dir=data_dir,
                full_start_date=args.full_start_date,
                force_refresh=args.force_refresh,
            )
            downloaded_rows.append({"asset": asset, "binance_symbol": symbol, **dl_q})

            daily, q = load_local_daily_for_core(out_path)
            if q["history_days"] < gov_cfg.min_history_days:
                continue

            strat = core.build_asset_strategy(baseline, daily, overlay_cfg, asset)
            asset_strategies[asset] = strat
            asset_quality_rows.append(
                {
                    "asset": asset,
                    "binance_symbol": symbol,
                    "cg_rank": row["cg_rank"],
                    "cg_id": row["cg_id"],
                    "name": row["name"],
                    **q,
                    "file": portable_path(out_path),
                }
            )
            log(f"[PHASE67] done {asset}")
        except Exception as e:
            download_fail_rows.append(
                {
                    "asset": asset,
                    "binance_symbol": symbol,
                    "cg_rank": row.get("cg_rank"),
                    "reason": str(e),
                }
            )
            log(f"[WARN] {asset} failed: {e}")

    governance, decisions_df, leaderboard_df = core.simulate_governance_strategy_probation(
        baseline=baseline,
        asset_strategies=asset_strategies,
        gov_cfg=gov_cfg,
    )

    prod_row = core.calc_metrics(governance, gov_cfg.profile_name)
    prod_row.update(core.window_metrics(governance, "2021-01-01"))
    prod_row.update(core.window_metrics(governance, "2023-01-01"))
    prod_row.update(core.window_metrics(governance, "2025-01-01"))
    prod_row["mode"] = gov_cfg.profile_name
    prod_row = add_delta_cols(prod_row, phase63_row, "phase63")
    if phase66g_ref is not None:
        prod_row = add_delta_cols(prod_row, phase66g_ref, "phase66g_narrow")

    selected_nonempty = governance["chosen_asset"].astype(str)
    prod_row["unique_selected_assets"] = int(selected_nonempty[selected_nonempty != ""].nunique())
    prod_row["selected_days_pct"] = float((selected_nonempty != "").mean() * 100.0)
    prod_row["decision_count"] = int(len(decisions_df))
    prod_row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty else 0
    prod_row["switch_count"] = int((decisions_df["selected_asset"].astype(str) != decisions_df["selected_asset"].astype(str).shift(1)).sum() - 1) if not decisions_df.empty else 0

    if not leaderboard_df.empty and "suspended" in leaderboard_df.columns:
        susp = leaderboard_df.groupby("asset", as_index=False)["suspended"].sum()
        prod_row["asset_suspensions_total"] = int(pd.to_numeric(susp["suspended"], errors="coerce").sum())
    else:
        prod_row["asset_suspensions_total"] = 0

    summary = pd.DataFrame([phase63_row, prod_row])

    asset_usage = (
        governance["chosen_asset"]
        .astype(str)
        .replace("", np.nan)
        .dropna()
        .value_counts()
        .rename_axis("asset")
        .reset_index(name="selected_days")
    )
    if not asset_usage.empty:
        asset_usage["selected_days_pct"] = asset_usage["selected_days"] / len(governance) * 100.0
        asset_usage["profile"] = gov_cfg.profile_name

    latest_available_date = governance.index.max().strftime("%Y-%m-%d") if len(governance) else ""
    current_asset = str(governance["weekly_authorized_asset"].astype(str).iloc[-1]) if len(governance) else ""
    current_asset = current_asset if current_asset else "BASELINE"
    next_rebalance_date = compute_next_rebalance_date(decisions_df, gov_cfg.rebalance_every_days)

    latest_decision_date = ""
    latest_period_start = ""
    latest_period_end = ""
    latest_keep_reason = ""
    if not decisions_df.empty:
        latest_decision = decisions_df.iloc[-1]
        latest_decision_date = str(latest_decision.get("decision_date", ""))
        latest_period_start = str(latest_decision.get("period_start", ""))
        latest_period_end = str(latest_decision.get("period_end", ""))
        latest_keep_reason = str(latest_decision.get("keep_reason", ""))

    latest_leaderboard = pd.DataFrame()
    if not leaderboard_df.empty and latest_decision_date:
        latest_leaderboard = (
            leaderboard_df[leaderboard_df["decision_date"].astype(str) == latest_decision_date]
            .copy()
            .sort_values(
                by=["passed_filters", "score", "recent_total_delta_pct", "train_total_delta_pct"],
                ascending=[False, False, False, False],
                na_position="last",
            )
            .reset_index(drop=True)
        )

    latest_top10 = latest_leaderboard.head(10).copy() if not latest_leaderboard.empty else pd.DataFrame()

    suspended_assets = pd.DataFrame()
    if not latest_leaderboard.empty and "suspended" in latest_leaderboard.columns:
        suspended_assets = latest_leaderboard[latest_leaderboard["suspended"] == True].copy()
        suspended_assets = suspended_assets.sort_values(
            by=["suspended_until_rebalance_idx", "asset"],
            ascending=[False, True],
            na_position="last",
        ).reset_index(drop=True)

    live_status = pd.DataFrame(
        [
            {
                "model": gov_cfg.profile_name,
                "latest_available_date": latest_available_date,
                "current_asset": current_asset,
                "latest_decision_date": latest_decision_date,
                "latest_period_start": latest_period_start,
                "latest_period_end": latest_period_end,
                "next_rebalance_date": next_rebalance_date,
                "latest_keep_reason": latest_keep_reason,
                "candidate_assets_loaded": len(asset_strategies),
                "matched_top_assets": len(mapping_df),
                "failed_assets_count": len(download_fail_rows),
                "suspended_assets_now": int(len(suspended_assets)),
            }
        ]
    )

    mapping_path = PHASE67_DIR / "phase67_top100_mapping.csv"
    unmatched_path = PHASE67_DIR / "phase67_top100_unmatched.csv"
    downloads_path = PHASE67_DIR / "phase67_top100_downloads.csv"
    failed_downloads_path = PHASE67_DIR / "phase67_top100_failed_downloads.csv"
    summary_path = PHASE67_DIR / "phase67_top100_production_summary.csv"
    compare_path = PHASE67_DIR / "phase67_top100_production_compare.csv"
    live_status_path = PHASE67_DIR / "phase67_live_status.csv"
    decisions_path = PHASE67_DIR / "phase67_top100_production_decisions.csv"
    leaderboard_path = PHASE67_DIR / "phase67_top100_production_leaderboard.csv"
    latest_top10_path = PHASE67_DIR / "phase67_latest_decision_top10.csv"
    suspended_now_path = PHASE67_DIR / "phase67_suspended_assets_now.csv"
    asset_quality_path = PHASE67_DIR / "phase67_top100_asset_quality.csv"
    asset_usage_path = PHASE67_DIR / "phase67_top100_asset_usage.csv"
    baseline_paper_path = PHASE67_DIR / f"{CURRENT_WINNER_KEY}_paper.csv"
    production_paper_path = PHASE67_DIR / f"{gov_cfg.profile_name}_paper.csv"
    manifest_path = PHASE67_DIR / "phase67_manifest.json"

    mapping_df.to_csv(mapping_path, index=False)
    unmatched_df.to_csv(unmatched_path, index=False)
    pd.DataFrame(downloaded_rows).to_csv(downloads_path, index=False)
    pd.DataFrame(download_fail_rows).to_csv(failed_downloads_path, index=False)
    summary.to_csv(summary_path, index=False)
    summary.to_csv(compare_path, index=False)
    live_status.to_csv(live_status_path, index=False)
    decisions_df.to_csv(decisions_path, index=False)
    leaderboard_df.to_csv(leaderboard_path, index=False)
    latest_top10.to_csv(latest_top10_path, index=False)
    suspended_assets.to_csv(suspended_now_path, index=False)
    pd.DataFrame(asset_quality_rows).to_csv(asset_quality_path, index=False)
    asset_usage.to_csv(asset_usage_path, index=False)

    baseline.reset_index().rename(columns={baseline.index.name or "index": "date"}).to_csv(baseline_paper_path, index=False)
    governance.reset_index().rename(columns={governance.index.name or "index": "date"}).to_csv(production_paper_path, index=False)

    manifest = {
        "phase": "phase67_top100_build_and_governance",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": portable_path(args.baseline_paper),
        "phase66g_summary": portable_path(PHASE66G_SUMMARY),
        "data_dir": portable_path(data_dir),
        "max_assets_requested": int(args.max_assets),
        "target_max_rank": int(args.target_max_rank),
        "full_start_date": args.full_start_date,
        "force_refresh": bool(args.force_refresh),
        "matched_top_assets": int(len(mapping_df)),
        "candidate_assets_loaded": int(len(asset_strategies)),
        "candidate_assets_failed": int(len(download_fail_rows)),
        "winner_profile": asdict(gov_cfg),
        "current_asset": current_asset,
        "latest_available_date": latest_available_date,
        "latest_decision_date": latest_decision_date,
        "next_rebalance_date": next_rebalance_date,
        "mapping_file": portable_path(mapping_path),
        "unmatched_file": portable_path(unmatched_path),
        "downloads_file": portable_path(downloads_path),
        "failed_downloads_file": portable_path(failed_downloads_path),
        "summary_file": portable_path(summary_path),
        "compare_file": portable_path(compare_path),
        "live_status_file": portable_path(live_status_path),
        "decisions_file": portable_path(decisions_path),
        "leaderboard_file": portable_path(leaderboard_path),
        "latest_top10_file": portable_path(latest_top10_path),
        "suspended_now_file": portable_path(suspended_now_path),
        "asset_quality_file": portable_path(asset_quality_path),
        "asset_usage_file": portable_path(asset_usage_path),
        "baseline_paper_saved": portable_path(baseline_paper_path),
        "production_paper_saved": portable_path(production_paper_path),
        "notes": [
            "2 kroky naraz: broad top100 universe build + production governance rerun.",
            "CoinGecko top market cap sa mapuje na Binance spot USDT páry.",
            "Current asset je based na poslednom dostupnom daily bare.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE67 TOP RESULT ===")
    log(f"model: {gov_cfg.profile_name}")
    log(f"cagr_pct: {prod_row['cagr_pct']:.2f}")
    log(f"max_drawdown_pct: {prod_row['max_drawdown_pct']:.2f}")
    log(f"since2023_cagr_pct: {prod_row['since2023_cagr_pct']:.2f}")
    log(f"since2025_cagr_pct: {prod_row['since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_cagr_pct: {prod_row['delta_vs_phase63_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_since2023_cagr_pct: {prod_row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_since2025_cagr_pct: {prod_row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_max_drawdown_pct: {prod_row['delta_vs_phase63_max_drawdown_pct']:.2f}")
    if phase66g_ref is not None:
        log(f"delta_vs_phase66g_narrow_cagr_pct: {prod_row['delta_vs_phase66g_narrow_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_narrow_since2023_cagr_pct: {prod_row['delta_vs_phase66g_narrow_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_narrow_since2025_cagr_pct: {prod_row['delta_vs_phase66g_narrow_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_narrow_max_drawdown_pct: {prod_row['delta_vs_phase66g_narrow_max_drawdown_pct']:.2f}")
    log(f"matched_top_assets: {len(mapping_df)}")
    log(f"candidate_assets_loaded: {len(asset_strategies)}")
    log(f"selection_count: {int(prod_row['selection_count'])}")
    log(f"switch_count: {int(prod_row['switch_count'])}")
    log(f"asset_suspensions_total: {int(prod_row['asset_suspensions_total'])}")
    log("")
    log("=== PHASE67 LIVE STATUS ===")
    log(f"latest_available_date: {latest_available_date}")
    log(f"current_asset: {current_asset}")
    log(f"latest_decision_date: {latest_decision_date}")
    log(f"next_rebalance_date: {next_rebalance_date}")
    log(f"suspended_assets_now: {len(suspended_assets)}")
    log("")

    if not asset_usage.empty:
        log("=== PHASE67 TOP USED ASSETS ===")
        for _, r in asset_usage.head(5).iterrows():
            log(f"{r['asset']}: {int(r['selected_days'])} days ({r['selected_days_pct']:.2f}%)")
        log("")

    log(f"[PHASE67] Saved mapping -> {mapping_path}")
    log(f"[PHASE67] Saved unmatched -> {unmatched_path}")
    log(f"[PHASE67] Saved downloads -> {downloads_path}")
    log(f"[PHASE67] Saved failed downloads -> {failed_downloads_path}")
    log(f"[PHASE67] Saved summary -> {summary_path}")
    log(f"[PHASE67] Saved compare -> {compare_path}")
    log(f"[PHASE67] Saved live status -> {live_status_path}")
    log(f"[PHASE67] Saved decisions -> {decisions_path}")
    log(f"[PHASE67] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE67] Saved latest top10 -> {latest_top10_path}")
    log(f"[PHASE67] Saved suspended now -> {suspended_now_path}")
    log(f"[PHASE67] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE67] Saved asset usage -> {asset_usage_path}")
    log(f"[PHASE67] Saved baseline paper -> {baseline_paper_path}")
    log(f"[PHASE67] Saved production paper -> {production_paper_path}")
    log(f"[PHASE67] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
