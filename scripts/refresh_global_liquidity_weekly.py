from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MACRO_DIR = ROOT / "data" / "macro"
SOURCE_DIR = ROOT / "data" / "macro_sources"

OUTPUT_PATH = MACRO_DIR / "global_liquidity_weekly.csv"
REPORT_PATH = ROOT / "outputs" / "app_freshness_verification" / "macro_refresh_report.json"

SOURCE_SPECS = [
    {
        "name": "g7_m2_yoy",
        "path": SOURCE_DIR / "g7_m2_yoy.csv",
        "preferred_columns": ["g7_m2_yoy", "value", "yoy", "close"],
    },
    {
        "name": "bis_gli_yoy",
        "path": SOURCE_DIR / "bis_gli_yoy.csv",
        "preferred_columns": ["bis_gli_yoy", "value", "yoy", "close"],
    },
    {
        "name": "cb_balance_sheet_yoy",
        "path": SOURCE_DIR / "cb_balance_sheet_yoy.csv",
        "preferred_columns": ["cb_balance_sheet_yoy", "value", "yoy", "close"],
    },
]

OUTPUT_COLUMNS = ["date", "g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def detect_date_column(df: pd.DataFrame) -> str:
    preferred = ["date", "datetime", "timestamp", "time", "week", "ds"]
    for col in preferred:
        if col in df.columns:
            return col
    raise ValueError(f"Missing date column. Available columns: {list(df.columns)}")


def detect_value_column(df: pd.DataFrame, preferred_columns: Iterable[str]) -> str:
    for col in preferred_columns:
        if col in df.columns:
            return col
    numeric_candidates = []
    for col in df.columns:
        if str(col).lower() in {"date", "datetime", "timestamp", "time", "week", "ds"}:
            continue
        numeric_candidates.append(col)
    if len(numeric_candidates) == 1:
        return str(numeric_candidates[0])
    raise ValueError(f"Unable to detect value column. Available columns: {list(df.columns)}")


def load_series_csv(path: Path, output_name: str, preferred_columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalize_columns(df)

    date_col = detect_date_column(df)
    value_col = detect_value_column(df, preferred_columns)

    out = df[[date_col, value_col]].copy()
    out.columns = ["date", output_name]
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out[output_name] = pd.to_numeric(out[output_name], errors="coerce")

    out = out.dropna(subset=["date", output_name]).copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    return out


def load_existing_output(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing macro snapshot: {path}")
    df = pd.read_csv(path)
    df = normalize_columns(df)
    missing = [col for col in OUTPUT_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Existing macro snapshot missing columns: {missing}")
    out = df[OUTPUT_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for col in OUTPUT_COLUMNS[1:]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date"]).copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    return out


def save_output(df: pd.DataFrame, path: Path) -> None:
    ensure_parent(path)
    out = df.copy()
    out = out[OUTPUT_COLUMNS].copy()
    out.to_csv(path, index=False)


def save_report(payload: dict) -> None:
    ensure_parent(REPORT_PATH)
    REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def existing_last_date(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    return str(df.iloc[-1]["date"])


def main() -> None:
    MACRO_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    available_sources = [spec for spec in SOURCE_SPECS if spec["path"].exists()]
    missing_sources = [str(spec["path"]) for spec in SOURCE_SPECS if not spec["path"].exists()]

    if len(available_sources) == len(SOURCE_SPECS):
        merged: pd.DataFrame | None = None

        for spec in SOURCE_SPECS:
            series_df = load_series_csv(
                path=spec["path"],
                output_name=spec["name"],
                preferred_columns=spec["preferred_columns"],
            )
            if merged is None:
                merged = series_df
            else:
                merged = merged.merge(series_df, on="date", how="outer")

        if merged is None or merged.empty:
            raise RuntimeError("Macro source files exist but produced empty merged dataframe.")

        merged = merged.sort_values("date").reset_index(drop=True)
        for col in OUTPUT_COLUMNS[1:]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

        merged = merged.dropna(subset=["date"]).copy()
        merged = merged.ffill().dropna(subset=OUTPUT_COLUMNS[1:]).copy()
        merged = merged[OUTPUT_COLUMNS].copy()

        save_output(merged, OUTPUT_PATH)

        payload = {
            "ts_utc": now_utc(),
            "status": "OK",
            "mode": "authoritative_refresh",
            "output_path": str(OUTPUT_PATH),
            "report_path": str(REPORT_PATH),
            "last_date": existing_last_date(merged),
            "source_files": [str(spec["path"]) for spec in SOURCE_SPECS],
            "rows": int(len(merged)),
        }
        save_report(payload)

        print("[MACRO] status=OK", flush=True)
        print("[MACRO] mode=authoritative_refresh", flush=True)
        print(f"[MACRO] output_path={OUTPUT_PATH}", flush=True)
        print(f"[MACRO] report_path={REPORT_PATH}", flush=True)
        print(f"[MACRO] last_date={payload['last_date']}", flush=True)
        return

    existing = load_existing_output(OUTPUT_PATH)

    payload = {
        "ts_utc": now_utc(),
        "status": "OK",
        "mode": "frozen_validate_only",
        "output_path": str(OUTPUT_PATH),
        "report_path": str(REPORT_PATH),
        "last_date": existing_last_date(existing),
        "rows": int(len(existing)),
        "missing_source_files": missing_sources,
        "note": "No authoritative macro source files found. Existing snapshot preserved unchanged.",
    }
    save_report(payload)

    print("[MACRO] status=OK", flush=True)
    print("[MACRO] mode=frozen_validate_only", flush=True)
    print(f"[MACRO] output_path={OUTPUT_PATH}", flush=True)
    print(f"[MACRO] report_path={REPORT_PATH}", flush=True)
    print(f"[MACRO] last_date={payload['last_date']}", flush=True)
    print(f"[MACRO] missing_source_files={len(missing_sources)}", flush=True)


if __name__ == "__main__":
    main()