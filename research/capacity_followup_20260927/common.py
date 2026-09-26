from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PARENT=ROOT/'research/new_strategy_20260926'
SPEC=json.loads((HERE/'contract.json').read_text())
def sha(data):return hashlib.sha256(data).hexdigest()
def digest(path):return sha(Path(path).read_bytes())
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def validate(x):
    if not isinstance(x,dict) or set(x)!=set(SPEC['schema']):raise ValueError('Unexpected/missing configuration keys')
    for k,values in SPEC['schema'].items():
        if not any(type(x[k]) is type(v) and x[k]==v for v in values):raise ValueError('Invalid type/enum '+k)
    y=dict(x)
    if y['blend']:y['lookback']=90
    return y
def cid(x):return 'B_'+sha(canonical(validate(x)).encode())[:12]
def log(path,x):
    with Path(path).open('a',encoding='utf-8') as f:f.write(canonical(x)+'\n')
