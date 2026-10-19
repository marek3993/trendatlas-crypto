import itertools, json
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd
DATA = Path('data')
ANN = 365.25
DEV = ("2019-01-01", "2022-12-31")
TEST = ("2023-01-01", "2026-10-17")
LAST_CLOSED = "2026-10-17"

# naklady (bps na jednu stranu obchodu)
PERP_FEE = 0.7 * 1.5 + 0.3 * 4.5     # 70 % maker, 30 % taker
SPOT_FEE = 0.7 * 4.0 + 0.3 * 7.0
SLIP = 5.0
SPOT_ASSETS = {"BTC", "ETH"}
CASH_YIELD = 0.04

TREND_LB = (20, 40, 80, 160)
SCORE_LB = (20, 40, 80)
VOL_LB = 60
MIN_HISTORY = 365
CUTOFF = {"LUNA": "2022-05-13"}      # po tomto datume je v archive uz LUNA 2.0


@dataclass(frozen=True)
class Params:
    regime_min: float = 0.5   # BTC trend >= toto (0 = aspon polovica lookbackov kladna, 0.5 = aspon 3 zo 4)
    universe_n: int = 10      # top N podla 30d medianu objemu
    top_k: int = 1            # pocet drzanych coinov (rovnaka vaha 1/K)
    switch_h: float = 0.25    # prah na vymenu drzaneho coinu (jednotky skore)
    btc_pref: float = 0.25    # bonus k skore BTC


GRID = [Params(r, n, k, h, b) for r, n, k, h, b in itertools.product(
    (0.0, 0.5), (10, 20), (1, 2), (0.0, 0.25), (0.0, 0.25))]


# ---------------------------------------------------------------- data
def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes, vols = {}, {}
    for p in sorted((DATA / "ohlcv").glob("*.csv")):
        d = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
        d = d[~d.index.duplicated()]
        if p.stem in CUTOFF:
            d = d.loc[:CUTOFF[p.stem]]
        closes[p.stem], vols[p.stem] = d["close"], d["quote_volume"]
    close = pd.DataFrame(closes)
    idx = pd.date_range(close.index.min(), LAST_CLOSED, freq="D")
    close, qv = close.reindex(idx), pd.DataFrame(vols).reindex(idx)
    fund = {}
    for p in sorted((DATA / "funding").glob("*.csv")):
        f = pd.read_csv(p, parse_dates=["date"]).set_index("date")["funding_daily"]
        fund[p.stem] = f[~f.index.duplicated()]
    funding = pd.DataFrame(fund).reindex(idx).reindex(columns=close.columns)
    funding = funding.apply(lambda c: c.fillna(funding["BTC"])).fillna(0.0003)  # chyba -> BTC funding / 0.01 %/8h
    return close, qv, funding


def price_returns(close: pd.DataFrame) -> pd.DataFrame:
    """Denny vynos; cez kratku medzeru (<= 3 dni) z poslednej ceny, cez dlhsiu nie (delisting)."""
    return close.ffill(limit=3).pct_change(fill_method=None)


# ---------------------------------------------------------------- signaly (len z dat <= D)
def features(close: pd.DataFrame, qv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    c = close.ffill(limit=3)
    ret = c.pct_change(fill_method=None)
    vol = ret.rolling(VOL_LB, min_periods=40).std()
    trend = sum(np.sign(c / c.shift(L) - 1.0) for L in TREND_LB) / len(TREND_LB)
    score = sum((c / c.shift(L) - 1.0) / (vol * np.sqrt(L)) for L in SCORE_LB) / len(SCORE_LB)
    hist = close.notna().cumsum()
    liq = qv.rolling(30, min_periods=20).median().where((hist >= MIN_HISTORY) & close.notna())
    return {"trend": trend, "score": score, "liq": liq, "alive": close.notna()}


def decide(p: Params, f: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Vahy rozhodnute na close dna D (index D) = drzanie pocas D+1."""
    trend, score, liq, alive = f["trend"], f["score"], f["liq"], f["alive"]
    cols = list(trend.columns)
    ci = {c: i for i, c in enumerate(cols)}
    T, S, L, A = trend.values, score.values, liq.values, alive.values
    btc = ci["BTC"]
    W = np.zeros((len(trend), len(cols)))
    held: list[str] = []
    for t in range(len(trend)):
        held = [h for h in held if A[t, ci[h]]]                      # delisting -> von
        if not (T[t, btc] >= p.regime_min):
            held = []
            continue
        l_row = L[t]
        ok = ~np.isnan(l_row)
        if ok.sum() == 0:
            held = []
            continue
        rank = pd.Series(l_row[ok], index=np.array(cols)[ok]).rank(ascending=False)
        universe = set(rank[rank <= p.universe_n].index)
        adj = {}
        for c in universe:
            s, tr = S[t, ci[c]], T[t, ci[c]]
            if tr > 0 and np.isfinite(s):
                adj[c] = s + (p.btc_pref if c == "BTC" else 0.0)
        if not adj:
            held = []
            continue
        ranked = sorted(adj, key=adj.get, reverse=True)
        keep = [h for h in held if h in adj]                        # drzane, stale vhodne
        new = list(keep)
        for c in ranked:
            if len(new) >= p.top_k:
                break
            if c not in new:
                new.append(c)
        # vymena drzaneho za jasne lepsieho
        for i, h in enumerate(list(new)):
            if h not in keep:
                continue
            for c in ranked:
                if c in new:
                    continue
                if adj[c] > adj[h] + p.switch_h:
                    new[i] = c
                break
        held = new[: p.top_k]
        for h in held:
            W[t, ci[h]] = 1.0 / p.top_k
    return pd.DataFrame(W, index=trend.index, columns=cols)
