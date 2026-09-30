"""Causal, daily-bar development proxy. No production or exchange account imports."""
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
    out = {}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            frame = pd.read_csv(io.BytesIO(archive.read(name)), index_col=0, parse_dates=True)
            frame = frame.loc[:end]
            if len(frame):
                out[name[:-4]] = frame
    return out


def load_market(input_dir: Path, end="2022-04-10"):
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
            name = symbol + "@" + restart.strftime("%Y%m%d")
            lower = restart
        frames[name] = frame.loc[frame.index >= lower]
    dates = pd.date_range("2019-01-01", end, freq="D")
    assets = sorted(frames)
    fields = {}
    for field in ("open", "high", "low", "close", "quote_volume"):
        fields[field] = pd.DataFrame({a: frames[a][field].reindex(dates) for a in assets}, index=dates).astype(float)
    opening, high, low, close, quote = (fields[k].to_numpy() for k in ("open", "high", "low", "close", "quote_volume"))
    observed = fields["close"].gt(0) & fields["quote_volume"].gt(0)
    liquidity = fields["quote_volume"].where(observed).shift(1).rolling(30, min_periods=30).mean()
    base = observed & observed.cumsum().ge(365) & liquidity.ge(10_000_000)
    notices = json.loads(notices_path.read_text())
    for event in notices:
        symbol = event["symbol"]
        if symbol not in base:
            continue
        known = pd.Timestamp(event["published_utc"]).tz_localize(None).normalize()
        effective = pd.Timestamp(event["effective_utc"]).tz_localize(None).normalize()
        base.loc[base.index >= max(known, effective - pd.Timedelta(days=3)), symbol] = False
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
    dates = pd.date_range("2019-01-01", "2022-04-10", freq="D")
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


def evaluate_fold(m: Market, genes: dict, start: str, end: str, *, cost_mult=1.0, delay_entries=False):
    """Flat-start fold; next-open fills, adverse gaps, and whole position episodes."""
    validate_genes(genes)
    lo = int(m.dates.get_indexer([pd.Timestamp(start)])[0])
    hi = int(m.dates.get_indexer([pd.Timestamp(end)])[0])
    if lo < 241 or hi < lo or hi >= len(m.dates):
        raise ValueError("fold_outside_development")
    n = len(m.assets)
    cash = 100.0
    quantity = np.zeros(n)
    previous_mark = m.close[lo-1].copy()
    previous_mark = np.where(np.isfinite(previous_mark), previous_mark, 0)
    nav_before = 100.0
    peak = 100.0
    mdd = 0.0
    daily_log = []
    daily_nav = []
    asset_log = np.zeros(n)
    episode_log = []
    episodes = [None]*n
    turnover = costs = 0.0
    trades = 0
    state = {"cooldown": {}, "previous": None}
    fee = .001*cost_mult
    slip = .001*cost_mult
    for i in range(lo, hi+1):
        signal_i = i-1
        target = targets(m, genes, signal_i, state)
        if delay_entries:
            delayed = targets(m, genes, i-2, {"previous":None,"cooldown":state["cooldown"]})
            target = np.minimum(target, delayed)
        if genes["family"] != "N":
            state["previous"] = target.copy()
        open_px, close_px, low_px = m.opening[i], m.close[i], m.low[i]
        held = quantity > 1e-12
        if np.any(held & (~np.isfinite(open_px) | ~np.isfinite(close_px) | (open_px <= 0) | (close_px <= 0))):
            raise ValueError("missing_held_asset_price")
        safe_open = np.where(np.isfinite(open_px) & (open_px > 0), open_px, 0)
        safe_close = np.where(np.isfinite(close_px) & (close_px > 0), close_px, safe_open)
        equity_open = cash + float(quantity @ safe_open)
        if equity_open <= 0:
            raise ValueError("nonpositive_equity")
        pnl = quantity*(safe_open-previous_mark)
        desired = np.zeros(n)
        allowed = np.isfinite(safe_open) & (safe_open > 0)
        target = np.where(allowed, target, 0)
        target *= min(1, .95/max(float(target.sum()), 1e-12))
        desired[allowed] = target[allowed]*equity_open/safe_open[allowed]
        # Exits execute before entries so the simulated book cannot borrow cash.
        for j in np.flatnonzero(desired < quantity-1e-12):
            delta = min(quantity[j], quantity[j]-desired[j])
            price = safe_open[j]*(1-slip)
            charge = delta*price*fee
            cash += delta*price-charge
            quantity[j] -= delta
            pnl[j] -= delta*(safe_open[j]-price)+charge
            costs += delta*(safe_open[j]-price)+charge
            turnover += delta*price/max(nav_before, 1e-12)
            trades += 1
            if quantity[j] < 1e-12:
                quantity[j] = 0
        for j in np.flatnonzero(desired > quantity+1e-12):
            price = safe_open[j]*(1+slip)
            delta = min(desired[j]-quantity[j], max(cash,0)/(price*(1+fee)))
            if delta <= 1e-12:
                continue
            charge = delta*price*fee
            cash -= delta*price+charge
            quantity[j] += delta
            pnl[j] -= delta*(price-safe_open[j])+charge
            costs += delta*(price-safe_open[j])+charge
            turnover += delta*price/max(nav_before, 1e-12)
            trades += 1
            if episodes[j] is None:
                episodes[j] = {"start": str(m.dates[i].date()), "asset": m.assets[j], "log": 0.0,
                               "entry": price, "high_water": price}
        # N uses a stop frozen from the prior completed bar. Today's high cannot
        # improve a stop that fills during this same bar.
        if genes["family"] == "N":
            prior_atr = m.features[f"atr{genes['atr_days']}"][i-1]
            for j in np.flatnonzero(quantity > 1e-12):
                ep = episodes[j]
                if ep is None or not np.isfinite(prior_atr[j]):
                    continue
                stop = max(ep["entry"]-genes["initial_stop_atr"]*prior_atr[j],
                           ep["high_water"]-genes["trailing_stop_atr"]*prior_atr[j])
                if np.isfinite(low_px[j]) and low_px[j] <= stop:
                    reference = min(safe_open[j], stop)
                    price = reference*(1-slip)
                    delta = quantity[j]
                    charge = delta*price*fee
                    cash += delta*price-charge
                    quantity[j] = 0
                    pnl[j] += delta*(reference-safe_open[j])-delta*(reference-price)-charge
                    costs += delta*(reference-price)+charge
                    turnover += delta*price/max(nav_before, 1e-12)
                    trades += 1
                    state["cooldown"][j] = i+7
                else:
                    ep["high_water"] = max(ep["high_water"], float(m.high[i,j]))
        pnl += quantity*(safe_close-safe_open)
        equity = cash + float(quantity @ safe_close)
        if equity <= 0 or not math.isfinite(equity):
            raise ValueError("nonpositive_or_nonfinite_equity")
        if not math.isclose(equity-nav_before, float(pnl.sum()), rel_tol=1e-8, abs_tol=1e-8):
            raise AssertionError("pnl_reconciliation")
        factor = math.log(equity/nav_before)/(equity-nav_before) if abs(equity-nav_before)>1e-12 else 1/nav_before
        contributions = pnl*factor
        asset_log += contributions
        for j, amount in enumerate(contributions):
            if episodes[j] is not None:
                episodes[j]["log"] += float(amount)
                if quantity[j] == 0:
                    episode_log.append(episodes[j]); episodes[j] = None
        low_book = cash + float(quantity @ np.where(np.isfinite(low_px),low_px,safe_close))
        peak = max(peak, equity)
        mdd = max(mdd, 1-min(equity,low_book)/peak)
        daily_log.append(math.log(equity/nav_before))
        daily_nav.append(equity)
        nav_before = equity
        previous_mark = safe_close.copy()
    for ep in episodes:
        if ep is not None:
            episode_log.append(ep)
    log_total = sum(daily_log)
    if not math.isclose(log_total, float(asset_log.sum()), rel_tol=1e-8, abs_tol=1e-8):
        raise AssertionError("log_attribution")
    years = len(daily_log)/365.25
    cagr = math.exp(log_total/years)-1
    returns = np.expm1(daily_log)
    std = float(np.std(returns, ddof=1)) if len(returns)>1 else 0
    sharpe = float(np.mean(returns)/std*math.sqrt(365.25)) if std>1e-12 else 0
    sorted_episodes = sorted((ep["log"] for ep in episode_log), reverse=True)
    best_day = max(daily_log)
    positive_assets = sorted((x for x in asset_log if x>0), reverse=True)
    return {
        "cagr": cagr, "mdd": mdd, "sharpe": sharpe,
        "calmar": cagr/mdd if mdd>1e-12 else 0,
        "net_return": equity/100-1,
        "no_best_day_cagr": math.exp((log_total-best_day)/years)-1,
        "no_top3_trades_cagr": math.exp((log_total-sum(sorted_episodes[:3]))/years)-1,
        "asset_concentration": positive_assets[0]/log_total if positive_assets and log_total>0 else None,
        "trade_concentration": sorted_episodes[0]/log_total if sorted_episodes and log_total>0 else None,
        "turnover": turnover/years,
        "cost_drag": costs/100/years,
        "episodes": len(episode_log), "trades": trades,
        "days": len(daily_log), "last_nav": equity,
        "audit": {"pnl_reconciled": True, "asset_timing": "signal_close_prior_day_fill_next_open",
                  "episodes_not_split_on_rebalance": True, "proxy_not_venue_certified": True},
    }
