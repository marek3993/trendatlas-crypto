"""Execute only the finite, Git-pinned campaign. No code generation or network."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import time

from . import runtime as w, walk_forward as engine

DEFINITION = Path(__file__).with_name('campaign_v3.json')
PREREGISTRATION = '8ade6f8992b6d89a63109d621d1a78f6046823fa'
THERMAL_PATH = Path('/sys/class/thermal/thermal_zone0/temp')


def replace_json(path, value):
    path = w.safe_path(path)
    temporary = w.safe_path(path.with_name(path.name + '.pending'))
    with temporary.open('wb') as handle:
        handle.write((w.canonical(value) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    w.sync_dir(path.parent)


def temperature():
    value = float(THERMAL_PATH.read_text()) / 1000
    if not 0 < value < 120:
        raise ValueError('Invalid thermal sensor')
    return value


def authorization(state, manifest):
    path = w.safe_path(state / 'campaign.json')
    auth = json.loads(path.read_bytes())
    definition = json.loads(DEFINITION.read_bytes())
    if (set(auth) != {'definition', 'release_sha256', 'preregistration_commit', 'activated_at'}
            or auth['definition'] != definition or auth['release_sha256'] != manifest['release_sha256']
            or not w.re.fullmatch('[0-9a-f]{40}', auth['preregistration_commit'])
            or auth['preregistration_commit'] != PREREGISTRATION):
        raise w.Blocked('Campaign authorization or release changed')
    return auth


def job_for(auth, study):
    return {'schema_version': 2, 'job_id': study['experiment_id'], 'mode': 'research',
            'engine': 'btc_walk_forward_mr_v3', 'campaign_id': auth['definition']['campaign_id'],
            'study': study, 'preregistration_commit': auth['preregistration_commit'],
            'release_sha256': auth['release_sha256'], 'input_name': 'BTCUSDT_1d.csv',
            'input_sha256': study['input_sha256']}


def validate_job(job, manifest, state):
    auth = authorization(state, manifest)
    choices = [job_for(auth, s) for s in auth['definition']['studies']]
    if job not in choices or job['job_id'] in w.DENIED_IDS:
        raise w.Blocked('Job is not an exact authorized campaign study')
    return auth


def known_jobs(state):
    path = w.safe_path(state / 'queue.sqlite3')
    if not path.exists():
        return {}
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        return {r[0]: {'state': r[1], 'outcome': r[2], 'reason': r[3]} for r in db.execute('SELECT id,state,outcome,reason FROM jobs')}
    finally:
        db.close()


def pending(state, manifest):
    auth = authorization(state, manifest)
    known = known_jobs(state)
    if any(v['state'] == 'BLOCKED' for v in known.values()):
        return False
    return any(known.get(s['experiment_id'], {}).get('state') != 'SEALED' for s in auth['definition']['studies'])


def enqueue(state, job, manifest, *, automatic=False):
    """Caller owns worker.lock; an automatic enqueue cannot expand the campaign."""
    auth = validate_job(job, manifest, state)
    known = known_jobs(state)
    if job['job_id'] in known:
        raise w.Blocked('Existing or SEALED job cannot be requeued')
    if any(v['state'] == 'BLOCKED' for v in known.values()):
        raise w.Blocked('Campaign has a blocked job')
    expected = next((s for s in auth['definition']['studies'] if known.get(s['experiment_id'], {}).get('state') != 'SEALED'), None)
    if expected != job['study']:
        raise w.Blocked('Only the next preregistered study can be enqueued')
    for directory in ('queue', 'campaign_queue'):
        if w.safe_path(state / directory / job['job_id'] / 'study.json').exists():
            raise w.Blocked('Duplicate queued job')
    w.atomic_json(state / ('campaign_queue' if automatic else 'queue') / job['job_id'] / 'study.json', job)


def activate(state, manifest, release, preregistration, source):
    """Operator-only bootstrap. Freeze input once; never read live input for later jobs."""
    definition = json.loads((release / DEFINITION.relative_to(Path(__file__).parents[3])).read_bytes())
    if len(definition['studies']) != 10 or definition['max_experiments'] != 10:
        raise w.Blocked('Campaign budget mismatch')
    auth = {'definition': definition, 'release_sha256': manifest['release_sha256'],
            'preregistration_commit': preregistration, 'activated_at': time.time()}
    if preregistration != PREREGISTRATION:
        raise w.Blocked('Wrong preregistration commit')
    if (state / 'campaign.json').exists():
        raise w.Blocked('Campaign already activated')
    raw = Path(source).read_bytes()
    if len(raw) > 5 * w.MIB:
        raise w.Blocked('Input too large')
    for study in definition['studies']:
        engine.validate(study, raw)
    w.atomic_bytes(state / 'campaign-input' / 'BTCUSDT_1d.csv', raw)
    w.atomic_json(state / 'campaign.json', auth)
    return job_for(auth, definition['studies'][0])


def read_status(state, *, inspect_system=False):
    path = w.safe_path(state / 'status.json')
    value = json.loads(path.read_bytes()) if path.exists() else {'status': 'QUEUED', 'next_step': 'dispatcher admission'}
    # Read-only SQLite evidence is authoritative, including after a crashed writer.
    job_id = value.get('job_id')
    if job_id and w.NAME.fullmatch(job_id):
        root = w.safe_path(state / 'jobs' / job_id)
        if (root / 'research.sqlite3').exists():
            report = engine.report(root)
            value.update(generation=report['meta']['completed_generations'],
                         current_generation=min(5, report['meta']['completed_generations'] + 1),
                         evaluated_candidates=report['evaluated_candidates'], period_evaluations=report['period_evaluations'],
                         leader=report['meta'].get('leader'))
    if inspect_system:
        from . import gate
        try:
            value['temperature_c'] = temperature()
            service = gate.properties('trendatlas-evolution-worker.service')
            value['systemd_state'] = service.get('ActiveState')
            value['pid'] = int(service.get('MainPID', '0'))
            value['systemd_cpu_seconds'] = int(service.get('CPUUsageNSec', '0')) / 1e9
            if value.get('status') == 'RUNNING' and service.get('ActiveState') != 'active':
                value.update(status='PAUSED', pause_reason='worker_not_active_resume_on_dispatch', next_step='next dispatcher tick after production/thermal admission')
        except (OSError, ValueError):
            value['system_probe'] = 'unavailable'
    return value


def publish(state, auth, job, status, reason=None, **extra):
    previous = json.loads((state / 'status.json').read_bytes()) if (state / 'status.json').exists() else {}
    value = {'campaign_id': auth['definition']['campaign_id'], 'job_id': job['job_id'] if job else previous.get('job_id'),
             'status': status, 'pause_reason': reason, 'updated_at': time.time(),
             'pid': os.getpid(), 'cpu_seconds_current_activation': time.process_time(),
             'last_completed_experiment': previous.get('last_completed_experiment'),
             'generation': 0, 'evaluated_candidates': 0, 'leader': None,
             'orders_sent': False, 'production_promotion': False, 'ai_api_used': False}
    try:
        value['temperature_c'] = temperature()
    except (OSError, ValueError):
        value['temperature_c'] = None
    value.update(extra)
    if job and (state / 'jobs' / job['job_id'] / 'research.sqlite3').exists():
        report = engine.report(state / 'jobs' / job['job_id'])
        value.update(generation=report['meta']['completed_generations'],
                     current_generation=min(5, report['meta']['completed_generations'] + 1),
                     evaluated_candidates=report['evaluated_candidates'], period_evaluations=report['period_evaluations'],
                     leader=report['meta'].get('leader'))
    replace_json(state / 'status.json', value)
    return value


def disk_guard(state):
    # Inspect each node once, rather than re-stat all its ancestors per checkpoint.
    used = 0
    for directory, dirs, files in os.walk(state, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or path.is_junction() or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise w.Blocked('Linked research state path')
            if stat.S_ISREG(info.st_mode):
                used += info.st_size
    if used > w.STATE_BUDGET or w.shutil.disk_usage(state).free < w.FREE_FLOOR + w.HEADROOM:
        raise w.Paused('Disk reserve/state budget')


def resource_guard(state, auth, root=None):
    disk_guard(state)
    if time.time() > auth['activated_at'] + auth['definition']['max_elapsed_seconds']:
        raise w.Blocked('Campaign elapsed budget exhausted')
    if root is not None:
        budget = json.loads(w.safe_path(root / 'budget.json').read_bytes())
        if time.time() > budget['deadline']:
            raise w.Blocked('Experiment elapsed budget exhausted')
        if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) >= budget['disk_bytes']:
            raise w.Paused('Experiment disk budget')
    path = w.safe_path(state / 'thermal.json')
    was_paused = json.loads(path.read_bytes()).get('paused', False) if path.exists() else False
    try:
        temp = temperature()
    except (OSError, ValueError):
        raise w.Paused('thermal_sensor_unavailable')
    paused = temp >= 68 if was_paused else temp > 75
    replace_json(path, {'paused': paused, 'temperature_c': temp})
    if paused:
        raise w.Paused('thermal_hysteresis_wait_below_68C')


def prepare(state, job):
    root = w.safe_path(state / 'jobs' / job['job_id'])
    if root.exists():
        for path in root.rglob('*'):
            w.safe_path(path)
        if json.loads(w.safe_path(root / 'accepted.json').read_bytes()) != job or w.sha(w.safe_path(root / 'input.csv')) != job['input_sha256']:
            raise w.Blocked('Accepted spec or input changed')
        return root
    staging = w.safe_path(state / 'staging' / job['job_id'])
    if staging.exists():
        for p in staging.rglob('*'):
            w.safe_path(p)
        w.shutil.rmtree(staging)
    staging.mkdir(parents=True)
    raw = w.safe_path(state / 'campaign-input' / 'BTCUSDT_1d.csv').read_bytes()
    w.atomic_json(staging / 'accepted.json', job)
    w.atomic_bytes(staging / 'input.csv', raw)
    budget_path = w.safe_path(state / 'budgets' / (job['job_id'] + '.json'))
    if not budget_path.exists():
        w.atomic_json(budget_path, {'deadline': time.time() + job['study']['max_elapsed_seconds'], 'disk_bytes': job['study']['disk_budget_bytes']})
    w.atomic_bytes(staging / 'budget.json', budget_path.read_bytes())
    engine.initialize(staging, job)
    root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, root)
    w.sync_dir(root.parent)
    return root


def seal(root, job, auth):
    path = w.safe_path(root / 'SEALED.json')
    if path.exists():
        result = json.loads(path.read_bytes())
        for name, digest in result['files'].items():
            target = w.safe_path(root / name)
            if not target.is_relative_to(root) or w.sha(target) != digest:
                raise w.Blocked('SEALED artifact changed')
        return result['outcome']
    result = engine.report(root)
    if result['meta']['state'] != 'SEALED':
        raise w.Blocked('Cannot seal incomplete study')
    w.atomic_json(root / 'report.json', result)
    w.atomic_json(root / 'audit.json', {'job_id': job['job_id'], 'release_sha256': job['release_sha256'],
        'preregistration_commit': job['preregistration_commit'], 'input_sha256': job['input_sha256'],
        'outcome': result['meta']['outcome'], 'orders_sent': False, 'production_writes': False,
        'ai_api_used': False, 'history_role': 'seen_exploratory_retrospective'})
    names = ['accepted.json', 'budget.json', 'input.csv', 'research.sqlite3', 'report.json', 'audit.json']
    if result['meta']['outcome'] == engine.pure.QUALIFIED:
        w.atomic_json(root / 'paper-monitor-proposal.json', {'candidate': result['meta']['frozen_candidate'],
            'forward_plan': auth['definition']['forward_plan'], 'status': 'REVIEW_REQUIRED_NOT_INSTALLED'})
        names.append('paper-monitor-proposal.json')
    w.atomic_json(path, {'outcome': result['meta']['outcome'], 'files': {n: w.sha(root / n) for n in names}})
    for n in names + ['SEALED.json']:
        (root / n).chmod(0o440)
    return result['meta']['outcome']


def run(release, state, *, check_production=True):
    if set(os.environ) - w.ALLOWED_ENV:
        raise w.Blocked('Worker requires empty allowlisted environment')
    state = w.state_path(state)
    manifest = w.verify_release(release)
    auth = authorization(state, manifest)
    job = None
    with w.worker_lock(state):
        db = w.ledger(state)
        old_handler = signal.getsignal(signal.SIGTERM)
        def preempt(*_):
            raise w.Paused('production_or_service_preemption')
        signal.signal(signal.SIGTERM, preempt)
        try:
            for study in auth['definition']['studies']:
                root = None
                job = job_for(auth, study)
                known = known_jobs(state)
                if any(v['state'] == 'BLOCKED' for v in known.values()):
                    return publish(state, auth, job, 'BLOCKED', 'campaign_has_blocked_job', next_step='operator review')
                row = known.get(job['job_id'])
                if row and row['state'] == 'SEALED':
                    seal(w.safe_path(state / 'jobs' / job['job_id']), job, auth)
                    continue
                def guard():
                    if check_production:
                        from . import gate
                        if gate.main() != 0:
                            raise w.Paused('production_priority')
                    resource_guard(state, auth, root)
                guard()
                paths = [w.safe_path(state / q / job['job_id'] / 'study.json') for q in ('queue', 'campaign_queue')]
                if not any(p.exists() for p in paths) and not row:
                    enqueue(state, job, manifest, automatic=True)
                    publish(state, auth, job, 'QUEUED', next_step='claim preregistered job')
                for path in paths:
                    if path.exists() and json.loads(path.read_bytes()) != job:
                        raise w.Blocked('Queued job changed')
                if row is None:
                    with db:
                        db.execute("INSERT INTO jobs VALUES(?,?,?,'RUNNING',NULL,NULL)",
                                   (job['job_id'], w.digest(w.canonical(job).encode()), w.study_fingerprint(study)))
                root = prepare(state, job)
                def progress():
                    publish(state, auth, job, 'RUNNING', next_step='evaluate frozen population then walk-forward assessment')
                progress()
                while engine.report(root)['meta']['state'] != 'SEALED':
                    guard()
                    engine.step(root, job, guard, progress)
                outcome = seal(root, job, auth)
                with db:
                    db.execute("UPDATE jobs SET state='SEALED',outcome=? WHERE id=?", (outcome, job['job_id']))
                publish(state, auth, job, 'SEALED', last_completed_experiment=job['job_id'],
                        next_step='next predeclared campaign experiment', outcome=outcome)
            return publish(state, auth, job, 'SEALED', 'campaign_budget_exhausted', next_step='no further jobs; review all historical outcomes')
        except w.Paused as exc:
            return publish(state, auth, job, 'PAUSED', str(exc), next_step='resume unchanged on next eligible dispatcher tick')
        except (w.Blocked, ValueError, sqlite3.Error, OSError) as exc:
            reason = type(exc).__name__ + ': ' + str(exc)
            if job:
                with db:
                    db.execute("INSERT OR IGNORE INTO jobs(id,state,reason) VALUES(?,'BLOCKED',?)", (job['job_id'], reason))
                    db.execute("UPDATE jobs SET state='BLOCKED',reason=? WHERE id=? AND state!='SEALED'", (reason, job['job_id']))
            return publish(state, auth, job, 'BLOCKED', reason, next_step='operator review; no new jobs')
        finally:
            signal.signal(signal.SIGTERM, old_handler)
            db.close()
