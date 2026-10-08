"""Coherent read-only evidence and hash-chain verification."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def audit(root):
    db = sqlite3.connect('file:'+(Path(root)/'lab.sqlite').as_posix()+'?mode=ro', uri=True)
    db.execute('BEGIN'); prior = 'GENESIS'
    try:
        for body, previous, hash_ in db.execute('SELECT body,previous,hash FROM events ORDER BY id'):
            if previous != prior or digest([body, previous]) != hash_: raise ValueError('lab_hash_chain_failure')
            prior = hash_
        counts = {n: db.execute('SELECT COUNT(*) FROM '+n).fetchone()[0] for n in
                  ('hypotheses', 'trials', 'results', 'selections', 'books', 'origins', 'handoffs', 'ai_receipts', 'events')}
        usage = []; accepted = 0
        for body, in db.execute('SELECT body FROM ai_receipts'):
            r = json.loads(body); usage.append(r['response'].get('usage', {})); accepted += len(r['accepted'])
        samples = []
        for body, in db.execute("SELECT body FROM books WHERE stress='nominal' ORDER BY origin,family"):
            r = json.loads(body)
            if 'discovery' in r:
                d = r['discovery']; samples.append({'family': d['rule']['family'], 'interval': d['interval'],
                                                   'frequency': d['frequency'], 'aftermath': {k: v for k, v in d['aftermath'].items() if k != 'events'},
                                                   'inference': d['inference'], 'verdict': d['verdict']})
        return {'counts': counts, 'hash_chain': 'PASS', 'last_event_hash': prior,
                'accepted_ai_proposals_including_dedup': accepted,
                'api_calls': sum(r.get('api_call', 0) for r in usage),
                'native_tokens': sum(r.get('total_tokens') or 0 for r in usage),
                'unknown_billing': any(r.get('uncertain') for r in usage),
                'usd_upper_estimate': sum(r.get('usd_upper_estimate') or 0 for r in usage),
                'samples': samples, 'status': json.loads((Path(root)/'status.json').read_text()) if (Path(root)/'status.json').exists() else None}
    finally: db.rollback(); db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path, required=True); a = p.parse_args()
    print(json.dumps(audit(a.root), sort_keys=True, allow_nan=False))
