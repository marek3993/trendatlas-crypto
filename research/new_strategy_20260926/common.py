from pathlib import Path
import hashlib, json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SPEC=json.loads((HERE/'contract.json').read_text())
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path,x):Path(path).write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def candidate_id(x):return x['family']+'_'+hashlib.sha256(canonical(x).encode()).hexdigest()[:12]
def validate(x,family=None):
    if not isinstance(x,dict) or x.get('family') not in ['A','B','C']:raise ValueError('Unknown family')
    if family and x['family']!=family:raise ValueError('Wrong family')
    schema=SPEC['experiment_schema'][x['family']]
    if set(x)!=set(schema)|{'family'}:raise ValueError('Unexpected/missing candidate keys')
    for k,allowed in schema.items():
        if not any(type(x[k]) is type(v) and x[k]==v for v in allowed):raise ValueError('Invalid type/enum '+k)
    return dict(x)
def protected():
    return {p.relative_to(ROOT).as_posix():(p.stat().st_size,p.stat().st_mtime_ns) for d in ['data','outputs','source_of_truth','canonical','scripts','src','dashboard','execution'] for p in (ROOT/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
