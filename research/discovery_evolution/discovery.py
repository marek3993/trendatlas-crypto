"""Bounded causal onset episodes; dependence is handled at portfolio/block level."""
from collections import Counter
import numpy as np
from research.anomaly_lab.rules import condition, validate
from research.anomaly_lab.statistics import block_interval


def episodes(mask, eligible, rank, assets, horizon, lo, hi):
    active = None; out = []; onsets = 0
    for i in range(max(1, lo), hi+1):
        if not eligible[i].any(): active = None; continue
        onset = mask[i] & ~mask[i-1] & eligible[i] & eligible[i-1]
        js = np.flatnonzero(onset); onsets += len(js)
        if not len(js): continue
        if active is None or i >= active['end_exclusive']:
            j = min(js, key=lambda j: (rank[i, j], assets[j]))
            active = {'start': i, 'end_exclusive': i+horizon, 'representative': int(j), 'last_onset': i, 'assets': set()}
            out.append(active)
        active['assets'].update(assets[j] for j in js); active['last_onset'] = i
    return [{**r, 'assets': sorted(r['assets']), 'duration_days': r['last_onset']-r['start']+1} for r in out], onsets


def discover(m, f, rule, interval):
    validate(rule); lo, hi = m.dates.get_indexer(interval)
    if lo < 1 or hi < lo: raise ValueError('discovery_window')
    mask = condition(m, f, rule); events, onset_count = episodes(mask, f['eligible'], m.rank, m.assets, rule['horizon'], int(lo), int(hi))
    covered = f['eligible'][lo:hi+1].any(axis=1); counts = np.zeros(hi-lo+1); years = {}; outcomes = []
    for e in events:
        i = e['start']; counts[i-lo] += 1; j = e['representative']; entry = i+2; exit_ = entry+rule['horizon']
        if exit_ <= hi and f['quality'][entry:exit_+1, j].all():
            outcomes.append(float(m.opening[exit_, j]/m.opening[entry, j]-1))
    for year in sorted(set(m.dates[lo:hi+1].year)):
        ix = m.dates[lo:hi+1].year == year; exposure = int(covered[ix].sum()); n = int(counts[ix].sum())
        years[str(year)] = {'episodes': n, 'eligible_calendar_days': exposure, 'annual_rate': n*365.25/exposure if exposure else None}
    gaps = [b['start']-a['start'] for a, b in zip(events, events[1:]) if covered[a['start']-lo:b['start']-lo+1].all()]
    return {'rule': rule, 'version': 'bounded_onset_v2', 'interval': interval, 'raw_asset_day_triggers': int(mask[lo:hi+1].sum()),
            'asset_onsets': int(onset_count), 'bounded_episodes': len(events), 'independent_events_claimed': False,
            'eligible_asset_days': int(f['eligible'][lo:hi+1].sum()), 'eligible_calendar_days': int(covered.sum()),
            'years': years, 'max_episode_duration': max((r['duration_days'] for r in events), default=0),
            'gap_median': float(np.median(gaps)) if gaps else None, 'gap_variance': float(np.var(gaps, ddof=1)) if len(gaps)>1 else None,
            'representative_assets': dict(Counter(m.assets[e['representative']] for e in events)),
            'regimes': dict(Counter(str(f['regime'][e['start']]) for e in events)),
            'frequency_ci95': block_interval(counts, covered, block=30, seed=20261009, scale=365.25) if len(events)>=20 else None,
            'uncertainty_status': 'BLOCK_DEVELOPMENT_ESTIMATE' if len(events)>=20 else 'INSUFFICIENT_EVIDENCE',
            'aftermath_descriptive': {'completed': len(outcomes), 'quantiles': [float(x) for x in np.quantile(outcomes, [.1,.5,.9])] if outcomes else None,
                                    'favorable_fraction': sum(v>0 for v in outcomes)/len(outcomes) if outcomes else None},
            'statistical_tests_performed': 0, 'confirmed_trading_candidate': False}
