"""Add a frozen research-space adapter to the existing isolated research units."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import research_spaces as spaces
from research.continuous_research import ledger
from research.continuous_research.common import canonical, digest, utc
from research.continuous_research.deploy import ROOT, MAILBOX, PY, WORKER, BROKER


def prefix(db):
    return {t: {'count': db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0],
                'sha256': digest(db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall())}
            for t in ledger.TABLES if t not in ('meta', 'events')}


def unit_revision(text, ancestor, release):
    if str(ancestor) not in text or 'research/continuous_research_protocol.py' not in text:
        raise ValueError('unexpected_research_unit')
    return text.replace(str(ancestor), str(release)).replace('research/continuous_research_protocol.py', 'research/research_spaces.py')


def main(package, ancestor):
    if os.geteuid() != 0:
        raise ValueError('research_admin_required')
    ancestor = Path(ancestor).resolve()
    if ancestor.parent != Path('/opt/trendatlas-research/continuous/releases'):
        raise ValueError('ancestor_scope')
    import grp
    gid = grp.getgrnam('trendatlas-research').gr_gid
    os.setegid(gid); os.umask(0o007)
    for name in (WORKER, BROKER):
        for suffix in ('.timer', '.service'):
            state = subprocess.run(['systemctl', 'is-active', name+suffix], capture_output=True, text=True).stdout.strip()
            if state in ('active', 'activating', 'reloading', 'deactivating'):
                raise ValueError('research_units_must_be_quiescent')
    package = Path(package); sha = hashlib.sha256(package.read_bytes()).hexdigest()
    release = ancestor.parent/sha[:16]
    units = {n: Path('/etc/systemd/system')/(n+'.service') for n in (WORKER, BROKER)}
    old_units = {n: p.read_text() for n, p in units.items()}
    new_units = {n: unit_revision(value, ancestor, release) for n, value in old_units.items()}
    with zipfile.ZipFile(package) as z:
        if set(z.namelist()) != set(spaces.FILES) or len(z.namelist()) != len(spaces.FILES):
            raise ValueError('package_scope')
        if not release.exists():
            shutil.copytree(ancestor, release)
            for name in spaces.FILES:
                path = release/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(z.read(name))
        for name in spaces.FILES:
            if (release/name).read_bytes() != z.read(name):
                raise ValueError('existing_release_mismatch')
    db = sqlite3.connect(ROOT/'research.sqlite'); api = sqlite3.connect(MAILBOX/'api.sqlite')
    before = prefix(db)
    reservations = api.execute('SELECT * FROM reservations ORDER BY id').fetchall()
    prior_protocol = json.loads((release/'protocol-freeze.json').read_text())
    path = release/'spaces-freeze.json'
    manifest = json.loads(path.read_text()) if path.exists() else {
        'version': spaces.KEY, 'utc': utc(), 'contract': digest(spaces.contract()),
        'files': spaces.fingerprint(release), 'ancestor_protocol': digest(prior_protocol),
        'ancestor_release': str(ancestor), 'prior_worker_hash': ledger.verify(db),
        'prior_tables': before, 'api_reservations_count': len(reservations),
        'api_reservations_digest': digest(reservations), 'old_units': old_units}
    spaces.verify_manifest(release, manifest)
    # Every pre-existing request, including an unpaid pending request, retains its wire.
    payloads = [json.loads(r[0])['payload'] for r in db.execute('SELECT body FROM requests')]
    old_wires = [digest(spaces.protocol.wire_body(p, prior_protocol['legacy_request_ids'])) for p in payloads]
    with spaces.installed(prior_protocol['legacy_request_ids']):
        if old_wires != [digest(spaces.planner.wire_body(p)) for p in payloads]:
            raise ValueError('historical_wire_changed')
    path.write_text(canonical(manifest)+'\n', encoding='utf-8')
    for p in (release, *release.rglob('*')):
        os.chown(p, 0, gid); p.chmod(0o750 if p.is_dir() else 0o640)
    result = subprocess.run(['sudo', '-u', 'trendatlas-continuous', PY, '-B', '-m', 'unittest',
                             'tests.test_research_spaces', '-v'], cwd=release, capture_output=True, text=True)
    (release/'spaces-native-regression.txt').write_text(result.stdout+result.stderr, encoding='utf-8')
    if result.returncode:
        raise ValueError('native_regressions_failed:'+result.stderr[-2000:])
    spaces.initialize_spaces(db)
    for target in (db, api):
        row = target.execute('SELECT body FROM meta WHERE key=?', (spaces.KEY,)).fetchone()
        if row and json.loads(row[0]) != digest(manifest):
            raise ValueError('different_space_revision_already_frozen')
        if not row:
            with target:
                target.execute('INSERT INTO meta VALUES(?,?)', (spaces.KEY, canonical(digest(manifest))))
                if target is db:
                    ledger.event(db, 'research_space_adapter_frozen', manifest=digest(manifest), files=manifest['files'])
    if prefix(db) != before or api.execute('SELECT * FROM reservations ORDER BY id').fetchall() != reservations:
        raise ValueError('existing_evidence_changed')
    db.close(); api.close()
    for name, path in units.items():
        path.write_text(new_units[name])
    subprocess.run(['systemd-analyze', 'verify', *map(str, units.values())], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'start', WORKER+'.timer', BROKER+'.timer'], check=True)
    print(canonical({'release': str(release), 'manifest': manifest, 'package_sha256': sha,
                     'native_regressions': 'PASS', 'old_evidence_and_reservations': 'UNCHANGED'}))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
