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
BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
TREND_HISTORY_PATH = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"

BOT_ID = "response_shape_bot_v1"
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
    parser = argparse.ArgumentParser(description="Build compact dev-only response-shape outputs")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--trend-history", type=str, default=str(TREND_HISTORY_PATH))
    return parser.parse_args()


def normalize_asset_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NAN", "NONE", "NULL", "NA"}:
        return ""
    if text.endswith("USDT"):
        return text[:-4]
    return text


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


def load_baseline_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()
    df["strategy_return"] = pd.to_numeric(df["strategy_return"], errors="coerce").fillna(0.0)
    df["executed_regime"] = df["executed_regime"].fillna("").astype(str).str.strip().str.upper()
    df["executed_position"] = df["executed_position"].fillna("").astype(str).str.strip().str.upper()
    if "chosen_asset" not in df.columns:
        df["chosen_asset"] = ""
    if "weekly_authorized_asset" not in df.columns:
        df["weekly_authorized_asset"] = ""
    df["chosen_asset"] = df["chosen_asset"].fillna("").astype(str)
    df["weekly_authorized_asset"] = df["weekly_authorized_asset"].fillna("").astype(str)
    selected_asset = df["weekly_authorized_asset"].map(normalize_asset_label)
    fallback_asset = df["chosen_asset"].map(normalize_asset_label)
    df["selected_asset"] = np.where(selected_asset == "", fallback_asset, selected_asset)
    return df


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


def build_event_row(frame: pd.DataFrame, event_idx: int, event_number: int) -> Dict[str, object] | None:
    if event_idx + LOOKAHEAD_DAYS >= len(frame):
        return None

    row = frame.iloc[event_idx]
    future_returns = frame["strategy_return"].iloc[event_idx + 1 : event_idx + 1 + LOOKAHEAD_DAYS].astype(float)
    if len(future_returns) < LOOKAHEAD_DAYS:
        return None

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

    trend_score = pd.to_numeric(pd.Series([row.get("trend_score")]), errors="coerce").iloc[0]
    context_label = trend_bucket(None if pd.isna(trend_score) else float(trend_score))
    response_regime_context = f"{row['executed_regime']}|{context_label}|{'named_asset' if row['selected_asset'] else 'no_named_asset'}"

    feature_row = {
        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
        "event_id": f"{pd.Timestamp(row['date']).strftime('%Y%m%d')}_{event_number:03d}",
        "event_type": "risk_on_entry",
        "entry_regime": str(row["executed_regime"]),
        "entry_position": str(row["executed_position"]),
        "selected_asset": "" if pd.isna(row["selected_asset"]) else f"{str(row['selected_asset'])}USDT",
        "trend_score": None if pd.isna(trend_score) else round_value(float(trend_score)),
        "trend_state_label": str(row.get("trend_state_label", "")),
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


def build_rows(baseline_df: pd.DataFrame, trend_df: pd.DataFrame) -> List[Dict[str, object]]:
    merged = baseline_df.merge(trend_df, on="date", how="left")
    active = merged["executed_regime"].ne("CASH")
    entry_mask = active & (~active.shift(1, fill_value=False))

    rows: List[Dict[str, object]] = []
    event_number = 0
    for event_idx in np.flatnonzero(entry_mask.to_numpy()):
        event_number += 1
        feature_row = build_event_row(merged, int(event_idx), event_number)
        if feature_row is not None:
            rows.append(feature_row)
    return rows


def main() -> None:
    args = parse_args()
    baseline_df = load_baseline_frame(Path(args.baseline_paper))
    trend_df = load_trend_frame(Path(args.trend_history))
    rows = build_rows(baseline_df, trend_df)
    paths = response_shape_file_paths(BOT_ID)
    checks = run_response_shape_output_checks(columns=REQUIRED_COLUMNS, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            bot_id=BOT_ID,
            input_refs=[
                str(Path(args.baseline_paper)),
                str(Path(args.trend_history)),
            ],
            features_csv_path=paths["features_csv"],
            quality_json_path=paths["quality_json"],
            profile_json_path=paths["profile_json"],
            column_schema=REQUIRED_COLUMNS,
            row_count=len(rows),
            lookahead_horizon_days=LOOKAHEAD_DAYS,
            contract_refs=[
                "research_os/dev_only/contracts/dev_only_response_shape_output_schema.contract.json",
                "research_os/dev_only/contracts/response_shape_bot_v1.contract.json",
            ],
            spec_refs=[
                "research_os/dev_only/specs/dev_only_response_shape_probe_runner.spec.json",
                "research_os/dev_only/specs/dev_only_response_shape_profile_runner.spec.json",
            ],
            notes=[
                "dev_only_response_shape_outputs_are_descriptive_only",
                "not_tradability_scoring",
                "not_candidate_quality",
                "not_leverage_guidance",
                "not_official_edge_discovery",
            ],
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

    print(f"{BOT_ID} response-shape outputs generated")
    print(paths["features_csv"])
    print(paths["manifest_json"])
    print(paths["quality_json"])


if __name__ == "__main__":
    main()
