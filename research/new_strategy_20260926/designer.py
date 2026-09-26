"""DeepSeek is an untrusted JSON proposer, with no tools or file access."""
import itertools,json,os,random
from urllib.request import Request,urlopen
from common import SPEC,validate,canonical,candidate_id

def strict_response(text,family):
    def pairs(values):
        d={}
        for k,v in values:
            if k in d:raise ValueError('Duplicate JSON key')
            d[k]=v
        return d
    x=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(x,dict) or set(x)!={'candidates'} or not isinstance(x['candidates'],list) or len(x['candidates'])!=4:raise ValueError('Expected exactly four candidates')
    return [validate(z,family) for z in x['candidates']]

def grid(family):
    s=SPEC['experiment_schema'][family];keys=list(s)
    return [dict(family=family,**dict(zip(keys,v))) for v in itertools.product(*(s[k] for k in keys))]

def initial(family,seed):
    all_=grid(family);rng=random.Random(seed);rng.shuffle(all_)
    # Explicit simple baselines guarantee all four momentum horizons are tested.
    if family=='A':fixed=[dict(family='A',slow=200,fast=50,confirm=10,breadth=b,cadence='weekly') for b in [0.,.4,.6]]
    elif family=='B':fixed=[dict(family='B',lookback=n,vol_adjusted=v,cadence='monthly',absolute=True,blend=False) for n in [30,90,180,365] for v in [False,True]]
    else:fixed=[dict(family='C',slow=200,confirm=10,entry='ema',entry_bars=24,exit_bars=24)]
    result=[]
    for x in fixed+all_:
        if x not in result:result.append(x)
        if len(result)==10:return result

def neighbors(cfg):
    out=[];schema=SPEC['experiment_schema'][cfg['family']]
    for key,values in schema.items():
        i=values.index(cfg[key])
        for j in [i-1,i+1]:
            if 0<=j<len(values):x=dict(cfg);x[key]=values[j];out.append(validate(x))
    return sorted(out,key=candidate_id)

class Designer:
    def __init__(self):self.calls=0;self.log=[]
    def propose(self,family,development,survivors,seen,seed):
        # Whitelist fields: no arbitrary report or raw object can be transmitted.
        safe=[]
        for r in development:
            if r.get('scope')!='development':raise ValueError('OOS/sealed designer input forbidden')
            safe.append({k:r[k] for k in ['candidate','status','cagr','mdd','sharpe','turnover'] if k in r})
        event=dict(family=family,seed=seed,input_scope='development',mode='deterministic',api_called=False)
        proposed=[];key=os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('MRV1_DEEPSEEK_API_KEY')
        if key and self.calls<SPEC['deepseek']['max_calls']:
            self.calls+=1;event['api_called']=True
            payload={'model':SPEC['deepseek']['model'],'max_tokens':1000,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':'Propose exactly four trading parameter mutations as JSON {"candidates":[...]}. Use only the given family/schema. No code, tools, data, metric, evaluator or contract changes. You see development metrics only.'},{'role':'user','content':canonical(dict(family=family,schema=SPEC['experiment_schema'][family],development=safe))}]}
            event['input']=json.loads(payload['messages'][1]['content'])
            try:
                req=Request(SPEC['deepseek']['endpoint'],data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
                with urlopen(req,timeout=25) as response:raw=json.load(response)
                content=raw['choices'][0]['message']['content'];proposed=strict_response(content,family)
                event.update(mode='deepseek_validated',response=content,usage=raw.get('usage'))
            except Exception as exc:event['failure_type']=type(exc).__name__
        else:event['reason']='No API key available' if not key else 'Frozen API budget exhausted'
        rng=random.Random(seed);local=[n for p in survivors for n in neighbors(p)];rng.shuffle(local);all_=grid(family);rng.shuffle(all_)
        result=[]
        for x in proposed+local+all_:
            if candidate_id(x) not in seen and x not in result:result.append(x)
            if len(result)==4:break
        if len(result)!=4:raise ValueError('Candidate space exhausted')
        event['accepted']=[candidate_id(x) for x in result];self.log.append(event)
        return result
