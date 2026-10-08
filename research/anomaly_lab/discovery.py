"""Occurrence, conditional aftermath and economics are separate measurements."""
from collections import Counter
import numpy as np
from .contract import load
from .rules import condition, clusters, definition
from .statistics import block_interval, block_test


def describe(m, f, rule, lo, hi, trial):
    c = load(); mask = condition(m, f, rule)
    grouped = [r for r in clusters(mask, f['eligible'], m.rank, m.assets, rule['horizon'], 0, hi) if r['start'] >= lo]
    days = hi-lo+1; eligible = f['eligible'][lo:hi+1]; daily_covered = eligible.any(axis=1)
    starts = np.zeros(days); raw = mask[lo:hi+1].sum(axis=1)
    asset_events = Counter(); regime_events = Counter(); year_events = Counter(); gaps = []; outcomes = []
    prior = None
    for r in grouped:
        i = r['start']; j = r['asset_index']; starts[i-lo] += 1
        asset_events[m.assets[j]] += 1; regime_events[f['regime'][i]] += 1
        year_events[str(m.dates[i].year)] += 1
        if prior is not None and daily_covered[prior-lo:i-lo+1].all(): gaps.append(i-prior)
        prior = i
        entry_day = i+1+c['publication_buffer_bars']; end = entry_day+rule['horizon']
        if end > hi or not f['quality'][entry_day:end+1, j].all(): continue
        entry = m.opening[entry_day, j]; gross = m.opening[end, j]/entry-1
        if not np.isfinite(gross): continue
        # Matched PRIOR non-event control: same asset and contemporaneous regime.
        control = None; control_date = None
        for k in range(i-rule['horizon']-2-c['publication_buffer_bars'], max(lo-1, i-91), -1):
            first = k+1+c['publication_buffer_bars']; terminal = first+rule['horizon']
            if (f['eligible'][k, j] and f['regime'][k] == f['regime'][i]
                    and not mask[k:terminal+1, j].any() and f['quality'][first:terminal+1, j].all()):
                control = m.opening[terminal, j]/m.opening[first, j]-1
                control_date = m.dates[k].strftime('%Y-%m-%d'); break
        sign = 1 if rule['action'] == 'long' else -1
        outcomes.append({'day': m.dates[i].strftime('%Y-%m-%d'), 'calendar_index': int(i), 'asset': m.assets[j],
                         'gross_forward_return': float(gross), 'favorable': bool(sign*gross > 0),
                         'control_return': float(control) if control is not None else None,
                         'control_day': control_date, 'excess': float(sign*(gross-control)) if control is not None else None,
                         'mfe': float(np.max(m.high[entry_day:end, j])/entry-1),
                         'mae': float(np.min(m.low[entry_day:end, j])/entry-1)})
    years = {}; exposures = []
    for year in sorted(set(m.dates[lo:hi+1].year)):
        ys = m.dates[lo:hi+1].year == year
        exposure = int(daily_covered[ys].sum()); exposures.append(exposure)
        years[str(year)] = {'independent_events': year_events[str(year)], 'raw_asset_day_triggers': int(raw[ys].sum()),
                            'eligible_asset_days': int(eligible[ys].sum()), 'eligible_calendar_days': exposure,
                            'annualized_event_rate': year_events[str(year)]*365.25/exposure if exposure else None}
    pairs = [r for r in outcomes if r['excess'] is not None]
    inference = block_test([r['excess'] for r in pairs], [r['calendar_index'] for r in pairs], trial,
                           block=c['block_days'], min_blocks=c['min_blocks'], repeats=c['resamples'], seed=c['seed']+trial)
    count = len(grouped); denom = int(eligible.sum()); calendar = int(daily_covered.sum())
    if count < c['min_events'] or len(pairs) < c['min_events'] or inference['p'] is None: verdict = 'INSUFFICIENT_EVIDENCE'
    elif inference['rejected']: verdict = 'STATISTICAL_ASSOCIATION_DEVELOPMENT'
    else: verdict = 'NO_ASSOCIATION'
    value = {**definition(rule), 'interval': [m.dates[lo].strftime('%Y-%m-%d'), m.dates[hi].strftime('%Y-%m-%d')],
             'frequency': {'raw_asset_day_triggers': int(raw.sum()), 'independent_events': count,
                           'events_per_year': count*365.25/calendar if calendar else None, 'by_year': years,
                           'eligible_asset_observations': denom, 'eligible_calendar_observations': calendar,
                           'eligible_trigger_share': int(raw.sum())/denom if denom else None,
                           'gap_days_median': float(np.median(gaps)) if gaps else None,
                           'gap_days_variance': float(np.var(gaps, ddof=1)) if len(gaps) > 1 else None,
                           'duration_days_median': float(np.median([r['duration_days'] for r in grouped])) if count else None,
                           'duration_days': [r['duration_days'] for r in grouped],
                           'by_asset': dict(asset_events), 'by_regime': dict(regime_events),
                           'calendar_coverage': calendar/days, 'asset_coverage': denom/(days*len(m.assets)),
                           'frequency_annual_rate_ci95': block_interval(starts, daily_covered, block=c['block_days'],
                                                                      seed=c['seed']+trial, scale=365.25),
                           'uncertainty_method': c['serial_uncertainty']},
             'aftermath': {'completed_events': len(outcomes), 'matched_controls': len(pairs),
                           'favorable_fraction': sum(r['favorable'] for r in outcomes)/len(outcomes) if outcomes else None,
                           'forward_return_quantiles': [float(x) for x in np.quantile([r['gross_forward_return'] for r in outcomes], [.1, .5, .9])] if outcomes else None,
                           'control': 'nearest prior non-event same asset/regime within 90 days; descriptive matched control, residual confounding possible',
                           'events': outcomes},
             'inference': inference, 'trial': trial, 'verdict': verdict,
             'confirmed_trading_candidate': False, 'rare_event_discarded': False,
             'historical_contamination': c['historical_independence']}
    return value
