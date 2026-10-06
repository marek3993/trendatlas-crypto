"""Overlay a recovery coordinator without migrating the frozen evaluator."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile


def call(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def digest_rows(db):
    return {name: hashlib.sha256(json.dumps(db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall(), separators=(',', ':')).encode()).hexdigest()
            for name in ('meta', 'candidates', 'evaluations', 'members', 'stages', 'selections', 'test_books', 'events')}


def main(package):
    package=Path(package)
    revision=hashlib.sha256(package.read_bytes()).hexdigest()[:16]
    base=Path('/opt/trendatlas-research/phase2-v2/releases/91237299dee6880e')
    release=base.parent/('continuation-'+revision)
    if release.exists():raise RuntimeError('recovery_release_already_exists')
    # The evaluator, original contract and sealed inputs are not modified.
    shutil.copytree(base, release)
    allowed={'research/phase2_v2/continuation.py','source_of_truth/phase2_v2_recovery_contract.json','tests/test_phase2_v2_continuation.py'}
    with zipfile.ZipFile(package) as z:
        if set(z.namelist())!=allowed:raise RuntimeError('recovery_package_scope')
        for name in allowed:(release/name).write_bytes(z.read(name))
    for p in (release, *release.rglob('*')):
        os.chown(p,0,os.stat(base).st_gid);p.chmod(0o750 if p.is_dir() else 0o640)
    for name in ('runtime.py','engine.py','market.py','contract.py'):
        assert (base/'research/phase2_v2'/name).read_bytes()==(release/'research/phase2_v2'/name).read_bytes()
    assert (base/'source_of_truth/phase2_v2_contract.json').read_bytes()==(release/'source_of_truth/phase2_v2_contract.json').read_bytes()
    py='/opt/trendatlas-research/venvs/causal-v1/bin/python'
    call(py,'-B','-m','unittest','tests.test_phase2_v2_continuation','tests.test_phase2_v2','-q',cwd=release)
    state=Path('/var/lib/trendatlas-research-v2')
    inputs=Path('/var/lib/trendatlas-research-v2-inputs/91237299dee6880e')
    sys.path.insert(0,str(release))
    from research.phase2_v2 import runtime as r
    bindings=r.binding(inputs)
    db=sqlite3.connect('file:'+str(state/'v2.sqlite')+'?mode=ro',uri=True)
    assert json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])==bindings
    db.close()
    call('systemctl','stop','trendatlas-phase2-v2-development.timer')
    call('systemctl','stop','trendatlas-phase2-v2-development.service')
    db=sqlite3.connect('file:'+str(state/'v2.sqlite')+'?mode=ro',uri=True)
    before=digest_rows(db)
    backup=state/('recovery-checkpoint-'+revision+'.sqlite')
    if backup.exists():raise RuntimeError('recovery_backup_already_exists')
    out=sqlite3.connect(backup);db.backup(out);out.close()
    assert digest_rows(db)==before
    cycle=json.loads(db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()[0]);db.close()
    drop=Path('/etc/systemd/system/trendatlas-phase2-v2-development.service.d')
    drop.mkdir(exist_ok=True)
    coordinator=release/'research/phase2_v2/continuation.py'
    (drop/'30-terminal-book-continuation.conf').write_text(f'''[Service]
WorkingDirectory={release}
ExecCondition=
ExecCondition={py} -I -B {coordinator} condition --root {state}
ExecStart=
ExecStart={py} -I -B {coordinator} run --root {state} --inputs {inputs} --workers 2 --seconds 240
''')
    receipt={'release':str(release),'backup':str(backup),'cycle':cycle,'unchanged_tables_sha256':before,
             'evaluator_binding_unchanged':bindings,'broker_changed':False,'production_touched':False}
    Path('/tmp/phase2-v2-recovery-deployment.json').write_text(json.dumps(receipt,indent=2)+'\n')
    call('systemctl','daemon-reload')
    # Timer, not a manually started worker, owns automatic checkpoint continuation.
    call('systemctl','start','trendatlas-phase2-v2-development.timer')
    print(json.dumps(receipt))


if __name__=='__main__':main(sys.argv[1])
