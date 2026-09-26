"""Bounded DeepSeek parameter proposer; no tools, files, OOS or code output."""
import datetime,itertools,json,os,random,urllib.request,urllib.error
from common import SPEC,validate,cid,canonical

def api_key():
    for name in ['DEEPSEEK_API_KEY','MRV1_DEEPSEEK_API_KEY']:
        value=os.environ.get(name)
        if value:return value,'process:'+name
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            for name in ['DEEPSEEK_API_KEY','MRV1_DEEPSEEK_API_KEY']:
                try:
                    value=winreg.QueryValueEx(key,name)[0]
                    if value:return value,'user_environment:'+name
                except FileNotFoundError:pass
    return None,'unavailable'

def strict_json(text):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate JSON key')
            out[k]=v
        return out
    x=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(x,dict) or set(x)!={'candidates'} or not isinstance(x['candidates'],list) or len(x['candidates'])!=4:raise ValueError('Expected exactly four candidate objects')
    return x['candidates']

def grid():
    schema=SPEC['schema'];seen={}
    for values in itertools.product(*schema.values()):
        c=validate(dict(zip(schema,values)));seen[cid(c)]=c
    return [seen[k] for k in sorted(seen)]

def initial():
    out=[dict(lookback=90,vol_adjusted=True,cadence=c,absolute=True,blend=False,top_k=k) for c in ['weekly','monthly'] for k in [1,2,3]]
    out += [dict(lookback=n,vol_adjusted=False,cadence='monthly',absolute=True,blend=False,top_k=1) for n in [30,180,365]]
    out += [dict(lookback=90,vol_adjusted=True,cadence='monthly',absolute=False,blend=False,top_k=3)]
    return out

def panel():
    return [dict(lookback=90,vol_adjusted=v,cadence=c,absolute=a,blend=False,top_k=k) for k,v,a,c in itertools.product([1,2,3],[False,True],[False,True],['weekly','monthly'])]

def neighbors(c):
    result={}
    for key,values in SPEC['schema'].items():
        i=values.index(c[key])
        for j in [i-1,i+1]:
            if 0<=j<len(values):
                new=validate(dict(c,**{key:values[j]}))
                if cid(new)!=cid(c):result[cid(new)]=new
    return [result[k] for k in sorted(result)]

def tariff(usage,when):
    peak=when.weekday()<5 and (1<=when.hour<4 or 6<=when.hour<10)
    factor=1. if peak else .5;prices=SPEC['deepseek']['usd_per_million_peak']
    hit=int(usage.get('prompt_cache_hit_tokens',0));miss=int(usage.get('prompt_cache_miss_tokens',max(0,usage.get('prompt_tokens',0)-hit)));out=int(usage.get('completion_tokens',0))
    return dict(cache_hit_tokens=hit,cache_miss_tokens=miss,output_tokens=out,total_tokens=hit+miss+out,estimated_usd=factor*(hit*prices['cache_hit']+miss*prices['cache_miss']+out*prices['output'])/1e6,tariff='peak_conservative_holiday' if peak else 'off_peak')

class Designer:
    def __init__(self,replay=None):self.calls=0;self.events=[];self.estimated_usd=0.;self.reserved_usd=0.;self.replay=replay
    def propose(self,arm,development,survivors,seen,seed):
        safe=[]
        for row in development:
            if row.get('scope')!='development':raise ValueError('OOS/sealed designer boundary')
            safe.append({k:row[k] for k in ['candidate','status','cagr','mdd','sharpe','calmar','turnover','costs','double_cost_cagr','delayed_cagr','benchmark_pass'] if k in row})
        event=dict(arm=arm,seed=seed,input_scope='development',api_called=False,accepted_proposals=[],rejected_proposals=[],mode='deterministic')
        proposals=[];key,source=api_key();spec=SPEC['deepseek']
        if arm=='deepseek' and self.replay is not None:
            saved=next(e for e in self.replay if e['arm']==arm and e['seed']==seed)
            if 'payload' in saved:
                supplied=json.loads(saved['payload']['messages'][1]['content']);assert supplied['development']==safe and supplied['schema']==SPEC['schema'] and supplied['seen_candidate_ids']==sorted(seen),'Recorded proposer input mismatch'
            for candidate in saved['accepted_proposals']:
                c=validate(candidate)
                if cid(c) in seen:raise ValueError('Recorded proposal already evaluated')
                proposals.append(c)
            event.update(mode='recorded_proposals_offline',accepted_proposals=proposals,rejected_proposals=saved['rejected_proposals'])
        elif arm=='deepseek' and key and self.calls<spec['max_calls']:
            system='Return only JSON {"candidates":[four parameter objects]}. Use exactly the provided keys and enum values. No family field. Propose unseen mutations. You see development results only. No tools, code, evaluator, data, metric or contract changes.'
            payload=dict(model=spec['model'],thinking={'type':'disabled'},max_tokens=spec['max_output_tokens'],response_format={'type':'json_object'},messages=[{'role':'system','content':system},{'role':'user','content':canonical(dict(schema=SPEC['schema'],development=safe,seen_candidate_ids=sorted(seen)))}])
            body=canonical(payload).encode();reserve=(len(body)*.30+spec['max_output_tokens']*1.20)/1e6
            if len(body)>spec['max_payload_characters'] or self.reserved_usd+reserve>spec['max_estimated_usd']:event['rejected_proposals'].append(dict(reason='Frozen payload/cost budget'))
            else:
                self.calls+=1;self.reserved_usd+=reserve;event.update(api_called=True,key_source=source,request_index=self.calls,payload=payload)
                when=datetime.datetime.now(datetime.timezone.utc);event['requested_utc']=when.isoformat()
                try:
                    req=urllib.request.Request(spec['endpoint'],data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
                    with urllib.request.urlopen(req,timeout=45) as response:raw=json.load(response)
                    event['response_model']=raw.get('model');event['usage']=raw.get('usage',{});event['billing']=tariff(event['usage'],when);self.estimated_usd+=event['billing']['estimated_usd']
                    content=raw['choices'][0]['message']['content'];event['response']=content;event['finish_reason']=raw['choices'][0].get('finish_reason')
                    for candidate in strict_json(content):
                        try:
                            c=validate(candidate)
                            if cid(c) in seen or c in proposals:raise ValueError('Duplicate/already evaluated configuration')
                            proposals.append(c);event['accepted_proposals'].append(c)
                        except (ValueError,TypeError) as exc:event['rejected_proposals'].append(dict(candidate=candidate,reason=str(exc)))
                    event['mode']='deepseek_validated' if proposals else 'deepseek_no_accepted_proposal'
                except Exception as exc:
                    event['rejected_proposals'].append(dict(reason=type(exc).__name__,http_status=getattr(exc,'code',None)))
                    event['mode']='api_failure_deterministic_fallback'
        elif arm=='deepseek':event['mode']='NO_API_KEY_DETERMINISTIC_FALLBACK' if not key else 'API_BUDGET_FALLBACK'
        rng=random.Random(seed);local=[x for parent in survivors for x in neighbors(parent)];rng.shuffle(local);all_=grid();rng.shuffle(all_)
        result=[]
        for c in proposals+local+all_:
            if cid(c) not in seen and c not in result:result.append(c)
            if len(result)==4:break
        if len(result)!=4:raise ValueError('Parameter space exhausted')
        event['accepted_final']=[dict(candidate=c,source='deepseek' if c in proposals else 'deterministic') for c in result];self.events.append(event)
        return result
