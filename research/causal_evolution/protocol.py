"""Immutable experimental design. No performance-dependent expansion of space."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import random
from pathlib import Path
from .vendor.common import config, validate, cid, neighbors, canonical

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / 'evolution_contract.json').read_text())
BASE_CONTRACT = json.loads(json.dumps(CONTRACT))

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)

def periods(origin):
    c = CONTRACT['split']
    outer = dt.date(origin, 1, 1)
    gap = dt.timedelta(days=c['purge_embargo_days'] + 1)
    last = outer - gap
    first = last - dt.timedelta(days=c['inner_validation_days'] * c['inner_windows'] - 1)
    result = []
    for k in range(c['inner_windows']):
        start = first + dt.timedelta(days=k*c['inner_validation_days'])
        end = start + dt.timedelta(days=c['inner_validation_days']-1)
        result += [dict(scope='inner_train', fold=k, start=c['anchored_train_start'], end=str(start-gap)),
                   dict(scope='inner_validation', fold=k, start=str(start), end=str(end))]
    result.append(dict(scope='outer', fold=origin, start=str(outer), end=f'{origin}-12-31'))
    return result

def initial(family, seed):
    """Named historical seeds are hypotheses, never imported stored performance."""
    common = [dict(signal='sma200'), dict(signal='mom90', cadence='monthly'),
              dict(signal='breakout120', cadence='weekly'), dict(signal='dual50_200'),
              dict(signal='mom180'), dict(signal='mom365', cadence='monthly')]
    if family == 'G':
        common = [dict(signal='sma150', cadence='monthly', satellite=.5, confirm=3),
                  dict(signal='sma150', cadence='monthly', satellite=.5, confirm=7, hysteresis=.01),
                  dict(signal='sma200'), dict(signal='breakout120'), dict(signal='mom180'),
                  dict(signal='dual50_200', satellite=.75, satellite_k=2)]
    if family == 'H':
        common = [dict(x, top_k=[2,3,5][i%3], weighting='inverse_vol' if i%2 else 'equal_risk')
                  for i,x in enumerate(common)]
    if family == 'D':
        common = [dict(x, recipe=['btc_regime','own_trend_ls','beta_neutral','funding_aware'][i%4],
                       gross=1.0 if i%2 else 1.25) for i,x in enumerate(common)]
    out = {cid(c): c for c in (config(family=family, **x) for x in common)}
    rng = random.Random(seed)
    while len(out) < 10:
        c = mutate(rng.choice(list(out.values())), rng)
        out[cid(c)] = c
    return list(out.values())

def mutate(parent, rng):
    keys = [k for k in CONTRACT['schema'] if k != 'family']
    for _ in range(1000):
        key = rng.choice(keys)
        raw = dict(parent, **{key: rng.choice(CONTRACT['schema'][key])})
        try:
            child = validate(raw)
        except ValueError:
            continue
        if child != parent:
            return child
    raise RuntimeError('No admissible mutation')

def four_mutations(parents, seed, existing):
    rng = random.Random(seed)
    result = []
    seen = set(existing)
    for _ in range(5000):
        parent = rng.choice(parents)
        genes = mutate(parent, rng)
        if cid(genes) in seen:
            continue
        result.append(dict(parent=cid(parent), genes=genes,
                           hypothesis='Deterministic single-enum causal rule mutation.'))
        seen.add(cid(genes))
        if len(result) == 4:
            return result
    raise RuntimeError('Mutation diversity exhausted')

def plateau_neighbors(genes):
    # Lexically stable subset frozen before any evaluation, never hand-picked.
    return neighbors(genes)[:CONTRACT['budget']['plateau_neighbors']]

def complexity(c):
    baseline = config(family=c['family']) if c['family'] != 'H' else config(family='H', weighting='inverse_vol')
    return sum(c[k] != baseline[k] for k in c) + (2 if c['signal'].startswith(('dual','combo')) else 1) + {'F':0,'G':2,'H':2,'D':3}[c['family']]

def next_refit(today):
    first = dt.date.fromisoformat(CONTRACT['continuation']['first_refit'])
    if today < first:
        return first
    for year in (today.year, today.year+1):
        for month in (1,4,7,10):
            d = dt.date(year,month,1)
            if d > today:
                return d

def successor_allowed(previous, incoming, today):
    """Hash changes alone never admit a successor, and reject loops cannot refit."""
    cutoff = dt.date.fromisoformat(incoming['closed_through'])
    anchor = max(dt.date.fromisoformat(previous['closed_through']),
                 dt.date.fromisoformat(CONTRACT['continuation']['new_days_anchor']))
    reasons = []
    if previous['status'] != 'SEALED': reasons.append('previous_not_sealed')
    if today < dt.date.fromisoformat(previous['next_refit']): reasons.append('fixed_refit_not_due')
    if (cutoff-anchor).days < 30: reasons.append('fewer_than_30_new_closed_days')
    if cutoff >= today: reasons.append('unclosed_UTC_day')
    if incoming['fingerprint'] == previous['fingerprint']: reasons.append('unchanged_data')
    if incoming['experiment_id'] == previous['experiment_id']: reasons.append('same_experiment_id')
    if incoming.get('parent_fingerprint') != previous['fingerprint']: reasons.append('not_append_only')
    if not incoming.get('coverage_complete'): reasons.append('incomplete_PIT_or_venue_coverage')
    return not reasons, reasons

def fingerprint(root=HERE):
    paths = sorted(p for p in root.rglob('*') if p.is_file() and
                   p.suffix in ('.py','.json','.zip') and
                   not any(x in p.parts for x in ('local_state','__pycache__','evidence')))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def freeze(state, synthetic=False):
    state = Path(state); path = state/'frozen_manifest.json'
    current = fingerprint()
    dataset=None
    if (state/'cycle.json').exists():
        descriptor=json.loads((state/'cycle.json').read_text())
        configure_cycle(descriptor)
        dataset=descriptor['dataset']
        current['external_dataset_manifest']=digest(dataset)
        for name,h in dataset['files'].items():
            actual=hashlib.sha256((Path(dataset['directory'])/name).read_bytes()).hexdigest()
            if actual!=h:raise RuntimeError('Frozen external raw data changed')
            current['external_inputs/'+name]=h
    if path.exists():
        old = json.loads(path.read_text())
        if old['files'] != current or old['synthetic'] != synthetic:
            raise RuntimeError('Frozen evaluator/data changed: new experiment required; cannot resume')
        return old
    manifest = dict(experiment_id=CONTRACT['id'] + ('_SYNTHETIC_TEST' if synthetic else ''),
                    created_utc=utc(), contract=CONTRACT, files=current,
                    fingerprint=digest(current), synthetic=synthetic,
                    periods={str(y):periods(y) for y in CONTRACT['budget']['outer_origins']},
                    historical_label='PREVIOUSLY_SEEN_NOT_GLOBAL_SEALED',
                    prospective_start='2026-09-27',dataset=dataset,
                    synthetic_profile=dict(islands=['F_spot'],origins=[2024],generations=2,seeds=[1701,2903,4517],arms=['deterministic','deepseek_fallback'],note='Small end-to-end protocol test; all four families covered by independent ledger/causality unit tests') if synthetic else None)
    atomic(path,manifest)
    return manifest

def configure_cycle(descriptor):
    """Only mechanical yearly roll, under the originally frozen budget/schema."""
    end=dt.date.fromisoformat(descriptor['dataset']['closed_through'])
    if (end.month,end.day)!=(12,31) or end.year<2026:raise ValueError('Successor requires a newly completed calendar year')
    expected=f'causal_nested_v1_{end.year+1}0101'
    if descriptor['experiment_id']!=expected:raise ValueError('Unexpected successor experiment ID')
    required={'spot_daily.zip','spot_4h.zip','perp_trade.zip','perp_mark.zip','funding.zip','identity_events.json','venue_notices.json'}
    if set(descriptor['dataset']['files'])!=required or not descriptor['dataset']['coverage_complete']:raise ValueError('Incomplete dataset contract')
    CONTRACT.clear();CONTRACT.update(json.loads(json.dumps(BASE_CONTRACT)))
    CONTRACT['id']=expected;CONTRACT['split']['data_end']=str(end)
    CONTRACT['split']['outer_years']=[end.year-1,end.year];CONTRACT['budget']['outer_origins']=[end.year-1,end.year]
    CONTRACT['continuation']['first_refit']=str(dt.date(end.year+2,1,1))
    from .vendor import data
    data.OLD=Path(descriptor['dataset']['directory']).resolve()
