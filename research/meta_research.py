"""Versioned research grammar and resource-paced continuation, no trading authority."""
import argparse
import copy
from functools import lru_cache
import hashlib
import itertools
import json
import math
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import research_spaces as spaces, meta_resources as resources
from research.continuous_research import runtime, planner, schema, broker, ledger
from research.continuous_research.common import canonical, digest, utc, atomic, lease, period
from research.continuous_research.bootstrap import metrics
from research.phase2_v2 import market, engine

BASE = Path(__file__).resolve().parents[1]
KEY = 'research_meta_policy_v1'
FILES = ('research/meta_research.py', 'research/meta_resources.py',
         'source_of_truth/research_meta_policy_v1.json', 'scripts/deploy_meta_research.py',
         'tests/test_meta_research.py')
OLD_K = spaces.genes
OLD_REMAINING = spaces.remaining
OLD_SPACE_WIRE = spaces.wire_body
OLD_SPACE_LOCAL = spaces.local_proposals
OLD_SPACE_REGISTER = spaces.register
OLD_REQUEST = spaces.ensure_request
OLD_TARGETS = market.targets
OLD_BACKTEST = runtime.backtest


@lru_cache(maxsize=1)
def policy():
    c = json.loads((BASE/FILES[2]).read_text())
    if c['candidate_starts_per_day'] is not None or c['candidates_per_activation'] != 1:
        raise ValueError('count_pacing_forbidden')
    if c['primitive_families'] != ['J', 'K', 'L', 'M', 'N'] or c['blend_families'] != ['J', 'K', 'L', 'M']:
        raise ValueError('unsupported_mechanism')
    if c['blend_left_weights'] != [.25, .5, .75] or any(c[k] for k in
            ('orders_allowed', 'production_writes_allowed', 'promotion_allowed', 'sealed_access')):
        raise ValueError('meta_authority')
    return c


@lru_cache(maxsize=1)
def domains():
    out = copy.deepcopy(market.SPACE); out['K'] = spaces.envelope()
    return out


def genes(value):
    if not isinstance(value, dict):
        raise ValueError('gene_object_required')
    family = value.get('family')
    if family in policy()['primitive_families']:
        domain = domains()[family]
        if set(value) != {'family', *domain}:
            raise ValueError('primitive_gene_keys')
        return {'family': family, **{k: schema.choice(value[k], v) for k, v in domain.items()}}
    if family != 'BLEND' or set(value) != {'family', 'left', 'right', 'left_weight'}:
        raise ValueError('unsupported_gene_grammar')
    if any(not isinstance(value[k], dict) or value[k].get('family') not in policy()['blend_families'] for k in ('left', 'right')):
        raise ValueError('unsupported_blend_component')
    left, right = genes(value['left']), genes(value['right'])
    if left['family'] == right['family']:
        raise ValueError('distinct_blend_families_required')
    weight = schema.choice(value['left_weight'], policy()['blend_left_weights'])
    if left['family'] > right['family']:
        left, right, weight = right, left, 1-weight
    return {'family': 'BLEND', 'left': left, 'right': right, 'left_weight': weight}


def targets(m, g, i, state):
    if g['family'] != 'BLEND':
        return OLD_TARGETS(m, g, i, state)
    import numpy as np
    memories = state.setdefault('components', [{}, {}]); vectors = []
    for k, name in enumerate(('left', 'right')):
        local = memories[k]
        prior = local.get('previous')
        component_state = {'previous': np.array(prior) if prior is not None else None, 'cooldown': {}}
        vector = OLD_TARGETS(m, g[name], i, component_state)
        # Persist JSON-safe component signal state; never substitute the aggregate signal.
        local['previous'] = vector.tolist(); vectors.append(vector)
    return g['left_weight']*vectors[0]+(1-g['left_weight'])*vectors[1]


def primitive_grid(family, seed=None, neighbor=True):
    domain = domains()[family]; values = seed or {}
    grid = {}
    for key, choices in domain.items():
        value = values.get(key)
        center = value if value in choices else choices[len(choices)//2]
        index = choices.index(center)
        grid[key] = choices[max(0, index-1):index+2] if neighbor else [center]
    return {'family': family, 'parameters': grid}


def seeds(views, family):
    for v in views:
        g = v['genes']
        if g['family'] == family:
            return g
        if g['family'] == 'BLEND':
            for key in ('left', 'right'):
                if g[key]['family'] == family:
                    return g[key]
    return views[0]['genes'] if views else {}


def neighborhood(category, views, generation, seed=None):
    families = category.split('+')
    if len(families) == 1:
        return primitive_grid(category, seed or seeds(views, category))
    children = []
    for i, family in enumerate(families):
        g = seed[('left', 'right')[i]] if seed else seeds(views, family)
        grid = primitive_grid(family, g, neighbor=False)
        key = list(grid['parameters'])[generation % len(grid['parameters'])]
        choices = domains()[family][key]; index = choices.index(grid['parameters'][key][0])
        grid['parameters'][key] = choices[max(0, index-1):index+2]
        children.append(grid)
    return {'family': 'BLEND', 'left': children[0], 'right': children[1],
            'left_weight': policy()['blend_left_weights']}


def full_grammar(category):
    fs = category.split('+')
    if len(fs) == 1:
        return {'family': category, 'parameters': domains()[category]}
    return {'family': 'BLEND', 'left': full_grammar(fs[0]), 'right': full_grammar(fs[1]),
            'left_weight': policy()['blend_left_weights']}


def cardinality(grammar):
    if grammar['family'] == 'BLEND':
        return cardinality(grammar['left'])*cardinality(grammar['right'])*len(grammar['left_weight'])
    return math.prod(len(v) for v in grammar['parameters'].values())


def at(grammar, ordinal):
    if ordinal < 0 or ordinal >= cardinality(grammar):
        raise ValueError('grammar_ordinal')
    if grammar['family'] == 'BLEND':
        q, w = divmod(ordinal, len(grammar['left_weight']))
        left, right = divmod(q, cardinality(grammar['right']))
        return {'family': 'BLEND', 'left': at(grammar['left'], left), 'right': at(grammar['right'], right),
                'left_weight': grammar['left_weight'][w]}
    result = {'family': grammar['family']}
    for k, choices in reversed(list(grammar['parameters'].items())):
        ordinal, index = divmod(ordinal, len(choices)); result[k] = choices[index]
    return result


def member(g, grammar):
    if g['family'] != grammar['family']:
        return False
    if g['family'] == 'BLEND':
        return member(g['left'], grammar['left']) and member(g['right'], grammar['right']) and g['left_weight'] in grammar['left_weight']
    return all(g[k] in v for k, v in grammar['parameters'].items())


def novel(db, grammar):
    seen = {r[0] for r in db.execute('SELECT id FROM genes')}
    return [g for i in range(cardinality(grammar)) if digest(g := at(grammar, i)) not in seen]


def remaining(db):
    _, space, _ = spaces.active(db)
    return len(novel(db, space['grammar'])) if 'grammar' in space else OLD_REMAINING(db)


def initialize_meta(db):
    db.execute('CREATE TABLE IF NOT EXISTS meta_scans(id INTEGER PRIMARY KEY,category TEXT,ordinal INTEGER,body TEXT)')
    ledger.immutable(db, ('meta_scans',)); db.commit()


def freeze_space(db, category, grammar, views):
    sid, previous, parent_hash = spaces.active(db); c = schema.load()
    debt = c['legacy_alpha_index']+db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0]
    count = len(novel(db, grammar))
    if not count:
        raise ValueError('no_novel_space')
    from research.discovery_evolution.statistics import design
    plan = design({'statistics': c['statistics'], 'test': c['diagnostic'], 'legacy_alpha_debt': debt, 'budgets': {'pool_max': count}})
    body = {'id': sid+1, 'parent_space_hash': parent_hash, 'meta_policy': digest(policy()),
            'origin': 'LOCAL_META_POLICY', 'category': category, 'grammar': grammar,
            'generation': previous.get('generation', 0)+1, 'parent_evidence': views[:2],
            'eligible_feedback_digest': digest(views), 'eligible_feedback_count': len(views), 'novel_at_freeze': count,
            'training': c['training'], 'validation': c['validation'], 'diagnostic': c['diagnostic'],
            'frequency_policy': c['hypotheses']['frequency'], 'history_status': c['history_status'],
            'mapping': 'Event-rule association motivates a supported primitive or target blend; it is not equivalence to an event-triggered strategy.',
            'lifetime_alpha_before': debt, 'design': plan, 'frozen_utc': utc(),
            'confirmed_trading_candidate': False, 'orders_allowed': False}
    with db:
        db.execute('INSERT INTO space_ends VALUES(?,?)', (sid, canonical({'space_hash': parent_hash, 'successor': sid+1, 'reason': 'NOVELTY_EXHAUSTED', 'utc': utc()})))
        db.execute('INSERT INTO research_spaces VALUES(?,?,?)', (sid+1, canonical(body), digest(body)))
        ledger.event(db, 'meta_space_frozen', space=sid+1, space_hash=digest(body), parent_space_hash=parent_hash,
                     category=category, novel=count, evidence=digest(views), lifetime_alpha_before=debt)


def advance(db):
    if remaining(db) > 0:
        return None
    for query in ('SELECT 1 FROM batches WHERE id NOT IN (SELECT batch FROM closed)',
                  'SELECT 1 FROM proposals WHERE id NOT IN (SELECT proposal FROM members)',
                  'SELECT 1 FROM scientific_attempts WHERE candidate NOT IN (SELECT candidate FROM feedback)'):
        if db.execute(query).fetchone():
            return None
    views = spaces.evidence(db)
    if not views:
        return 'IDLE_NO_VALID_TRAIN_VALIDATION_FEEDBACK'
    _, previous, _ = spaces.active(db); categories = policy()['categories']
    start = (categories.index(previous['category'])+1) % len(categories) if 'category' in previous else 0
    generation = previous.get('generation', 0)+1
    for offset in range(len(categories)):
        category = categories[(start+offset) % len(categories)]
        grammar = neighborhood(category, views, generation)
        if novel(db, grammar):
            freeze_space(db, category, grammar, views); return None
        full = full_grammar(category); total = cardinality(full)
        row = db.execute('SELECT ordinal FROM meta_scans WHERE category=? ORDER BY id DESC LIMIT 1', (category,)).fetchone()
        cursor = row[0] if row else 0
        if cursor >= total:
            continue
        seen = {r[0] for r in db.execute('SELECT id FROM genes')}; found = None
        end = min(total, cursor+policy()['scan_positions_per_activation'])
        for ordinal in range(cursor, end):
            g = at(full, ordinal)
            if digest(g) not in seen:
                found = g; end = ordinal+1; break
        with db:
            db.execute('INSERT INTO meta_scans(category,ordinal,body) VALUES(?,?,?)',
                       (category, end, canonical({'utc': utc(), 'from': cursor, 'to': end, 'total': total, 'found': digest(found) if found else None})))
        if found:
            freeze_space(db, category, neighborhood(category, views, generation, found), views); return None
        return 'WAIT_META_SCAN'
    return 'IDLE_META_GRAMMAR_EXHAUSTED'


def register(db, value, origin, request=None, response_index=None):
    _, space, _ = spaces.active(db)
    if 'grammar' not in space:
        return OLD_SPACE_REGISTER(db, value, origin, request, response_index)
    if not member(genes(value['genes']), space['grammar']):
        raise ValueError('outside_frozen_meta_space')
    c = copy.deepcopy(schema.load()); c['hypotheses']['mapping'] = space['mapping']
    with patch.object(planner, 'load', lambda: c):
        return spaces.OLD_REGISTER(db, value, origin, request, response_index)


def local_proposals(db, number):
    _, space, _ = spaces.active(db)
    if 'grammar' not in space:
        return OLD_SPACE_LOCAL(db, number)
    parent = space['parent_evidence'][0]; out = []
    for g in novel(db, space['grammar'])[:number]:
        p = register(db, {'parent': parent['id'], 'genes': g, 'rule': parent['rule'],
                         'mechanism': 'Local exploration of supported signal mechanisms and parameters from prior train/validation evidence.',
                         'falsification': 'Invalid prices, weak validation growth or drawdown refute this development configuration.'}, 'LOCAL_META_POLICY')
        if p:
            out.append(p)
    return out


def wire_body(payload, legacy_ids=()):
    if 'meta_space' not in payload:
        return OLD_SPACE_WIRE(payload, legacy_ids)
    if set(payload) != {'scope', 'cutoff', 'parents', 'coverage', 'meta_space'} or payload['scope'] != 'prior_train_validation_only' or payload['cutoff'] != schema.load()['feedback_cutoff']:
        raise ValueError('meta_payload_scope')
    parents = [spaces.safe_view(p) for p in payload['parents'][:2]]
    value = {'scope': payload['scope'], 'cutoff': payload['cutoff'], 'parents': parents,
             'coverage': {k: int(v) for k, v in payload['coverage'].items()}, 'space': payload['meta_space'],
             'allowed_rules': list({digest(p['rule']): p['rule'] for p in parents}.values())}
    system = ('Return JSON with exactly evaluation (1-600 character critique) and proposals (at most two). '
              'Each proposal has exactly parent (supplied id), rule (one allowed_rules object), genes, mechanism (8-300 chars), falsification (8-220 chars). '
              'A primitive genes object has family plus ALL parameters with enum values from space.grammar.parameters. '
              'BLEND genes has exactly family=BLEND,left,right,left_weight; left/right are primitive genes objects from their respective grammars. '
              'Propose novel configurations from this frozen grammar. No code, new sources or altered bounds. '
              'Use only supplied prior training/validation evidence; all history is contaminated development, never proof of a trading candidate. '
              'Return only complete JSON, no markdown.')
    body = {'model': schema.load()['api']['model'], 'thinking': {'type': 'disabled'}, 'max_tokens': 1500,
            'response_format': {'type': 'json_object'}, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': canonical(value)}]}
    if len(canonical(body).encode())+256 > 6500:
        raise ValueError('wire_token_bound')
    return body


def ensure_request(db, mailbox):
    sid, space, sha = spaces.active(db)
    if 'grammar' not in space:
        return OLD_REQUEST(db, mailbox)
    row = db.execute('SELECT id,body,utc FROM requests WHERE id NOT IN (SELECT id FROM ingested) ORDER BY utc LIMIT 1').fetchone()
    if row:
        atomic(Path(mailbox)/'requests'/f'{row[0]}.json', json.loads(row[1])); return row[0], row[2]
    if remaining(db) <= 0:
        return None
    trigger = db.execute('SELECT COALESCE(MAX(batch),0) FROM closed').fetchone()[0]
    if db.execute('SELECT 1 FROM requests WHERE trigger_batch=?', (trigger,)).fetchone():
        return None
    payload = {'scope': 'prior_train_validation_only', 'cutoff': schema.load()['feedback_cutoff'],
               'parents': spaces.evidence(db)[:2], 'coverage': {'completed': db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 'remaining_in_space': remaining(db)},
               'meta_space': {'id': sid, 'hash': sha, 'grammar': space['grammar']}}
    try:
        planner.wire_body(payload)
    except ValueError:
        payload['parents'] = payload['parents'][:1]
        try: planner.wire_body(payload)
        except ValueError: return None  # No oversized paid request may block local backtests.
    rid = digest(payload); body = {'id': rid, 'payload': payload, 'created_utc': utc()}
    with db:
        db.execute('INSERT INTO requests VALUES(?,?,?,?)', (rid, trigger, canonical(body), body['created_utc']))
        ledger.event(db, 'AI_meta_request_queued', request=rid, space=sid, trigger_batch=trigger)
    atomic(Path(mailbox)/'requests'/f'{rid}.json', body); return rid, body['created_utc']


def backtest(db, root, m, f, gid, g, phase, interval, stress='nominal', evaluator=runtime.default_evaluator):
    if not db.execute('SELECT 1 FROM backtests WHERE key=?', (digest([gid, phase, interval, stress]),)).fetchone():
        resources.admit(root)
    return OLD_BACKTEST(db, root, m, f, gid, g, phase, interval, stress, evaluator)


def tick(db, root, mailbox, get_market, evaluator=runtime.default_evaluator, now=None, discovery_fn=None):
    initialize_meta(db)
    try:
        resources.admit(root)
        planner.ingest(db, mailbox)
        number, batch, reason = spaces.freeze_next(db, mailbox, now)
        if reason:
            return reason
        pending = [p for p in batch['entries'] if not db.execute('SELECT 1 FROM feedback WHERE candidate=?', (p['gene_id'],)).fetchone()]
        if pending:
            lease(root, 'PREPARING_MARKET', batch=number); m, f = get_market(); p = pending[0]
            discovery = runtime.inbox(db, root, m, f, number, p, discovery_fn)
            evaluate_candidate(db, root, m, f, number, p, discovery, evaluator, now)
        if all(db.execute('SELECT 1 FROM feedback WHERE candidate=?', (p['gene_id'],)).fetchone() for p in batch['entries']):
            with db:
                db.execute('INSERT INTO closed VALUES(?,?)', (number, utc())); ledger.event(db, 'batch_closed', batch=number)
            ensure_request(db, mailbox)
        return 'PROGRESSED'
    except resources.ResourcePause as exc:
        return str(exc)


def snapshot(db, root, mailbox):
    value = spaces.snapshot(db, root, mailbox)
    value.update(research_space_contract=policy()['id'], candidate_starts_per_day=None,
                 next_space_creation='automatic resource-admitted meta-policy; shared scientific/API history persists',
                 remaining_unregistered_scope='current_frozen_space')
    path = Path(root)/'resources.json'
    value['resource_admission'] = json.loads(path.read_text()) if path.exists() else None
    return value


def installed(legacy_ids=()):
    stack = spaces.installed(legacy_ids)
    replacements = [(schema, 'genes', genes), (spaces, 'genes', genes), (market, 'validate_genes', genes),
                    (engine, 'validate_genes', genes), (engine, 'targets', targets),
                    (planner, 'register', register), (planner, 'local_proposals', local_proposals),
                    (spaces, 'advance', advance), (runtime, 'tick', tick), (runtime, 'snapshot', snapshot)]
    for module in (spaces, planner, runtime):
        replacements.extend([(module, 'remaining', remaining), (module, 'ensure_request', ensure_request)])
    for module in (schema, planner, broker):
        replacements.append((module, 'wire_body', lambda p: wire_body(p, legacy_ids)))
    for module, name, value in replacements:
        stack.enter_context(patch.object(module, name, value))
    return stack


def fingerprint(base):
    return {n: hashlib.sha256((Path(base)/n).read_bytes()).hexdigest() for n in FILES}


def verify_manifest(base, manifest):
    if manifest['files'] != fingerprint(base) or manifest['contract'] != digest(policy()):
        raise ValueError('meta_source_changed')
    prior = json.loads((Path(base)/'spaces-freeze.json').read_text())
    if digest(prior) != manifest['ancestor_spaces']:
        raise ValueError('meta_ancestor_changed')
    return spaces.verify_manifest(base, prior)


def main():
    p = argparse.ArgumentParser(); p.add_argument('mode', choices=('worker', 'broker', 'audit'))
    p.add_argument('--root', type=Path); p.add_argument('--mailbox', type=Path, required=True)
    p.add_argument('--inputs', type=Path); p.add_argument('--bootstrap', type=Path)
    a = p.parse_args(); manifest = json.loads((BASE/'meta-freeze.json').read_text())
    old = verify_manifest(BASE, manifest)
    path = a.mailbox/'api.sqlite' if a.mode == 'broker' else a.root/'research.sqlite'
    spaces.protocol.verify_ledger(path, old)
    db = sqlite3.connect('file:'+path.as_posix()+'?mode=ro', uri=True)
    try:
        if ledger.meta(db, KEY) != digest(manifest): raise ValueError('meta_not_frozen')
        if ledger.meta(db, spaces.KEY) != digest(json.loads((BASE/'spaces-freeze.json').read_text())):
            raise ValueError('ancestor_space_binding_changed')
    finally: db.close()
    with installed(old['legacy_request_ids']):
        value = {'state': broker.once(a.mailbox)} if a.mode == 'broker' else (
            runtime.audit(a.root, a.mailbox) if a.mode == 'audit' else runtime.run(a.root, a.mailbox, a.inputs, a.bootstrap))
    print(canonical(value))


# Candidate accounting below deliberately retains the frozen v1 calculations;
# only the two-line daily-count gate is removed. Every alpha reservation persists.

def evaluate_candidate(db,root,m,f,batch,p,discovery,evaluator=runtime.default_evaluator,now=None):
    c=schema.load();gid=p['gene_id'];row=db.execute('SELECT id FROM scientific_attempts WHERE candidate=?',(gid,)).fetchone()
    if row:index=c['legacy_alpha_index']+row[0]
    else:
        day,_=period(now)
        with db:
            cur=db.execute('INSERT INTO scientific_attempts(candidate,day,utc) VALUES(?,?,?)',(gid,day,utc()));index=c['legacy_alpha_index']+cur.lastrowid
            ledger.event(db,'scientific_attempt_reserved',candidate=gid,alpha_index=index,batch=batch,day=day)
    results={}
    for phase,interval,stress in [('training',c['training'],'nominal'),('validation',c['validation'],'nominal'),
                                  ('diagnostic',c['diagnostic'],'nominal'),('double_cost',c['diagnostic'],'double_cost'),('delayed',c['diagnostic'],'delayed')]:
        results[phase]=backtest(db,root,m,f,gid,p['genes'],phase,interval,stress,evaluator)
    control=backtest(db,root,m,f,'BTC_HALF','BTC_HALF','control',c['diagnostic'],evaluator=evaluator)
    row=db.execute('SELECT body FROM statistics WHERE candidate=?',(gid,)).fetchone()
    if row:stat=json.loads(row[0])
    else:
        from research.discovery_evolution.statistics import infer
        if results['diagnostic']['valid'] and control['valid']:
            stat=infer(runtime.book(root,results['diagnostic'])['equity'],runtime.book(root,control)['equity'],index,c)
        else:stat={'verdict':'UNDEFINED_INVALID','p':None,'alpha_index':index,'confirmed_trading_candidate':False}
        with db:
            db.execute('INSERT INTO statistics VALUES(?,?,?,?)',(gid,index,canonical(stat),utc()))
            ledger.event(db,'conditional_statistic_completed',candidate=gid,alpha_index=index,p=stat['p'],confirmed_trading_candidate=False)
    view={'id':gid,'genes':p['genes'],'rule':p['rule'],'cutoff':c['feedback_cutoff'],'frequency_episodes':discovery['bounded_episodes'],
          'source':p['origin'],'training':{'interval':c['training'],'valid':results['training']['valid'],'metrics':metrics(results['training']['metrics'])},
          'validation':{'interval':c['validation'],'valid':results['validation']['valid'],'metrics':metrics(results['validation']['metrics'])}}
    feedback={'candidate':gid,'proposal':p['id'],'batch':batch,'origin':p['origin'],'request':p['request'],'training_view':view,
              'diagnostic_only':{k:{'valid':results[k]['valid'],'metrics':metrics(results[k]['metrics'])} for k in ('diagnostic','double_cost','delayed')},
              'statistics':stat,'valid':all(v['valid'] for v in results.values()) and discovery.get('valid',True),
              'contamination':c['history_status'],'confirmed_trading_candidate':False,'new_market_discovery':False,'orders_allowed':False,'utc':utc()}
    with db:
        db.execute('INSERT INTO feedback VALUES(?,?,?,?)',(gid,batch,canonical(feedback),utc()))
        ledger.event(db,'feedback_completed',batch=batch,candidate=gid,origin=p['origin'],request=p['request'],training_feedback_hash=digest(view))
    atomic(Path(root)/'feedback'/f'{gid}.json',feedback);return True


if __name__ == "__main__":
    main()
