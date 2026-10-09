"""Finite data-only proposal grammar. Narrative never changes executable logic."""
import json
from pathlib import Path
from .common import canonical,digest
from .contract import load

BASE=Path(__file__).resolve().parents[2]/'source_of_truth'


def spaces():
    genes=json.loads((BASE/'phase2_development_contract.json').read_text())['gene_space']['K']
    rules=json.loads((BASE/'anomaly_lab_contract.json').read_text())
    return genes,{k:{'threshold':v['threshold'],'action':v['action']} for k,v in rules['families'].items()},rules['horizons']


def choice(value,values):
    if type(value) not in (int,float):raise ValueError('numeric_enum_required')
    for x in values:
        if value==x:return x
    raise ValueError('enum_value')


def genes(value):
    space,_,_=spaces()
    if not isinstance(value,dict) or set(value)!={'family',*space} or value['family']!='K':raise ValueError('K_schema')
    return {'family':'K',**{k:choice(value[k],v) for k,v in space.items()}}


def rule(value):
    _,rules,horizons=spaces()
    if not isinstance(value,dict) or set(value)!={'family','threshold','horizon','action'} or value['family'] not in rules:raise ValueError('rule_schema')
    entry=rules[value['family']]
    if value['action']!=entry['action']:raise ValueError('rule_action')
    return {'family':value['family'],'threshold':choice(value['threshold'],entry['threshold']),
            'horizon':choice(value['horizon'],horizons),'action':value['action']}


def proposal(value,parents=None):
    if not isinstance(value,dict) or set(value)!={'parent','rule','genes','mechanism','falsification'}:raise ValueError('proposal_shape')
    if value['parent'] is not None and (not isinstance(value['parent'],str) or (parents is not None and value['parent'] not in parents)):raise ValueError('unknown_parent')
    for k,limit in [('mechanism',300),('falsification',220)]:
        if not isinstance(value[k],str) or not 8<=len(value[k])<=limit:raise ValueError('narrative_bound')
    return {**value,'rule':rule(value['rule']),'genes':genes(value['genes'])}


def identity(value):return digest({'rule':rule(value['rule']),'genes':genes(value['genes'])})


SYSTEM=('Return JSON with exactly evaluation (brief critique string) and proposals (at most two objects). '
        'Each proposal has exactly parent (supplied id or null), rule (family,threshold,horizon,action), '
        'genes (family K and ALL its enum parameters), mechanism (8-300 chars), falsification (8-220 chars). '
        'Use supplied prior train/validation metrics and frequency; propose your own new K combinations, not copies of parents or duplicates. '
        'Only the supplied finite enums are legal. Explain a testable mechanism and how it can fail. No code or new data. '
        'These are configurations of known mechanisms, not proven market discoveries. History is already seen development. '
        'Diagnostic tests are not supplied for selection. Dates from 2026-09-27 and forward 2027 are sealed. '
        'No trading permission or confirmed candidate. LUNA identity/price gaps cannot be repaired by invented exits.')


def wire_body(payload):
    c=load();space,rules,horizons=spaces()
    if set(payload)!={'scope','cutoff','parents','coverage','duplicate_genes'} or payload['scope']!='prior_train_validation_only' or payload['cutoff']!=c['feedback_cutoff']:
        raise ValueError('payload_scope')
    parents=[]
    for p in payload['parents'][:2]:
        if p['cutoff']>c['feedback_cutoff']:raise ValueError('future_feedback')
        out={'id':p['id'],'genes':genes(p['genes']),'rule':rule(p['rule']),'cutoff':p['cutoff'],'frequency_episodes':p.get('frequency_episodes')}
        for phase in ('training','validation'):
            part=p.get(phase)
            if part:
                if part['interval'][1]>c['feedback_cutoff']:raise ValueError('future_metrics')
                m=part.get('metrics') or {}
                out[phase]={'valid':bool(part['valid']),'interval':part['interval'],
                            'metrics':{k:m.get(k) for k in ('cagr','mdd','log_growth','cost_drag','asset_concentration')}}
            else:out[phase]=None
        parents.append(out)
    coverage={k:int(payload['coverage'][k]) for k in ('completed','remaining_K','rejected_duplicates')}
    value={'scope':payload['scope'],'cutoff':payload['cutoff'],'parents':parents,'coverage':coverage,
           'duplicate_genes':[genes(g) for g in payload['duplicate_genes'][:2]],'K_schema':space,
           'rule_schema':rules,'horizons':horizons,'requested':2}
    body={'model':c['api']['model'],'thinking':{'type':'disabled'},'max_tokens':c['api']['output_tokens_per_request'],
          'response_format':{'type':'json_object'},'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':canonical(value)}]}
    if len(canonical(body).encode())+256>c['api']['input_tokens_per_request']:raise ValueError('wire_token_bound')
    return body
