"""No same-data succession. Public monthly feeds and annual rolling experiments.

Quarterly admission checks may skip a refit: a new fully closed annual outer
window is required, in addition to >=30 new UTC days. A hash alone never admits.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from .protocol import atomic,digest,utc,HERE,CONTRACT,successor_allowed
from .acquisition import collect_months,StopActivation,FILES
from .locking import WorkerLock

def baseline_dataset():
    hashes={n:hashlib.sha256((HERE/'inputs'/n).read_bytes()).hexdigest() for n in FILES}
    return dict(closed_through='2025-12-31',directory=str(HERE/'inputs'),fingerprint=digest(hashes),files=hashes,coverage_complete=True)

def read_status(root):
    path=root/'status.json'
    return json.loads(path.read_text()) if path.exists() else dict(status='RUNNING')

def forward(base,current,dataset):
    """Separate database: cannot modify the sealed historical search or proposer."""
    path=current/'frozen_finalists.json'
    if not path.exists():return dict(status='NOT_YET_FROZEN')
    frozen=json.loads(path.read_text());stamp=dt.datetime.fromtimestamp(path.stat().st_mtime,dt.timezone.utc).date()
    start=max(dt.date(2026,9,27),stamp+dt.timedelta(days=1))
    end=dt.date.fromisoformat(dataset['closed_through'])
    if end<start:return dict(status='AWAIT_NEW_CLOSED_MONTH',first_eligible_day=str(start),dataset_end=str(end))
    from .vendor import data
    from .evaluator import Evaluator
    from .store import Store
    from .vendor.common import config
    data.OLD=Path(dataset['directory']);CONTRACT['split']['data_end']=str(end)
    s=Store(base/'forward'/current.name/dataset['closed_through']);s.set('outer_opened',True);s.set('fingerprint',dataset['fingerprint'])
    e=Evaluator(s);seen=set();rows=[];last=max(f['origin'] for f in frozen)
    try:
        for f in frozen:
            if f['origin']!=last or f['id'] in seen:continue
            seen.add(f['id']);track=f['island'].split('_')[1]
            p=dict(scope='prospective_forward',fold='forward',start=str(start),end=str(end))
            result=e.evaluate(f['genes'],p,track);bench=e.evaluate(config(),p,track,benchmark=True)
            rows.append(dict(candidate=f['id'],metrics=result['metrics'],benchmark=bench['metrics']))
        output=dict(status='OBSERVED_NO_MUTATION_FEEDBACK',first_eligible_day=str(start),end=str(end),nominee_frozen_utc=dt.datetime.fromtimestamp(path.stat().st_mtime,dt.timezone.utc).isoformat(),rows=rows,refit_not_before='2027-01-01')
        atomic(s.root/'forward.json',output);return output
    finally:s.close()

def maintain(base,today=None):
    base=Path(base);today=today or dt.datetime.now(dt.timezone.utc).date()
    with WorkerLock(base/'maintenance.lock'):
        current=(base/'current').resolve();status=read_status(current)
        if status['status'] not in ('SEALED','WAITING_FOR_NEW_DATA'):
            atomic(base/'continuation_status.json',dict(status=status['status'],reason='historical_worker_has_priority',utc=utc()));return
        from .gate import main as gate
        if os.name=='posix' and gate()!=0:
            atomic(base/'continuation_status.json',dict(status='WAITING_FOR_NEW_DATA',reason='production_priority',utc=utc()));return
        latest=base/'feed'/'latest_dataset.json'
        source=json.loads(latest.read_text()) if latest.exists() else baseline_dataset()
        cutoff=today.replace(day=1)-dt.timedelta(days=1)
        if today.day<=7:cutoff=cutoff.replace(day=1)-dt.timedelta(days=1)
        if dt.date.fromisoformat(source['closed_through'])<cutoff:
            try:source=collect_months(base/'feed',source['directory'],source['closed_through'],str(cutoff),source['fingerprint'])
            except StopActivation as exc:
                atomic(base/'continuation_status.json',dict(status='WAITING_FOR_NEW_DATA',reason=str(exc),utc=utc()));return
        prospective=forward(base,current,source)
        descriptor_path=current/'cycle.json';previous_dataset=json.loads(descriptor_path.read_text())['dataset'] if descriptor_path.exists() else baseline_dataset()
        prev=dict(status=status['status'],closed_through=previous_dataset['closed_through'],fingerprint=previous_dataset['fingerprint'],experiment_id=status['experiment_id'],next_refit=status.get('next_allowed_cycle','2027-01-01'))
        incoming=dict(source,experiment_id=f"causal_nested_v1_{cutoff.year+1}0101",parent_fingerprint=previous_dataset['fingerprint'])
        # Verify the recorded append-only chain, rather than trusting a rewritten parent.
        chain=source;verified=False
        for _ in range(24):
            if chain.get('parent_fingerprint')==previous_dataset['fingerprint']:verified=True;break
            matches=[]
            for p in (base/'feed'/'datasets').glob('*/dataset.json'):
                item=json.loads(p.read_text())
                if item['fingerprint']==chain.get('parent_fingerprint'):matches.append(item)
            if len(matches)!=1:break
            chain=matches[0]
        if not verified:incoming['parent_fingerprint']='UNVERIFIED'
        ok,reasons=successor_allowed(prev,incoming,today)
        if (cutoff.month,cutoff.day)!=(12,31):ok=False;reasons.append('no_new_complete_annual_outer_window')
        if ok:
            name=incoming['experiment_id'];target=base/'cycles'/name
            if target.exists():ok=False;reasons.append('immutable_experiment_id_already_exists')
            else:
                target.mkdir(parents=True)
                atomic(target/'cycle.json',dict(experiment_id=name,dataset=source,predecessor=status['experiment_id'],admitted_utc=utc(),prior_attempts=status.get('counts',{}).get('trials',0)))
                atomic(target/'status.json',dict(status='RUNNING',experiment_id=name,phase='PREREGISTERED_SUCCESSOR',utc=utc()))
                link=base/'current.next';link.symlink_to(target,target_is_directory=True);link.replace(base/'current')
        atomic(base/'continuation_status.json',dict(status='RUNNING' if ok else 'WAITING_FOR_NEW_DATA',reason=reasons,
              prospective=prospective,next_allowed_cycle=prev['next_refit'],source_closed_through=source['closed_through'],utc=utc()))
