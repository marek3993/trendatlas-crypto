"""Frozen rolling-window research; period checkpoints, never production imports."""
import hashlib
import json
from pathlib import Path
import random
import sqlite3

from research_os.dev_only.mean_reversion import controller as pure
from research_os.dev_only.mean_reversion.backtest import backtest, canonical, read_bars, DOMAINS


def connect(root):
    db = sqlite3.connect(Path(root) / 'research.sqlite3', timeout=5)
    db.execute('PRAGMA synchronous=FULL')
    return db


def meta(db):
    return json.loads(db.execute('SELECT payload FROM meta').fetchone()[0])


def save(db, value):
    db.execute('UPDATE meta SET payload=?', (canonical(value),))


def selection(study):
    folds = study['selection_folds']
    return folds + [{'id': 'continuous', 'start': folds[0]['start'], 'end': folds[-1]['end']}]


def validate(study, raw):
    from datetime import date, timedelta
    bars = read_bars(raw)
    if hashlib.sha256(raw).hexdigest() != study['input_sha256']:
        raise ValueError('Frozen input mismatch')
    if study['domains'] != DOMAINS or [study[k] for k in ('generations', 'population', 'survivors', 'mutations')] != [5, 10, 6, 4]:
        raise ValueError('Search domain or budget changed')
    if (study['fee_bps_one_way'], study['slippage_bps_one_way']) != (10, 5):
        raise ValueError('Costs changed')
    folds = study['selection_folds'] + [study['assessment']]
    if len(folds) != 5 or len({f['id'] for f in folds}) != 5:
        raise ValueError('Four selection folds and one assessment required')
    last = None
    days = {b.day for b in bars}
    for fold in folds:
        start, end = [date.fromisoformat(fold[k]) for k in ('start', 'end')]
        if start >= end or (last and start != last + timedelta(days=1)):
            raise ValueError('Chronological contiguous disjoint windows required')
        if fold['start'] not in days or fold['end'] not in days or sum(b.day < fold['start'] for b in bars) < 200:
            raise ValueError('Missing fold dates or warmup')
        last = end
    return bars


def initialize(root, job):
    study = job['study']
    validate(study, (root / 'input.csv').read_bytes())
    with (root / 'research.sqlite3').open('xb'):
        pass
    db = connect(root)
    try:
        db.executescript('''
          CREATE TABLE meta(payload TEXT NOT NULL);
          CREATE TABLE candidates(id TEXT PRIMARY KEY, genes TEXT, parent TEXT, born INTEGER);
          CREATE TABLE populations(generation INTEGER, slot INTEGER, candidate TEXT,
            PRIMARY KEY(generation,slot), UNIQUE(generation,candidate));
          CREATE TABLE evaluations(candidate TEXT, period TEXT, payload TEXT,
            PRIMARY KEY(candidate,period));
          CREATE TABLE generations(generation INTEGER PRIMARY KEY, payload TEXT);
        ''')
        with db:
            db.execute('INSERT INTO meta VALUES(?)', (canonical({'study': study, 'state': 'SEARCH',
                'release_sha256': job['release_sha256'], 'completed_generations': 0,
                'leader': None, 'outcome': None}),))
            for slot, (cid, genes) in enumerate(pure.initial_population(random.Random(study['seed'])).items()):
                db.execute('INSERT INTO candidates VALUES(?,?,NULL,1)', (cid, canonical(genes)))
                db.execute('INSERT INTO populations VALUES(1,?,?)', (slot, cid))
    finally:
        db.close()


def step(root, job, guard, progress):
    """Committed period results survive restart; selection/final freeze is atomic."""
    db = connect(root)
    try:
        info = meta(db)
        study = job['study']
        if info['study'] != study or info['release_sha256'] != job['release_sha256']:
            raise ValueError('Frozen study or code mismatch')
        if info['state'] == 'SEALED':
            raise ValueError('SEALED study cannot resume search')
        bars = validate(study, (root / 'input.csv').read_bytes())
        genes = {r[0]: json.loads(r[1]) for r in db.execute('SELECT id,genes FROM candidates')}

        def evaluate(cid, period, benchmark=None):
            row = db.execute('SELECT payload FROM evaluations WHERE candidate=? AND period=?',
                             (cid, period['id'])).fetchone()
            if row:
                return json.loads(row[0])['metrics']
            guard()
            chosen = genes[cid] if benchmark is None else next(iter(genes.values()))
            # Even an accidental lookahead in the pure adapter cannot see later bars.
            visible = [b for b in bars if b.day <= period['end']]
            result = backtest(visible, chosen, period['start'], period['end'], benchmark=benchmark)
            with db:
                db.execute('INSERT INTO evaluations VALUES(?,?,?)', (cid, period['id'], canonical(result)))
            progress()
            guard()
            return result['metrics']

        if info['state'] == 'SEARCH':
            generation = info['completed_generations'] + 1
            if generation > 5:
                raise ValueError('Five generation budget exhausted')
            current = [r[0] for r in db.execute('SELECT candidate FROM populations WHERE generation=? ORDER BY slot', (generation,))]
            if len(current) != 10:
                raise ValueError('Population contract violated')
            results, scores, disqualified = {}, {}, {}
            for cid in current:
                results[cid] = {p['id']: evaluate(cid, p) for p in selection(study)}
                scores[cid] = [results[cid][p['id']]['fitness'] for p in study['selection_folds']]
                breaches = [p for p, value in results[cid].items() if value['turnover_disqualified']]
                if breaches:
                    disqualified[cid] = breaches
            for benchmark in ('cash', 'btc'):
                for period in selection(study):
                    evaluate(benchmark, period, benchmark)
            ranking = pure.rank_candidates(scores, disqualified)
            survivors = ranking[:6]
            children = pure.adjacent_children(survivors, genes, set(genes), random.Random(study['seed'] + generation)) if len(survivors) == 6 else []
            summary = {'generation': generation, 'population': current, 'ranking': ranking,
                       'survivors': survivors, 'scores': scores, 'disqualified': disqualified,
                       'mutations': [{'id': c, 'genes': g, 'parent': p} for c, g, p in children]}
            with db:
                for cid, child, parent in children:
                    db.execute('INSERT INTO candidates VALUES(?,?,?,?)', (cid, canonical(child), parent, generation + 1))
                for slot, cid in enumerate(survivors + [c[0] for c in children]):
                    db.execute('INSERT INTO populations VALUES(?,?,?)', (generation + 1, slot, cid))
                db.execute('INSERT INTO generations VALUES(?,?)', (generation, canonical(summary)))
                info.update(completed_generations=generation, leader=ranking[0] if ranking else None)
                if len(survivors) < 6:
                    info.update(state='SEALED', outcome=pure.REJECT, reasons=['fewer_than_six_eligible_survivors'])
                elif generation == 5:
                    info.update(state='ASSESSMENT', frozen_candidate={'sha256': ranking[0], 'genes': genes[ranking[0]]})
                save(db, info)
            progress()
            return info
        if info['state'] != 'ASSESSMENT' or info['completed_generations'] != 5:
            raise ValueError('Unexpected lifecycle')
        cid = info['frozen_candidate']['sha256']
        assessment = evaluate(cid, study['assessment'])
        for benchmark in ('cash', 'btc'):
            evaluate(benchmark, study['assessment'], benchmark)
        all_results = {p['id']: evaluate(cid, p) for p in selection(study)}
        all_results[study['assessment']['id']] = assessment
        outcome, failures = pure.qualification(all_results)
        with db:
            info.update(state='SEALED', outcome=outcome, reasons=failures)
            save(db, info)
        progress()
        return info
    finally:
        db.close()


def report(root):
    db = sqlite3.connect((Path(root) / 'research.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        info = meta(db)
        comparisons = {}
        for cid in (info.get('leader'), 'cash', 'btc'):
            if cid:
                comparisons[cid] = {r[0]: json.loads(r[1])['metrics'] for r in db.execute(
                    'SELECT period,payload FROM evaluations WHERE candidate=?', (cid,))}
        return {'meta': info, 'generations': [json.loads(r[0]) for r in db.execute('SELECT payload FROM generations ORDER BY generation')],
                'comparisons': comparisons, 'evaluated_candidates': db.execute("SELECT COUNT(DISTINCT candidate) FROM evaluations WHERE candidate NOT IN ('cash','btc')").fetchone()[0],
                'period_evaluations': db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0],
                'history_role': 'seen_exploratory_retrospective', 'production_pass': False}
    finally:
        db.close()
