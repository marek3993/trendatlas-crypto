from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "phase67e_guardrail_sweep"

PHASE67D_SUMMARY = (
    PROJECT_ROOT
    / "outputs"
    / "phase67d_weekly_shortlist_challenger_governance"
    / "phase67d_weekly_shortlist_challenger_summary.csv"
)
PHASE67D_DECISIONS = (
    PROJECT_ROOT
    / "outputs"
    / "phase67d_weekly_shortlist_challenger_governance"
    / "phase67d_weekly_shortlist_challenger_decisions.csv"
)

BASELINE_MODEL = "phase66g_production_soft_filters"
CHALLENGER_MODEL = "phase67d_weekly_challenger_base"

STRICT_INPUT_MODE = True

ATTRIBUTION_FILENAME = "recent_regime_attribution_2025_daily_behavior.csv"
ATTRIBUTION_CANDIDATES = [
    PROJECT_ROOT / "outputs" / "recent_regime_audit_2025" / ATTRIBUTION_FILENAME,
    PROJECT_ROOT / "outputs" / "phase67e_guardrail_sweep" / ATTRIBUTION_FILENAME,
    PROJECT_ROOT / "outputs" / "phase67d_weekly_shortlist_challenger_governance" / ATTRIBUTION_FILENAME,
    PROJECT_ROOT / "outputs" / ATTRIBUTION_FILENAME,
    PROJECT_ROOT / ATTRIBUTION_FILENAME,
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _local_now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@dataclass
class SavedArtifact:
    kind: str
    label: str
    path: str
    size_bytes: int
    rows: Optional[int] = None
    cols: Optional[int] = None


class ScriptRuntime:
    def __init__(self, script_name: Optional[str] = None, fail_on_empty_df: bool = True) -> None:
        self.script_name = script_name or Path(sys.argv[0]).name
        self.fail_on_empty_df = fail_on_empty_df
        self.started_monotonic = time.monotonic()
        self.saved_artifacts: List[SavedArtifact] = []
        self.counters: Dict[str, Any] = {}
        self.started = False
        self.finished = False

    def log(self, message: str) -> None:
        print(f"[{_local_now_iso()}] [{self.script_name}] {message}", flush=True)

    def start(self) -> None:
        if self.started:
            self.log("WARN start() called more than once")
            return
        self.started = True
        self.log("START")
        self.log(f"cwd={Path.cwd()}")
        self.log(f"python={sys.executable}")
        self.log(f"argv={' '.join(sys.argv)}")

    def finish_ok(self, extra: Optional[Dict[str, Any]] = None) -> None:
        self._finish("OK", extra)

    def finish_fail(self, error_message: Optional[str] = None) -> None:
        if error_message:
            self.log(f"ERROR {error_message}")
        self._finish("FAIL", None)

    def _finish(self, status: str, extra: Optional[Dict[str, Any]]) -> None:
        if self.finished:
            return
        self.finished = True
        elapsed_sec = time.monotonic() - self.started_monotonic
        self.log(f"END status={status} elapsed_sec={elapsed_sec:.3f}")
        for key, value in self.counters.items():
            self.log(f"SUMMARY {key}={value}")
        self.log(f"SUMMARY saved_files_count={len(self.saved_artifacts)}")
        for idx, item in enumerate(self.saved_artifacts, start=1):
            msg = (
                f"SAVED_FILE[{idx}] kind={item.kind} label={item.label} path={item.path} "
                f"size_bytes={item.size_bytes}"
            )
            if item.rows is not None:
                msg += f" rows={item.rows}"
            if item.cols is not None:
                msg += f" cols={item.cols}"
            self.log(msg)
        if extra:
            for key, value in extra.items():
                self.log(f"SUMMARY {key}={value}")

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value
        self.log(f"{key}={value}")

    def fail(self, message: str) -> None:
        self.log(f"FAIL {message}")
        raise RuntimeError(message)

    def require_dir(self, path: Path, label: str) -> Path:
        self.log(f"CHECK dir {label}: {path}")
        if not path.exists():
            self.fail(f"missing required directory: {path}")
        if not path.is_dir():
            self.fail(f"required path is not a directory: {path}")
        self.log(f"OK dir {label}")
        return path

    def require_file(self, path: Path, label: str) -> Path:
        self.log(f"CHECK file {label}: {path}")
        if not path.exists():
            self.fail(f"missing required file: {path}")
        if not path.is_file():
            self.fail(f"required path is not a file: {path}")
        self.log(f"OK file {label}: size_bytes={path.stat().st_size}")
        return path

    def require_non_empty_df(self, df: pd.DataFrame, label: str) -> pd.DataFrame:
        rows, cols = df.shape
        self.log(f"CHECK df {label}: rows={rows} cols={cols}")
        if self.fail_on_empty_df and rows == 0:
            self.fail(f"{label} is empty")
        return df

    def note_df(self, df: pd.DataFrame, label: str) -> None:
        rows, cols = df.shape
        self.log(f"DF {label}: rows={rows} cols={cols}")

    def save_csv(self, df: pd.DataFrame, path: Path, label: str, index: bool = False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.fail_on_empty_df and len(df) == 0:
            self.fail(f"refusing to save empty DataFrame to CSV: {path}")
        df.to_csv(path, index=index)
        size = path.stat().st_size
        rows, cols = df.shape
        self.saved_artifacts.append(
            SavedArtifact(kind="csv", label=label, path=str(path), size_bytes=size, rows=rows, cols=cols)
        )
        self.log(f"SAVED kind=csv label={label} path={path} rows={rows} cols={cols} size_bytes={size}")
        return path

    def save_text(self, text: str, path: Path, label: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        size = path.stat().st_size
        self.saved_artifacts.append(SavedArtifact(kind="txt", label=label, path=str(path), size_bytes=size))
        self.log(f"SAVED kind=txt label={label} path={path} size_bytes={size}")
        return path

    def save_json(self, obj: Any, path: Path, label: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        size = path.stat().st_size
        self.saved_artifacts.append(SavedArtifact(kind="json", label=label, path=str(path), size_bytes=size))
        self.log(f"SAVED kind=json label={label} path={path} size_bytes={size}")
        return path


def run_script(main_func, *, script_name: Optional[str] = None, fail_on_empty_df: bool = True) -> None:
    rt = ScriptRuntime(script_name=script_name, fail_on_empty_df=fail_on_empty_df)
    try:
        rt.start()
        result = main_func(rt)
        if isinstance(result, dict):
            rt.finish_ok(result)
        else:
            rt.finish_ok()
    except Exception as exc:
        rt.log(f"EXCEPTION type={type(exc).__name__} message={exc}")
        for line in traceback.format_exc().rstrip().splitlines():
            rt.log(f"TRACE {line}")
        rt.finish_fail(str(exc))
        raise


def build_basic_manifest(
    *,
    dataset_name: str,
    source_files: List[Path],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    files_out: List[Dict[str, Any]] = []
    for path in source_files:
        files_out.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "modified_utc": (
                    datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    if path.exists()
                    else None
                ),
            }
        )

    payload: Dict[str, Any] = {
        "dataset_name": dataset_name,
        "built_at_utc": _utc_now_iso(),
        "script": Path(sys.argv[0]).name,
        "cwd": str(Path.cwd()),
        "python": sys.executable,
        "files": files_out,
    }
    if extra:
        payload["extra"] = extra
    return payload


@dataclass(frozen=True)
class GuardrailConfig:
    config_id: str
    promotion_margin: float
    persistence_weeks: int
    cooldown_days: int
    downside_lookback_days: int
    bnb_shield_margin: float


def load_summary(rt: ScriptRuntime) -> pd.DataFrame:
    path = rt.require_file(PHASE67D_SUMMARY, label="phase67d_summary")
    df = pd.read_csv(path)
    rt.require_non_empty_df(df, label="phase67d_summary_df")
    rt.note_df(df, label="phase67d_summary_df")
    return df


def load_decisions(rt: ScriptRuntime) -> pd.DataFrame:
    path = rt.require_file(PHASE67D_DECISIONS, label="phase67d_decisions")
    df = pd.read_csv(path)
    rt.require_non_empty_df(df, label="phase67d_decisions_df")
    for col in ["decision_date", "period_start", "period_end"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    rt.note_df(df, label="phase67d_decisions_df")
    return df


def resolve_attribution_2025_path_strict(rt: ScriptRuntime) -> Path:
    rt.log("CHECK attribution candidates start")
    found: List[Path] = []

    for path in ATTRIBUTION_CANDIDATES:
        rt.log(f"ATTRIBUTION_CANDIDATE path={path}")
        if path.exists() and path.is_file():
            found.append(path.resolve())

    unique_found: List[Path] = []
    seen = set()
    for path in found:
        key = str(path)
        if key not in seen:
            unique_found.append(path)
            seen.add(key)

    if not unique_found:
        rt.fail(
            "strict mode: attribution file nebol nájdený v žiadnej povolenej ceste. "
            f"candidates={ATTRIBUTION_CANDIDATES}"
        )

    if len(unique_found) > 1:
        rt.fail(
            "strict mode: našlo sa viac attribution candidate súborov; "
            f"očakávaný je presne 1. found={unique_found}"
        )

    chosen = unique_found[0]
    rt.log(f"ATTRIBUTION status=resolved path={chosen}")
    return chosen


def build_attribution_quality(rt: ScriptRuntime, df: pd.DataFrame, path: Path) -> Dict[str, Any]:
    ts_min = None
    ts_max = None
    if "ts" in df.columns and len(df) > 0:
        ts_min = df["ts"].min()
        ts_max = df["ts"].max()

    quality = {
        "input_mode": "strict",
        "path": str(path),
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "ts_null_rows": int(df["ts"].isna().sum()) if "ts" in df.columns else None,
        "ts_min": None if ts_min is None or pd.isna(ts_min) else str(ts_min),
        "ts_max": None if ts_max is None or pd.isna(ts_max) else str(ts_max),
        "same_selection_null_rows": int(df["same_selection"].isna().sum()) if "same_selection" in df.columns else None,
        "ret_diff_null_rows": int(df["ret_diff_main_minus_leader"].isna().sum()) if "ret_diff_main_minus_leader" in df.columns else None,
        "unique_main_assets": sorted(df["main_selected"].dropna().astype(str).unique().tolist())
        if "main_selected" in df.columns
        else [],
        "unique_leader_assets": sorted(df["leader_selected"].dropna().astype(str).unique().tolist())
        if "leader_selected" in df.columns
        else [],
    }
    rt.log(
        "ATTRIBUTION_QUALITY "
        f"rows={quality['rows']} cols={quality['cols']} "
        f"ts_min={quality['ts_min']} ts_max={quality['ts_max']} "
        f"ts_null_rows={quality['ts_null_rows']}"
    )
    return quality


def load_attribution_2025_strict(rt: ScriptRuntime) -> Tuple[pd.DataFrame, Path, Dict[str, Any]]:
    path = resolve_attribution_2025_path_strict(rt)
    df = pd.read_csv(path)
    rt.require_non_empty_df(df, label="attribution_2025_df")

    required_cols = {"ts", "same_selection", "ret_diff_main_minus_leader"}
    missing_cols = sorted(required_cols - set(df.columns))
    if missing_cols:
        rt.fail(f"strict mode: attribution file missing required columns {missing_cols}: {path}")

    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    bad_ts = int(df["ts"].isna().sum())
    rt.log(f"ATTRIBUTION ts_null_rows={bad_ts}")
    if bad_ts > 0:
        rt.fail(f"strict mode: attribution file má nevalidné ts hodnoty. ts_null_rows={bad_ts} path={path}")

    null_ret_diff = int(df["ret_diff_main_minus_leader"].isna().sum())
    if null_ret_diff > 0:
        rt.fail(
            "strict mode: attribution file má null v 'ret_diff_main_minus_leader'. "
            f"null_rows={null_ret_diff} path={path}"
        )

    null_same_selection = int(df["same_selection"].isna().sum())
    if null_same_selection > 0:
        rt.fail(
            "strict mode: attribution file má null v 'same_selection'. "
            f"null_rows={null_same_selection} path={path}"
        )

    rt.note_df(df, label="attribution_2025_df")
    quality = build_attribution_quality(rt, df, path)
    return df, path, quality


def get_model_row(summary_df: pd.DataFrame, model_name: str) -> pd.Series:
    rows = summary_df.loc[summary_df["model"] == model_name]
    if rows.empty:
        raise ValueError(f"Model '{model_name}' neexistuje v summary.")
    return rows.iloc[0]


def summarize_2025_damage_strict(
    attrib_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    diff = attrib_df.loc[attrib_df["same_selection"] == False].copy()  # noqa: E712
    diff["month"] = diff["ts"].dt.to_period("M").astype(str)

    by_month = (
        diff.groupby("month", dropna=False)["ret_diff_main_minus_leader"]
        .agg(diff_days="count", diff_sum="sum", diff_mean="mean")
        .reset_index()
        .sort_values("diff_sum")
    )

    main_col = "main_selected" if "main_selected" in diff.columns else None
    leader_col = "leader_selected" if "leader_selected" in diff.columns else None

    if main_col is not None:
        by_main = (
            diff.groupby(main_col, dropna=False)["ret_diff_main_minus_leader"]
            .agg(diff_days="count", diff_sum="sum", diff_mean="mean")
            .reset_index()
            .sort_values("diff_sum")
        )
    else:
        by_main = pd.DataFrame(columns=["main_selected", "diff_days", "diff_sum", "diff_mean"])

    if leader_col is not None:
        by_leader = (
            diff.groupby(leader_col, dropna=False)["ret_diff_main_minus_leader"]
            .agg(diff_days="count", diff_sum="sum", diff_mean="mean")
            .reset_index()
            .sort_values("diff_sum")
        )
    else:
        by_leader = pd.DataFrame(columns=["leader_selected", "diff_days", "diff_sum", "diff_mean"])

    metrics = {
        "all_days_2025": float(len(attrib_df)),
        "different_selection_days_2025": float(len(diff)),
        "different_selection_days_pct_2025": float(len(diff) / len(attrib_df) * 100.0) if len(attrib_df) else 0.0,
        "sum_ret_diff_main_minus_leader": float(diff["ret_diff_main_minus_leader"].sum()) if len(diff) else 0.0,
        "avg_ret_diff_main_minus_leader": float(diff["ret_diff_main_minus_leader"].mean()) if len(diff) else 0.0,
        "worst_day_ret_diff_main_minus_leader": float(diff["ret_diff_main_minus_leader"].min()) if len(diff) else 0.0,
        "damage_data_available": 1.0,
    }
    return by_month, by_main, by_leader, metrics


def summarize_weekly_decisions(decisions_df: pd.DataFrame) -> pd.DataFrame:
    if "profile" not in decisions_df.columns:
        raise ValueError("Decisions file nemá stĺpec 'profile'.")
    if "decision_date" not in decisions_df.columns:
        raise ValueError("Decisions file nemá stĺpec 'decision_date'.")
    if "selected_asset" not in decisions_df.columns:
        raise ValueError("Decisions file nemá stĺpec 'selected_asset'.")

    base = decisions_df.loc[decisions_df["profile"] == CHALLENGER_MODEL].copy()
    if base.empty:
        available_profiles = sorted(decisions_df["profile"].dropna().astype(str).unique().tolist())
        raise ValueError(
            f"V decisions nie je profil '{CHALLENGER_MODEL}'. "
            f"Dostupné profily: {available_profiles[:10]}"
        )

    named_aggs = {
        "rows": ("selected_asset", "count"),
        "selected_asset": ("selected_asset", "last"),
    }

    optional_cols = [
        "selected",
        "keep_reason",
        "best_passed_asset",
        "best_passed_score",
        "selected_score",
        "core_score",
    ]
    for col in optional_cols:
        if col in base.columns:
            named_aggs[col] = (col, "last")

    weekly = (
        base.groupby("decision_date", dropna=False)
        .agg(**named_aggs)
        .reset_index()
        .sort_values("decision_date")
    )

    weekly["selected_asset"] = weekly["selected_asset"].fillna("CORE")
    weekly["selected_asset_prev"] = weekly["selected_asset"].shift(1)
    weekly["asset_changed"] = (weekly["selected_asset"] != weekly["selected_asset_prev"]).fillna(False)

    streaks: List[int] = []
    streak = 0
    prev_asset: Optional[str] = None
    for asset in weekly["selected_asset"].astype(str):
        if asset == prev_asset:
            streak += 1
        else:
            streak = 1
            prev_asset = asset
        streaks.append(streak)
    weekly["hold_streak_weeks"] = streaks

    weekly["is_core"] = weekly["selected_asset"].astype(str).str.upper().isin(["CORE", "BASELINE"])
    weekly["is_challenger"] = ~weekly["is_core"]

    if "best_passed_asset" in weekly.columns:
        weekly["best_passed_asset"] = weekly["best_passed_asset"].fillna("CORE")

    return weekly


def build_guardrail_grid() -> List[GuardrailConfig]:
    configs: List[GuardrailConfig] = []
    idx = 1
    for promotion_margin in [0.00, 0.01, 0.02, 0.03]:
        for persistence_weeks in [1, 2]:
            for cooldown_days in [0, 7, 14]:
                for downside_lookback_days in [21, 42, 63]:
                    for bnb_shield_margin in [0.00, 0.01, 0.02]:
                        configs.append(
                            GuardrailConfig(
                                config_id=f"g{idx:03d}",
                                promotion_margin=promotion_margin,
                                persistence_weeks=persistence_weeks,
                                cooldown_days=cooldown_days,
                                downside_lookback_days=downside_lookback_days,
                                bnb_shield_margin=bnb_shield_margin,
                            )
                        )
                        idx += 1
    return configs


def get_damage_context(
    by_month: pd.DataFrame,
    by_main: pd.DataFrame,
    by_leader: pd.DataFrame,
) -> Tuple[Optional[pd.Series], Optional[pd.Series], Optional[pd.Series]]:
    worst_month_row = by_month.iloc[0] if not by_month.empty else None
    worst_main_row = by_main.iloc[0] if not by_main.empty else None
    worst_leader_row = by_leader.iloc[0] if not by_leader.empty else None
    return worst_month_row, worst_main_row, worst_leader_row


def estimate_config_score(
    cfg: GuardrailConfig,
    baseline_row: pd.Series,
    challenger_row: pd.Series,
    damage_metrics: Dict[str, float],
    by_month: pd.DataFrame,
    by_main: pd.DataFrame,
    by_leader: pd.DataFrame,
    weekly_decisions: pd.DataFrame,
) -> Dict[str, float]:
    since2025_gap_vs_66g = float(challenger_row["since2025_cagr_pct"] - baseline_row["since2025_cagr_pct"])
    dd_gap_vs_66g = float(challenger_row["max_drawdown_pct"] - baseline_row["max_drawdown_pct"])
    full_history_lift_vs_66g = float(challenger_row["cagr_pct"] - baseline_row["cagr_pct"])
    since2023_lift_vs_66g = float(challenger_row["since2023_cagr_pct"] - baseline_row["since2023_cagr_pct"])

    worst_month_row, worst_main_row, worst_leader_row = get_damage_context(by_month, by_main, by_leader)

    damage_available = bool(damage_metrics.get("damage_data_available", 0.0) > 0.0)
    worst_month_damage = abs(float(worst_month_row["diff_sum"])) if worst_month_row is not None else 0.0
    worst_main_damage = abs(float(worst_main_row["diff_sum"])) if worst_main_row is not None else 0.0
    worst_leader_damage = abs(float(worst_leader_row["diff_sum"])) if worst_leader_row is not None else 0.0

    leader_name = ""
    if worst_leader_row is not None and "leader_selected" in worst_leader_row.index:
        leader_name = str(worst_leader_row["leader_selected"]).upper()
    leader_is_bnb = 1.0 if "BNB" in leader_name else 0.0

    change_count = float(weekly_decisions["asset_changed"].sum()) if not weekly_decisions.empty else 0.0
    median_hold = float(weekly_decisions["hold_streak_weeks"].median()) if not weekly_decisions.empty else 1.0
    challenger_weeks = float(weekly_decisions["is_challenger"].sum()) if not weekly_decisions.empty else 0.0

    promotion_fit = {0.00: 0.35, 0.01: 0.90, 0.02: 1.00, 0.03: 0.75}[cfg.promotion_margin]
    persistence_fit = {1: 0.60, 2: 1.00}[cfg.persistence_weeks]
    cooldown_fit = {0: 0.45, 7: 1.00, 14: 0.82}[cfg.cooldown_days]
    downside_fit = {21: 0.65, 42: 1.00, 63: 0.92}[cfg.downside_lookback_days]
    bnb_shield_fit = {0.00: 0.45, 0.01: 1.00, 0.02: 0.82}[cfg.bnb_shield_margin]

    strictness_penalty = 0.0
    if cfg.promotion_margin >= 0.03:
        strictness_penalty += 0.40
    if cfg.persistence_weeks >= 2 and cfg.cooldown_days >= 14:
        strictness_penalty += 0.35
    if cfg.promotion_margin >= 0.02 and cfg.bnb_shield_margin >= 0.02:
        strictness_penalty += 0.30

    score = 0.0
    score += 45.0 * promotion_fit
    score += 35.0 * persistence_fit
    score += 30.0 * cooldown_fit
    score += 40.0 * downside_fit

    if damage_available:
        score += 55.0 * bnb_shield_fit * leader_is_bnb
        score += 12.0 * min(worst_month_damage / 0.10, 3.0)
        score += 8.0 * min(worst_main_damage / 0.05, 3.0)
        score += 14.0 * min(worst_leader_damage / 0.10, 3.0)
    else:
        score += 18.0 * bnb_shield_fit
        score += 8.0 if cfg.promotion_margin >= 0.01 else 0.0
        score += 6.0 if cfg.persistence_weeks >= 2 else 0.0
        score += 5.0 if cfg.downside_lookback_days >= 42 else 0.0

    score += 0.40 * full_history_lift_vs_66g
    score += 0.35 * since2023_lift_vs_66g
    score -= 4.50 * abs(since2025_gap_vs_66g)
    score -= 1.75 * abs(dd_gap_vs_66g)

    score += 4.0 * min(change_count / 20.0, 2.0)
    score += 2.0 * min(median_hold / 4.0, 2.0)
    score += 2.0 * min(challenger_weeks / 20.0, 2.0)

    score -= 25.0 * strictness_penalty

    est_since2025_repair = 0.0
    est_since2025_repair += 0.7 if cfg.promotion_margin >= 0.01 else 0.0
    est_since2025_repair += 0.9 if cfg.persistence_weeks >= 2 else 0.0
    est_since2025_repair += 0.7 if cfg.cooldown_days >= 7 else 0.0
    est_since2025_repair += 0.8 if cfg.downside_lookback_days >= 42 else 0.0
    est_since2025_repair += 1.2 if cfg.bnb_shield_margin >= 0.01 else 0.0

    if not damage_available:
        est_since2025_repair *= 0.75

    est_full_history_lift_retained = full_history_lift_vs_66g
    est_full_history_lift_retained -= 2.2 if cfg.promotion_margin >= 0.02 else 0.0
    est_full_history_lift_retained -= 1.3 if cfg.persistence_weeks >= 2 else 0.0
    est_full_history_lift_retained -= 1.0 if cfg.cooldown_days >= 14 else 0.0
    est_full_history_lift_retained -= 0.8 if cfg.bnb_shield_margin >= 0.02 else 0.0

    est_dd_help = 0.0
    est_dd_help += 0.5 if cfg.promotion_margin >= 0.01 else 0.0
    est_dd_help += 0.5 if cfg.persistence_weeks >= 2 else 0.0
    est_dd_help += 0.8 if cfg.downside_lookback_days >= 42 else 0.0
    est_dd_help += 0.5 if cfg.cooldown_days >= 7 else 0.0

    return {
        "score": round(score, 6),
        "est_since2025_repair_pct_pts": round(est_since2025_repair, 4),
        "est_full_history_lift_retained_pct_pts": round(est_full_history_lift_retained, 4),
        "est_dd_help_pct_pts": round(est_dd_help, 4),
        "base_full_history_lift_vs_66g_pct_pts": round(full_history_lift_vs_66g, 4),
        "base_since2023_lift_vs_66g_pct_pts": round(since2023_lift_vs_66g, 4),
        "base_since2025_gap_vs_66g_pct_pts": round(since2025_gap_vs_66g, 4),
        "base_dd_gap_vs_66g_pct_pts": round(dd_gap_vs_66g, 4),
        "damage_data_available": int(damage_available),
    }


def build_recommendation_table(
    baseline_row: pd.Series,
    challenger_row: pd.Series,
    by_month: pd.DataFrame,
    by_main: pd.DataFrame,
    by_leader: pd.DataFrame,
    damage_metrics: Dict[str, float],
    weekly_decisions: pd.DataFrame,
) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []
    for cfg in build_guardrail_grid():
        score_dict = estimate_config_score(
            cfg=cfg,
            baseline_row=baseline_row,
            challenger_row=challenger_row,
            damage_metrics=damage_metrics,
            by_month=by_month,
            by_main=by_main,
            by_leader=by_leader,
            weekly_decisions=weekly_decisions,
        )
        row = asdict(cfg)
        row.update(score_dict)
        rows.append(row)

    df = pd.DataFrame(rows)
    df["profile_label"] = (
        "pm" + df["promotion_margin"].map(lambda x: f"{x:.2f}")
        + "_pw" + df["persistence_weeks"].astype(str)
        + "_cd" + df["cooldown_days"].astype(str)
        + "_dl" + df["downside_lookback_days"].astype(str)
        + "_bs" + df["bnb_shield_margin"].map(lambda x: f"{x:.2f}")
    )
    df = df.sort_values(
        by=["score", "est_since2025_repair_pct_pts", "est_dd_help_pct_pts", "est_full_history_lift_retained_pct_pts"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    return df


def safe_str(value: object) -> str:
    if pd.isna(value):
        return "N/A"
    return str(value)


def build_top_findings_text(
    baseline_row: pd.Series,
    challenger_row: pd.Series,
    damage_metrics: Dict[str, float],
    by_month: pd.DataFrame,
    by_main: pd.DataFrame,
    by_leader: pd.DataFrame,
    weekly_decisions: pd.DataFrame,
    ranked_df: pd.DataFrame,
    attribution_path: Path,
) -> str:
    worst_month_row, worst_main_row, worst_leader_row = get_damage_context(by_month, by_main, by_leader)
    best_row = ranked_df.iloc[0]
    second_row = ranked_df.iloc[1] if len(ranked_df) > 1 else best_row
    third_row = ranked_df.iloc[2] if len(ranked_df) > 2 else best_row

    change_count = int(weekly_decisions["asset_changed"].sum()) if not weekly_decisions.empty else 0
    median_hold = float(weekly_decisions["hold_streak_weeks"].median()) if not weekly_decisions.empty else 0.0
    challenger_weeks = int(weekly_decisions["is_challenger"].sum()) if not weekly_decisions.empty else 0

    lines: List[str] = []
    lines.append("=== PHASE67E GUARDRAIL SWEEP PLANNER ===")
    lines.append("")
    lines.append("Input mode")
    lines.append("- strict")
    lines.append(f"- attribution source: {attribution_path}")
    lines.append("")
    lines.append("Baseline vs latest challenger baseline")
    lines.append(
        f"- {BASELINE_MODEL}: CAGR {baseline_row['cagr_pct']:.2f} | Max DD {baseline_row['max_drawdown_pct']:.2f} | "
        f"since2023 {baseline_row['since2023_cagr_pct']:.2f} | since2025 {baseline_row['since2025_cagr_pct']:.2f}"
    )
    lines.append(
        f"- {CHALLENGER_MODEL}: CAGR {challenger_row['cagr_pct']:.2f} | Max DD {challenger_row['max_drawdown_pct']:.2f} | "
        f"since2023 {challenger_row['since2023_cagr_pct']:.2f} | since2025 {challenger_row['since2025_cagr_pct']:.2f}"
    )
    lines.append("")
    lines.append("2025 damage concentration")
    lines.append(
        f"- different selection days: {int(damage_metrics['different_selection_days_2025'])} / "
        f"{int(damage_metrics['all_days_2025'])} ({damage_metrics['different_selection_days_pct_2025']:.2f}%)"
    )
    lines.append(
        f"- total ret diff main minus leader on different days: "
        f"{damage_metrics['sum_ret_diff_main_minus_leader']:.6f}"
    )
    lines.append(
        f"- worst single different day diff: {damage_metrics['worst_day_ret_diff_main_minus_leader']:.6f}"
    )
    if worst_month_row is not None:
        lines.append(
            f"- worst month: {safe_str(worst_month_row.get('month'))} | "
            f"diff_sum {float(worst_month_row['diff_sum']):.6f} | diff_days {int(worst_month_row['diff_days'])}"
        )
    if worst_main_row is not None:
        main_name = safe_str(worst_main_row.get("main_selected"))
        lines.append(
            f"- worst main asset on differing days: {main_name} | "
            f"diff_sum {float(worst_main_row['diff_sum']):.6f} | diff_days {int(worst_main_row['diff_days'])}"
        )
    if worst_leader_row is not None:
        leader_name = safe_str(worst_leader_row.get("leader_selected"))
        lines.append(
            f"- worst leader asset on differing days: {leader_name} | "
            f"diff_sum {float(worst_leader_row['diff_sum']):.6f} | diff_days {int(worst_leader_row['diff_days'])}"
        )
    lines.append("")
    lines.append("Weekly challenger baseline behavior")
    lines.append(f"- weekly asset changes: {change_count}")
    lines.append(f"- challenger weeks: {challenger_weeks}")
    lines.append(f"- median hold streak weeks: {median_hold:.2f}")
    lines.append("")
    lines.append("Top recommended Phase67E configs to backtest next")
    for rank, row in enumerate([best_row, second_row, third_row], start=1):
        lines.append(
            f"{rank}. {row['profile_label']} | "
            f"score {row['score']:.2f} | "
            f"est_2025_repair +{row['est_since2025_repair_pct_pts']:.2f} p.b. | "
            f"est_DD_help +{row['est_dd_help_pct_pts']:.2f} p.b. | "
            f"est_lift_retained {row['est_full_history_lift_retained_pct_pts']:.2f} p.b."
        )

    lines.append("")
    lines.append("Recommended exact first run set")
    lines.append(f"- winner_candidate_1 = {best_row['profile_label']}")
    lines.append(f"- winner_candidate_2 = {second_row['profile_label']}")
    lines.append(f"- winner_candidate_3 = {third_row['profile_label']}")
    lines.append("")
    lines.append("Interpretation")
    lines.append("- priorita: promotion margin + 2-week persistence + 42d downside lookback")
    lines.append("- BNB shield nechaj v first pass sete")
    lines.append("- cieľ first passu: opraviť 2025 / DD bez zabitia 67D liftu")
    return "\n".join(lines)


def main(rt: ScriptRuntime):
    rt.require_dir(PROJECT_ROOT, label="project_root")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rt.require_dir(OUTPUT_DIR, label="phase67e_output_dir")

    summary_df = load_summary(rt)
    decisions_df = load_decisions(rt)

    if not STRICT_INPUT_MODE:
        rt.fail("STRICT_INPUT_MODE musí byť True pre túto verziu skriptu.")

    attrib_df, attribution_path, attribution_quality = load_attribution_2025_strict(rt)

    baseline_row = get_model_row(summary_df, BASELINE_MODEL)
    challenger_row = get_model_row(summary_df, CHALLENGER_MODEL)

    by_month, by_main, by_leader, damage_metrics = summarize_2025_damage_strict(attrib_df)
    weekly_decisions = summarize_weekly_decisions(decisions_df)
    ranked_df = build_recommendation_table(
        baseline_row=baseline_row,
        challenger_row=challenger_row,
        by_month=by_month,
        by_main=by_main,
        by_leader=by_leader,
        damage_metrics=damage_metrics,
        weekly_decisions=weekly_decisions,
    )

    rt.require_non_empty_df(ranked_df, label="phase67e_ranked_df")
    rt.note_df(ranked_df.head(20), label="phase67e_ranked_top20_preview")
    rt.note_df(weekly_decisions, label="phase67e_weekly_decisions")

    top20_path = OUTPUT_DIR / "phase67e_guardrail_ranked_top20.csv"
    ranked_all_path = OUTPUT_DIR / "phase67e_guardrail_ranked_all.csv"
    by_month_path = OUTPUT_DIR / "phase67e_2025_damage_by_month.csv"
    by_main_path = OUTPUT_DIR / "phase67e_2025_damage_by_main_asset.csv"
    by_leader_path = OUTPUT_DIR / "phase67e_2025_damage_by_leader_asset.csv"
    weekly_path = OUTPUT_DIR / "phase67e_weekly_decision_behavior.csv"
    text_path = OUTPUT_DIR / "phase67e_guardrail_verdict.txt"
    manifest_path = OUTPUT_DIR / "phase67e_input_manifest.json"
    quality_path = OUTPUT_DIR / "phase67e_attribution_input_quality.json"

    rt.save_csv(ranked_df.head(20), top20_path, label="phase67e_guardrail_ranked_top20")
    rt.save_csv(ranked_df, ranked_all_path, label="phase67e_guardrail_ranked_all")
    rt.save_csv(by_month, by_month_path, label="phase67e_2025_damage_by_month")
    rt.save_csv(by_main, by_main_path, label="phase67e_2025_damage_by_main_asset")
    rt.save_csv(by_leader, by_leader_path, label="phase67e_2025_damage_by_leader_asset")
    rt.save_csv(weekly_decisions, weekly_path, label="phase67e_weekly_decision_behavior")

    verdict_text = build_top_findings_text(
        baseline_row=baseline_row,
        challenger_row=challenger_row,
        damage_metrics=damage_metrics,
        by_month=by_month,
        by_main=by_main,
        by_leader=by_leader,
        weekly_decisions=weekly_decisions,
        ranked_df=ranked_df,
        attribution_path=attribution_path,
    )
    rt.save_text(verdict_text, text_path, label="phase67e_guardrail_verdict")
    rt.save_json(attribution_quality, quality_path, label="phase67e_attribution_input_quality")

    source_files: List[Path] = [
        PHASE67D_SUMMARY,
        PHASE67D_DECISIONS,
        attribution_path,
        top20_path,
        ranked_all_path,
        by_month_path,
        by_main_path,
        by_leader_path,
        weekly_path,
        text_path,
        quality_path,
    ]

    manifest_extra = {
        "input_mode": "strict",
        "strict_input_mode": True,
        "baseline_model": BASELINE_MODEL,
        "challenger_model": CHALLENGER_MODEL,
        "attribution_path": str(attribution_path),
        "damage_data_available": int(damage_metrics.get("damage_data_available", 0.0)),
        "summary_rows": int(len(summary_df)),
        "decisions_rows": int(len(decisions_df)),
        "attribution_rows": int(len(attrib_df)),
        "weekly_rows": int(len(weekly_decisions)),
        "ranked_rows": int(len(ranked_df)),
        "top_profile_label": str(ranked_df.iloc[0]["profile_label"]),
        "top_score": float(ranked_df.iloc[0]["score"]),
    }
    manifest = build_basic_manifest(
        dataset_name="phase67e_guardrail_sweep",
        source_files=source_files,
        extra=manifest_extra,
    )
    rt.save_json(manifest, manifest_path, label="phase67e_input_manifest")

    best = ranked_df.iloc[0]
    rt.log("TOP_RECOMMENDATION")
    rt.log(f"profile_label={best['profile_label']}")
    rt.log(f"score={best['score']:.2f}")
    rt.log(f"est_since2025_repair_pct_pts={best['est_since2025_repair_pct_pts']:.2f}")
    rt.log(f"est_dd_help_pct_pts={best['est_dd_help_pct_pts']:.2f}")
    rt.log(f"est_full_history_lift_retained_pct_pts={best['est_full_history_lift_retained_pct_pts']:.2f}")

    rt.set_counter("summary_rows", len(summary_df))
    rt.set_counter("decisions_rows", len(decisions_df))
    rt.set_counter("attribution_rows", len(attrib_df))
    rt.set_counter("weekly_rows", len(weekly_decisions))
    rt.set_counter("ranked_rows", len(ranked_df))
    rt.set_counter("damage_data_available", int(damage_metrics.get("damage_data_available", 0.0)))
    rt.set_counter("different_selection_days_2025", int(damage_metrics.get("different_selection_days_2025", 0.0)))
    rt.set_counter("top_score", float(best["score"]))

    return {
        "input_mode": "strict",
        "top_profile_label": str(best["profile_label"]),
        "manifest_path": str(manifest_path),
        "quality_path": str(quality_path),
        "attribution_path": str(attribution_path),
    }


if __name__ == "__main__":
    run_script(
        main,
        script_name=Path(__file__).name,
        fail_on_empty_df=False,
    )