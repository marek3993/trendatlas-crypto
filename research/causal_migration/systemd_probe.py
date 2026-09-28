"""Real process/systemd stop, unexpected signal and hard-timeout regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runtime as r

ROOT=Path('/run/trendatlas-migration-probe')
UNITS=Path('/run/systemd/system')
PREFIX='trendatlas-migration-probe-'


def call(*args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
def wait(predicate,seconds=30):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.2)
    raise RuntimeError('Probe wait timed out')
def props(name):return dict(x.split('=',1) for x in call('systemctl','show',name,'-p','ActiveState','-p','Result','-p','MainPID').splitlines())


CHILD='''import sys,signal,time,subprocess,json
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import runtime as r
r.legacy.load_engine(r.ENGINE)
from research.causal_evolution.store import Store
from research.causal_evolution.protocol import freeze
root=Path(sys.argv[2]);mode=sys.argv[3]
if mode=='stop':r.request_stop(root);raise SystemExit(0)
s=Store(root)
if mode=='finalize':
 import os
 r.finalize(s,os.environ.get('SERVICE_RESULT','unknown'));s.close();raise SystemExit(0)
if s.counts()['evaluations']==0:
 m=freeze(root,True)
 for k in ('experiment_id','fingerprint'):s.set(k,m[k])
 value={k:{} for k in ('request','metrics','daily','episodes','orders','folds','audit')}
 attempt=s.reserve('synthetic-checkpoint','inner_train');s.save('synthetic-checkpoint',attempt,value)
s.set('status','CHECKPOINTED')
def loop(s,e,g):
 (root/'entered').write_text('ready')
 if mode=='hung':
  s.reserve('unfinished','inner_train');signal.signal(signal.SIGTERM,signal.SIG_IGN)
  while True:time.sleep(.1)
 s.reserve('unfinished-'+str(s.counts()['attempts']),'inner_train')
 while True:
  subprocess.run(['/bin/sleep','.1'],check=True)
  g(force=True)
try:r.activate(s,seconds=1680,synthetic=True,loop=loop,no_outer=True)
finally:s.close()
'''


def main():
    if ROOT.exists():raise FileExistsError(ROOT)
    ROOT.mkdir();(ROOT/'child.py').write_text(CHILD)
    names=[PREFIX+x+'.service' for x in ('admin','unexpected','timeout')]
    results={}
    try:
        for kind,name in zip(('admin','unexpected','timeout'),names):
            state=ROOT/kind;state.mkdir()
            common=f'{sys.executable} -I -B {ROOT}/child.py {r.HERE} {state}'
            unit=f'''[Service]
Type=exec
ExecStart={common} {'hung' if kind=='timeout' else 'work'}
ExecStop={common} stop
ExecStopPost={common} finalize
TimeoutStopSec=2s
KillMode=mixed
RuntimeMaxSec={'3s' if kind=='timeout' else '60s'}
PrivateNetwork=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={ROOT}
'''
            (UNITS/name).write_text(unit)
        call('systemctl','daemon-reload')
        for kind,name in zip(('admin','unexpected','timeout'),names):
            state=ROOT/kind;call('systemctl','start',name)
            wait(lambda:(state/'entered').exists())
            if kind=='admin':call('systemctl','stop',name)
            elif kind=='unexpected':os.kill(int(props(name)['MainPID']),15)
            wait(lambda:props(name)['ActiveState'] in ('inactive','failed'))
            db=r.legacy.readonly(state/'candidates.sqlite');meta=r.legacy.metadata(db)
            attempt_counts=db.execute('SELECT status,COUNT(*) FROM attempts GROUP BY status').fetchall();db.close()
            results[kind]=dict(systemd=props(name),status=meta['status'],failure=meta.get('failure'),attempts=attempt_counts)
            assert meta['status']==('FAILED' if kind=='unexpected' else 'CHECKPOINTED'),results[kind]
            if kind=='timeout':assert props(name)['Result']=='timeout'
        print(json.dumps(results,indent=2))
    finally:
        for name in names:
            subprocess.run(['systemctl','stop',name],capture_output=True)
            (UNITS/name).unlink(missing_ok=True)
            subprocess.run(['systemctl','reset-failed',name],capture_output=True)
        call('systemctl','daemon-reload')
    # Keep probe state/log evidence; never auto-delete a checkpoint.


if __name__=='__main__':main()
