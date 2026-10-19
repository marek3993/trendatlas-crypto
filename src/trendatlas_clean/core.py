"""Frozen Clean 50/50 signal math. Index D means decision at close D, never a fill."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

ANN = 365.25
TREND_LB = (20, 40, 80, 160)
SCORE_LB = (20, 40, 80)
VOL_LB = 60
MIN_HISTORY = 365
STRATEGY_ID = "trendatlas_clean_5050_v1"
CUTOFF = {"LUNA": "2022-05-13"}


@dataclass(frozen=True)
class Params:
    regime_min: float = 0.5
    universe_n: int = 10
    top_k: int = 1
    switch_h: float = 0.25
    btc_pref: float = 0.25

    def __post_init__(self) -> None:
        if not all(math.isfinite(x) for x in (self.regime_min, self.switch_h, self.btc_pref)):
            raise ValueError("Parameters must be finite")
        if self.universe_n < 1 or self.top_k < 1 or self.top_k > self.universe_n or self.switch_h < 0:
            raise ValueError("Invalid universe, top_k, or hysteresis")


LIVE_PARAMS = Params()


def validate_panel(close: pd.DataFrame, qv: pd.DataFrame) -> None:
    if close.empty or "BTC" not in close.columns:
        raise ValueError("A non-empty panel containing BTC is required")
    if not isinstance(close.index, pd.DatetimeIndex) or close.index.tz is not None:
        raise ValueError("Use normalized, timezone-naive UTC dates")
    if close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise ValueError("Dates must be unique and ascending")
    if not close.index.equals(pd.date_range(close.index[0], close.index[-1], freq="D")):
        raise ValueError("Reindex to every UTC calendar day before computing features")
    if close.columns.has_duplicates or not close.index.equals(qv.index) or not close.columns.equals(qv.columns):
        raise ValueError("Close and quote-volume axes must match exactly")
    if set(close.columns) & {"BASE", "CASH"}:
        raise ValueError("BASE/CASH are not market-price columns")
    cv, qvv = close.to_numpy(dtype=float), qv.to_numpy(dtype=float)
    if np.isinf(cv).any() or ((cv <= 0) & ~np.isnan(cv)).any():
        raise ValueError("Observed close must be finite and positive")
    if np.isinf(qvv).any() or ((qvv < 0) & ~np.isnan(qvv)).any():
        raise ValueError("Observed quote volume must be finite and non-negative")


def features(close: pd.DataFrame, qv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Same equations/ddof/min_periods as the supplied reference, including alive."""
    validate_panel(close, qv)
    c = close.ffill(limit=3)
    ret = c.pct_change(fill_method=None)
    vol = ret.rolling(VOL_LB, min_periods=40).std()
    trend = sum(np.sign(c / c.shift(L) - 1.0) for L in TREND_LB) / len(TREND_LB)
    score = sum((c / c.shift(L) - 1.0) / (vol * np.sqrt(L)) for L in SCORE_LB) / len(SCORE_LB)
    hist = close.notna().cumsum()
    liq = qv.rolling(30, min_periods=20).median().where((hist >= MIN_HISTORY) & close.notna())
    return {"trend": trend, "score": score, "liq": liq, "alive": close.notna()}


def decide(p: Params, f: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Reference state machine; alphabetical ordering resolves exact score ties."""
    trend, score, liq, alive = (f[k] for k in ("trend", "score", "liq", "alive"))
    cols = list(trend.columns)
    ci = {c: i for i, c in enumerate(cols)}
    T, S, L, A = trend.values, score.values, liq.values, alive.values
    btc = ci["BTC"]
    W = np.zeros((len(trend), len(cols)))
    held: list[str] = []
    for t in range(len(trend)):
        held = [h for h in held if A[t, ci[h]]]
        if not (T[t, btc] >= p.regime_min):
            held = []
            continue
        l_row = L[t]
        ok = ~np.isnan(l_row)
        if ok.sum() == 0:
            held = []
            continue
        rank = pd.Series(l_row[ok], index=np.array(cols)[ok]).rank(ascending=False)
        universe = sorted(rank[rank <= p.universe_n].index)
        adj = {}
        for c in universe:
            s, tr = S[t, ci[c]], T[t, ci[c]]
            if tr > 0 and np.isfinite(s):
                adj[c] = s + (p.btc_pref if c == "BTC" else 0.0)
        if not adj:
            held = []
            continue
        ranked = sorted(adj, key=lambda c: (-adj[c], c))
        keep = [h for h in held if h in adj]
        new = list(keep)
        for c in ranked:
            if len(new) >= p.top_k:
                break
            if c not in new:
                new.append(c)
        for i, h in enumerate(list(new)):
            if h not in keep:
                continue
            for c in ranked:
                if c in new:
                    continue
                if adj[c] > adj[h] + p.switch_h:
                    new[i] = c
                break
        held = new[:p.top_k]
        for h in held:
            W[t, ci[h]] = 1.0 / p.top_k
    return pd.DataFrame(W, index=trend.index, columns=cols)


def target_weights(close: pd.DataFrame, qv: pd.DataFrame) -> pd.DataFrame:
    """Decision weights at close D. No signal-side shift is applied."""
    f = features(close, qv)
    W_clean = decide(LIVE_PARAMS, f)
    W_btc = pd.DataFrame(0.0, index=W_clean.index, columns=W_clean.columns)
    W_btc["BTC"] = (f["trend"]["BTC"] >= 0.5).astype(float)
    return 0.5 * W_clean + 0.5 * W_btc


def price_returns(close: pd.DataFrame) -> pd.DataFrame:
    return close.ffill(limit=3).pct_change(fill_method=None)


def weights_dict(row: pd.Series, *, include_cash: bool = True) -> dict[str, float]:
    if not np.isfinite(row.to_numpy(dtype=float)).all() or (row < 0).any() or row.sum() > 1.0 + 1e-12:
        raise ValueError("Weights must be finite, long-only, and total at most 1x")
    out = {str(c): float(w) for c, w in sorted(row.items()) if w > 1e-12}
    if include_cash and row.sum() < 1 - 1e-12:
        out["CASH"] = float(1 - row.sum())
    return out


def explain_day(close: pd.DataFrame, qv: pd.DataFrame, day: str) -> dict[str, Any]:
    """Reference-check diagnostics, including the top-10 boundary and observations."""
    f = features(close.loc[:day], qv.loc[:day])
    liq = f["liq"].iloc[-1].dropna()
    ranks = liq.rank(ascending=False)
    rows = []
    for c in sorted(liq.index, key=lambda c: (-liq[c], c))[:15]:
        raw_score = f["score"].iloc[-1][c]
        rows.append({"asset": c, "liquidity_usd": float(liq[c]), "rank": float(ranks[c]),
                     "eligible_top10": bool(ranks[c] <= 10), "trend": float(f["trend"].iloc[-1][c]) if np.isfinite(f["trend"].iloc[-1][c]) else None,
                     "score": float(raw_score) if np.isfinite(raw_score) else None,
                     "adjusted_score": float(raw_score + (0.25 if c == "BTC" else 0)) if np.isfinite(raw_score) else None})
    btc_trend = f["trend"]["BTC"].iloc[-1]
    return {"day": day, "btc_trend": float(btc_trend) if np.isfinite(btc_trend) else None,
            "params": asdict(LIVE_PARAMS), "liquidity_ranking": rows}
