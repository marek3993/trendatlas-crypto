"""Finite declarative conditions and causal target adapter for the existing book."""
from collections import Counter
import itertools
import numpy as np
import pandas as pd
from research.phase2_v2.market import digest
from .contract import load


def validate(rule):
    c = load()
    if not isinstance(rule, dict) or set(rule) != {'family', 'threshold', 'horizon', 'action'}:
        raise ValueError('declarative_rule_keys')
    f = c['families'].get(rule['family'])
    if f is None or rule['action'] != f['action']:
        raise ValueError('rule_family_or_action')
    if type(rule['horizon']) is not int or rule['horizon'] not in c['horizons']:
        raise ValueError('rule_horizon')
    if type(rule['threshold']) is not type(f['threshold'][0]) or rule['threshold'] not in f['threshold']:
        raise ValueError('rule_threshold')
    return rule


def catalogue():
    c = load()
    return [validate(dict(family=k, threshold=t, horizon=h, action=v['action']))
            for k, v in c['families'].items() for t, h in itertools.product(v['threshold'], c['horizons'])]


def neighbors(rule):
    c = load(); out = []
    for key, values in [('threshold', c['families'][rule['family']]['threshold']), ('horizon', c['horizons'])]:
        j = values.index(rule[key])
        for i in (j-1, j+1):
            if 0 <= i < len(values):
                out.append(validate({**rule, key: values[i]}))
    return out


def prepare(m, production=None):
    """Only current/past bars; suspect bars and unresolved identity segments quarantined."""
    close = pd.DataFrame(m.close, index=m.dates)
    quote = pd.DataFrame(m.quote, index=m.dates)
    good = (np.isfinite(m.opening) & np.isfinite(m.high) & np.isfinite(m.low) & np.isfinite(m.close)
            & np.isfinite(m.quote) & (m.opening > 0) & (m.low > 0) & (m.quote > 0)
            & (m.high >= np.maximum(m.opening, m.close)) & (m.low <= np.minimum(m.opening, m.close)))
    jumps = np.abs(close.pct_change(fill_method=None).to_numpy()) > 9
    good &= ~jumps
    identity = np.array(['@' in a or not a.endswith('USDT') for a in m.assets])
    good[:, identity] = False
    # Consecutive observations, never filling a gap with a stale value.
    coverage = pd.DataFrame(good).rolling(61, min_periods=61).sum().eq(61).to_numpy()
    eligible = m.eligible & coverage
    btc = m.assets.index('BTCUSDT')
    returns = close.pct_change(fill_method=None)
    features = {'quality': good, 'eligible': eligible, 'production': production or {}, 'btc': btc}
    for days in (3, 5, 10, 30):
        features['mom'+str(days)] = (close/close.shift(days)-1).to_numpy()
    std = close.rolling(20, min_periods=20).std()
    features['z20'] = ((close-close.rolling(20, min_periods=20).mean()) / std.replace(0, np.nan)).to_numpy()
    features['vol_ratio'] = (returns.rolling(10).std()/returns.rolling(60).std().replace(0, np.nan)).to_numpy()
    features['volume_ratio'] = (quote/quote.shift(1).rolling(30).mean().replace(0, np.nan)).to_numpy()
    for days in (20, 40, 60):
        features['high'+str(days)] = pd.DataFrame(m.high).rolling(days).max().shift(1).to_numpy()
    prior_mom10 = np.vstack([np.full(len(m.assets), np.nan)]*3 + list(features['mom10'][:-3]))
    features['prior_mom10'] = prior_mom10
    model_asset = np.full(len(m.dates), -1, dtype=int); switches = np.zeros(len(m.dates))
    last = None
    for i, date in enumerate(m.dates):
        asset, exposure = features['production'].get(date.strftime('%Y-%m-%d'), ('CASH', 0.))
        symbol = asset+'USDT'
        if exposure and symbol in m.assets:
            model_asset[i] = m.assets.index(symbol)
        switches[i] = int(last is not None and last != asset)
        last = asset
    features['model_asset'] = model_asset
    features['switches14'] = pd.Series(switches).rolling(14, min_periods=14).sum().to_numpy()
    features['regime'] = np.where(features['mom30'][:, btc] > .05, 'bull',
                                 np.where(features['mom30'][:, btc] < -.05, 'bear', 'sideways'))
    features['health'] = {'invalid_or_unavailable_asset_bars': int((~good).sum()),
                          'suspect_jumps': int(jumps.sum()),
                          'lineage_segments_excluded': [a for a, flag in zip(m.assets, identity) if flag],
                          'derivatives': 'UNAVAILABLE',
                          'volume_kind': 'SPOT_MIXED_EXACT_AND_DECLARED_PROXY',
                          'venue_certified': False, 'point_in_time_universe_certified': False}
    return features


def condition(m, f, rule):
    validate(rule); name = rule['family']; t = rule['threshold']
    if name == 'momentum': mask = f['mom30'] > t
    elif name == 'breakout': mask = m.close > f['high'+str(t)]
    elif name == 'mean_reversion': mask = f['z20'] < -t
    elif name == 'vol_compression': mask = (f['vol_ratio'] < t) & (f['mom5'] > 0)
    elif name == 'vol_expansion': mask = (f['vol_ratio'] > t) & (f['mom5'] > 0)
    elif name == 'volume_reaction': mask = (f['volume_ratio'] > t) & (m.close > m.opening)
    elif name == 'relative_strength':
        mask = (f['mom30']-f['mom30'][:, f['btc'], None] > t) & (f['mom30'][:, f['btc'], None] >= 0)
    elif name == 'reentry_confirmation': mask = (f['mom3'] > t) & (f['prior_mom10'] < 0)
    else:
        if name == 'rotation_churn': mask = (f['switches14'][:, None] >= t) & (f['mom5'] < 0)
        elif name == 'take_profit_context': mask = f['z20'] > t
        elif name == 'stop_trail_context': mask = m.close/f['high20']-1 < -t
        else: raise ValueError('unknown_family')
        mask &= np.arange(len(m.assets))[None, :] == f['model_asset'][:, None]
    return mask & f['eligible']


def clusters(mask, eligible, rank, assets, horizon, lo, hi):
    """Transitive global clustering, with starts known at the first trigger."""
    out = []; last = None
    for i in range(lo, hi+1):
        if not eligible[i].any():
            last = None
            continue
        js = np.flatnonzero(mask[i])
        if not len(js): continue
        if last is None or i-last['last'] > horizon:
            j = min(js, key=lambda j: (rank[i, j], assets[j]))
            last = {'start': i, 'last': i, 'asset_index': int(j), 'assets': set()}
            out.append(last)
        last['last'] = i
        last['assets'].update(assets[j] for j in js)
    return [{**r, 'assets': sorted(r['assets']), 'duration_days': r['last']-r['start']+1} for r in out]


def target_map(m, f, rule, lo, hi):
    """Streaming adapter; neither cluster end nor future label affects an entry."""
    mask = condition(m, f, rule); c = load()
    result = {}; held = None; expiry = -1; last_trigger = None; blocked = False
    for i in range(0, hi+1):
        if not f['eligible'][i].any(): last_trigger = None
        js = np.flatnonzero(mask[i])
        fresh = len(js) and (last_trigger is None or i-last_trigger > rule['horizon'])
        if len(js): last_trigger = i
        if fresh:
            j = min(js, key=lambda j: (m.rank[i, j], m.assets[j]))
            held = m.assets[j].removesuffix('USDT'); expiry = i+rule['horizon']; blocked = True
        if i >= expiry: held = None; blocked = False
        if i < lo-1-c['publication_buffer_bars']: continue
        day = m.dates[i].strftime('%Y-%m-%d')
        if rule['action'] == 'long':
            result[day] = (held, c['exposure']) if held else ('CASH', 0.)
        else:
            base = f['production'].get(day)
            if base is None: raise ValueError('missing_historical_model_target:'+day)
            result[day] = (base[0], base[1]*(.5 if rule['action'] == 'reduce' else 0.)) if blocked else base
    lag = c['publication_buffer_bars']
    return {day.strftime('%Y-%m-%d'): result.get((day-pd.Timedelta(days=lag)).strftime('%Y-%m-%d'), ('CASH', 0.))
            for day in m.dates[max(0, lo-1):hi+1]}


def definition(rule):
    c = load()
    return {'rule': rule, 'normalized_id': digest(rule), 'definition': c['families'][rule['family']]['definition'],
            'availability': '61 consecutive valid bars; frozen top10 prior-liquidity eligibility; identity changes quarantined',
            'signal_publication': c['publication_status'],
            'fill': 'one extra publication-buffer bar then next open; frozen 10bps fee plus 10bps adverse slippage',
            'clustering': c['clustering'], 'scope': 'previously_seen_development', 'data_anomaly_is_signal': False}
