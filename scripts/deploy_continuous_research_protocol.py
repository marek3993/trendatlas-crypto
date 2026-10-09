"""Freeze an additive wire revision with no scientific/accounting reset."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.continuous_research.common import canonical,digest,utc
from research.continuous_research.deploy import ROOT,MAILBOX,PY,WORKER,BROKER
from research.continuous_research_protocol import FILES,KEY,fingerprint,verify_manifest


def overlay(z,release):
    if set(z.namelist())!=set(FILES) or len(z.namelist())!=len(FILES):raise ValueError('package_scope')
    for name in FILES:
        path=Path(release)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(z.read(name))


def main(package,ancestor):
    if os.geteuid()!=0:raise ValueError('research_admin_required')
    for name in (WORKER,BROKER):
        for suffix in ('.timer','.service'):
            state=subprocess.run(['systemctl','is-active',name+suffix],capture_output=True,text=True).stdout.strip()
            if state in ('active','activating','reloading'):raise ValueError('units_must_be_quiescent')
    db=sqlite3.connect(ROOT/'research.sqlite');api=sqlite3.connect(MAILBOX/'api.sqlite')
    if db.execute('SELECT 1 FROM requests WHERE id NOT IN(SELECT id FROM ingested)').fetchone():raise ValueError('pending_old_wire_request')
    if db.execute('SELECT 1 FROM meta WHERE key=?',(KEY,)).fetchone():raise ValueError('revision_already_frozen')
    package=Path(package);sha=hashlib.sha256(package.read_bytes()).hexdigest()
    release=Path('/opt/trendatlas-research/continuous/releases')/sha[:16]
    with zipfile.ZipFile(package) as z:
        if set(z.namelist())!=set(FILES) or len(z.namelist())!=len(FILES):raise ValueError('package_scope')
        shutil.copytree(ancestor,release)
        overlay(z,release)
    binding=json.loads(db.execute("SELECT body FROM meta WHERE key='binding'").fetchone()[0])
    manifest={'version':KEY,'utc':utc(),'contract':digest(json.loads((release/FILES[2]).read_text())),
        'files':fingerprint(release),'ancestor_release':str(ancestor),'ancestor_binding':binding,
        'legacy_request_ids':[r[0] for r in db.execute('SELECT id FROM requests ORDER BY id')],
        'prior_worker_hash':db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone()[0],
        'completed_at_freeze':db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],
        'reserved_api_at_freeze':api.execute('SELECT COUNT(*),SUM(nanousd) FROM reservations').fetchone(),
        'no_scientific_change':True,'shared_budget_retained':True}
    verify_manifest(release,manifest)
    (release/'protocol-freeze.json').write_text(canonical(manifest)+'\n')
    import grp
    gid=grp.getgrnam('trendatlas-research').gr_gid
    for path in (release,*release.rglob('*')):os.chown(path,0,gid);path.chmod(0o750 if path.is_dir() else 0o640)
    subprocess.run(['sudo','-u','trendatlas-continuous',PY,'-B','-m','unittest','tests.test_continuous_research_protocol','-q'],cwd=release,check=True)
    # Append only; the existing immutable meta binding and all rows are retained.
    from research.continuous_research.ledger import event
    with db:
        db.execute('INSERT INTO meta VALUES(?,?)',(KEY,canonical(digest(manifest))))
        event(db,'prospective_wire_protocol_frozen',manifest=digest(manifest),files=manifest['files'],legacy_request_ids=manifest['legacy_request_ids'])
    with api:api.execute('INSERT INTO meta VALUES(?,?)',(KEY,canonical(digest(manifest))))
    db.close();api.close()
    for name in (WORKER,BROKER):
        path=Path('/etc/systemd/system')/(name+'.service');old=path.read_text()
        previous=str(ancestor)
        if previous not in old or 'research/continuous_research/entry.py' not in old:raise ValueError('unexpected_unit')
        new=old.replace(previous,str(release)).replace('research/continuous_research/entry.py','research/continuous_research_protocol.py')
        path.write_text(new)
    subprocess.run(['systemd-analyze','verify',*[str(Path('/etc/systemd/system')/(n+'.service')) for n in (WORKER,BROKER)]],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','start',WORKER+'.timer',BROKER+'.timer'],check=True)
    print(canonical({'release':str(release),'manifest':manifest,'package_sha256':sha}))


if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
