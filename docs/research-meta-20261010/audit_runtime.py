"""Read-only native acceptance snapshot; run through the existing research SSH path."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path('/var/lib/trendatlas-continuous-research')
MAIL = Path('/var/lib/trendatlas-continuous-mailbox')
RELEASE = Path('/opt/trendatlas-research/continuous/releases/b7ea9e89cfd1caef')
group = (MAIL/'api.sqlite').stat().st_gid
assert (ROOT/'research.sqlite').stat().st_gid == group
os.setegid(group); os.umask(0o007)
sys.path.insert(0, str(RELEASE))
from research import meta_research as meta
from research.continuous_research import runtime, ledger, broker
from research.continuous_research.common import utc, digest, period
from research.continuous_research.deploy import predecessors

manifest = json.loads((RELEASE/'meta-freeze.json').read_text())
prior = meta.verify_manifest(RELEASE, manifest)
db = sqlite3.connect('file:'+str(ROOT/'research.sqlite')+'?mode=ro', uri=True)
api = sqlite3.connect('file:'+str(MAIL/'api.sqlite')+'?mode=ro', uri=True)
db.execute('BEGIN'); api.execute('BEGIN')
assert ledger.meta(db, meta.KEY) == digest(manifest) == ledger.meta(api, meta.KEY)
for table, expected in manifest['prior_tables'].items():
    rows = db.execute('SELECT * FROM '+table+' ORDER BY rowid LIMIT ?', (expected['count'],)).fetchall()
    assert len(rows) == expected['count'] and digest(rows) == expected['sha256'], table
reservations = api.execute('SELECT * FROM reservations ORDER BY id').fetchall()
assert digest(reservations[:manifest['api_reservations_count']]) == manifest['api_reservations_digest']
with meta.installed(prior['legacy_request_ids']):
    value = runtime.snapshot(db, ROOT, MAIL)
value['hash_chain'] = ledger.verify(db)
new = []
for cid, body in db.execute('SELECT candidate,body FROM feedback ORDER BY rowid LIMIT -1 OFFSET ?',
                           (manifest['prior_tables']['feedback']['count'],)):
    feedback = json.loads(body); books = []
    for key, phase, body in db.execute('SELECT key,phase,body FROM backtests WHERE candidate=? ORDER BY rowid', (cid,)):
        receipt = json.loads(body)
        if receipt['valid']:
            raw = (ROOT/receipt['book']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == receipt['book_sha256']
            assert runtime.book(ROOT, receipt)['audit']['pnl_reconciled']
        books.append({'key': key, 'phase': phase, 'valid': receipt['valid'], 'attempt': receipt['attempt'],
                      'book_sha256': receipt.get('book_sha256')})
    new.append({'candidate': cid, 'batch': feedback['batch'], 'origin': feedback['origin'],
                'valid': feedback['valid'], 'utc': feedback['utc'],
                'alpha_index': feedback['statistics']['alpha_index'], 'books': books})
day, _ = period()
proof = {'utc': utc(), 'release': str(RELEASE), 'audit': value,
         'starts_today': db.execute('SELECT COUNT(*) FROM scientific_attempts WHERE day=?', (day,)).fetchone()[0],
         'completed_today': db.execute('SELECT COUNT(*) FROM feedback f JOIN scientific_attempts s ON s.candidate=f.candidate WHERE s.day=?', (day,)).fetchone()[0],
         'new_completed_after_deploy': new, 'preexisting_table_prefixes_unchanged': True,
         'preexisting_api_reservations_unchanged': True, 'predecessors': predecessors(),
         'native_regressions': (RELEASE/'meta-native-regression.txt').read_text(),
         'units': subprocess.check_output(['systemctl', 'show', 'trendatlas-continuous-research.service',
              'trendatlas-continuous-broker.service', '-p', 'Result', '-p', 'ActiveState', '-p', 'ExecStart',
              '-p', 'ExecMainStartTimestamp', '-p', 'ExecMainExitTimestamp', '-p', 'Nice', '-p', 'CPUWeight',
              '-p', 'CPUQuotaPerSecUSec', '-p', 'MemoryHigh', '-p', 'MemoryMax', '-p', 'IOWeight',
              '-p', 'IOSchedulingClass', '-p', 'PrivateNetwork', '-p', 'ReadWritePaths', '-p', 'InaccessiblePaths'], text=True)}
print(json.dumps(proof))
db.rollback(); api.rollback(); db.close(); api.close()
