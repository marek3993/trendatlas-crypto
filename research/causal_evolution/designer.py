"""Separate, allowlisted JSON proposal broker; never imported by the Pi worker."""
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from .protocol import CONTRACT, digest, utc, periods
from .vendor.common import canonical, validate, cid

SAFE_METRICS={'cagr','mdd','sharpe','calmar','turnover','costs_usd','trades',
              'asset_concentration','episode_concentration','reliable','worst_fold'}

def api_key():
    for name in ('DEEPSEEK_API_KEY','MRV1_DEEPSEEK_API_KEY'):
        if os.environ.get(name):return os.environ[name]
    directory=os.environ.get('CREDENTIALS_DIRECTORY')
    if directory:
        p=Path(directory)/'deepseek-key'
        if p.is_file():return p.read_text().strip()
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            for name in ('DEEPSEEK_API_KEY','MRV1_DEEPSEEK_API_KEY'):
                try:
                    value=winreg.QueryValueEx(key,name)[0]
                    if value:return value
                except FileNotFoundError:pass
    return None

def payload(run,generation,rows,seen):
    safe=[]
    for row in rows:
        folds=[]
        for fold in row['folds']:
            if fold['scope'] not in CONTRACT['deepseek']['allowed_scopes']:raise ValueError('Outer/forward prompt boundary')
            folds.append(dict(scope=fold['scope'],fold=fold['fold'],start=fold['start'],end=fold['end'],
                              metrics={k:v for k,v in fold['metrics'].items() if k in SAFE_METRICS}))
        safe.append(dict(id=row['id'],genes=row['genes'],folds=folds))
    return dict(run=run,generation=generation,schema=CONTRACT['schema'],parents=safe,seen=sorted(seen))

def validate_payload(p):
    if not isinstance(p,dict) or set(p)!={'run','generation','schema','parents','seen'}:raise ValueError('Unexpected payload keys')
    if p['schema']!=CONTRACT['schema']:raise ValueError('Schema changed')
    if not isinstance(p['generation'],int) or not 1<=p['generation']<5:raise ValueError('Generation')
    if len(p['parents'])!=6:raise ValueError('Six parents required')
    origin=int(p['run'].split(':')[0])
    permitted=[x for x in periods(origin) if x['scope']!='outer']
    for row in p['parents']:
        if set(row)!={'id','genes','folds'} or cid(validate(row['genes']))!=row['id']:raise ValueError('Parent identity')
        for fold in row['folds']:
            if set(fold)!={'scope','fold','start','end','metrics'}:raise ValueError('Unexpected fold metadata')
            if fold['scope'] not in CONTRACT['deepseek']['allowed_scopes']:raise ValueError('Outer or forward input')
            if {k:fold[k] for k in ('scope','fold','start','end')} not in permitted:raise ValueError('Date/scope boundary mismatch')
            if not set(fold['metrics'])<=SAFE_METRICS:raise ValueError('Unapproved metric')
    if len(canonical(p))>40000:raise ValueError('Payload byte budget')

def strict_json(text):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate JSON key')
            out[k]=v
        return out
    def bad(_):raise ValueError('Nonfinite JSON')
    x=json.loads(text,object_pairs_hook=pairs,parse_constant=bad)
    if not isinstance(x,dict) or set(x)!={'candidates'} or not isinstance(x['candidates'],list) or len(x['candidates'])!=4:
        raise ValueError('Exactly four candidates required')
    return x['candidates']

def validate_response(text,p):
    validate_payload(p);accepted=[];rejected=[];seen=set(p['seen']);parents={r['id']:r['genes'] for r in p['parents']}
    try:rows=strict_json(text)
    except (ValueError,TypeError) as e:return [],[dict(reason=str(e))]
    for raw in rows:
        try:
            if not isinstance(raw,dict) or set(raw)!={'parent','genes','hypothesis'}:raise ValueError('Proposal keys')
            if raw['parent'] not in parents:raise ValueError('Unknown parent')
            if not isinstance(raw['hypothesis'],str) or not 1<=len(raw['hypothesis'])<=600:raise ValueError('Hypothesis length')
            genes=validate(raw['genes'])
            if genes!=raw['genes']:raise ValueError('Noncanonical inactive genes')
            if genes['family']!=parents[raw['parent']]['family']:raise ValueError('Island escape')
            if cid(genes) in seen:raise ValueError('Duplicate/already tried')
            seen.add(cid(genes));accepted.append(dict(raw,genes=genes))
        except (ValueError,TypeError,KeyError) as e:rejected.append(dict(proposal=raw,reason=str(e)))
    return accepted,rejected

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('API redirect forbidden')

def billing(usage):
    # Peak rate is a reproducible conservative upper estimate, not an invoice claim.
    hit=int(usage.get('prompt_cache_hit_tokens',0));miss=int(usage.get('prompt_cache_miss_tokens',max(0,usage.get('prompt_tokens',0)-hit)));out=int(usage.get('completion_tokens',0))
    return dict(api_call=1,cache_hit_tokens=hit,cache_miss_tokens=miss,output_tokens=out,
                total_tokens=hit+miss+out,usd=(hit*.006+miss*.30+out*1.20)/1e6,
                tariff='documented_peak_upper_estimate_20260927')

def broker_once(store,forced_no_key=False):
    """Exact queued payload only. No data/evaluation queries, no process tools."""
    if (store.root/'SEALED.json').exists():return False
    row=store.db.execute("SELECT * FROM proposals WHERE state='QUEUED' ORDER BY created LIMIT 1").fetchone()
    if not row:return False
    p=json.loads(row['payload']);validate_payload(p)
    key=None if forced_no_key else api_key();used=list(store.db.execute('SELECT usage FROM proposals WHERE usage IS NOT NULL'))
    calls=sum(json.loads(r[0]).get('api_call',0) for r in used);reserved=sum(json.loads(r[0]).get('reserved_usd',0) for r in used)
    body=dict(model=CONTRACT['deepseek']['model'],thinking={'type':'disabled'},max_tokens=CONTRACT['deepseek']['max_output_tokens'],response_format={'type':'json_object'},
              messages=[dict(role='system',content='Return ONLY JSON {"candidates":[exactly four objects with parent, genes, hypothesis]}. Mutate supplied parents within their island. Complete canonical enum genes, no inactive-gene changes. Never write code, tools, data, evaluator or metric changes. You see only development/inner-validation. Propose unseen IDs. F scope only; G satellite fields only; H top_k2/3/5 and inverse_vol/equal_risk; D recipe/gross/top_k/weighting. Shared signal/cadence/confirm/hysteresis allowed. G forbids sma50/breakout20/breakout55/mom90.'),dict(role='user',content=canonical(p))])
    encoded=canonical(body).encode();reserve=(len(encoded)*.30+CONTRACT['deepseek']['max_output_tokens']*1.20)/1e6
    reason=None
    if not key:reason='NO_API_KEY_AI_EVOLUTION_NOT_RUN'
    if calls>=CONTRACT['budget']['max_api_calls'] or reserved+reserve>CONTRACT['budget']['api_usd_ceiling']:reason='FROZEN_API_BUDGET'
    if reason:
        with store.db:store.db.execute('UPDATE proposals SET state=?,validation=?,usage=? WHERE id=?',('FALLBACK',canonical(dict(accepted=[],rejected=[dict(reason=reason)])),canonical(dict(api_call=0,usd=0)),row['id']))
        return True
    # Reservation committed BEFORE I/O. Uncertain crashes are not automatically retried.
    usage=dict(api_call=1,reserved_usd=reserve,usd=0,total_tokens=0,uncertain=True)
    with store.db:store.db.execute('UPDATE proposals SET state=?,usage=? WHERE id=?',('INFLIGHT',canonical(usage),row['id']))
    try:
        request=urllib.request.Request(CONTRACT['deepseek']['endpoint'],data=encoded,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=45) as response:
            raw=response.read(250000)
        reply=json.loads(raw);content=reply['choices'][0]['message']['content'];usage.update(billing(reply.get('usage',{})),uncertain=False,response_model=reply.get('model'))
        accepted,rejected=validate_response(content,p);state='COMPLETE';response_content=dict(request=body,content=content,finish_reason=reply['choices'][0].get('finish_reason'))
    except Exception as e:
        accepted=[];rejected=[dict(reason=type(e).__name__,http_status=getattr(e,'code',None))];state='FALLBACK';response_content=None
    with store.db:store.db.execute('UPDATE proposals SET state=?,response=?,validation=?,usage=? WHERE id=?',
        (state,canonical(response_content),canonical(dict(accepted=accepted,rejected=rejected)),canonical(usage),row['id']))
    return True
