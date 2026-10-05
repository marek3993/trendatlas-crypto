"""Frozen descendant of v1 market features and J-N signals, separate v2 lineage."""
from __future__ import annotations

import hashlib
import io
import json
import math
import random
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


CONTRACT_FILE = Path(__file__).resolve().parents[2] / "source_of_truth" / "phase2_development_contract.json"
SPACE = json.loads(CONTRACT_FILE.read_text())["gene_space"]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_genes(genes):
    if not isinstance(genes, dict) or genes.get("family") not in SPACE:
        raise ValueError("unknown_family")
    family = genes["family"]
    if set(genes) != {"family", *SPACE[family]}:
        raise ValueError("gene_keys")
    for key, choices in SPACE[family].items():
        if type(genes[key]) is not type(choices[0]) or genes[key] not in choices:
            raise ValueError("gene_value:" + key)
    return genes


def mutate(parent, seed, seen):
    rng = random.Random(seed)
    keys = list(SPACE[parent["family"]])
    rng.shuffle(keys)
    for key in keys:
        options = SPACE[parent["family"]][key]
        index = options.index(parent[key])
        adjacent = [options[j] for j in (index-1,index+1) if 0<=j<len(options)]
        rng.shuffle(adjacent)
        values = adjacent + [v for v in options if v!=parent[key] and v not in adjacent]
        for value in values:
            child = dict(parent, **{key: value})
            if digest(child) not in seen:
                return child, f"deterministic:{key}:{parent[key]}->{value}"
    return None, "space_exhausted"


@dataclass
class Market:
    dates: pd.DatetimeIndex
    assets: list[str]
    opening: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    quote: np.ndarray
    eligible: np.ndarray
    rank: np.ndarray
    features: dict
    input_hash: str


def _read_zip(path, end):
    from .inputs import guarded_rows
    from .contract import load, allowed
    contract=load()
    if not allowed(end,contract): raise ValueError("locked_market_end")
    out = {}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                rows=list(guarded_rows(stream,contract,end))
            if not rows: continue
            frame=pd.DataFrame(rows).set_index("date").astype(float)
            frame.index=pd.to_datetime(frame.index)
            if len(frame):
                out[name[:-4]] = frame
    return out


def load_market(input_dir: Path, end="2026-09-25"):
    """Read only development dates. Assets need 365 observed days and prior liquidity."""
    input_dir = Path(input_dir)
    archive = input_dir / "spot_daily.zip"
    events_path = input_dir / "identity_events.json"
    notices_path = input_dir / "venue_notices.json"
    frames = _read_zip(archive, end)
    events = json.loads(events_path.read_text())
    # An identity change creates two distinct assets, never one spliced PnL path.
    for symbol in {x["symbol"] for x in events}:
        if symbol not in frames:
            continue
        frame = frames.pop(symbol)
        lower = None
        name = symbol + "@original"
        for event in sorted((x for x in events if x["symbol"] == symbol), key=lambda x: x["effective_utc"]):
            halt = pd.Timestamp(event["effective_utc"]).tz_localize(None)
            restart = pd.Timestamp(event["new_start"]).tz_localize(None)
            segment = frame if lower is None else frame.loc[frame.index >= lower]
            frames[name] = segment.loc[segment.index + pd.Timedelta(days=1) <= halt]
            # Publication-aware eligibility below includes the original segment.
            name = symbol + "@" + restart.strftime("%Y%m%d")
            lower = restart
        frames[name] = frame.loc[frame.index >= lower]
    dates = pd.date_range("2018-05-05", end, freq="D")
    assets = sorted(frames)
    fields = {}
    for field in ("open", "high", "low", "close", "quote_volume"):
        fields[field] = pd.DataFrame({a: frames[a][field].reindex(dates) for a in assets}, index=dates).astype(float)
    opening, high, low, close, quote = (fields[k].to_numpy() for k in ("open", "high", "low", "close", "quote_volume"))
    observed = fields["close"].gt(0) & fields["quote_volume"].gt(0)
    liquidity = fields["quote_volume"].where(observed).shift(1).rolling(30, min_periods=30).mean()
    base = observed & observed.cumsum().ge(365) & liquidity.ge(10_000_000)
    notices = json.loads(notices_path.read_text())
    notices += [{**e, 'policy':'identity_change'} for e in events]
    for event in notices:
        symbol = event["symbol"]
        known = pd.Timestamp(event["published_utc"]).tz_localize(None).normalize()
        effective = pd.Timestamp(event["effective_utc"]).tz_localize(None).normalize()
        for asset in [a for a in base if a==symbol or a.startswith(symbol+'@')]:
            observed_dates=frames[asset].index
            if not len(observed_dates) or observed_dates.min() >= effective:
                continue  # A genuinely distinct successor must mature on its own observations.
            base.loc[base.index >= max(known, effective - pd.Timedelta(days=3)), asset] = False
    rank = liquidity.where(base).rank(axis=1, ascending=False, method="first")
    eligible = (base & rank.le(10)).to_numpy()
    returns = fields["close"].pct_change(fill_method=None)
    features = {"returns": returns.to_numpy()}
    sma_vol_lengths = sorted({120,20,63} |
        {x for family in SPACE.values() for field, choices in family.items()
         if field in ("trend_days","market_sma_days","slow_days","vol_days") for x in choices})
    for length in sma_vol_lengths:
        features[f"sma{length}"] = fields["close"].rolling(length, min_periods=length).mean().to_numpy()
        features[f"vol{length}"] = (returns.rolling(length, min_periods=length).std() * math.sqrt(365.25)).to_numpy()
    for length in sorted({x for family in SPACE.values() for field, choices in family.items() if field=="breakout_days" for x in choices}):
        features[f"breakout{length}"] = fields["high"].rolling(length, min_periods=length).max().shift(1).to_numpy()
    previous_close = fields["close"].shift(1)
    tr = pd.DataFrame(np.maximum.reduce([(fields["high"]-fields["low"]).to_numpy(),
                                         (fields["high"]-previous_close).abs().to_numpy(),
                                         (fields["low"]-previous_close).abs().to_numpy()]), index=dates, columns=assets)
    for length in SPACE["N"]["atr_days"]:
        features[f"atr{length}"] = tr.rolling(length, min_periods=length).mean().to_numpy()
    for length in sorted({x for family in SPACE.values() for field, choices in family.items() if field=="momentum_days" for x in choices}):
        features[f"mom{length}"] = (fields["close"] / fields["close"].shift(length) - 1).to_numpy()
    input_hash = hashlib.sha256(b"".join(hashlib.sha256(p.read_bytes()).digest() for p in (archive, events_path, notices_path))).hexdigest()
    return Market(dates, assets, opening, high, low, close, quote, eligible, rank.to_numpy(), features, input_hash)


def synthetic_market():
    dates = pd.date_range("2018-05-05", "2026-09-25", freq="D")
    n = len(dates)
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    x = np.arange(n, dtype=float)
    close = np.stack([100*np.exp(.0005*x + .15*np.sin(x/60+j)) for j in range(3)], axis=1)
    opening = np.vstack([close[0], close[:-1]])
    high = np.maximum(opening, close)*1.01
    low = np.minimum(opening, close)*.99
    quote = np.ones_like(close)*20_000_000
    eligible = np.ones_like(close, bool)
    rank = np.tile(np.arange(1, 4), (n, 1))
    frame = pd.DataFrame(close, index=dates, columns=assets)
    returns = frame.pct_change(fill_method=None)
    features = {"returns": returns.to_numpy()}
    sma_vol_lengths = sorted({120,20,63} |
        {x for family in SPACE.values() for field, choices in family.items()
         if field in ("trend_days","market_sma_days","slow_days","vol_days") for x in choices})
    for length in sma_vol_lengths:
        features[f"sma{length}"] = frame.rolling(length).mean().to_numpy()
        features[f"vol{length}"] = (returns.rolling(length).std()*math.sqrt(365.25)).to_numpy()
    for length in sorted({x for family in SPACE.values() for field, choices in family.items() if field=="breakout_days" for x in choices}):
        features[f"breakout{length}"] = pd.DataFrame(high, index=dates).rolling(length).max().shift(1).to_numpy()
    tr = pd.DataFrame(high-low, index=dates)
    for length in SPACE["N"]["atr_days"]:
        features[f"atr{length}"] = tr.rolling(length).mean().to_numpy()
    for length in sorted({x for family in SPACE.values() for field, choices in family.items() if field=="momentum_days" for x in choices}):
        features[f"mom{length}"] = (frame/frame.shift(length)-1).to_numpy()
    return Market(dates, assets, opening, high, low, close, quote, eligible, rank, features, "synthetic-v1")


def targets(m: Market, genes: dict, i: int, state: dict):
    """Signal uses completed day i; caller trades on day i+1."""
    validate_genes(genes)
    family = genes["family"]
    n = len(m.assets)
    result = np.zeros(n)
    eligible = np.flatnonzero(m.eligible[i] & np.isfinite(m.close[i]))
    if not len(eligible):
        return result
    ranks = sorted(eligible, key=lambda j: (m.rank[i, j], m.assets[j]))
    btc = m.assets.index("BTCUSDT")
    c = m.close[i]
    f = m.features
    if family == "J":
        positive = c > f[f"sma{genes['trend_days']}"][i]
        vol = f[f"vol{genes['vol_days']}"][i]
        previous = state.get("previous")
        exit_days = genes["exit_confirm_days"]
        for j in ranks:
            if positive[j] and np.isfinite(vol[j]) and vol[j] > 0:
                result[j] = min(.25, genes["vol_target"]/vol[j]/max(1, len(ranks)))
            elif previous is not None and previous[j] > 0 and exit_days > 1:
                recent = m.close[i-exit_days+1:i+1,j] < f[f"sma{genes['trend_days']}"][i-exit_days+1:i+1,j]
                if not np.all(recent):
                    result[j] = previous[j]
        return result
    if family == "K":
        if i % genes["rebalance_days"] and state.get("previous") is not None:
            return state["previous"].copy()
        chosen = []
        vol = f[f"vol{genes['vol_days']}"][i]
        for j in ranks:
            if c[j] <= f[f"sma{genes['trend_days']}"][i, j] or not np.isfinite(vol[j]) or vol[j] <= 0:
                continue
            pair_ok = True
            for k in chosen:
                a, b = f["returns"][i-89:i+1, j], f["returns"][i-89:i+1, k]
                if i < 90 or not np.isfinite(a).all() or not np.isfinite(b).all():
                    pair_ok = False; break
                if np.corrcoef(a, b)[0, 1] > genes["correlation_cap"]:
                    pair_ok = False; break
            if pair_ok:
                chosen.append(j)
            if len(chosen) == 5:
                break
        for j in chosen:
            result[j] = min(genes["asset_weight_cap"], genes["vol_target"]/vol[j]/max(1, len(chosen)))
        return result
    if family == "L":
        market_on = c[btc] > f[f"sma{genes['market_sma_days']}"][i, btc]
        breadth = sum(c[j] > f["sma120"][i, j] for j in ranks)/len(ranks)
        btc_vol = f["vol20"][i, btc]
        prior = f["vol20"][max(0, i-63):i, btc]
        vol_ok = len(prior) >= 30 and np.isfinite(prior).sum() >= 30 and btc_vol <= 1.2*np.nanmedian(prior)
        previous_on = state.get("previous") is not None and np.any(state["previous"] > genes["adverse_exposure_fraction"]*.001)
        threshold = genes["breadth_on"]-.1 if previous_on else genes["breadth_on"]
        good = market_on and breadth >= threshold and vol_ok
        scale = 1 if good else genes["adverse_exposure_fraction"]
        if scale:
            selected = [j for j in ranks if f[f"mom{genes['momentum_days']}"][i, j] > 0]
            vol = f["vol20"][i]
            for j in selected:
                if np.isfinite(vol[j]) and vol[j] > 0:
                    result[j] = min(.25, scale*genes["vol_target"]/vol[j]/max(1, len(selected)))
        return result
    if family == "M":
        vol = f["vol20"][i]
        sleeves = [lambda j: c[j] > f[f"sma{genes['slow_days']}"][i,j],
                   lambda j: c[j] > f[f"breakout{genes['breakout_days']}"][i,j],
                   lambda j: f[f"mom{genes['momentum_days']}"][i,j] > 0]
        for sleeve in sleeves:
            selected = [j for j in ranks if sleeve(j) and np.isfinite(vol[j]) and vol[j] > 0]
            for j in selected:
                result[j] += min(.25/3, genes["vol_target"]/vol[j]/max(1,len(selected))/3)
        return result
    if family == "N":
        atr = f[f"atr{genes['atr_days']}"][i]
        for j in ranks:
            if state.get("cooldown", {}).get(j, -1) > i:
                continue
            if c[j] > f[f"breakout{genes['breakout_days']}"][i,j] and np.isfinite(atr[j]) and atr[j] > 0:
                result[j] = min(.25, genes["risk_per_entry"]*c[j]/(genes["initial_stop_atr"]*atr[j]))
        return result
    raise AssertionError(family)
