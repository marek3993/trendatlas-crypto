from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ohlcv"

TARGET_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
]

DATE_CANDIDATES = ["timestamp", "date", "datetime", "time", "open_time"]


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = None
    for c in DATE_CANDIDATES:
        if c in df.columns:
            date_col = c
            break

    if date_col is None:
        raise ValueError(f"{path} nemá dátumový stĺpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).copy()
    df["ret_cc"] = df["close"].pct_change()
    return df


def main() -> None:
    all_rows = []

    for symbol in TARGET_SYMBOLS:
        path = DATA_DIR / f"{symbol}_1d.csv"
        if not path.exists():
            print(f"CHÝBA: {path}")
            continue

        df = load_csv(path)
        outliers = df[df["ret_cc"].abs() >= 0.40].copy()

        print(f"\n=== {symbol} | abs(close-close return) >= 40% ===")
        if outliers.empty:
            print("Žiadne")
            continue

        print(outliers[["open", "high", "low", "close", "volume", "ret_cc"]].to_string())

        tmp = outliers[["open", "high", "low", "close", "volume", "ret_cc"]].copy()
        tmp["symbol"] = symbol
        all_rows.append(tmp.reset_index())

    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
        out.to_csv(ROOT / "outputs" / "audit_ohlcv_outliers.csv", index=False)
        print("\nuložené: outputs\\audit_ohlcv_outliers.csv")
    else:
        print("\nŽiadne outliery >= 40% sa nenašli.")


if __name__ == "__main__":
    main()