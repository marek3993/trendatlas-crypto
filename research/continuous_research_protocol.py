"""Prospective, separately frozen AI wire adapter. The v1 runtime stays byte-identical."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.continuous_research import schema,planner,broker,runtime,ledger
from research.continuous_research.common import canonical,digest

BASE_WIRE=schema.wire_body
KEY='protocol_v2'
FILES=('research/continuous_research_protocol.py','scripts/deploy_continuous_research_protocol.py',
       'source_of_truth/continuous_research_protocol_v2.json','tests/test_continuous_research_protocol.py')


def wire_body(payload,legacy_ids=()):
    body=BASE_WIRE(payload)
    if digest(payload) in legacy_ids:return body
    value=json.loads(body['messages'][1]['content'])
    parent=value['parents'][0]
    example={'evaluation':'Compare the supplied training and validation metrics here; this is development evidence.',
             'proposals':[{'parent':parent['id'],'rule':parent['rule'],'genes':parent['genes'],
               'mechanism':'A short testable reason for YOUR new enum-valid parameter combination.',
               'falsification':'A short train/validation observation that would refute your proposed configuration.'}]}
    body['messages'][0]['content'] += (
        ' REQUIRED JSON OUTPUT EXAMPLE (shape only; do not copy its genes): '+canonical(example)+
        ' The top-level keys MUST be evaluation and proposals, never type. evaluation is REQUIRED, 1-600 characters. '
        'Use 1-2 proposals. mechanism max 300 characters; falsification max 220. '
        'Copy enum VALUES exactly from K_schema and rule_schema, including the rule action; do not invent intermediate numbers. '
        'Return the entire JSON object only. No markdown.')
    value['output_instruction']='Return {"evaluation":"your compact critique","proposals":[your new proposal objects]}. All enum and character constraints are mandatory.'
    body['messages'][1]['content']=canonical(value)
    if len(canonical(body).encode())+256>schema.load()['api']['input_tokens_per_request']:
        raise ValueError('wire_token_bound')
    return body


def fingerprint(base):
    base=Path(base)
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in FILES}


def verify_manifest(base,manifest):
    if manifest['files']!=fingerprint(base):raise ValueError('protocol_code_changed')
    c=json.loads((Path(base)/'source_of_truth/continuous_research_protocol_v2.json').read_text())
    if manifest['contract']!=digest(c) or any(c[k] for k in ('scientific_changes','orders_allowed','sealed_access')):
        raise ValueError('protocol_contract_changed')
    old=Path(base)/'research/continuous_research'
    actual={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(old.glob('*.py'))}
    if actual!=manifest['ancestor_binding']['code']:raise ValueError('ancestor_code_changed')
    if digest(schema.load())!=manifest['ancestor_binding']['contract']:raise ValueError('ancestor_contract_changed')


def verify_ledger(path,manifest):
    db=sqlite3.connect('file:'+Path(path).as_posix()+'?mode=ro',uri=True)
    try:
        row=db.execute('SELECT body FROM meta WHERE key=?',(KEY,)).fetchone()
        if not row or json.loads(row[0])!=digest(manifest):raise ValueError('protocol_not_frozen')
    finally:db.close()


def install(manifest):
    # Explicit compatibility adapter at the three v1 wire-consumer entry points.
    # No parser, planner, evaluator, source binding or scientific threshold changes.
    def bound(payload):return wire_body(payload,manifest['legacy_request_ids'])
    schema.wire_body=bound;planner.wire_body=bound;broker.wire_body=bound


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('worker','broker','audit'))
    p.add_argument('--root',type=Path);p.add_argument('--mailbox',type=Path,required=True)
    p.add_argument('--inputs',type=Path);p.add_argument('--bootstrap',type=Path)
    a=p.parse_args();base=Path(__file__).resolve().parents[1]
    manifest=json.loads((base/'protocol-freeze.json').read_text());verify_manifest(base,manifest)
    verify_ledger((a.mailbox/'api.sqlite') if a.mode=='broker' else (a.root/'research.sqlite'),manifest)
    install(manifest)
    if a.mode=='broker':value={'state':broker.once(a.mailbox)}
    else:value=runtime.audit(a.root,a.mailbox) if a.mode=='audit' else runtime.run(a.root,a.mailbox,a.inputs,a.bootstrap)
    print(canonical(value))


if __name__=='__main__':main()
