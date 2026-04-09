from __future__ import annotations

import argparse
from typing import Dict, List

import numpy as np
import pandas as pd

from research_os_dev_only_feature_anti_leakage import run_feature_output_checks
from research_os_dev_only_feature_inputs_common import (
    CORE_OHLCV_DIR,
    EPSILON,
    PHASE67_PAPER_PATH,
    PHASE68_PAPER_PATH,
    TOP100_OHLCV_DIR,
    load_active_leader_rows,
    load_close_matrix,
    load_daily_ohlcv,
    round_value,
)
from research_os_dev_only_feature_output_common import (
    build_manifest,
    build_quality_report,
    feature_file_paths,
    save_csv,
    save_json,
)


LOOKBACK_DAYS = 40
WINDOW_DAYS = 20

FAMILY_ID = "cross_asset_decoupling_stack"
FAMILY_TYPE = "regime-context"
REQUIRED_COLUMNS = [
    "date",
    "asset",
    "rolling_correlation_break",
    "beta_deviation",
    "relative_momentum_decoupling",
    "leader_lag_follower_escape",
    "isolated_strength_flag",
    "isolated_weakness_flag",
    "feature_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only cross-asset decoupling feature probe")
    parser.add_argument("--asset", default="", help="Optional asset filter such as XTZ or XTZUSDT.")
    return parser.parse_args()


def compute_beta(x: pd.Series, y: pd.Series) -> float:
    clean = pd.concat([x, y], axis=1).dropna()
    if len(clean) < 2:
        return 0.0
    variance = float(clean.iloc[:, 1].var(ddof=0))
    if variance <= EPSILON:
        return 0.0
    covariance = float(clean.iloc[:, 0].cov(clean.iloc[:, 1], ddof=0))
    return covariance / variance


def build_feature_row(
    *,
    date: pd.Timestamp,
    asset: str,
    asset_cache: Dict[str, pd.DataFrame],
    universe_returns_3d: pd.DataFrame,
    btc_frame: pd.DataFrame,
    eth_frame: pd.DataFrame,
) -> Dict[str, object] | None:
    asset_frame = load_daily_ohlcv(asset, asset_cache, directories=[TOP100_OHLCV_DIR, CORE_OHLCV_DIR])
    joined = pd.DataFrame(
        {
            "asset_ret": asset_frame["base_ret"],
            "asset_ret_3d": asset_frame["ret_3d"],
            "btc_ret": btc_frame["base_ret"],
            "btc_ret_3d": btc_frame["ret_3d"],
            "eth_ret": eth_frame["base_ret"],
            "eth_ret_3d": eth_frame["ret_3d"],
        }
    ).dropna()

    if date not in joined.index:
        return None

    position = joined.index.get_loc(date)
    if isinstance(position, slice):
        position = position.stop - 1
    if position + 1 < LOOKBACK_DAYS:
        return None

    window = joined.iloc[position + 1 - LOOKBACK_DAYS : position + 1]
    prior = window.head(WINDOW_DAYS)
    current = window.tail(WINDOW_DAYS)

    corr_break_btc = abs(float(current["asset_ret"].corr(current["btc_ret"])) - float(prior["asset_ret"].corr(prior["btc_ret"])))
    corr_break_eth = abs(float(current["asset_ret"].corr(current["eth_ret"])) - float(prior["asset_ret"].corr(prior["eth_ret"])))
    rolling_correlation_break = float(np.nanmean([corr_break_btc, corr_break_eth]))

    beta_dev_btc = abs(compute_beta(current["asset_ret"], current["btc_ret"]) - compute_beta(prior["asset_ret"], prior["btc_ret"]))
    beta_dev_eth = abs(compute_beta(current["asset_ret"], current["eth_ret"]) - compute_beta(prior["asset_ret"], prior["eth_ret"]))
    beta_deviation = float(np.nanmean([beta_dev_btc, beta_dev_eth]))

    if date not in universe_returns_3d.index or asset not in universe_returns_3d.columns:
        return None

    basket_slice = universe_returns_3d.loc[date].drop(labels=[asset], errors="ignore").dropna()
    if basket_slice.empty:
        return None

    leader_context_3d = float(np.median([current["btc_ret_3d"].iloc[-1], current["eth_ret_3d"].iloc[-1], basket_slice.median()]))
    relative_momentum_decoupling = float(current["asset_ret_3d"].iloc[-1] - leader_context_3d)

    leader_context_1d = float(np.mean([current["btc_ret"].iloc[-1], current["eth_ret"].iloc[-1]]))
    prior_underperformance = float(
        min(
            current["asset_ret"].iloc[-4:-1].mean() - current[["btc_ret", "eth_ret"]].iloc[-4:-1].mean(axis=1).mean(),
            0.0,
        )
    )
    leader_lag_follower_escape = float((current["asset_ret"].iloc[-1] - leader_context_1d) - prior_underperformance)

    isolated_strength_flag = int(
        relative_momentum_decoupling > 0.0
        and current["asset_ret"].iloc[-1] > max(current["btc_ret"].iloc[-1], current["eth_ret"].iloc[-1])
        and rolling_correlation_break > 0.0
    )
    isolated_weakness_flag = int(
        relative_momentum_decoupling < 0.0
        and current["asset_ret"].iloc[-1] < min(current["btc_ret"].iloc[-1], current["eth_ret"].iloc[-1])
        and rolling_correlation_break > 0.0
    )

    return {
        "date": date.strftime("%Y-%m-%d"),
        "asset": asset,
        "rolling_correlation_break": round_value(np.nan_to_num(rolling_correlation_break)),
        "beta_deviation": round_value(np.nan_to_num(beta_deviation)),
        "relative_momentum_decoupling": round_value(relative_momentum_decoupling),
        "leader_lag_follower_escape": round_value(leader_lag_follower_escape),
        "isolated_strength_flag": isolated_strength_flag,
        "isolated_weakness_flag": isolated_weakness_flag,
        "feature_ready_flag": True,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "strategy_advancement": False,
    }


def build_rows(asset_filter: str) -> List[Dict[str, object]]:
    active_rows = load_active_leader_rows(asset_filter)
    asset_cache: Dict[str, pd.DataFrame] = {}
    btc_frame = load_daily_ohlcv("BTCUSDT", asset_cache, directories=[CORE_OHLCV_DIR])
    eth_frame = load_daily_ohlcv("ETHUSDT", asset_cache, directories=[CORE_OHLCV_DIR, TOP100_OHLCV_DIR])
    universe_closes = load_close_matrix(TOP100_OHLCV_DIR)
    universe_returns_3d = universe_closes.pct_change(3, fill_method=None)

    rows: List[Dict[str, object]] = []
    for _, row in active_rows.iterrows():
        feature_row = build_feature_row(
            date=row["date"],
            asset=str(row["asset"]),
            asset_cache=asset_cache,
            universe_returns_3d=universe_returns_3d,
            btc_frame=btc_frame,
            eth_frame=eth_frame,
        )
        if feature_row is not None:
            rows.append(feature_row)
    return rows


def main() -> None:
    args = parse_args()
    rows = build_rows(args.asset)
    paths = feature_file_paths(FAMILY_ID)
    checks = run_feature_output_checks(columns=REQUIRED_COLUMNS, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            family_id=FAMILY_ID,
            family_type=FAMILY_TYPE,
            input_refs=[
                "data/ohlcv/BTCUSDT_1d.csv",
                "data/ohlcv/ETHUSDT_1d.csv",
                "data/ohlcv_phase67_top100/*.csv",
                str(PHASE67_PAPER_PATH),
                str(PHASE68_PAPER_PATH),
            ],
            features_csv_path=paths["features_csv"],
            quality_json_path=paths["quality_json"],
            profile_json_path=paths["profile_json"],
            column_schema=REQUIRED_COLUMNS,
            row_count=len(rows),
        ),
    )
    save_json(
        paths["quality_json"],
        build_quality_report(
            family_id=FAMILY_ID,
            row_count=len(rows),
            required_columns=REQUIRED_COLUMNS,
            leakage_checks=checks,
        ),
    )

    print(f"{FAMILY_ID} dev-only outputs generated")
    print(paths["features_csv"])
    print(paths["manifest_json"])
    print(paths["quality_json"])


if __name__ == "__main__":
    main()
