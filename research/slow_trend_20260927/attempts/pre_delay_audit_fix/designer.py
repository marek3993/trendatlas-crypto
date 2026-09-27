"""A parameter proposer has no evaluator, filesystem or OOS capability."""
import importlib.util,json,random,urllib.request,datetime
from common import OLD,SPEC,validate,cid,canonical,neighbors,now
spec=importlib.util.spec_from_file_location('ancestor_designer_utilities',OLD/'designer.py');util=importlib.util.module_from_spec(spec);spec.loader.exec_module(util)
def safe_rows(rows):
    safe=[]
    for r in rows:
        if r.get('scope')!='development':raise ValueError('Only development may enter proposer')
        safe.append({k:r[k] for k in ['candidate','reliable','cagr','mdd','sharpe','calmar','turnover']})
    return safe
class Designer:
    def __init__(self,replay=None,continue_proposals=False):self.events=[];self.calls=0;self.cost=0.;self.reserved=0.;self.replay=replay;self.continue_proposals=continue_proposals
    def propose(self,family,arm,rows,parents,seen,seed):
        safe=safe_rows(rows);event=dict(family=family,arm=arm,seed=seed,scope='development',api_called=False,accepted=[],rejected=[],utc=now());proposals=[]
        schema=dict(SPEC['schema']);schema['family']=[family]
        if family=='G':schema['signal']=[s for s in schema['signal'] if s not in ['sma50','breakout20','breakout55','mom90']]
        payload=dict(model=SPEC['deepseek']['model'],thinking={'type':'disabled'},max_tokens=2500,response_format={'type':'json_object'},messages=[dict(role='system',content='Return strictly JSON {"candidates":[four complete parameter objects]}. Use only given enum schema. Inactive keys canonicalize to defaults. Propose novel candidates in this family only. No code, tools, evaluator or data changes. Only development results provided.'),dict(role='user',content=canonical(dict(schema=schema,development=safe,seen=sorted(seen))))])
        prior=next((e for e in (self.replay or []) if e['family']==family and e['seed']==seed and e['arm']==arm),None)
        if arm=='deepseek' and self.replay is not None and prior is not None:
            if prior.get('payload'):assert prior['payload']==payload,'Replay development payload mismatch'
            proposals=[validate(c) for c in prior['accepted']];event.update(prior);event.update(mode='recorded_offline',reused_without_new_call=True)
            self.calls+=int(prior['api_called']);self.cost+=prior.get('billing',{}).get('estimated_usd',0.)
            self.reserved+=(len(canonical(payload).encode())*.30+2500*1.20)/1e6 if prior['api_called'] else 0
        elif arm=='deepseek' and self.replay is not None and not self.continue_proposals:
            raise ValueError('Missing recorded proposal event; offline replay never calls API')
        elif arm=='deepseek':
            key,source=util.api_key();body=canonical(payload).encode();reserve=(len(body)*.30+2500*1.20)/1e6
            if not key:event['mode']='NO_API_KEY_DETERMINISTIC_FALLBACK'
            elif self.calls>=12 or self.reserved+reserve>1 or len(body)>48000:event['mode']='FROZEN_BUDGET_FALLBACK'
            else:
                self.calls+=1;self.reserved+=reserve;event.update(api_called=True,key_source=source,payload=payload,mode='api')
                try:
                    req=urllib.request.Request(SPEC['deepseek']['endpoint'],data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
                    with urllib.request.urlopen(req,timeout=45) as response:raw=json.load(response)
                    event['usage']=raw.get('usage',{});event['response_model']=raw.get('model');event['billing']=util.tariff(event['usage'],datetime.datetime.now(datetime.timezone.utc));self.cost+=event['billing']['estimated_usd']
                    event['response']=raw['choices'][0]['message']['content']
                    for c in util.strict_json(event['response']):
                        try:
                            v=validate(c)
                            if v['family']!=family:raise ValueError('Wrong family')
                            if cid(v) in seen or v in proposals:raise ValueError('Duplicate')
                            proposals.append(v);event['accepted'].append(v)
                        except (TypeError,ValueError) as exc:event['rejected'].append(dict(candidate=c,reason=str(exc)))
                except Exception as exc:event['rejected'].append(dict(reason=type(exc).__name__,http_status=getattr(exc,'code',None)))
        rng=random.Random(seed);local=[n for p in parents for n in neighbors(p)];rng.shuffle(local)
        # Bounded deterministic random mutations fill any holes; no result feedback beyond dev parents.
        for _ in range(300):
            c=dict(rng.choice(parents));key=rng.choice([k for k in schema if k!='family']);c[key]=rng.choice(schema[key])
            try:local.append(validate(c))
            except ValueError:pass
        chosen=[]
        for c in proposals+local:
            if cid(c) not in seen and c not in chosen:chosen.append(c)
            if len(chosen)==4:break
        if len(chosen)!=4:raise ValueError('Mutation space exhausted')
        event['selected']=[dict(candidate=c,source='deepseek' if c in proposals else 'deterministic') for c in chosen];self.events.append(event)
        return chosen
