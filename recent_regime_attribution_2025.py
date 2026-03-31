from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
AUDIT_DIR = OUTPUTS / "recent_regime_audit_2025"

RECENT_EQUITY_PATH = AUDIT_DIR / "recent_regime_audit_2025_equity_curves.csv"

START_DATE = "2025-01-01"
TRADING_DAYS_PER_YEAR = 365.25

MAIN_KEY = "phase45_without_BNBUSDT"
LEADER_KEY = "phase42_full12"

STRICT_INPUT_MODE = True

MODEL_LABELS = {
    MAIN_KEY: "Hlavna strategia",
    LEADER_KEY: "Predosly lider",
}

# exact deterministic upstream inputs
MAIN_DAILY_PAPER_PATH = OUTPUTS / "phase49_final_compare" / "phase49_no_bnb_baseline_paper.csv"
LEADER_DAILY_PAPER_PATH = OUTPUTS / "phase59_bnb_selective_restore" / "phase59_phase42_core_paper.csv"


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

    def save_json(self, obj: Any, path: Path, label: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        size = path.stat().st_size
        self.saved_artifacts.append(SavedArtifact(kind="json", label=label, path=str(path), size_bytes=size))
        self.log(f"SAVED kind=json label={label} path={path} size_bytes={size}")
        return path

    def save_text(self, text: str, path: Path, label: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        size = path.stat().st_size
        self.saved_artifacts.append(SavedArtifact(kind="txt", label=label, path=str(path), size_bytes=size))
        self.log(f"SAVED kind=txt label={label} path={path} size_bytes={size}")
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


def compute_metrics_from_equity(ts: pd.Series, eq: pd.Series) -> dict:
    df = pd.DataFrame({"ts": pd.to_datetime(ts), "equity": pd.to_numeric(eq, errors="coerce")})
    df = df.dropna().sort_values("ts").copy()
    if df.empty or len(df) < 2:
        raise ValueError("equity séria je prázdna alebo príliš krátka na metriky")

    df["ret"] = df["equity"].pct_change().fillna(0.0)

    total_return = float(df["equity"].iloc[-1] / df["equity"].iloc[0] - 1.0)
    span_days = max((df["ts"].iloc[-1] - df["ts"].iloc[0]).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float((df["equity"].iloc[-1] / df["equity"].iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = df["equity"] / df["equity"].cummax() - 1.0
    max_dd = float(dd.min())

    r = df["ret"].copy()
    worst_day = float(r.min())

    worst_3d = None
    if len(r) >= 3:
        worst_3d = float(((1.0 + r).rolling(3).apply(np.prod, raw=True) - 1.0).min())

    worst_5d = None
    if len(r) >= 5:
        worst_5d = float(((1.0 + r).rolling(5).apply(np.prod, raw=True) - 1.0).min())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "worst_day_pct": round(worst_day * 100.0, 2) if worst_day is not None else None,
        "worst_3d_pct": round(worst_3d * 100.0, 2) if worst_3d is not None else None,
        "worst_5d_pct": round(worst_5d * 100.0, 2) if worst_5d is not None else None,
        "days": int(len(df)),
    }


def normalize_ts_col(df: pd.DataFrame) -> pd.DataFrame:
    ts_col = None
    for c in ["ts", "timestamp", "date", "datetime"]:
        if c in df.columns:
            ts_col = c
            break

    if ts_col is None:
        unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
        if unnamed:
            ts_col = unnamed[0]

    if ts_col is None:
        raise ValueError("Subor nema casovy stlpec")

    df = df.copy()
    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).copy()
    df = df.rename(columns={ts_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    return df.sort_values("ts")


def looks_like_daily_paper(df: pd.DataFrame) -> bool:
    cols = set(df.columns)
    required_one = {"selected", "gross_exposure", "strategy_ret"}
    return len(required_one.intersection(cols)) >= 2


def prepare_daily_paper(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalize_ts_col(df)

    for col in ["strategy_ret", "gross_exposure", "turnover", "selected_ret_next", "best_available_next", "equity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "selected" not in df.columns:
        df["selected"] = "UNKNOWN"
    df["selected"] = df["selected"].fillna("UNKNOWN").astype(str)

    if "gross_exposure" not in df.columns:
        df["gross_exposure"] = np.where(df["selected"] != "CASH", 1.0, 0.0)

    if "strategy_ret" not in df.columns:
        if "equity" in df.columns:
            df["strategy_ret"] = df["equity"].pct_change().fillna(0.0)
        else:
            raise ValueError(f"{path} nema strategy_ret ani equity")

    if "turnover" not in df.columns:
        prev = df["selected"].shift(1).fillna("CASH")
        curr = df["selected"]
        df["turnover"] = np.where(prev != curr, 1.0, 0.0)

    return df


def validate_daily_paper(rt: ScriptRuntime, df: pd.DataFrame, path: Path, model_key: str) -> Dict[str, Any]:
    rt.require_non_empty_df(df, label=f"{model_key}_daily_paper_df")

    if not looks_like_daily_paper(df):
        rt.fail(f"daily paper nevyzerá validne pre {model_key}: {path}")

    if "ts" not in df.columns:
        rt.fail(f"daily paper nema ts po normalize pre {model_key}: {path}")

    ts_min = df["ts"].min()
    ts_max = df["ts"].max()
    if pd.isna(ts_min) or pd.isna(ts_max):
        rt.fail(f"daily paper ma nevalidny ts range pre {model_key}: {path}")

    recent = df.loc[df["ts"] >= pd.Timestamp(START_DATE)].copy()
    if recent.empty:
        rt.fail(f"daily paper nema ziadne riadky od {START_DATE} pre {model_key}: {path}")

    quality = {
        "model_key": model_key,
        "path": str(path),
        "rows_total": int(len(df)),
        "rows_since_start_date": int(len(recent)),
        "ts_min": str(ts_min),
        "ts_max": str(ts_max),
        "selected_null_rows": int(df["selected"].isna().sum()) if "selected" in df.columns else None,
        "strategy_ret_null_rows": int(df["strategy_ret"].isna().sum()) if "strategy_ret" in df.columns else None,
        "gross_exposure_null_rows": int(df["gross_exposure"].isna().sum()) if "gross_exposure" in df.columns else None,
        "unique_selected_count": int(df["selected"].nunique()) if "selected" in df.columns else 0,
    }
    rt.log(
        f"DAILY_PAPER_QUALITY model_key={model_key} rows_total={quality['rows_total']} "
        f"rows_since_start_date={quality['rows_since_start_date']} ts_min={quality['ts_min']} ts_max={quality['ts_max']}"
    )
    return quality


def monthly_returns_from_equity(ts: pd.Series, eq: pd.Series, label: str) -> pd.DataFrame:
    df = pd.DataFrame({"ts": pd.to_datetime(ts), "equity": pd.to_numeric(eq, errors="coerce")})
    df = df.dropna().sort_values("ts").copy()
    df["ret"] = df["equity"].pct_change().fillna(0.0)
    monthly = ((1.0 + df.set_index("ts")["ret"]).resample("ME").prod() - 1.0) * 100.0
    out = monthly.to_frame(label).reset_index()
    out["month"] = out["ts"].dt.strftime("%Y-%m")
    return out[["month", label]]


def selection_stats(df: pd.DataFrame, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    recent = df.loc[df["ts"] >= pd.Timestamp(START_DATE)].copy()

    cash_days_pct = float((pd.to_numeric(recent["gross_exposure"], errors="coerce").fillna(0.0) <= 0.0).mean() * 100.0)
    trade_count = int((pd.to_numeric(recent["turnover"], errors="coerce").fillna(0.0) > 0).sum())

    summary = pd.DataFrame(
        [
            {
                "label": label,
                "cash_days_pct": round(cash_days_pct, 2),
                "trade_count": trade_count,
                "days": len(recent),
            }
        ]
    )

    held = recent.loc[recent["selected"].ne("CASH")].copy()
    if held.empty:
        top = pd.DataFrame(columns=["label", "selected", "days_held", "share_of_in_market_days_pct"])
    else:
        top = (
            held.groupby("selected")
            .size()
            .reset_index(name="days_held")
            .sort_values(["days_held", "selected"], ascending=[False, True])
        )
        total_held_days = max(int(top["days_held"].sum()), 1)
        top["share_of_in_market_days_pct"] = (top["days_held"] / total_held_days * 100.0).round(2)
        top.insert(0, "label", label)

    return summary, top


def compare_daily_behavior(main_df: pd.DataFrame, leader_df: pd.DataFrame) -> pd.DataFrame:
    a = main_df[["ts", "selected", "gross_exposure", "strategy_ret"]].copy()
    a = a.rename(
        columns={
            "selected": "main_selected",
            "gross_exposure": "main_gross_exposure",
            "strategy_ret": "main_strategy_ret",
        }
    )

    b = leader_df[["ts", "selected", "gross_exposure", "strategy_ret"]].copy()
    b = b.rename(
        columns={
            "selected": "leader_selected",
            "gross_exposure": "leader_gross_exposure",
            "strategy_ret": "leader_strategy_ret",
        }
    )

    merged = a.merge(b, on="ts", how="inner")
    merged = merged.loc[merged["ts"] >= pd.Timestamp(START_DATE)].copy()

    if merged.empty:
        raise ValueError("daily behavior merge je prázdny po START_DATE filtri")

    merged["ret_diff_main_minus_leader"] = merged["main_strategy_ret"] - merged["leader_strategy_ret"]
    merged["same_selection"] = merged["main_selected"] == merged["leader_selected"]
    merged["main_in_market"] = pd.to_numeric(merged["main_gross_exposure"], errors="coerce").fillna(0.0) > 0
    merged["leader_in_market"] = pd.to_numeric(merged["leader_gross_exposure"], errors="coerce").fillna(0.0) > 0
    merged["main_cash_leader_in"] = (~merged["main_in_market"]) & merged["leader_in_market"]
    merged["leader_cash_main_in"] = (~merged["leader_in_market"]) & merged["main_in_market"]

    return merged


def build_behavior_quality(behavior: pd.DataFrame) -> Dict[str, Any]:
    return {
        "rows": int(len(behavior)),
        "ts_min": str(behavior["ts"].min()) if len(behavior) else None,
        "ts_max": str(behavior["ts"].max()) if len(behavior) else None,
        "same_selection_pct": round(float(behavior["same_selection"].mean() * 100.0), 4) if len(behavior) else 0.0,
        "different_selection_days": int((~behavior["same_selection"]).sum()) if len(behavior) else 0,
        "main_cash_leader_in_days": int(behavior["main_cash_leader_in"].sum()) if len(behavior) else 0,
        "leader_cash_main_in_days": int(behavior["leader_cash_main_in"].sum()) if len(behavior) else 0,
        "ret_diff_null_rows": int(behavior["ret_diff_main_minus_leader"].isna().sum()) if "ret_diff_main_minus_leader" in behavior.columns else None,
    }


def main(rt: ScriptRuntime):
    rt.require_dir(ROOT, label="project_root")
    rt.require_dir(OUTPUTS, label="outputs_dir")
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    rt.require_dir(AUDIT_DIR, label="audit_dir")

    if not STRICT_INPUT_MODE:
        rt.fail("STRICT_INPUT_MODE musí byť True pre túto verziu skriptu.")

    equity_path = rt.require_file(RECENT_EQUITY_PATH, label="recent_equity_curves")
    equity_df = pd.read_csv(equity_path)
    rt.require_non_empty_df(equity_df, label="recent_equity_curves_df")

    if "ts" not in equity_df.columns:
        rt.fail(f"recent equity csv nema stlpec 'ts': {equity_path}")
    equity_df["ts"] = pd.to_datetime(equity_df["ts"], errors="coerce")
    equity_df = equity_df.dropna(subset=["ts"]).sort_values("ts").copy()
    rt.require_non_empty_df(equity_df, label="recent_equity_curves_df_clean")

    if MAIN_KEY not in equity_df.columns or LEADER_KEY not in equity_df.columns:
        rt.fail("V recent equity csv chyba hlavna strategia alebo predosly lider")

    main_path = rt.require_file(MAIN_DAILY_PAPER_PATH, label="main_daily_paper")
    leader_path = rt.require_file(LEADER_DAILY_PAPER_PATH, label="leader_daily_paper")

    summary_rows = []
    for key in [LEADER_KEY, MAIN_KEY]:
        metrics = compute_metrics_from_equity(equity_df["ts"], equity_df[key])
        summary_rows.append({"model": key, "label": MODEL_LABELS[key], **metrics})
    summary_df = pd.DataFrame(summary_rows)

    monthly_main = monthly_returns_from_equity(equity_df["ts"], equity_df[MAIN_KEY], "main_return_pct")
    monthly_leader = monthly_returns_from_equity(equity_df["ts"], equity_df[LEADER_KEY], "leader_return_pct")
    monthly = monthly_main.merge(monthly_leader, on="month", how="outer").sort_values("month")
    monthly["diff_main_minus_leader_pct"] = (monthly["main_return_pct"] - monthly["leader_return_pct"]).round(2)

    main_df = prepare_daily_paper(main_path)
    leader_df = prepare_daily_paper(leader_path)

    main_quality = validate_daily_paper(rt, main_df, main_path, MAIN_KEY)
    leader_quality = validate_daily_paper(rt, leader_df, leader_path, LEADER_KEY)

    main_stats, main_top = selection_stats(main_df, MODEL_LABELS[MAIN_KEY])
    leader_stats, leader_top = selection_stats(leader_df, MODEL_LABELS[LEADER_KEY])

    selection_summary = pd.concat([main_stats, leader_stats], ignore_index=True)
    top_holdings = pd.concat([main_top.head(10), leader_top.head(10)], ignore_index=True)

    behavior = compare_daily_behavior(main_df, leader_df)
    rt.require_non_empty_df(behavior, label="daily_behavior_df")
    behavior_quality = build_behavior_quality(behavior)

    worst_main_days = (
        behavior[["ts", "main_selected", "leader_selected", "ret_diff_main_minus_leader"]]
        .sort_values("ret_diff_main_minus_leader")
        .head(20)
        .copy()
    )
    best_main_days = (
        behavior[["ts", "main_selected", "leader_selected", "ret_diff_main_minus_leader"]]
        .sort_values("ret_diff_main_minus_leader", ascending=False)
        .head(20)
        .copy()
    )

    summary_csv = AUDIT_DIR / "recent_regime_attribution_2025_equity_summary.csv"
    monthly_csv = AUDIT_DIR / "recent_regime_attribution_2025_monthly.csv"
    selection_summary_csv = AUDIT_DIR / "recent_regime_attribution_2025_selection_summary.csv"
    top_holdings_csv = AUDIT_DIR / "recent_regime_attribution_2025_top_holdings.csv"
    behavior_csv = AUDIT_DIR / "recent_regime_attribution_2025_daily_behavior.csv"
    worst_main_days_csv = AUDIT_DIR / "recent_regime_attribution_2025_worst_main_vs_leader_days.csv"
    best_main_days_csv = AUDIT_DIR / "recent_regime_attribution_2025_best_main_vs_leader_days.csv"
    quality_json = AUDIT_DIR / "recent_regime_attribution_2025_input_quality.json"
    manifest_json = AUDIT_DIR / "recent_regime_attribution_2025_manifest.json"
    verdict_txt = AUDIT_DIR / "recent_regime_attribution_2025_verdict.txt"

    rt.save_csv(summary_df, summary_csv, label="recent_regime_attribution_2025_equity_summary")
    rt.save_csv(monthly, monthly_csv, label="recent_regime_attribution_2025_monthly")
    rt.save_csv(selection_summary, selection_summary_csv, label="recent_regime_attribution_2025_selection_summary")
    rt.save_csv(top_holdings, top_holdings_csv, label="recent_regime_attribution_2025_top_holdings")
    rt.save_csv(behavior, behavior_csv, label="recent_regime_attribution_2025_daily_behavior")
    rt.save_csv(worst_main_days, worst_main_days_csv, label="recent_regime_attribution_2025_worst_main_vs_leader_days")
    rt.save_csv(best_main_days, best_main_days_csv, label="recent_regime_attribution_2025_best_main_vs_leader_days")

    main_return = float(summary_df.loc[summary_df["model"] == MAIN_KEY, "total_return_pct"].iloc[0])
    leader_return = float(summary_df.loc[summary_df["model"] == LEADER_KEY, "total_return_pct"].iloc[0])

    verdict_lines = [
        "=== RECENT REGIME ATTRIBUTION 2025 ===",
        "",
        "Input mode",
        "- strict",
        f"- main_daily_paper: {main_path}",
        f"- leader_daily_paper: {leader_path}",
        "",
        "Quick read",
        f"- Total return rozdiel main - leader: {main_return - leader_return:+.2f} p.b.",
        f"- Rovnaky vyber coinu v tie iste dni: {behavior_quality['same_selection_pct']:.2f}%",
        f"- Dni, ked hlavna strategia bola v cashi a leader bol v trhu: {behavior_quality['main_cash_leader_in_days']}",
        f"- Dni, ked leader bol v cashi a hlavna strategia bola v trhu: {behavior_quality['leader_cash_main_in_days']}",
        f"- Different selection days: {behavior_quality['different_selection_days']}",
    ]
    rt.save_text("\n".join(verdict_lines), verdict_txt, label="recent_regime_attribution_2025_verdict")

    quality_payload = {
        "input_mode": "strict",
        "strict_input_mode": True,
        "recent_equity_path": str(equity_path),
        "main_daily_paper": main_quality,
        "leader_daily_paper": leader_quality,
        "behavior": behavior_quality,
    }
    rt.save_json(quality_payload, quality_json, label="recent_regime_attribution_2025_input_quality")

    manifest = build_basic_manifest(
        dataset_name="recent_regime_attribution_2025",
        source_files=[
            equity_path,
            main_path,
            leader_path,
            summary_csv,
            monthly_csv,
            selection_summary_csv,
            top_holdings_csv,
            behavior_csv,
            worst_main_days_csv,
            best_main_days_csv,
            quality_json,
            verdict_txt,
        ],
        extra={
            "input_mode": "strict",
            "strict_input_mode": True,
            "main_key": MAIN_KEY,
            "leader_key": LEADER_KEY,
            "main_daily_paper_path": str(main_path),
            "leader_daily_paper_path": str(leader_path),
            "behavior_rows": int(len(behavior)),
            "same_selection_pct": behavior_quality["same_selection_pct"],
            "different_selection_days": behavior_quality["different_selection_days"],
        },
    )
    rt.save_json(manifest, manifest_json, label="recent_regime_attribution_2025_manifest")

    rt.set_counter("summary_rows", len(summary_df))
    rt.set_counter("monthly_rows", len(monthly))
    rt.set_counter("selection_summary_rows", len(selection_summary))
    rt.set_counter("top_holdings_rows", len(top_holdings))
    rt.set_counter("behavior_rows", len(behavior))
    rt.set_counter("different_selection_days", behavior_quality["different_selection_days"])
    rt.set_counter("same_selection_pct", behavior_quality["same_selection_pct"])

    return {
        "input_mode": "strict",
        "behavior_csv": str(behavior_csv),
        "quality_json": str(quality_json),
        "manifest_json": str(manifest_json),
        "main_daily_paper": str(main_path),
        "leader_daily_paper": str(leader_path),
    }


if __name__ == "__main__":
    run_script(
        main,
        script_name=Path(__file__).name,
        fail_on_empty_df=True,
    )