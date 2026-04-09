from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from research_os_dev_only_response_shape_anti_leakage import run_response_shape_output_checks
from research_os_dev_only_response_shape_output_common import (
    MANDATORY_DEV_FLAGS,
    MANDATORY_SEMANTIC_FIELDS,
    build_manifest,
    build_quality_report,
    response_shape_file_paths,
    save_csv,
    save_json,
)


ROOT = Path(__file__).resolve().parents[1]
ANOMALY_CSV_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_features" / "anomaly_ranking_heuristics.csv"
TREND_HISTORY_PATH = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"
DATA_DIR = ROOT / "data"
OHLCV_DIR = ROOT / "data" / "ohlcv"
OUTPUT_ROOT = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_response_shape_aligned"

BOT_ID = "response_shape_bot_v1_anomaly_aligned"
LOOKAHEAD_DAYS = 10
EPSILON = 1e-9

REQUIRED_COLUMNS = [
    "date",
    "event_id",
    "event_type",
    "entry_regime",
    "entry_position",
    "selected_asset",
    "trend_score",
    "trend_state_label",
    "anchor_interestingness_score",
    "anchor_active_family_count",
    "anchor_cluster_note",
    "response_regime_context",
    "lookahead_window_days",
    "observed_return_3d",
    "observed_return_5d",
    "observed_return_10d",
    "observed_max_drawdown_5d",
    "observed_max_drawdown_10d",
    "observed_recovery_from_5d_low_to_10d",
    "observed_realized_volatility_10d",
    "observed_downside_volatility_10d",
    "follow_through_quality",
    "false_start_risk",
    "volatility_damage_shape",
    "recovery_vs_exhaustion",
    "analysis_mode",
    "live_decision_ready",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build anomaly-aligned dev-only response-shape outputs")
    parser.add_argument("--anomaly-csv", type=str, default=str(ANOMALY_CSV_PATH))
    parser.add_argument("--trend-history", type=str, default=str(TREND_HISTORY_PATH))
    return parser.parse_args()


def normalize_asset_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NAN", "NONE", "NULL", "NA"}:
        return ""
    if text.endswith("USDT"):
        return text[:-4]
    return text


def resolve_asset_daily_path(asset: str) -> Path:
    direct_path = OHLCV_DIR / f"{asset}USDT_1d.csv"
    if direct_path.exists():
        return direct_path

    exact_candidates = sorted(
        [
            path
            for path in DATA_DIR.rglob("*.csv")
            if path.name.upper().startswith(f"{asset.upper()}USDT") and "1D" in path.name.upper()
        ]
    )
    if exact_candidates:
        return exact_candidates[0]

    loose_candidates = sorted(
        [
            path
            for path in DATA_DIR.rglob("*.csv")
            if asset.upper() in path.name.upper() and "USDT" in path.name.upper() and "1D" in path.name.upper()
        ]
    )
    if loose_candidates:
        return loose_candidates[0]

    return direct_path


def load_asset_daily(asset: str, cache: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    if asset in cache:
        return cache[asset]

    path = resolve_asset_daily_path(asset)
    if not path.exists():
        raise FileNotFoundError(f"Missing OHLCV input for {asset}: {path}")

    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df["asset_return"] = df["close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    cache[asset] = df.set_index("date")[["close", "asset_return"]]
    return cache[asset]


def round_value(value: float) -> float:
    return round(float(value), 6)


def cumulative_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float((1.0 + returns).prod() - 1.0)


def max_drawdown_from_returns(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    path = (1.0 + returns).cumprod()
    drawdown = path / path.cummax() - 1.0
    return float(drawdown.min())


def downside_volatility(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    downside = returns.where(returns < 0.0, 0.0)
    return float(downside.std(ddof=0))


def trend_bucket(trend_score: float | None) -> str:
    if trend_score is None or pd.isna(trend_score):
        return "unknown"
    if trend_score < -0.15:
        return "weak_negative"
    if trend_score <= 0.15:
        return "near_flat"
    return "constructive"


def load_anomaly_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["entity"] = df["entity"].fillna("").astype(str).str.upper().str.strip()
    df["interestingness_score"] = pd.to_numeric(df["interestingness_score"], errors="coerce")
    df["active_family_count"] = pd.to_numeric(df["active_family_count"], errors="coerce")
    df["cluster_note"] = df["cluster_note"].fillna("").astype(str).str.strip()
    df["interestingness_band"] = df.get("interestingness_band", "").fillna("").astype(str).str.strip()
    return df.dropna(subset=["date"]).sort_values(["date", "entity"]).drop_duplicates(subset=["date", "entity"], keep="first")


def load_trend_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()
    if "trend_score" not in df.columns:
        df["trend_score"] = np.nan
    if "trend_state_label" not in df.columns:
        df["trend_state_label"] = ""
    df["trend_score"] = pd.to_numeric(df["trend_score"], errors="coerce")
    df["trend_state_label"] = df["trend_state_label"].fillna("").astype(str).str.strip()
    return df[["date", "trend_score", "trend_state_label"]]


def build_anchor_row(
    anchor_row: pd.Series,
    trend_lookup: pd.DataFrame,
    asset_cache: Dict[str, pd.DataFrame],
) -> Dict[str, object] | None:
    entity = str(anchor_row["entity"]).strip().upper()
    asset_code = normalize_asset_label(entity)
    if not asset_code:
        return None

    try:
        asset_df = load_asset_daily(asset_code, asset_cache)
    except FileNotFoundError:
        return None

    date_value = pd.Timestamp(anchor_row["date"])
    if date_value not in asset_df.index:
        return None

    anchor_loc = asset_df.index.get_loc(date_value)
    if isinstance(anchor_loc, slice):
        anchor_loc = anchor_loc.stop - 1
    if anchor_loc + LOOKAHEAD_DAYS >= len(asset_df):
        return None

    future_returns = asset_df["asset_return"].iloc[anchor_loc + 1 : anchor_loc + 1 + LOOKAHEAD_DAYS].astype(float)
    if len(future_returns) < LOOKAHEAD_DAYS:
        return None

    trend_match = trend_lookup.loc[trend_lookup["date"].eq(date_value)]
    trend_score = np.nan
    trend_state_label = ""
    if not trend_match.empty:
        trend_score = pd.to_numeric(pd.Series([trend_match.iloc[0]["trend_score"]]), errors="coerce").iloc[0]
        trend_state_label = str(trend_match.iloc[0]["trend_state_label"])

    returns_3d = future_returns.iloc[:3]
    returns_5d = future_returns.iloc[:5]
    returns_10d = future_returns.iloc[:10]
    path_10d = (1.0 + returns_10d).cumprod()
    low_5d = float(path_10d.iloc[:5].min())

    observed_return_3d = cumulative_return(returns_3d)
    observed_return_5d = cumulative_return(returns_5d)
    observed_return_10d = cumulative_return(returns_10d)
    observed_max_drawdown_5d = max_drawdown_from_returns(returns_5d)
    observed_max_drawdown_10d = max_drawdown_from_returns(returns_10d)
    observed_recovery_from_5d_low_to_10d = float(path_10d.iloc[-1] / max(low_5d, EPSILON) - 1.0)
    observed_realized_volatility_10d = float(returns_10d.std(ddof=0))
    observed_downside_volatility_10d = downside_volatility(returns_10d)

    follow_through_quality = observed_return_5d - abs(min(0.0, observed_max_drawdown_5d))
    false_start_risk = abs(min(0.0, observed_return_3d)) + abs(min(0.0, observed_max_drawdown_5d))
    volatility_damage_shape = observed_downside_volatility_10d / max(observed_realized_volatility_10d, EPSILON)
    recovery_vs_exhaustion = observed_recovery_from_5d_low_to_10d - abs(min(0.0, observed_return_3d))

    trend_context = trend_bucket(None if pd.isna(trend_score) else float(trend_score))
    interestingness_band = str(anchor_row.get("interestingness_band", "")).strip() or "unbanded"
    response_regime_context = f"anomaly_anchor|{trend_context}|{interestingness_band}"

    feature_row = {
        "date": date_value.strftime("%Y-%m-%d"),
        "event_id": f"{date_value.strftime('%Y%m%d')}_{entity}",
        "event_type": "anomaly_aligned_anchor",
        "entry_regime": "ANOMALY_ANCHOR",
        "entry_position": str(int(anchor_row["active_family_count"])) if pd.notna(anchor_row["active_family_count"]) else "",
        "selected_asset": entity,
        "trend_score": None if pd.isna(trend_score) else round_value(float(trend_score)),
        "trend_state_label": trend_state_label,
        "anchor_interestingness_score": None if pd.isna(anchor_row["interestingness_score"]) else round_value(float(anchor_row["interestingness_score"])),
        "anchor_active_family_count": None if pd.isna(anchor_row["active_family_count"]) else int(anchor_row["active_family_count"]),
        "anchor_cluster_note": str(anchor_row.get("cluster_note", "")),
        "response_regime_context": response_regime_context,
        "lookahead_window_days": LOOKAHEAD_DAYS,
        "observed_return_3d": round_value(observed_return_3d),
        "observed_return_5d": round_value(observed_return_5d),
        "observed_return_10d": round_value(observed_return_10d),
        "observed_max_drawdown_5d": round_value(observed_max_drawdown_5d),
        "observed_max_drawdown_10d": round_value(observed_max_drawdown_10d),
        "observed_recovery_from_5d_low_to_10d": round_value(observed_recovery_from_5d_low_to_10d),
        "observed_realized_volatility_10d": round_value(observed_realized_volatility_10d),
        "observed_downside_volatility_10d": round_value(observed_downside_volatility_10d),
        "follow_through_quality": round_value(follow_through_quality),
        "false_start_risk": round_value(false_start_risk),
        "volatility_damage_shape": round_value(volatility_damage_shape),
        "recovery_vs_exhaustion": round_value(recovery_vs_exhaustion),
    }
    feature_row.update(MANDATORY_SEMANTIC_FIELDS)
    feature_row.update(MANDATORY_DEV_FLAGS)
    return feature_row


def build_rows(anomaly_df: pd.DataFrame, trend_df: pd.DataFrame) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    asset_cache: Dict[str, pd.DataFrame] = {}
    for _, anchor_row in anomaly_df.iterrows():
        feature_row = build_anchor_row(anchor_row, trend_df, asset_cache)
        if feature_row is not None:
            rows.append(feature_row)
    return rows


def main() -> None:
    args = parse_args()
    anomaly_df = load_anomaly_frame(Path(args.anomaly_csv))
    trend_df = load_trend_frame(Path(args.trend_history))
    rows = build_rows(anomaly_df, trend_df)
    paths = response_shape_file_paths(BOT_ID, output_root=OUTPUT_ROOT)
    checks = run_response_shape_output_checks(columns=REQUIRED_COLUMNS, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            bot_id=BOT_ID,
            input_refs=[
                str(Path(args.anomaly_csv)),
                str(Path(args.trend_history)),
                "data/ohlcv/*.csv",
                "data/ohlcv_phase67_top100/*.csv",
            ],
            features_csv_path=paths["features_csv"],
            quality_json_path=paths["quality_json"],
            profile_json_path=paths["profile_json"],
            column_schema=REQUIRED_COLUMNS,
            row_count=len(rows),
            lookahead_horizon_days=LOOKAHEAD_DAYS,
            contract_refs=[
                "research_os/dev_only/contracts/dev_only_response_shape_output_schema.contract.json",
                "research_os/dev_only/contracts/response_shape_bot_v1_anomaly_aligned.contract.json",
            ],
            spec_refs=[
                "research_os/dev_only/specs/dev_only_response_shape_anomaly_aligned_probe_runner.spec.json",
                "research_os/dev_only/specs/dev_only_response_shape_anomaly_aligned_profile_runner.spec.json",
            ],
            notes=[
                "anomaly_selected_anchor_mapping_only",
                "exact_date_and_entity_anchor_only",
                "descriptive_aftermath_only",
                "not_tradability_scoring",
                "not_official_edge_discovery",
            ],
            output_root=OUTPUT_ROOT,
        ),
    )
    save_json(
        paths["quality_json"],
        build_quality_report(
            bot_id=BOT_ID,
            row_count=len(rows),
            required_columns=REQUIRED_COLUMNS,
            leakage_checks=checks,
        ),
    )

    print(f"{BOT_ID} anomaly-aligned response-shape outputs generated")
    print(paths["features_csv"])
    print(paths["manifest_json"])
    print(paths["quality_json"])


if __name__ == "__main__":
    main()
