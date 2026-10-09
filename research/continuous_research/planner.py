"""Lifetime novelty and successor construction, independent of renewable quotas."""
import itertools
import json
from pathlib import Path
from .common import canonical,digest,utc,instant,atomic
from .contract import load
from .ledger import meta,event
from .schema import genes,rule,proposal,identity,spaces,wire_body


def frequency_key(r):return digest({'rule':rule(r),'version':'bounded_onset_v2','window':[load()['training'][0],load()['feedback_cutoff']]})


def initialize(db,boot,binding):
    row=db.execute("SELECT body FROM meta WHERE key='binding'").fetchone()
    if row:
        if json.loads(row[0])!=binding:raise ValueError('frozen_binding_changed')
        return
    if boot['contract']!=digest(load()) or boot['inherited']['alpha_index']!=load()['legacy_alpha_index']:
        raise ValueError('bootstrap_contract')
    with db:
        for key,value in [('binding',binding),('bootstrap',boot)]:db.execute('INSERT INTO meta VALUES(?,?)',(key,canonical(value)))
        db.executemany('INSERT INTO genes VALUES(?,?)',((g,'legacy') for g in boot['seen_genes']))
        for r in boot['known_rules']:
            r=rule(r);db.execute('INSERT OR IGNORE INTO hypotheses VALUES(?,?,?,?)',(digest(r),'mechanism',canonical(r),'legacy'))
        for p in boot['configuration_hypotheses']:
            db.execute('INSERT OR IGNORE INTO hypotheses VALUES(?,?,?,?)',(identity(p),'configuration',canonical(p),'legacy'))
        for d in boot['cached_discoveries']:
            if d['interval']!=[load()['training'][0],load()['feedback_cutoff']] or d['version']!='bounded_onset_v2':raise ValueError('frequency_cache_scope')
            db.execute('INSERT OR IGNORE INTO discoveries VALUES(?,?,?,?)',(frequency_key(d['rule']),canonical(d),'frozen_predecessor',utc()))
        event(db,'continuous_scheduler_frozen',contract=digest(load()),binding=digest(binding),inherited=boot['inherited'],lifetime_batch_limit=None)


def remaining(db):
    boot=meta(db,'bootstrap')
    return boot['K_cardinality']-boot['historical_K_count']-db.execute("SELECT COUNT(*) FROM genes WHERE source!='legacy'").fetchone()[0]


def register(db,value,origin,request=None,response_index=None):
    p=proposal(value);gid=digest(p['genes']);hid=identity(p);rid=digest(p['rule'])
    receipt_key=digest([request,response_index]) if request else digest([origin,p])
    existing=db.execute('SELECT body FROM proposal_receipts WHERE receipt_key=?',(receipt_key,)).fetchone()
    if existing:
        old=json.loads(existing[0]);return old['proposal'] if old['status']=='ACCEPTED' else None
    reason=('duplicate_gene' if db.execute('SELECT 1 FROM genes WHERE id=?',(gid,)).fetchone() else
            'duplicate_hypothesis' if db.execute('SELECT 1 FROM hypotheses WHERE id=?',(hid,)).fetchone() else None)
    body={**p,'id':hid,'gene_id':gid,'mechanism_id':rid,'origin':origin,'request':request,'response_index':response_index,
          'novel_configuration':True,'new_market_discovery':False,'mapping':load()['hypotheses']['mapping']}
    with db:
        db.execute('INSERT INTO proposal_receipts(receipt_key,request,body,utc) VALUES(?,?,?,?)',(receipt_key,request,canonical({'status':reason or 'ACCEPTED','proposal':body}),utc()))
        if reason:return None
        db.execute('INSERT INTO genes VALUES(?,?)',(gid,origin))
        db.execute('INSERT INTO hypotheses VALUES(?,?,?,?)',(hid,'configuration',canonical({'rule':p['rule'],'genes':p['genes']}),origin))
        db.execute('INSERT OR IGNORE INTO hypotheses VALUES(?,?,?,?)',(rid,'mechanism',canonical(p['rule']),origin))
        db.execute('INSERT INTO proposals VALUES(?,?,?,?,?)',(hid,gid,canonical(body),origin,utc()))
        event(db,'proposal_accepted',proposal=hid,gene=gid,origin=origin,request=request,mechanism_id=rid,new_market_discovery=False)
    return body


def ingest(db,mailbox):
    root=Path(mailbox)
    for rid,payload in db.execute('SELECT id,body FROM requests WHERE id NOT IN (SELECT id FROM ingested) ORDER BY utc').fetchall():
        path=root/'responses'/f'{rid}.json'
        if not path.exists():continue
        response=json.loads(path.read_text());request=json.loads(payload)
        if response['request']!=rid or response['wire_hash']!=digest(wire_body(request['payload'])):raise ValueError('AI_response_binding')
        accepted=[];errors=[];evaluation=None
        if response['state']=='COMPLETE' and not response.get('budget_violation'):
            try:
                content=json.loads(response['content'])
                if set(content)!={'evaluation','proposals'} or not isinstance(content['evaluation'],str) or len(content['evaluation'])>600 or not isinstance(content['proposals'],list) or len(content['proposals'])>2:
                    raise ValueError('AI_envelope')
                evaluation=content['evaluation'];parents={p['id'] for p in request['payload']['parents']}
                # Durable request/index admission receipts make a mid-response crash idempotent.
                for i,value in enumerate(content['proposals']):
                    try:
                        value=proposal(value,parents);out=register(db,value,'AI_AUTHORED',rid,i)
                        if out:accepted.append(out['id'])
                    except (ValueError,KeyError,TypeError) as exc:errors.append({'index':i,'type':type(exc).__name__,'reason':str(exc)})
            except (ValueError,KeyError,TypeError) as exc:errors.append({'reason':str(exc)})
        with db:
            receipt={'response_hash':digest(response),'state':response['state'],'accepted':accepted,'errors':errors,'evaluation':evaluation,
                     'provider_request_id':response.get('provider_request_id'),'model':response.get('model')}
            db.execute('INSERT INTO ingested VALUES(?,?,?)',(rid,canonical(receipt),utc()));event(db,'AI_response_ingested',request=rid,**receipt)


def parents(db):
    rows=[json.loads(r[0])['training_view'] for r in db.execute('SELECT body FROM feedback ORDER BY utc DESC')]
    if not rows:rows=meta(db,'bootstrap')['prior_training']
    def score(p):
        v=p.get('validation') or p['training'];m=v.get('metrics') or {}
        return (bool(v.get('valid')),m.get('log_growth',-1e9),-m.get('mdd',1))
    best=sorted(rows,key=score,reverse=True)
    if not best:return []
    out=[best[0]]
    for p in rows:
        if p['id']!=out[0]['id']:out.append(p);break
    return out


def ensure_request(db,mailbox):
    if remaining(db)<=0:return None
    pending=db.execute('SELECT id,body,utc FROM requests WHERE id NOT IN (SELECT id FROM ingested) ORDER BY utc LIMIT 1').fetchone()
    if pending:
        # Recovery after DB commit and before mailbox materialization.
        atomic(Path(mailbox)/'requests'/f'{pending[0]}.json',json.loads(pending[1]));return pending[0],pending[2]
    trigger=db.execute('SELECT COALESCE(MAX(batch),0) FROM closed').fetchone()[0]
    if db.execute('SELECT 1 FROM requests WHERE trigger_batch=?',(trigger,)).fetchone():return None
    ps=parents(db)
    if not ps:return None
    duplicates=[]
    for body, in db.execute("SELECT body FROM proposal_receipts WHERE json_extract(body,'$.status')='duplicate_gene' ORDER BY id DESC LIMIT 2"):
        duplicates.append(json.loads(body)['proposal']['genes'])
    payload={'scope':'prior_train_validation_only','cutoff':load()['feedback_cutoff'],'parents':ps,
        'coverage':{'completed':db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],
                    'remaining_K':remaining(db),'rejected_duplicates':db.execute("SELECT COUNT(*) FROM proposal_receipts WHERE json_extract(body,'$.status') LIKE 'duplicate_%'").fetchone()[0]},
        'duplicate_genes':duplicates}
    wire_body(payload);rid=digest(payload)
    if db.execute('SELECT 1 FROM requests WHERE id=?',(rid,)).fetchone():return None
    body={'id':rid,'payload':payload,'created_utc':utc()}
    with db:
        db.execute('INSERT INTO requests VALUES(?,?,?,?)',(rid,trigger,canonical(body),body['created_utc']))
        event(db,'AI_feedback_request_queued',request=rid,trigger_batch=trigger,parents=[p['id'] for p in ps],cutoff=payload['cutoff'])
    atomic(Path(mailbox)/'requests'/f'{rid}.json',body);return rid,body['created_utc']


def local_proposals(db,number):
    space=spaces()[0];keys=list(space);seen={x[0] for x in db.execute('SELECT id FROM genes')};ps=parents(db)
    if not ps:return []
    options=[]
    for parent in ps:
        for key in keys:
            for value in space[key]:
                g={**parent['genes'],key:value}
                if digest(g) not in seen:
                    options.append((g,parent,'LOCAL_NEIGHBOR'));seen.add(digest(g))
                    if len(options)>=number:break
            if len(options)>=number:break
        if len(options)>=number:break
    if len(options)<number:
        for values in itertools.product(*(space[k] for k in keys)):
            g={'family':'K',**dict(zip(keys,values))}
            if digest(g) in seen:continue
            options.append((g,ps[0],'LOCAL_ENUMERATION'));seen.add(digest(g))
            if len(options)>=number:break
    accepted=[]
    for g,p,source in options:
        out=register(db,{'parent':p['id'],'genes':g,'rule':p['rule'],
            'mechanism':'Local exploration of an untried K configuration around prior train/validation evidence; not AI authored.',
            'falsification':'Weak validation growth, excessive drawdown or invalid held prices refute this configuration.'},source)
        if out:accepted.append(out)
    return accepted


def freeze_next(db,mailbox,now=None):
    row=db.execute('SELECT id,body FROM batches WHERE id NOT IN (SELECT batch FROM closed) ORDER BY id LIMIT 1').fetchone()
    if row:return row[0],json.loads(row[1]),None
    pending=ensure_request(db,mailbox)
    ready=db.execute('SELECT COUNT(*) FROM proposals WHERE id NOT IN (SELECT proposal FROM members)').fetchone()[0]
    status_path=Path(mailbox)/'status.json';status=json.loads(status_path.read_text())['state'] if status_path.exists() else ''
    if pending and not ready and (instant(now)-instant(pending[1])).total_seconds()<load()['scheduler']['ai_grace_seconds'] and status not in ('WAIT_DAILY_API_BUDGET','WAIT_MONTHLY_API_BUDGET','WAIT_VERIFIED_TARIFF','WAIT_PROVIDER_USAGE_VIOLATION'):
        return None,None,'WAIT_AI_RESPONSE'
    if ready<load()['scheduler']['batch_size']:local_proposals(db,load()['scheduler']['batch_size']-ready)
    entries=[json.loads(r[0]) for r in db.execute("SELECT body FROM proposals WHERE id NOT IN (SELECT proposal FROM members) ORDER BY CASE WHEN origin='AI_AUTHORED' THEN 0 ELSE 1 END,utc,id LIMIT ?",(load()['scheduler']['batch_size'],))]
    if not entries:return None,None,'IDLE_NO_AUTHORIZED_NOVEL_WORK'
    number=db.execute('SELECT COALESCE(MAX(id),0)+1 FROM batches').fetchone()[0]
    prior=[json.loads(r[0])['training_view'] for r in db.execute('SELECT body FROM feedback WHERE batch=? ORDER BY candidate',(number-1,))]
    c=load();debt=c['legacy_alpha_index']+db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0]
    from research.discovery_evolution.statistics import design
    d=design({'statistics':c['statistics'],'test':c['diagnostic'],'legacy_alpha_debt':debt,'budgets':{'pool_max':len(entries)}})
    d['required_blocks_for_alpha_resolution']=__import__('math').ceil(-__import__('math').log2(d['worst_planned_alpha']))
    body={'id':number,'entries':entries,'contract':digest(c),'training':c['training'],'validation':c['validation'],'diagnostic':c['diagnostic'],
        'statistics':c['statistics'],'design':d,'first_alpha_index':debt+1,'last_alpha_index':debt+len(entries),
        'prior_training_feedback_hashes':[digest(p) for p in prior],'selection_scope':'TRAIN_VALIDATION_ONLY',
        'frequency_method':c['hypotheses']['frequency'],'frequency_refs':{p['id']:frequency_key(p['rule']) for p in entries},
        'contamination':c['history_status'],'frozen_utc':utc(),'orders_allowed':False,'confirmed_trading_candidate':False}
    with db:
        db.execute('INSERT INTO batches VALUES(?,?,?)',(number,canonical(body),utc()))
        db.executemany('INSERT INTO members VALUES(?,?,?)',((p['id'],number,i) for i,p in enumerate(entries)))
        event(db,'batch_frozen',batch=number,hash=digest(body),parents=body['prior_training_feedback_hashes'],origins=[p['origin'] for p in entries])
    return number,body,None
