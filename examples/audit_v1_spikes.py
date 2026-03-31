from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DATA_DIR = ROOT / "data" / "ohlcv"

PAPER_PATH = OUTPUTS / "phase11_cost_15_oos.csv"
BTC_PATH = DATA_DIR / "BTCUSDT_1d.csv"


def load_indexed_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    if "ts" in df.columns:
        idx_col = "ts"
    else:
        unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
        if unnamed:
            idx_col = unnamed[0]
        else:
            raise ValueError(f"{path} nemá ts index")

    df[idx_col] = pd.to_datetime(df[idx_col], errors="coerce")
    df = df.dropna(subset=[idx_col]).copy()
    df = df.set_index(idx_col).sort_index()
    df.index.name = "ts"
    return df


def clean_selected(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.strip()
    out = out.replace(
        {
            "": "CASH",
            "nan": "CASH",
            "NaN": "CASH",
            "None": "CASH",
            "none": "CASH",
            "NULL": "CASH",
            "null": "CASH",
        }
    )
    return out.fillna("CASH")


def load_paper(path: Path) -> pd.DataFrame:
    df = load_indexed_csv(path)

    for c in ["strategy_ret", "raw_strategy_ret", "turnover", "cost", "equity", "n_selected", "gross_exposure"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    if "selected" not in df.columns:
        df["selected"] = "CASH"
    df["selected"] = clean_selected(df["selected"])

    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full_idx)
    df.index.name = "ts"

    df["strategy_ret"] = pd.to_numeric(df["strategy_ret"], errors="coerce").fillna(0.0)

    if "raw_strategy_ret" not in df.columns:
        df["raw_strategy_ret"] = 0.0
    df["raw_strategy_ret"] = pd.to_numeric(df["raw_strategy_ret"], errors="coerce").fillna(0.0)

    if "turnover" not in df.columns:
        df["turnover"] = 0.0
    df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0.0)

    if "cost" not in df.columns:
        df["cost"] = 0.0
    df["cost"] = pd.to_numeric(df["cost"], errors="coerce").fillna(0.0)

    if "gross_exposure" not in df.columns:
        df["gross_exposure"] = 0.0
    df["gross_exposure"] = pd.to_numeric(df["gross_exposure"], errors="coerce").fillna(0.0)

    df["selected"] = clean_selected(df["selected"])
    df["equity"] = (1.0 + df["strategy_ret"]).cumprod()
    return df


def load_btc(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = None
    for c in ["date", "timestamp", "datetime", "time", "open_time"]:
        if c in df.columns:
            date_col = c
            break

    if date_col is None:
        raise ValueError("BTC csv nemá dátumový stĺpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()
    df.index.name = "ts"

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).copy()

    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full_idx)
    df["close"] = df["close"].ffill()
    df["btc_ret"] = df["close"].pct_change().fillna(0.0)
    return df[["close", "btc_ret"]]


def main() -> None:
    if not PAPER_PATH.exists():
        raise FileNotFoundError(PAPER_PATH)
    if not BTC_PATH.exists():
        raise FileNotFoundError(BTC_PATH)

    paper = load_paper(PAPER_PATH)
    btc = load_btc(BTC_PATH)

    df = paper.join(btc[["btc_ret"]], how="left")
    df["btc_ret"] = df["btc_ret"].fillna(0.0)
    df["abs_strategy_ret"] = df["strategy_ret"].abs()

    cols = [
        "selected",
        "gross_exposure",
        "raw_strategy_ret",
        "cost",
        "strategy_ret",
        "btc_ret",
        "equity",
    ]

    top_up = df.sort_values("strategy_ret", ascending=False)[cols].head(20)
    top_down = df.sort_values("strategy_ret", ascending=True)[cols].head(20)
    top_abs = df.sort_values("abs_strategy_ret", ascending=False)[cols + ["abs_strategy_ret"]].head(40)

    big_moves = df[df["abs_strategy_ret"] >= 0.10][cols + ["abs_strategy_ret"]].copy()

    top_up.to_csv(OUTPUTS / "audit_top_up_days.csv")
    top_down.to_csv(OUTPUTS / "audit_top_down_days.csv")
    top_abs.to_csv(OUTPUTS / "audit_top_abs_days.csv")
    big_moves.to_csv(OUTPUTS / "audit_big_moves_over_10pct.csv")

    print("=== TOP UP DAYS ===")
    print(top_up.to_string())
    print()

    print("=== TOP DOWN DAYS ===")
    print(top_down.to_string())
    print()

    print("=== TOP ABS DAYS ===")
    print(top_abs.to_string())
    print()

    print("=== BIG MOVES >= 10% ===")
    if big_moves.empty:
        print("Žiadne")
    else:
        print(big_moves.to_string())
    print()

    print("uložené:")
    print("outputs\\audit_top_up_days.csv")
    print("outputs\\audit_top_down_days.csv")
    print("outputs\\audit_top_abs_days.csv")
    print("outputs\\audit_big_moves_over_10pct.csv")


if __name__ == "__main__":
    main()