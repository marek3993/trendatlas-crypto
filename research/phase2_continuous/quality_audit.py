"""Read-only before/after lineage quality under the unchanged development evaluator."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .runtime import candidate_summary


def measure(root, cutoff):
    db = sqlite3.connect('file:' + (Path(root) / 'research.sqlite').as_posix() + '?mode=ro', uri=True)
    db.execute('BEGIN')
    result = {'utc': datetime.now(timezone.utc).isoformat(), 'cutoff_utc': cutoff,
              'definition': 'Exact candidate_summary eligibility on unchanged development folds; observational comparison, unequal sample sizes.'}
    for when, op in [('before', '<'), ('after', '>=')]:
        families = {}
        for family in ['J', 'K', 'L', 'M', 'N']:
            ids = [r[0] for r in db.execute("SELECT id FROM candidates WHERE mutation LIKE 'deepseek:%' AND created " + op + " ? AND family=?", (cutoff, family))]
            summaries = [candidate_summary(db, cid) for cid in ids]
            rows = [r for r in summaries if r and 'metrics' in r]
            if not rows:
                continue
            families[family] = {'registered': len(ids), 'fully_evaluated': len(rows),
                                'eligible': sum(r['eligible'] for r in rows),
                                **{'mean_' + key: sum(r['metrics'][key] for r in rows) / len(rows)
                                   for key in ['cagr', 'mdd', 'double_cost_cagr', 'delayed_entry_cagr', 'parameter_stability']},
                                'reasons': {reason: sum(reason in r['reasons'] for r in rows)
                                            for reason in sorted({s for r in rows for s in r['reasons']})}}
        result[when + '_by_family'] = families
    db.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/var/lib/trendatlas-research-development')
    parser.add_argument('--cutoff', required=True)
    args = parser.parse_args()
    print(json.dumps(measure(args.root, args.cutoff), sort_keys=True))
