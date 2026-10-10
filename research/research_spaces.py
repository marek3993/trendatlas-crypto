"""Prospective finite-space continuation; frozen ancestors remain byte-identical."""
import argparse
from contextlib import ExitStack
from decimal import Decimal
from functools import lru_cache
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.continuous_research import planner, runtime, schema, broker, ledger
from research.continuous_research.common import canonical, digest, utc, atomic
from research import continuous_research_protocol as protocol

BASE = Path(__file__).resolve().parents[1]
KEY = 'research_spaces_v1'
FILES = ('research/research_spaces.py', 'source_of_truth/research_space_successor_v1.json',
         'scripts/deploy_research_spaces.py', 'tests/test_research_spaces.py')
OLD_REGISTER = planner.register
OLD_LOCAL = planner.local_proposals
OLD_FREEZE = planner.freeze_next
OLD_INITIALIZE = planner.initialize
OLD_SNAPSHOT = runtime.snapshot


@lru_cache(maxsize=1)
def contract():
    c = json.loads((BASE / FILES[1]).read_text(encoding='utf-8'))
    if c['ancestor_contract'] != schema.load()['id'] or any(c[k] for k in
            ('orders_allowed', 'production_writes_allowed', 'promotion_allowed', 'sealed_access')):
        raise ValueError('space_authority')
    expected = {'vol_target': (.06, .24, .005), 'correlation_cap': (.3, .9, .05),
                'asset_weight_cap': (.1, .25, .025)}
    if c['refinement'] != {k: dict(zip(('min', 'max', 'step'), v)) for k, v in expected.items()}:
        raise ValueError('space_envelope_changed')
    if c['fixed_axes'] != ['trend_days', 'vol_days', 'rebalance_days']:
        raise ValueError('lookback_extension_forbidden')
    return c


@lru_cache(maxsize=1)
def envelope():
    out = dict(schema.spaces()[0])
    for k, v in contract()['refinement'].items():
        lo, hi, step = (Decimal(str(v[x])) for x in ('min', 'max', 'step'))
        out[k] = [float(lo + i * step) for i in range(int((hi-lo)/step)+1)]
    return out


def genes(value):
    domain = envelope()
    if not isinstance(value, dict) or set(value) != {'family', *domain} or value['family'] != 'K':
        raise ValueError('K_schema')
    return {'family': 'K', **{k: schema.choice(value[k], vs) for k, vs in domain.items()}}


def configurations(grid):
    for values in itertools.product(*grid.values()):
        yield {'family': 'K', **dict(zip(grid, values))}


def active(db):
    row = db.execute('SELECT id,body,hash FROM research_spaces ORDER BY id DESC LIMIT 1').fetchone()
    return row[0], json.loads(row[1]), row[2]


def unseen(db, grid):
    seen = {r[0] for r in db.execute('SELECT id FROM genes')}
    return [g for g in configurations(grid) if digest(g) not in seen]


def remaining(db):
    sid, space, _ = active(db)
    if sid == 1 and space['K_schema'] == schema.spaces()[0]:
        boot = ledger.meta(db, 'bootstrap')
        return boot['K_cardinality']-boot['historical_K_count']-db.execute("SELECT COUNT(*) FROM genes WHERE source!='legacy'").fetchone()[0]
    return len(unseen(db, space['K_schema']))


def safe_view(value):
    c = schema.load()
    if value['cutoff'] > c['feedback_cutoff']:
        raise ValueError('future_feedback')
    out = {k: value.get(k) for k in ('id', 'cutoff', 'frequency_episodes')}
    out.update(genes=genes(value['genes']), rule=schema.rule(value['rule']))
    for phase in ('training', 'validation'):
        part = value[phase]
        if not part or part['valid'] is not True or part['interval'] != c[phase]:
            raise ValueError('invalid_parent_interval_or_receipt')
        m = part.get('metrics') or {}
        for name in ('log_growth', 'mdd'):
            if type(m.get(name)) not in (float, int) or not math.isfinite(m[name]):
                raise ValueError('nonfinite_parent')
        out[phase] = {'valid': True, 'interval': part['interval'], 'metrics': {
            k: m.get(k) for k in ('cagr', 'mdd', 'log_growth', 'cost_drag', 'asset_concentration')}}
    return out


def evidence(db):
    views = []
    for body, in db.execute('SELECT body FROM feedback ORDER BY candidate'):
        try:
            views.append(safe_view(json.loads(body)['training_view']))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(views, key=lambda p: (-p['validation']['metrics']['log_growth'],
                                       p['validation']['metrics']['mdd'], p['id']))


def freeze_space(db, grid, parent=None, views=()):
    c = schema.load()
    previous = active(db) if db.execute('SELECT 1 FROM research_spaces').fetchone() else None
    number = previous[0]+1 if previous else 1
    debt = c['legacy_alpha_index'] + db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0]
    novel = len(unseen(db, grid))
    from research.discovery_evolution.statistics import design
    plan = design({'statistics': c['statistics'], 'test': c['diagnostic'],
                   'legacy_alpha_debt': debt, 'budgets': {'pool_max': max(1, novel)}})
    body = {'id': number, 'parent_space_hash': previous[2] if previous else None,
            'K_schema': grid, 'contract': digest(contract()), 'base_contract': digest(c),
            'origin': 'LOCAL_RESULT_REFINEMENT' if previous else 'INHERITED_K_SPACE',
            'parent_evidence': parent, 'eligible_feedback_count': len(views),
            'eligible_feedback_digest': digest(views), 'novel_at_freeze': novel,
            'training': c['training'], 'validation': c['validation'], 'diagnostic': c['diagnostic'],
            'frequency_policy': c['hypotheses']['frequency'], 'lifetime_alpha_before': debt,
            'design': plan, 'history_status': c['history_status'], 'frozen_utc': utc(),
            'confirmed_trading_candidate': False, 'orders_allowed': False}
    with db:
        if previous:
            ended = {'space_hash': previous[2], 'reason': 'GLOBAL_NOVEL_CONFIGURATIONS_EXHAUSTED',
                     'successor': number, 'utc': utc()}
            db.execute('INSERT INTO space_ends VALUES(?,?)', (previous[0], canonical(ended)))
        db.execute('INSERT INTO research_spaces VALUES(?,?,?)', (number, canonical(body), digest(body)))
        ledger.event(db, 'research_space_frozen', space=number, space_hash=digest(body),
                     parent_space_hash=body['parent_space_hash'], novel=novel, origin=body['origin'])
    return number, body, digest(body)


def initialize_spaces(db, initial_grid=None):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS research_spaces(id INTEGER PRIMARY KEY,body TEXT NOT NULL,hash TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS space_batches(batch INTEGER PRIMARY KEY,space INTEGER NOT NULL,space_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS space_ends(space INTEGER PRIMARY KEY,body TEXT NOT NULL);
    ''')
    ledger.immutable(db, ('research_spaces', 'space_batches', 'space_ends')); db.commit()
    if not db.execute('SELECT 1 FROM research_spaces').fetchone():
        freeze_space(db, initial_grid or schema.spaces()[0])
    # Recovery also binds pre-extension frozen batches to their inherited space.
    number, _, sha = active(db)
    with db:
        db.execute('INSERT INTO space_batches SELECT id,?,? FROM batches WHERE id NOT IN (SELECT batch FROM space_batches)', (number, sha))


def advance(db):
    if remaining(db):
        return None
    for query in (
            'SELECT 1 FROM batches WHERE id NOT IN (SELECT batch FROM closed)',
            'SELECT 1 FROM proposals WHERE id NOT IN (SELECT proposal FROM members)',
            'SELECT 1 FROM scientific_attempts WHERE candidate NOT IN (SELECT candidate FROM feedback)'):
        if db.execute(query).fetchone():
            return None
    if db.execute('SELECT 1 FROM requests WHERE id NOT IN (SELECT id FROM ingested)').fetchone():
        return 'WAIT_PENDING_SPACE_REQUEST'
    views = evidence(db)
    domain = envelope()
    seen = {r[0] for r in db.execute('SELECT id FROM genes')}
    for parent in views:
        grid = {k: [v] for k, v in parent['genes'].items() if k != 'family'}
        for k in contract()['refinement']:
            index = domain[k].index(parent['genes'][k])
            grid[k] = domain[k][max(0, index-1):index+2]
        if any(digest(g) not in seen for g in configurations(grid)):
            freeze_space(db, grid, parent, views)
            return None
    return 'IDLE_NO_ELIGIBLE_NOVEL_FRONTIER' if views else 'IDLE_NO_VALID_TRAIN_VALIDATION_FEEDBACK'


def register(db, value, origin, request=None, response_index=None):
    _, space, _ = active(db)
    g = genes(value['genes'])
    if any(g[k] not in vs for k, vs in space['K_schema'].items()):
        raise ValueError('outside_frozen_active_space')
    return OLD_REGISTER(db, value, origin, request, response_index)


def local_proposals(db, number):
    sid, space, _ = active(db)
    if sid == 1 and space['K_schema'] == schema.spaces()[0]:
        return OLD_LOCAL(db, number)
    parent = space['parent_evidence'] or planner.parents(db)[0]
    out = []
    for g in unseen(db, space['K_schema'])[:number]:
        p = register(db, {'parent': parent['id'], 'genes': g, 'rule': parent['rule'],
                         'mechanism': 'Local parameter refinement from prior train/validation evidence; not AI authored.',
                         'falsification': 'Invalid prices, weak validation growth or excessive drawdown refute this configuration.'},
                     'LOCAL_RESULT_REFINEMENT')
        if p:
            out.append(p)
    return out


def descriptor(db):
    sid, space, sha = active(db)
    return {'id': sid, 'hash': sha, 'K_schema': space['K_schema']}


def wire_body(payload, legacy_ids=()):
    if 'research_space' not in payload:
        return protocol.wire_body(payload, legacy_ids)
    space = payload['research_space']; grid = space['K_schema']; domain = envelope()
    if set(space) != {'id', 'hash', 'K_schema'} or type(space['id']) is not int or space['id'] < 2:
        raise ValueError('space_descriptor')
    if set(grid) != set(domain) or not all(vs and len(vs) <= 3 and all(schema.choice(v, domain[k]) == v for v in vs) for k, vs in grid.items()):
        raise ValueError('space_grid')
    if math.prod(map(len, grid.values())) > 27:
        raise ValueError('space_size')
    body = protocol.wire_body({k: v for k, v in payload.items() if k != 'research_space'}, legacy_ids)
    value = json.loads(body['messages'][1]['content'])
    value.update(K_schema=grid, research_space={'id': space['id'], 'hash': space['hash']})
    body['messages'][1]['content'] = canonical(value)
    if len(canonical(body).encode())+256 > schema.load()['api']['input_tokens_per_request']:
        raise ValueError('wire_token_bound')
    return body


def ensure_request(db, mailbox):
    pending = db.execute('SELECT id,body,utc FROM requests WHERE id NOT IN (SELECT id FROM ingested) ORDER BY utc LIMIT 1').fetchone()
    if pending:
        atomic(Path(mailbox)/'requests'/f'{pending[0]}.json', json.loads(pending[1]))
        return pending[0], pending[2]
    left = remaining(db)
    if left <= 0:
        return None
    trigger = db.execute('SELECT COALESCE(MAX(batch),0) FROM closed').fetchone()[0]
    if db.execute('SELECT 1 FROM requests WHERE trigger_batch=?', (trigger,)).fetchone():
        return None
    sid = active(db)[0]
    ps = evidence(db)[:2] if sid > 1 else planner.parents(db)
    if not ps:
        return None
    payload = {'scope': 'prior_train_validation_only', 'cutoff': schema.load()['feedback_cutoff'], 'parents': ps,
               'coverage': {'completed': db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 'remaining_K': left,
                            'rejected_duplicates': db.execute("SELECT COUNT(*) FROM proposal_receipts WHERE json_extract(body,'$.status') LIKE 'duplicate_%'").fetchone()[0]},
               'duplicate_genes': [json.loads(r[0])['proposal']['genes'] for r in db.execute("SELECT body FROM proposal_receipts WHERE json_extract(body,'$.status')='duplicate_gene' ORDER BY id DESC LIMIT 2")]}
    if sid > 1:
        payload['research_space'] = descriptor(db)
    planner.wire_body(payload)
    rid = digest(payload)
    if db.execute('SELECT 1 FROM requests WHERE id=?', (rid,)).fetchone():
        return None
    body = {'id': rid, 'payload': payload, 'created_utc': utc()}
    with db:
        db.execute('INSERT INTO requests VALUES(?,?,?,?)', (rid, trigger, canonical(body), body['created_utc']))
        ledger.event(db, 'AI_feedback_request_queued', request=rid, trigger_batch=trigger,
                     parents=[p['id'] for p in ps], cutoff=payload['cutoff'], space=sid)
    atomic(Path(mailbox)/'requests'/f'{rid}.json', body)
    return rid, body['created_utc']


def freeze_next(db, mailbox, now=None):
    reason = advance(db)
    if reason:
        return None, None, reason
    number, batch, reason = OLD_FREEZE(db, mailbox, now)
    if number is not None:
        sid, _, sha = active(db)
        with db:
            db.execute('INSERT OR IGNORE INTO space_batches VALUES(?,?,?)', (number, sid, sha))
        row = db.execute('SELECT space,space_hash FROM space_batches WHERE batch=?', (number,)).fetchone()
        if row != (sid, sha):
            raise ValueError('batch_space_binding')
    return number, batch, reason


def snapshot(db, root, mailbox):
    value = OLD_SNAPSHOT(db, root, mailbox)
    sid, space, sha = active(db)
    value.update(research_space=sid, research_space_hash=sha, research_space_origin=space['origin'],
                 research_space_contract=contract()['id'],
                 last_progress_utc=db.execute('SELECT MAX(utc) FROM backtests').fetchone()[0],
                 next_space_creation='after full global novelty exhaustion and all pending work closes; eligible train/validation refinement only')
    return value


def installed(legacy_ids=()):
    """Scoped adapter: input enums widen prospectively; evaluator math is unchanged."""
    from research.phase2_v2 import market, engine
    old_validator = market.validate_genes
    def validate(g):
        return genes(g) if isinstance(g, dict) and g.get('family') == 'K' else old_validator(g)
    def initialize(db, boot, binding):
        OLD_INITIALIZE(db, boot, binding); initialize_spaces(db)
    stack = ExitStack()
    replacements = [(schema, 'genes', genes), (market, 'validate_genes', validate), (engine, 'validate_genes', validate),
                    (planner, 'register', register), (planner, 'local_proposals', local_proposals),
                    (runtime, 'initialize', initialize), (runtime, 'snapshot', snapshot)]
    for module in (schema, planner, broker):
        replacements.append((module, 'wire_body', lambda payload: wire_body(payload, legacy_ids)))
    for module in (planner, runtime):
        replacements.extend([(module, 'remaining', remaining), (module, 'ensure_request', ensure_request),
                             (module, 'freeze_next', freeze_next)])
    for module, name, value in replacements:
        stack.enter_context(patch.object(module, name, value))
    return stack


def fingerprint(base):
    return {name: hashlib.sha256((Path(base)/name).read_bytes()).hexdigest() for name in FILES}


def verify_manifest(base, manifest):
    if manifest['files'] != fingerprint(base) or manifest['contract'] != digest(contract()):
        raise ValueError('research_space_code_or_contract_changed')
    old = json.loads((Path(base)/'protocol-freeze.json').read_text())
    protocol.verify_manifest(base, old)
    if digest(old) != manifest['ancestor_protocol']:
        raise ValueError('research_space_ancestor_changed')
    return old


def main():
    p = argparse.ArgumentParser(); p.add_argument('mode', choices=('worker', 'broker', 'audit'))
    p.add_argument('--root', type=Path); p.add_argument('--mailbox', type=Path, required=True)
    p.add_argument('--inputs', type=Path); p.add_argument('--bootstrap', type=Path)
    a = p.parse_args()
    manifest = json.loads((BASE/'spaces-freeze.json').read_text())
    old = verify_manifest(BASE, manifest)
    path = a.mailbox/'api.sqlite' if a.mode == 'broker' else a.root/'research.sqlite'
    protocol.verify_ledger(path, old)
    import sqlite3
    db = sqlite3.connect('file:'+path.as_posix()+'?mode=ro', uri=True)
    try:
        if ledger.meta(db, KEY) != digest(manifest):
            raise ValueError('research_space_not_frozen')
    finally:
        db.close()
    with installed(old['legacy_request_ids']):
        value = {'state': broker.once(a.mailbox)} if a.mode == 'broker' else (
            runtime.audit(a.root, a.mailbox) if a.mode == 'audit' else runtime.run(a.root, a.mailbox, a.inputs, a.bootstrap))
    print(canonical(value))


if __name__ == '__main__':
    main()
