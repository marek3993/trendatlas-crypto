from pathlib import Path
import hashlib,json,datetime
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
OLD=ROOT/'inputs'
PARENT=ROOT
SPEC=json.loads((HERE/'contract.json').read_text())
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(p):return sha(Path(p).read_bytes())
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False,default=str)+'\n',encoding='utf-8')
def log(p,x):
    with Path(p).open('a',encoding='utf-8') as f:f.write(canonical(x)+'\n')
DEFAULT=dict(family='F',signal='sma200',cadence='weekly',confirm=0,hysteresis=0.0,scope='BTC',top_k=5,weighting='equal',satellite=0.25,satellite_k=1,gross=1.0,recipe='btc_regime')
def validate(c):
    if not isinstance(c,dict) or set(c)!=set(SPEC['schema']):raise ValueError('Unexpected/missing keys')
    for k,vals in SPEC['schema'].items():
        if not any(type(c[k]) is type(v) and c[k]==v for v in vals):raise ValueError('Bad enum/type '+k)
    d=dict(c);f=d['family']
    active={'family','signal','cadence','confirm','hysteresis'}
    active|={'F':{'scope'},'G':{'satellite','satellite_k'},'H':{'top_k','weighting'},'D':{'recipe','gross','top_k','weighting'}}[f]
    if f=='H' and d['top_k']==1:raise ValueError('H top_k must2/3/5')
    if f=='H' and d['weighting']=='equal':raise ValueError('H only inverse_vol/equal_risk; equal-notional is outside user contract')
    if f=='G' and d['signal'] in ['sma50','breakout20','breakout55','mom90']:raise ValueError('G requires slow core')
    if f=='D' and d['recipe']=='btc_regime':active-={'top_k','weighting'}
    for k in set(d)-active:d[k]=DEFAULT[k]
    return d
def config(**kw):return validate(dict(DEFAULT,**kw))
def cid(c):return c['family']+'_'+sha(canonical(validate(c)).encode())[:12]
def neighbors(c):
    out={}
    for k,vals in SPEC['schema'].items():
        if k=='family':continue
        i=vals.index(c[k])
        for j in [i-1,i+1]:
            if 0<=j<len(vals):
                try:d=validate(dict(c,**{k:vals[j]}))
                except ValueError:continue
                if d!=c:out[cid(d)]=d
    return [out[k] for k in sorted(out)]
