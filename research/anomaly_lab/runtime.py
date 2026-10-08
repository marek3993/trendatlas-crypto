"""Append-only checkpointed research, bounded per tick, without network or secrets."""
from datetime import datetime, timedelta
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

from research.phase2_v2.market import canonical, digest, load_market
from research.phase2_v2.engine import evaluate, curve_metrics
from research.phase2_v2.contract import load as phase2_contract
from research.phase2_v2.inputs import guarded_rows
from research.phase2_v2.runtime import atomic, utc
from research.phase2_v2.broker import broker_lock
from .contract import load
from .rules import catalogue, validate, neighbors, prepare, target_map, definition
from .discovery import describe
from .statistics import block_interval


def connect(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root/'lab.sqlite', timeout=20)
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS hypotheses(id TEXT PRIMARY KEY,rule TEXT,parent TEXT,source TEXT,origin INTEGER,narrative TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS trials(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT UNIQUE,spec TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS results(trial INTEGER PRIMARY KEY,origin INTEGER,hypothesis TEXT,phase TEXT,body TEXT,utc TEXT,UNIQUE(origin,hypothesis,phase));
    CREATE TABLE IF NOT EXISTS requests(origin INTEGER PRIMARY KEY,hash TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS ai_receipts(origin INTEGER PRIMARY KEY,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS selections(origin INTEGER,family TEXT,hypothesis TEXT,body TEXT,utc TEXT,PRIMARY KEY(origin,family));
    CREATE TABLE IF NOT EXISTS books(origin INTEGER,family TEXT,stress TEXT,body TEXT,utc TEXT,PRIMARY KEY(origin,family,stress));
    CREATE TABLE IF NOT EXISTS origins(origin INTEGER PRIMARY KEY,utc TEXT);
    CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,body TEXT,previous TEXT,hash TEXT UNIQUE);
    ''')
    for table in ('meta', 'hypotheses', 'trials', 'results', 'requests', 'ai_receipts', 'selections', 'books', 'origins', 'handoffs', 'events'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_lab_evidence'); END")
    db.commit(); return db


def event(db, kind, **body):
    previous = db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
    prior = previous[0] if previous else 'GENESIS'
    value = canonical({'utc': utc(), 'kind': kind, **body})
    db.execute('INSERT INTO events(body,previous,hash) VALUES(?,?,?)', (value, prior, digest([value, prior])))


def binding(inputs):
    c = load(); inputs = Path(inputs)
    manifest_path = inputs/'manifest.json'
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != c['input_manifest_sha256']:
        raise ValueError('unauthorized_frozen_input_manifest')
    manifest = json.loads(manifest_path.read_text())
    if manifest['development'] != [c['development']] or manifest['last'] > c['development'][1]:
        raise ValueError('sealed_or_incompatible_input_manifest')
    for name, expected in manifest['files'].items():
        path = (inputs/name).resolve()
        if path.parent != inputs.resolve() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('frozen_input_changed:'+name)
    here = Path(__file__).resolve().parent
    source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(here.glob('*.py'))}
    phase2 = here.parent/'phase2_v2'
    return {'contract': digest(c), 'code': source, 'inputs': digest(manifest),
            'engine': hashlib.sha256((phase2/'engine.py').read_text().encode()).hexdigest(),
            'market_loader': hashlib.sha256((phase2/'market.py').read_text().encode()).hexdigest(),
            'phase2_contract': digest(phase2_contract())}


def initialize(db, bound):
    row = db.execute("SELECT body FROM meta WHERE key='binding'").fetchone()
    if row:
        if json.loads(row[0]) != bound: raise ValueError('lab_checkpoint_binding_changed')
        return
    with db:
        db.execute("INSERT INTO meta VALUES('binding',?)", (canonical(bound),))
        db.execute("INSERT INTO meta VALUES('budget_id',?)", (canonical(load()['api_budget_id']),))
        event(db, 'experiment_frozen', binding=bound, contract=load(), folds=phase2_contract()['walk_forward']['validation_folds'])


def register(db, rule, origin, source, parent=None, narrative=None):
    validate(rule); hid = digest(rule)
    existing = db.execute('SELECT id FROM hypotheses WHERE id=?', (hid,)).fetchone()
    if existing: return hid
    if db.execute('SELECT COUNT(*) FROM hypotheses').fetchone()[0] >= load()['budgets']['max_hypotheses']:
        raise ValueError('finite_hypothesis_budget')
    with db:
        db.execute('INSERT INTO hypotheses VALUES(?,?,?,?,?,?,?)',
                   (hid, canonical(rule), parent, source, origin, canonical(narrative or {}), utc()))
        event(db, 'hypothesis_registered', id=hid, origin=origin, source=source, parent=parent,
              similarity='same family; threshold/horizon Hamming distance', normalized_identity=hid)
    return hid


def reserve(db, origin, hid, phase, folds):
    key = digest([origin, hid, phase]); row = db.execute('SELECT id FROM trials WHERE key=?', (key,)).fetchone()
    if row: return row[0]
    rule = json.loads(db.execute('SELECT rule FROM hypotheses WHERE id=?', (hid,)).fetchone()[0]) if hid else None
    spec = {'origin': origin, 'hypothesis': hid, 'phase': phase, 'folds': folds, 'rule': rule,
            'contract': digest(load()), 'binding': json.loads(db.execute("SELECT body FROM meta WHERE key='binding'").fetchone()[0]),
            'null': load()['null'], 'multiplicity': load()['multiplicity'], 'costs': phase2_contract()['execution'],
            'neighbors': neighbors(rule) if rule else [], 'freeze_before_results': True}
    with db:
        cursor = db.execute('INSERT INTO trials(key,spec,utc) VALUES(?,?,?)', (key, canonical(spec), utc()))
        number = cursor.lastrowid; event(db, 'trial_reserved', trial=number, key=key, phase=phase)
    return number


def training(origin):
    start = datetime.fromisoformat(phase2_contract()['walk_forward']['validation_folds'][origin][0]).date()
    c = load(); lo = start-timedelta(days=c['training']['days']); end = start-timedelta(days=c['training']['purge_days']+1)
    mid = lo+timedelta(days=(end-lo).days//2)
    return [[lo.isoformat(), mid.isoformat()], [(mid+timedelta(days=1)).isoformat(), end.isoformat()]]


def index(m, folds):
    lo, hi = m.dates.get_indexer([folds[0][0], folds[-1][1]])
    if lo < 200 or hi < lo: raise ValueError('lab_insufficient_warmup')
    return int(lo), int(hi)


def execute(m, f, rule, folds, stress='nominal', checkpoint=None):
    lo, hi = index(m, folds)
    targets = target_map(m, f, rule, lo, hi)
    check_trade_data(m, f, targets, lo, hi, checkpoint)
    return evaluate(m, 'PRODUCTION', folds, production_targets=targets, initial_state=copy.deepcopy(checkpoint),
                    cost_mult=2. if stress == 'double_cost' else 1., delay_entries=stress == 'delayed_entry')


def control(m, f, rule, folds, stress='nominal', checkpoint=None):
    lo, hi = index(m, folds)
    c = load()
    targets = {}
    for date in m.dates[max(0, lo-1):hi+1]:
        key = date.strftime('%Y-%m-%d')
        if rule['action'] == 'long': targets[key] = ('BTC', c['exposure'])
        else:
            prior = (date-timedelta(days=c['publication_buffer_bars'])).strftime('%Y-%m-%d')
            if prior not in f['production']: raise ValueError('missing_historical_control_target:'+prior)
            targets[key] = f['production'][prior]
    check_trade_data(m, f, targets, lo, hi, checkpoint)
    return evaluate(m, 'PRODUCTION', folds, production_targets=targets, initial_state=copy.deepcopy(checkpoint),
                    cost_mult=2. if stress == 'double_cost' else 1., delay_entries=stress == 'delayed_entry')


def check_trade_data(m, f, targets, lo, hi, checkpoint=None):
    # Outcome-time integrity audit invalidates a trial; it never changes signals
    # with future quality knowledge or invents a sale around a halt/bad candle.
    possible = {m.assets[j] for j, q in enumerate((checkpoint or {}).get('quantity', [])) if q > 1e-12}
    recent = []
    for i in range(lo, hi+1):
        prior = m.dates[i-1].strftime('%Y-%m-%d'); asset, weight = targets.get(prior, ('CASH', 0.))
        active = {asset+'USDT'} if weight else set()
        for symbol in possible | active | set().union(*recent):
            if symbol in m.assets and not f['quality'][i, m.assets.index(symbol)]:
                raise ValueError('invalid_execution_candle:'+m.dates[i].strftime('%Y-%m-%d')+':'+symbol)
        recent = (recent+[active])[-2:]; possible = set()


def compact_discovery(value):
    return {k: v for k, v in value.items() if k != 'aftermath'} | {
        'aftermath': {k: v for k, v in value['aftermath'].items() if k != 'events'}}


def train_result(db, m, f, hid, origin):
    existing = db.execute("SELECT body FROM results WHERE origin=? AND hypothesis=? AND phase='train'", (origin, hid)).fetchone()
    if existing: return json.loads(existing[0])
    rule = json.loads(db.execute('SELECT rule FROM hypotheses WHERE id=?', (hid,)).fetchone()[0])
    folds = training(origin); trial = reserve(db, origin, hid, 'train', folds); lo, hi = index(m, folds)
    description = describe(m, f, rule, lo, hi, trial)
    try:
        result = execute(m, f, rule, folds); reference = control(m, f, rule, folds)
        inner = result['folds'][1]['metrics']; reference_inner = reference['folds'][1]['metrics']
        value = {'valid': True, 'metrics': result['metrics'], 'folds': result['folds'],
                 'validation_excess': inner['log_growth']-reference_inner['log_growth'],
                 'screen_excess': result['folds'][0]['metrics']['log_growth']-reference['folds'][0]['metrics']['log_growth'],
                 'validation_mdd': inner['mdd'], 'audit': result['audit'], 'discovery': compact_discovery(description)}
    except (ValueError, AssertionError) as exc:
        value = {'valid': False, 'error': str(exc), 'verdict': 'UNDEFINED_INVALID', 'discovery': compact_discovery(description)}
    with db:
        db.execute('INSERT INTO results VALUES(?,?,?,?,?,?)', (trial, origin, hid, 'train', canonical(value), utc()))
        event(db, 'trial_completed', trial=trial, valid=value['valid'])
    return value


def queue_ai(db, root, origin):
    existing = db.execute('SELECT hash FROM requests WHERE origin=?', (origin,)).fetchone()
    if existing: return existing[0]
    c = load(); rows = []
    for hid, rule, body in db.execute("SELECT h.id,h.rule,r.body FROM hypotheses h JOIN results r ON h.id=r.hypothesis WHERE r.origin=? AND r.phase='train' ORDER BY h.id", (origin,)):
        rule = json.loads(rule); value = json.loads(body); d = value['discovery']
        rows.append({'id': hid, 'rule': rule, 'events': d['frequency']['independent_events'],
                     'per_year': d['frequency']['events_per_year'], 'favorable': d['aftermath']['favorable_fraction'],
                     'quantiles': d['aftermath']['forward_return_quantiles'],
                     'validation_excess': value.get('validation_excess'), 'failure': value.get('error'),
                     'mdd': value.get('validation_mdd')})
    # Bounded representatives, never arrays, historical ledgers or seen hashes.
    by_family = {}
    for row in rows:
        k = row['rule']['family']
        if k not in by_family or (row['validation_excess'] or -1e9) > (by_family[k]['validation_excess'] or -1e9): by_family[k] = row
    payload = {'cycle_id': c['api_budget_id'], 'scope': 'anomaly_prior_training_only', 'origin': origin,
               'training_cutoff': training(origin)[-1][1], 'schema': {k: {'threshold': v['threshold'], 'action': v['action']} for k, v in c['families'].items()},
               'horizons': c['horizons'], 'aggregates': list(by_family.values()),
               'required': 'inputs, rule, direction, horizon, mechanism, parameters, falsification, parent; four hypotheses',
               'derivatives': 'UNAVAILABLE', 'historical_independence': 'NONE_PREVIOUSLY_SEEN'}
    key = digest(payload)
    path = Path(root)/'mailbox/requests'/f'{key}.json'
    atomic(path, {'hash': key, 'payload': payload})
    with db:
        db.execute('INSERT INTO requests VALUES(?,?,?)', (origin, key, utc())); event(db, 'ai_request_queued', origin=origin, hash=key)
    return key


def collect_ai(db, root, origin, key):
    if db.execute('SELECT 1 FROM ai_receipts WHERE origin=?', (origin,)).fetchone(): return True
    path = Path(root)/'mailbox/responses'/f'{key}.json'
    queued = db.execute('SELECT utc FROM requests WHERE origin=?', (origin,)).fetchone()[0]
    if not path.exists() and (datetime.now().astimezone()-datetime.fromisoformat(queued)).total_seconds() < load()['budgets']['ai_wait_seconds']:
        return False
    response = json.loads(path.read_text()) if path.exists() else {'state': 'FALLBACK', 'error': 'ai_wait_timeout'}
    accepted = []; rejected = []
    if response.get('hash', key) != key: raise ValueError('ai_response_binding')
    if response['state'] == 'COMPLETE':
        try:
            body = json.loads(response['content'])
            if set(body) != {'hypotheses'} or not isinstance(body['hypotheses'], list) or len(body['hypotheses']) > 4:
                raise ValueError('ai_envelope')
            for proposal in body['hypotheses']:
                try:
                    required = {'inputs', 'rule', 'direction', 'horizon', 'mechanism', 'parameters', 'falsification', 'parent'}
                    if set(proposal) != required: raise ValueError('ai_hypothesis_fields')
                    validate(proposal['rule'])
                    parent = proposal['parent']
                    if parent is not None and not db.execute('SELECT 1 FROM hypotheses WHERE id=? AND origin<=?', (parent, origin)).fetchone():
                        raise ValueError('unknown_or_future_parent')
                    if proposal['horizon'] != proposal['rule']['horizon'] or proposal['parameters'] != {'threshold': proposal['rule']['threshold']}:
                        raise ValueError('hypothesis_parameters_disagree')
                    if proposal['direction'] != proposal['rule']['action'] or not isinstance(proposal['inputs'], list):
                        raise ValueError('hypothesis_direction_or_inputs')
                    if not all(isinstance(proposal[k], str) and 0 < len(proposal[k]) <= 500 for k in ('mechanism', 'falsification')):
                        raise ValueError('hypothesis_explanation')
                    hid = register(db, proposal['rule'], origin, 'deepseek', parent, proposal); accepted.append(hid)
                except (ValueError, TypeError) as exc: rejected.append(str(exc))
        except (ValueError, TypeError, KeyError) as exc: rejected.append(str(exc))
    with db:
        db.execute('INSERT INTO ai_receipts VALUES(?,?,?)', (origin, canonical({'accepted': accepted, 'rejected': rejected, 'response': response}), utc()))
        event(db, 'ai_proposals_validated', origin=origin, accepted=accepted, rejected=rejected, state=response['state'])
    return True


def freeze_selection(db, origin, family):
    row = db.execute('SELECT hypothesis,body FROM selections WHERE origin=? AND family=?', (origin, family)).fetchone()
    if row: return row[0], json.loads(row[1])
    choices = []
    for hid, rule, body in db.execute("SELECT h.id,h.rule,r.body FROM hypotheses h JOIN results r ON h.id=r.hypothesis WHERE r.origin=? AND r.phase='train'", (origin,)):
        rule = json.loads(rule); value = json.loads(body)
        if rule['family'] != family or not value['valid']: continue
        if not np_finite(value.get('validation_excess')): continue
        choices.append((value['validation_excess'], -value['validation_mdd'], hid, rule, value))
    if not choices:
        hid = None; evidence = {'selection': 'CASH_NO_VALID_HYPOTHESIS', 'rule': None, 'neighbors': [], 'neighbor_stable': False}
    else:
        best = sorted(choices, key=lambda r: (-r[0], -r[1], r[2]))[0]
        hid, rule, value = best[2:]
        neighbor_results = []
        for neighbor in neighbors(rule):
            row = db.execute("SELECT body FROM results WHERE origin=? AND hypothesis=? AND phase='train'", (origin, digest(neighbor))).fetchone()
            if row is None: raise ValueError('missing_predeclared_neighbor_evaluation')
            nb = json.loads(row[0]); neighbor_results.append({'id': digest(neighbor), 'valid': nb['valid'], 'validation_excess': nb.get('validation_excess')})
        stable = all(r['valid'] and r['validation_excess'] >= 0 for r in neighbor_results)
        evidence = {'selection': 'EXPLORATORY_PAST_ONLY', 'rule': rule, 'training_cutoff': training(origin)[-1][1],
                    'validation_excess': value['validation_excess'], 'screen_excess': value['screen_excess'],
                    'neighbors': neighbor_results, 'neighbor_stable': stable, 'independent_validation': False,
                    'eligibility': value['validation_excess'] > 0 and value['screen_excess'] > 0 and stable}
    with db:
        db.execute('INSERT INTO selections VALUES(?,?,?,?,?)', (origin, family, hid, canonical(evidence), utc()))
        event(db, 'selection_frozen_before_test', origin=origin, family=family, hypothesis=hid, evidence=evidence)
    return hid, evidence


def np_finite(value):
    import math
    return isinstance(value, (int, float)) and math.isfinite(value)


def previous_book(db, origin, family, stress):
    if not origin: return None
    row = db.execute('SELECT body FROM books WHERE origin=? AND family=? AND stress=?', (origin-1, family, stress)).fetchone()
    if row is None: raise ValueError('missing_previous_continuous_book')
    return json.loads(row[0])


def test_book(db, m, f, origin, family, stress, hid, evidence):
    if db.execute('SELECT 1 FROM books WHERE origin=? AND family=? AND stress=?', (origin, family, stress)).fetchone(): return
    folds = [phase2_contract()['walk_forward']['validation_folds'][origin]]
    rule = evidence['rule']; key = digest([hid, family, stress])
    trial = reserve(db, origin, hid, 'test_'+family+'_'+stress, folds)
    previous = previous_book(db, origin, family, stress)
    try:
        if previous and not previous.get('valid'): raise ValueError('NOT_EVALUABLE_CONTINUITY_LOST')
        checkpoint = previous['result']['checkpoint'] if previous else None
        result = (execute(m, f, rule, folds, stress, checkpoint) if rule else
                  evaluate(m, 'CASH', folds, initial_state=checkpoint, cost_mult=2. if stress == 'double_cost' else 1.))
        if rule and stress == 'nominal':
            from .accounting import check
            lo, hi = index(m, folds)
            result['audit']['independent_accounting'] = check(m, target_map(m, f, rule, lo, hi), folds, result, checkpoint)
        body = {'valid': True, 'result': result, 'hypothesis': hid, 'trial': trial}
    except (ValueError, AssertionError) as exc:
        body = {'valid': False, 'error': str(exc), 'verdict': 'UNDEFINED_INVALID', 'hypothesis': hid, 'trial': trial}
    if rule and stress == 'nominal':
        lo, hi = index(m, folds); body['discovery'] = describe(m, f, rule, lo, hi, trial)
    with db:
        db.execute('INSERT INTO books VALUES(?,?,?,?,?)', (origin, family, stress, canonical(body), utc()))
        event(db, 'frozen_test_completed', origin=origin, family=family, stress=stress, valid=body['valid'], trial=trial)


def benchmark_book(db, m, f, origin, family):
    if db.execute("SELECT 1 FROM books WHERE origin=? AND family=? AND stress='nominal'", (origin, family)).fetchone(): return
    folds = [phase2_contract()['walk_forward']['validation_folds'][origin]]
    reserve(db, origin, None, family, folds); previous = previous_book(db, origin, family, 'nominal')
    try:
        if previous and not previous.get('valid'): raise ValueError('NOT_EVALUABLE_CONTINUITY_LOST')
        checkpoint = previous['result']['checkpoint'] if previous else None
        if family == 'control_cash': result = evaluate(m, 'CASH', folds, initial_state=checkpoint)
        else: result = control(m, f, {'action': 'long' if family == 'control_btc' else 'avoid'}, folds, checkpoint=checkpoint)
        body = {'valid': True, 'result': result}
    except (ValueError, AssertionError) as exc: body = {'valid': False, 'error': str(exc), 'verdict': 'UNDEFINED_INVALID'}
    with db: db.execute('INSERT INTO books VALUES(?,?,?,?,?)', (origin, family, 'nominal', canonical(body), utc()))


def summarize(db, family, stress='nominal'):
    books = [json.loads(r[0]) for r in db.execute('SELECT body FROM books WHERE family=? AND stress=? ORDER BY origin', (family, stress))]
    if not books: return None
    if any(not b['valid'] for b in books): return {'valid': False, 'verdict': 'UNDEFINED_INVALID', 'cagr': None, 'failures': [b.get('error') for b in books if not b['valid']]}
    rows = [r for b in books for r in b['result']['equity']]
    metrics = curve_metrics([r['date'] for r in rows], [r['equity'] for r in rows])
    # Whole episodes in final checkpoint contain their FULL carried history.
    episodes = {ep['id']: ep for b in books for ep in b['result']['episodes']}
    growth = metrics['log_growth']; years = len(rows)/365.25
    positive_closed = sorted([e for e in episodes.values() if e['status'] == 'CLOSED' and e['log_contribution'] > 0], key=lambda e: e['log_contribution'], reverse=True)
    asset_growth = {}; period_growth = {}
    for b in books:
        for r in b['result']['assets']: asset_growth[r['asset']] = asset_growth.get(r['asset'], 0.)+r['log_contribution']
        for r in b['result']['equity']:
            year = r['date'][:4]; period_growth[year] = period_growth.get(year, 0.)+r['log_return']
    import math
    metrics.update(no_top3_trades_cagr=math.expm1((growth-sum(e['log_contribution'] for e in positive_closed[:3]))/years) if len(positive_closed) >= 3 else None,
                   top3_removed=[e['id'] for e in positive_closed[:3]],
                   asset_concentration=max(asset_growth.values())/growth if growth > 0 else None,
                   trade_concentration=max((e['log_contribution'] for e in episodes.values()), default=0.)/growth if growth > 0 and episodes else None,
                   period_concentration=max(period_growth.values())/growth if growth > 0 else None,
                   profitable_fold_fraction=sum(b['result']['metrics']['net_return'] > 0 for b in books)/len(books),
                   costs_usd=sum(r['costs_usd'] for r in rows),
                   daily_net_return_ci95=block_interval([math.expm1(r['log_return']) for r in rows], [1.]*len(rows), seed=load()['seed']))
    if not math.isclose(sum(e['log_contribution'] for e in episodes.values()), growth, rel_tol=1e-7, abs_tol=1e-7):
        raise AssertionError('whole_episode_reconciliation')
    return {'valid': True, **metrics, 'processed_folds': len(books), 'scope': 'causal_nested_previously_seen_development',
            'initial_equity': 100., 'terminal_equity': rows[-1]['equity'], 'confirmed_trading_candidate': False}


def report(db, root, f=None):
    c = load(); completed = db.execute('SELECT COUNT(*) FROM origins').fetchone()[0]
    families = {}
    for family in (*c['families'], 'control_btc', 'control_model', 'control_cash'):
        value = summarize(db, family)
        if value is None: continue
        if family in c['families'] and value['valid']:
            double = summarize(db, family, 'double_cost'); delayed = summarize(db, family, 'delayed_entry')
            value['double_cost_cagr'] = double.get('cagr') if double else None
            value['delayed_entry_cagr'] = delayed.get('cagr') if delayed else None
            gates = c['economic_gates']; failed = []
            for key, cap in [('mdd', gates['mdd_max']), ('asset_concentration', gates['asset_concentration_max']),
                             ('trade_concentration', gates['trade_concentration_max']), ('period_concentration', gates['period_concentration_max'])]:
                if value.get(key) is None or value[key] > cap: failed.append(key)
            for key in ('double_cost_cagr', 'delayed_entry_cagr', 'no_best_day_cagr', 'no_top3_trades_cagr'):
                if value.get(key) is None or value[key] <= 0: failed.append(key)
            if any(not json.loads(r[0]).get('neighbor_stable') for r in db.execute('SELECT body FROM selections WHERE family=?', (family,))): failed.append('parameter_neighbors')
            value['economic_gates_failed'] = failed; value['economically_useful_development'] = not failed
        families[family] = value
    status = {'utc': utc(), 'state': 'EXHAUSTED' if completed == c['budgets']['max_origins'] else 'RUNNING',
              'processed_origins': completed, 'lifetime_trials': db.execute('SELECT COUNT(*) FROM trials').fetchone()[0],
              'hypotheses': db.execute('SELECT COUNT(*) FROM hypotheses').fetchone()[0],
              'completed_training': db.execute('SELECT COUNT(*) FROM results').fetchone()[0],
              'completed_books': db.execute('SELECT COUNT(*) FROM books').fetchone()[0],
              'ai_receipts': db.execute('SELECT COUNT(*) FROM ai_receipts').fetchone()[0],
              'handoffs': db.execute('SELECT COUNT(*) FROM handoffs').fetchone()[0],
              'sealed_access': False, 'orders_allowed': False, 'production_touched': False,
              'scope': c['historical_independence'], 'family_portfolios': families}
    if f: status['data_health'] = f['health']
    atomic(Path(root)/'status.json', status); return status


def work(db, root, m, f, deadline):
    c = load(); origin = db.execute('SELECT COUNT(*) FROM origins').fetchone()[0]
    if origin >= c['budgets']['max_origins']: return report(db, root, f)
    for rule in catalogue():
        # Initial declarative seed and its complete declared neighbors.
        if rule['threshold'] == c['families'][rule['family']]['threshold'][1] and rule['horizon'] == c['horizons'][0]:
            parent = register(db, rule, origin, 'deterministic')
            for nb in neighbors(rule): register(db, nb, origin, 'neighbor', parent)
    for hid, in db.execute('SELECT id FROM hypotheses WHERE origin<=? ORDER BY id', (origin,)).fetchall():
        train_result(db, m, f, hid, origin)
        if time.monotonic() >= deadline: return report(db, root, f)
    key = queue_ai(db, root, origin)
    if not collect_ai(db, root, origin, key): return report(db, root, f)
    # AI ideas and their neighbors are tested ONLY on this origin's previous data.
    for hid, rule in db.execute('SELECT id,rule FROM hypotheses WHERE origin<=? ORDER BY id', (origin,)).fetchall():
        for nb in neighbors(json.loads(rule)): register(db, nb, origin, 'neighbor', hid)
    for hid, in db.execute('SELECT id FROM hypotheses WHERE origin<=? ORDER BY id', (origin,)).fetchall():
        train_result(db, m, f, hid, origin)
        if time.monotonic() >= deadline: return report(db, root, f)
    from .handoff import export
    for family in c['families']:
        hid, evidence = freeze_selection(db, origin, family)
        if hid: export(db, root, origin, hid, evidence)
        for stress in ('nominal', 'double_cost', 'delayed_entry'):
            test_book(db, m, f, origin, family, stress, hid, evidence)
            if time.monotonic() >= deadline: return report(db, root, f)
    for family in ('control_btc', 'control_model', 'control_cash'): benchmark_book(db, m, f, origin, family)
    with db:
        db.execute('INSERT INTO origins VALUES(?,?)', (origin, utc())); event(db, 'origin_completed', origin=origin)
    return report(db, root, f)


def run(root, inputs, seconds=None):
    c = load(); root = Path(root)
    if shutil.disk_usage(root.parent).free < c['budgets']['disk_reserve_bytes']: raise ValueError('disk_reserve')
    if (root/'lab.sqlite').exists() and (root/'lab.sqlite').stat().st_size > c['budgets']['ledger_max_bytes']: raise ValueError('ledger_budget')
    root.mkdir(parents=True, exist_ok=True)
    with broker_lock(root):
        db = connect(root)
        try:
            initialize(db, binding(inputs))
            if db.execute('SELECT COUNT(*) FROM origins').fetchone()[0] == c['budgets']['max_origins']: return report(db, root)
            started = time.monotonic(); m = load_market(Path(inputs), c['development'][1])
            production = {}
            with (Path(inputs)/'production_targets.csv').open('rb') as stream:
                for row in guarded_rows(stream, phase2_contract()):
                    production[row['date'][:10]] = (row['execution_target_asset'], float(row['execution_target_exposure']))
            f = prepare(m, production)
            result = work(db, root, m, f, started+(seconds or c['budgets']['worker_seconds']))
            return result
        finally: db.close()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True); parser.add_argument('--seconds', type=int)
    args = parser.parse_args(); print(canonical(run(args.root, args.inputs, args.seconds)))


if __name__ == '__main__': main()
