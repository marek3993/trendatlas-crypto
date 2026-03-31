from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ohlcv_4h"
OUTPUT_DIR = ROOT / "outputs"

DATE_CANDIDATES = ["timestamp", "date", "datetime", "time", "open_time"]
RENAME_MAP = {
    "Date": "date",
    "Timestamp": "timestamp",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Open time": "open_time",
}

TARGET_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
]

BARS_PER_DAY = 6
BARS_PER_YEAR = 365.25 * BARS_PER_DAY


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df = df.rename(columns=RENAME_MAP)

    date_col = next((c for c in DATE_CANDIDATES if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path} nemá dátumový stĺpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()


def build_base_tables(assets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close_df = pd.concat({s: df["close"] for s, df in assets.items()}, axis=1).sort_index()
    high_df = pd.concat({s: df["high"] for s, df in assets.items()}, axis=1).sort_index()
    low_df = pd.concat({s: df["low"] for s, df in assets.items()}, axis=1).sort_index()
    vol_df = pd.concat({s: df["volume"] for s, df in assets.items()}, axis=1).sort_index()

    ret6 = close_df.pct_change(6)      # 1d
    ret18 = close_df.pct_change(18)    # 3d
    ret42 = close_df.pct_change(42)    # 7d
    ret126 = close_df.pct_change(126)  # 21d
    ret252 = close_df.pct_change(252)  # 42d

    btc18 = ret18["BTCUSDT"]
    btc42 = ret42["BTCUSDT"]
    btc126 = ret126["BTCUSDT"]
    btc252 = ret252["BTCUSDT"]

    rs18 = ret18.sub(btc18, axis=0).fillna(0.0)
    rs42 = ret42.sub(btc42, axis=0).fillna(0.0)
    rs126 = ret126.sub(btc126, axis=0).fillna(0.0)
    rs252 = ret252.sub(btc252, axis=0).fillna(0.0)

    xs18 = (rs18.rank(axis=1, pct=True) - 0.5) * 200.0
    xs42 = (rs42.rank(axis=1, pct=True) - 0.5) * 200.0
    xs126 = (rs126.rank(axis=1, pct=True) - 0.5) * 200.0
    xs252 = (rs252.rank(axis=1, pct=True) - 0.5) * 200.0
    xs_persist = (0.55 * xs126 + 0.45 * xs252).rolling(6).mean().fillna(0.0)
    accel = (xs18 - xs126).fillna(0.0)

    dollar_vol = (close_df * vol_df).rolling(30).median()
    dv_rank = dollar_vol.rank(axis=1, pct=True).fillna(0.0)

    rolling_high_30 = high_df.shift(1).rolling(30).max()
    breakout30 = ((close_df / rolling_high_30) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    vol_burst = (vol_df / vol_df.shift(1).rolling(30).median()).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    breadth42 = (xs42 > 0).mean(axis=1).fillna(0.0)
    breadth126 = (xs126 > 0).mean(axis=1).fillna(0.0)

    out = {}
    for symbol, df in assets.items():
        t = df.copy()

        prev_close = t["close"].shift(1)
        tr = pd.concat(
            [
                (t["high"] - t["low"]).abs(),
                (t["high"] - prev_close).abs(),
                (t["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_pct = (tr.rolling(14).mean() / t["close"]) * 100.0

        ema42 = t["close"].ewm(span=42, adjust=False).mean()
        ema126 = t["close"].ewm(span=126, adjust=False).mean()
        ema252 = t["close"].ewm(span=252, adjust=False).mean()

        ret_next = t["close"].pct_change().shift(-1)

        conf_raw = 100.0 - (
            (
                (xs18[symbol] - ((xs18[symbol] + xs42[symbol] + xs126[symbol]) / 3.0)).abs()
                + (xs42[symbol] - ((xs18[symbol] + xs42[symbol] + xs126[symbol]) / 3.0)).abs()
                + (xs126[symbol] - ((xs18[symbol] + xs42[symbol] + xs126[symbol]) / 3.0)).abs()
            ) / 3.0
        )
        confidence = conf_raw.clip(0.0, 100.0)

        t["ret_next"] = ret_next
        t["ema42"] = ema42
        t["ema126"] = ema126
        t["ema252"] = ema252
        t["atr_pct"] = atr_pct.fillna(0.0)

        t["xs18"] = xs18[symbol].reindex(t.index).fillna(0.0)
        t["xs42"] = xs42[symbol].reindex(t.index).fillna(0.0)
        t["xs126"] = xs126[symbol].reindex(t.index).fillna(0.0)
        t["xs252"] = xs252[symbol].reindex(t.index).fillna(0.0)
        t["xs_persist"] = xs_persist[symbol].reindex(t.index).fillna(0.0)
        t["accel"] = accel[symbol].reindex(t.index).fillna(0.0)
        t["dv_rank"] = dv_rank[symbol].reindex(t.index).fillna(0.0)
        t["breakout30"] = breakout30[symbol].reindex(t.index).fillna(0.0)
        t["vol_burst"] = vol_burst[symbol].reindex(t.index).fillna(0.0)
        t["breadth42"] = breadth42.reindex(t.index).fillna(0.0)
        t["breadth126"] = breadth126.reindex(t.index).fillna(0.0)
        t["confidence"] = confidence.reindex(t.index).fillna(0.0)

        out[symbol] = t

    return out


def score_row(row: pd.Series, model: str) -> float:
    if model == "base_4h":
        return (
            0.45 * float(row["xs42"])
            + 0.25 * float(row["xs126"])
            + 0.20 * float(row["xs_persist"])
            + 0.10 * float(row["xs18"])
        )

    if model == "fast_4h":
        return (
            0.35 * float(row["xs18"])
            + 0.30 * float(row["xs42"])
            + 0.20 * float(row["accel"])
            + 0.15 * float(row["xs_persist"])
        )

    if model == "fast_breakout_4h":
        breakout_bonus = 220.0 * float(row["breakout30"])
        vol_bonus = 12.0 * clamp(float(row["vol_burst"]) - 1.0, 0.0, 3.0)
        return (
            0.30 * float(row["xs18"])
            + 0.25 * float(row["xs42"])
            + 0.20 * float(row["accel"])
            + 0.15 * float(row["xs_persist"])
            + 0.10 * breakout_bonus
            + vol_bonus
        )

    raise ValueError(f"Unknown model: {model}")


def candidate_ok(row: pd.Series, model: str) -> bool:
    if pd.isna(row["ret_next"]):
        return False

    if model == "base_4h":
        return (
            float(row["close"]) > float(row["ema126"])
            and float(row["ema42"]) > float(row["ema126"])
            and float(row["xs42"]) > 0.0
            and float(row["confidence"]) >= 35.0
            and float(row["dv_rank"]) >= 0.25
            and float(row["atr_pct"]) <= 8.0
            and float(row["breadth42"]) >= 0.40
        )

    if model == "fast_4h":
        return (
            float(row["close"]) > float(row["ema42"])
            and float(row["ema42"]) > float(row["ema126"])
            and float(row["xs18"]) > 0.0
            and float(row["confidence"]) >= 25.0
            and float(row["dv_rank"]) >= 0.20
            and float(row["atr_pct"]) <= 10.0
            and float(row["breadth42"]) >= 0.35
        )

    if model == "fast_breakout_4h":
        return (
            float(row["close"]) > float(row["ema42"])
            and float(row["ema42"]) > float(row["ema126"])
            and float(row["xs18"]) > 0.0
            and float(row["accel"]) > -5.0
            and float(row["dv_rank"]) >= 0.25
            and float(row["atr_pct"]) <= 10.0
            and float(row["breadth42"]) >= 0.35
            and float(row["breakout30"]) >= -0.01
            and float(row["vol_burst"]) >= 1.05
        )

    raise ValueError(f"Unknown model: {model}")


def run_model(
    asset_tables: dict[str, pd.DataFrame],
    model: str,
    total_cost_bps: float = 15.0,
) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(t.index) for t in asset_tables.values()]))
    symbols = sorted(asset_tables.keys())
    trade_cost = total_cost_bps / 10000.0

    prev_weights = {s: 0.0 for s in symbols}
    rows = []

    for dt in all_dates:
        candidates = []
        best_available_next = -999.0

        for symbol, tbl in asset_tables.items():
            if dt not in tbl.index:
                continue

            row = tbl.loc[dt]

            if pd.notna(row["ret_next"]):
                best_available_next = max(best_available_next, float(row["ret_next"]))

            if not candidate_ok(row, model):
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "score": score_row(row, model),
                    "ret_next": float(row["ret_next"]),
                }
            )

        target_weights = {s: 0.0 for s in symbols}
        selected_symbol = "CASH"
        selected_ret_next = 0.0

        if candidates:
            candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
            selected_symbol = candidates[0]["symbol"]
            selected_ret_next = candidates[0]["ret_next"]
            target_weights[selected_symbol] = 1.0

        raw_ret = selected_ret_next if selected_symbol != "CASH" else 0.0
        gross_exposure = 1.0 if selected_symbol != "CASH" else 0.0

        turnover = sum(abs(target_weights[s] - prev_weights[s]) for s in symbols)
        cost = turnover * trade_cost
        strategy_ret = raw_ret - cost

        rows.append(
            {
                "ts": dt,
                "selected": selected_symbol,
                "n_selected": 0 if selected_symbol == "CASH" else 1,
                "gross_exposure": gross_exposure,
                "raw_strategy_ret": raw_ret,
                "turnover": turnover,
                "cost": cost,
                "strategy_ret": strategy_ret,
                "selected_ret_next": selected_ret_next,
                "best_available_next": best_available_next if best_available_next > -900 else np.nan,
                "captured_spike_bar": int(selected_ret_next >= 0.04),
                "available_spike_bar": int(best_available_next >= 0.04) if best_available_next > -900 else 0,
            }
        )

        prev_weights = target_weights

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=[
                "selected", "n_selected", "gross_exposure", "raw_strategy_ret", "turnover",
                "cost", "strategy_ret", "selected_ret_next", "best_available_next",
                "captured_spike_bar", "available_spike_bar", "equity"
            ]
        ).rename_axis("ts")

    out = out.set_index("ts")
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    return out


def compute_summary(paper: pd.DataFrame) -> dict:
    if paper.empty:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": 0,
        }

    rets = paper["strategy_ret"].fillna(0.0)
    if len(rets) < 30:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": int((paper["turnover"] > 0).sum()),
        }

    equity = (1.0 + rets).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)

    span_days = max((equity.index.max() - equity.index.min()).days, 1)
    years = span_days / 365.25
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std())
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(BARS_PER_YEAR))

    downside = rets[rets < 0].std()
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(BARS_PER_YEAR))

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((paper["turnover"] > 0).sum()),
    }


def spike_stats(paper: pd.DataFrame) -> dict:
    available = int(paper["available_spike_bar"].sum()) if "available_spike_bar" in paper.columns else 0
    captured = int(paper["captured_spike_bar"].sum()) if "captured_spike_bar" in paper.columns else 0
    capture_ratio = (captured / available) if available > 0 else 0.0

    captured_only = paper.loc[paper["captured_spike_bar"] == 1, "selected_ret_next"] if "captured_spike_bar" in paper.columns else pd.Series(dtype=float)
    avg_captured = float(captured_only.mean()) if len(captured_only) > 0 else 0.0

    return {
        "available_spike_bars": available,
        "captured_spike_bars": captured,
        "spike_capture_ratio": round(capture_ratio, 3),
        "avg_captured_spike_ret_pct": round(avg_captured * 100.0, 2),
    }


def split_windows(paper: pd.DataFrame, window_size: int = 1080) -> list[pd.DataFrame]:
    if paper.empty:
        return []
    out = []
    for start in range(0, len(paper), window_size):
        part = paper.iloc[start:start + window_size].copy()
        if len(part) > 30:
            out.append(part)
    return out


def result_row(model: str, paper: pd.DataFrame) -> dict:
    full = compute_summary(paper)
    spikes = spike_stats(paper)

    wins = []
    for i, win in enumerate(split_windows(paper, 1080), start=1):
        s = compute_summary(win)
        s["window"] = i
        wins.append(s)

    wf = pd.DataFrame(wins)

    median_sharpe = float(wf["sharpe"].median()) if not wf.empty else 0.0
    median_sortino = float(wf["sortino"].median()) if not wf.empty else 0.0
    median_cagr = float(wf["cagr_pct"].median()) if not wf.empty else 0.0
    median_ret = float(wf["total_return_pct"].median()) if not wf.empty else 0.0
    worst_dd = float(wf["max_drawdown_pct"].min()) if not wf.empty else 0.0
    pos_ratio = float((wf["total_return_pct"] > 0).mean()) if not wf.empty else 0.0

    robust_score = (
        14.0 * median_sharpe
        + 10.0 * median_sortino
        + 0.20 * median_cagr
        + 0.05 * median_ret
        - 0.60 * abs(worst_dd)
        + 10.0 * spikes["spike_capture_ratio"]
    )

    return {
        "model": model,
        "robust_score": round(robust_score, 3),
        "median_window_sharpe": round(median_sharpe, 3),
        "median_window_sortino": round(median_sortino, 3),
        "median_window_cagr_pct": round(median_cagr, 2),
        "median_window_return_pct": round(median_ret, 2),
        "worst_window_dd_pct": round(worst_dd, 2),
        "positive_window_ratio": round(pos_ratio, 3),
        **spikes,
        "full_total_return_pct": full["total_return_pct"],
        "full_cagr_pct": full["cagr_pct"],
        "full_max_drawdown_pct": full["max_drawdown_pct"],
        "full_sharpe": full["sharpe"],
        "full_sortino": full["sortino"],
        "full_trade_count": full["trade_count"],
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    missing = [s for s in TARGET_SYMBOLS if not (DATA_DIR / f"{s}_4h.csv").exists()]
    if missing:
        print("CHÝBAJÚ 4H CSV:")
        for s in missing:
            print(f"- data\\ohlcv_4h\\{s}_4h.csv")
        return

    assets = {s: load_ohlcv_csv(DATA_DIR / f"{s}_4h.csv") for s in TARGET_SYMBOLS}
    asset_tables = build_base_tables(assets)

    models = ["base_4h", "fast_4h", "fast_breakout_4h"]

    rows = []
    for model in models:
        print(f"testujem {model}...", flush=True)
        paper = run_model(asset_tables, model=model, total_cost_bps=15.0)
        rows.append(result_row(model, paper))
        paper.to_csv(OUTPUT_DIR / f"phase16_{model}.csv")

    out = pd.DataFrame(rows).sort_values(
        ["robust_score", "full_sharpe", "full_cagr_pct"],
        ascending=False,
    ).reset_index(drop=True)

    out.to_csv(OUTPUT_DIR / "phase16_4h_results.csv", index=False)

    best = out.iloc[0].to_dict()
    with open(OUTPUT_DIR / "phase16_4h_best.json", "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    print("\nPHASE 16 4H")
    print(out.to_string(index=False))
    print("\nuložené:")
    print("outputs\\phase16_4h_results.csv")
    print("outputs\\phase16_4h_best.json")
    print("outputs\\phase16_base_4h.csv")
    print("outputs\\phase16_fast_4h.csv")
    print("outputs\\phase16_fast_breakout_4h.csv")


if __name__ == "__main__":
    main()