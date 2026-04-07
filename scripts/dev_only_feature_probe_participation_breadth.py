from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from research_os_dev_only_feature_output_common import (
    build_manifest,
    build_quality_report,
    feature_file_paths,
    save_csv,
    save_json,
)
from research_os_dev_only_feature_anti_leakage import run_feature_output_checks


ROOT = Path(__file__).resolve().parents[1]
PHASE67_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
PHASE68_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
CORE_OHLCV_DIR = ROOT / "data" / "ohlcv"
TOP100_OHLCV_DIR = ROOT / "data" / "ohlcv_phase67_top100"
EPSILON = 1e-9

FAMILY_ID = "participation_breadth_confirmation_stack"
FAMILY_TYPE = "confidence-stack"
REQUIRED_COLUMNS = [
    "date",
    "leader_asset",
    "breadth_count",
    "participation_ratio",
    "leader_follower_spread",
    "cluster_confirmation_ratio",
    "internal_agreement_score",
    "breadth_thrust",
    "participation_divergence",
    "feature_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only participation breadth feature probe")
    parser.add_argument(
        "--leader-asset",
        default="",
        help="Optional leader filter such as XTZ or XTZUSDT.",
    )
    return parser.parse_args()


def normalize_asset_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return ""
    if not text.endswith("USDT"):
        text = f"{text}USDT"
    return text


def round_value(value: float) -> float:
    return round(float(value), 6)


def load_close_matrix(directory: Path) -> pd.DataFrame:
    series_list: List[pd.Series] = []
    for path in sorted(directory.glob("*USDT_1d.csv")):
        symbol = path.stem.replace("_1d", "").upper()
        frame = pd.read_csv(path, usecols=["date", "close"])
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).copy()
        frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        series = frame.set_index("date")["close"].rename(symbol)
        series_list.append(series)

    if not series_list:
        return pd.DataFrame()

    return pd.concat(series_list, axis=1).sort_index()


def load_leader_rows(asset_filter: str) -> tuple[pd.DataFrame, pd.Series]:
    phase67 = pd.read_csv(PHASE67_PAPER_PATH)
    phase68 = pd.read_csv(PHASE68_PAPER_PATH)

    phase67["date"] = pd.to_datetime(phase67["date"], errors="coerce")
    phase68["date"] = pd.to_datetime(phase68["date"], errors="coerce")

    phase67 = phase67.dropna(subset=["date"]).copy()
    phase68 = phase68.dropna(subset=["date"]).copy()

    phase67["leader_symbol"] = phase67["chosen_asset"].map(normalize_asset_label)
    leaders = phase67[phase67["leader_symbol"] != ""].copy()

    normalized_filter = normalize_asset_label(asset_filter)
    if normalized_filter:
        leaders = leaders[leaders["leader_symbol"] == normalized_filter].copy()

    base_returns = phase68[["date", "base_ret"]].copy()
    base_returns["base_ret"] = pd.to_numeric(base_returns["base_ret"], errors="coerce").fillna(0.0)
    base_returns = base_returns.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    base_anchor = ((1.0 + base_returns["base_ret"]).rolling(3).apply(np.prod, raw=True) - 1.0).fillna(base_returns["base_ret"])
    base_anchor.index = base_returns["date"]

    leaders = leaders.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    leaders["base_anchor"] = leaders["date"].map(base_anchor).fillna(0.0)
    return leaders, base_anchor


def compute_snapshot(
    *,
    date: pd.Timestamp,
    leader_symbol: str,
    universe_returns: pd.DataFrame,
    core_returns: pd.DataFrame,
    base_anchor: float,
) -> Dict[str, float] | None:
    if date not in universe_returns.index or leader_symbol not in universe_returns.columns:
        return None

    universe_slice = universe_returns.loc[date].dropna()
    if leader_symbol not in universe_slice.index:
        return None

    leader_ret = float(universe_slice[leader_symbol])
    direction = 1 if leader_ret > 0 else -1 if leader_ret < 0 else 0
    if direction == 0:
        return None

    move_threshold = max(abs(base_anchor) * 0.5, 0.0)
    direction_mask = np.sign(universe_slice) == direction
    magnitude_mask = universe_slice.abs() >= move_threshold
    participating = universe_slice[direction_mask & magnitude_mask]

    breadth_count = int(len(participating))
    participation_ratio = float(breadth_count / len(universe_slice)) if len(universe_slice) else 0.0

    followers = participating.drop(labels=[leader_symbol], errors="ignore")
    follower_median = float(followers.median()) if len(followers) else 0.0
    leader_follower_spread = leader_ret - follower_median

    if date in core_returns.index:
        core_slice = core_returns.loc[date].dropna()
        core_direction_mask = np.sign(core_slice) == direction
        core_magnitude_mask = core_slice.abs() >= move_threshold
        core_matches = core_slice[core_direction_mask & core_magnitude_mask]
        cluster_confirmation_ratio = float(len(core_matches) / len(core_slice)) if len(core_slice) else 0.0
    else:
        cluster_confirmation_ratio = 0.0

    if len(followers) >= 2:
        mean_abs = abs(float(followers.mean()))
        dispersion = float(followers.std(ddof=0) / (mean_abs + EPSILON))
    elif len(followers) == 1:
        mean_abs = abs(float(followers.iloc[0]))
        dispersion = abs(float(followers.iloc[0]) - leader_ret) / (mean_abs + EPSILON)
    else:
        dispersion = 1.0

    internal_agreement_score = float(np.clip((1.0 - min(dispersion, 1.0)) * participation_ratio, 0.0, 1.0))
    participation_divergence = abs(follower_median - base_anchor) + abs(participation_ratio - cluster_confirmation_ratio)

    return {
        "breadth_count": breadth_count,
        "participation_ratio": participation_ratio,
        "leader_follower_spread": leader_follower_spread,
        "cluster_confirmation_ratio": cluster_confirmation_ratio,
        "internal_agreement_score": internal_agreement_score,
        "participation_divergence": participation_divergence,
    }


def build_real_rows(asset_filter: str) -> List[Dict[str, object]]:
    leaders, base_anchor_series = load_leader_rows(asset_filter)
    universe_closes = load_close_matrix(TOP100_OHLCV_DIR)
    core_closes = load_close_matrix(CORE_OHLCV_DIR)

    universe_returns = universe_closes.pct_change(3, fill_method=None)
    core_returns = core_closes.pct_change(3, fill_method=None)

    snapshot_cache: Dict[tuple[pd.Timestamp, str], Dict[str, float] | None] = {}

    def cached_snapshot(date: pd.Timestamp, leader_symbol: str) -> Dict[str, float] | None:
        cache_key = (date, leader_symbol)
        if cache_key not in snapshot_cache:
            snapshot_cache[cache_key] = compute_snapshot(
                date=date,
                leader_symbol=leader_symbol,
                universe_returns=universe_returns,
                core_returns=core_returns,
                base_anchor=float(base_anchor_series.get(date, 0.0)),
            )
        return snapshot_cache[cache_key]

    rows: List[Dict[str, object]] = []
    for _, leader_row in leaders.iterrows():
        date = leader_row["date"]
        leader_symbol = str(leader_row["leader_symbol"])
        snapshot = cached_snapshot(date, leader_symbol)
        if snapshot is None:
            continue

        previous_dates = universe_returns.index[universe_returns.index < date][-3:]
        historical_ratios = [
            prior_snapshot["participation_ratio"]
            for prior_date in previous_dates
            if (prior_snapshot := cached_snapshot(prior_date, leader_symbol)) is not None
        ]
        prior_mean = float(np.mean(historical_ratios)) if historical_ratios else 0.0
        breadth_thrust = snapshot["participation_ratio"] - prior_mean

        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "leader_asset": leader_symbol,
                "breadth_count": int(snapshot["breadth_count"]),
                "participation_ratio": round_value(snapshot["participation_ratio"]),
                "leader_follower_spread": round_value(snapshot["leader_follower_spread"]),
                "cluster_confirmation_ratio": round_value(snapshot["cluster_confirmation_ratio"]),
                "internal_agreement_score": round_value(snapshot["internal_agreement_score"]),
                "breadth_thrust": round_value(breadth_thrust),
                "participation_divergence": round_value(snapshot["participation_divergence"]),
                "feature_ready_flag": True,
                "dev_only": True,
                "non_authoritative": True,
                "official_truth": False,
                "strategy_advancement": False,
            }
        )

    return rows


def main() -> None:
    args = parse_args()
    rows = build_real_rows(args.leader_asset)
    paths = feature_file_paths(FAMILY_ID)
    columns = REQUIRED_COLUMNS

    checks = run_feature_output_checks(columns=columns, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            family_id=FAMILY_ID,
            family_type=FAMILY_TYPE,
            input_refs=[
                "data/ohlcv/*.csv",
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
