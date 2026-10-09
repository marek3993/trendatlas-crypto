"""Read-only native evidence collector; no experiment or budget mutations."""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def prepare_observer(root,mailbox):
    """SQLite mode=ro can still create WAL sidecars; preserve the writers' group."""
    groups={(root/'research.sqlite').stat().st_gid,(mailbox/'api.sqlite').stat().st_gid}
    if len(groups)!=1:raise ValueError('ledgers_do_not_share_group')
    group=groups.pop()
    if os.name=='posix':os.setegid(group);os.umask(0o007)
    return group


def collect(release,root,mailbox):
    shared_group=prepare_observer(root,mailbox)
    sys.path.insert(0,str(release))
    from research.continuous_research import runtime,ledger,schema
    from research.continuous_research.common import digest,utc,canonical
    from research.continuous_research.deploy import predecessors
    from research.continuous_research_protocol import verify_manifest,verify_ledger,wire_body
    db=sqlite3.connect('file:'+str(root/'research.sqlite')+'?mode=ro',uri=True)
    api=sqlite3.connect('file:'+str(mailbox/'api.sqlite')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row;api.row_factory=sqlite3.Row;db.execute('BEGIN');api.execute('BEGIN')
    def rows(d,table):
        out=[dict(r) for r in d.execute('SELECT * FROM '+table)]
        for row in out:
            if 'body' in row:row['body']=json.loads(row['body'])
        return out
    snapshot_utc=utc()
    worker={t:rows(db,t) for t in ['batches','closed','proposals','candidates','inbox','discoveries','scientific_attempts',
        'attempts','backtests','statistics','feedback','requests','ingested','proposal_receipts','events']}
    paid={t:rows(api,t) for t in ['tariffs','reservations','results','finals']}
    manifest=json.loads((release/'protocol-freeze.json').read_text());verify_manifest(release,manifest)
    verify_ledger(root/'research.sqlite',manifest);verify_ledger(mailbox/'api.sqlite',manifest)
    actual=runtime.binding(schema.load()['input_directory'],release/'continuous-bootstrap.json')
    assert actual==json.loads(db.execute("SELECT body FROM meta WHERE key='binding'").fetchone()[0])
    legacy={r[0] for r in db.execute("SELECT id FROM genes WHERE source='legacy'")}
    assert not legacy.intersection(p['gene'] for p in worker['proposals'])
    frozen={b['id']:b for b in worker['batches']}
    for row in worker['candidates']:assert frozen[row['batch']]['utc']<=row['utc']
    for row in worker['backtests']:
        receipt=row['body']
        if receipt['valid']:assert hashlib.sha256((root/receipt['book']).read_bytes()).hexdigest()==receipt['book_sha256']
    req={r['id']:r for r in worker['requests']};responses={r['request']:r['body'] for r in paid['finals']}
    wires={}
    for rid,r in req.items():
        body=wire_body(r['body']['payload'],manifest['legacy_request_ids']);bound=len(canonical(body).encode())+256
        assert bound<=6500
        if rid in responses:assert digest(body)==responses[rid]['wire_hash']
        wires[rid]={'upper_input_tokens':bound,'wire_hash':digest(body),'body':body}
    ai=[]
    feedback={r['candidate']:r for r in worker['feedback']}
    for p in worker['proposals']:
        if p['origin']!='AI_AUTHORED':continue
        p=p['body'];reply=responses[p['request']]
        raw=json.loads(reply['content'])['proposals'][p['response_index']]
        assert schema.proposal(raw)=={k:p[k] for k in ('parent','rule','genes','mechanism','falsification')}
        f=feedback.get(p['gene_id']);fh=digest(f['body']['training_view']) if f else None
        ai.append({'proposal':p['id'],'gene':p['gene_id'],'request':p['request'],'provider_id':reply['provider_request_id'],
            'raw_matches_accepted':True,'completed':bool(f),'feedback_hash':fh,
            'successor_batches_using_feedback':[b['id'] for b in worker['batches'] if fh in b['body']['prior_training_feedback_hashes']]})
    interruption=json.loads((root/'interruption-proof.json').read_text());key=interruption['pending_attempt']['key']
    attempt=[r for r in worker['attempts'] if r['key']==key];done=[r for r in worker['backtests'] if r['key']==key]
    assert len(attempt)==len(done)==1 and done[0]['body']['attempt']==attempt[0]['id']==interruption['pending_attempt']['id']
    assert interruption['before']['last_event_hash'] in {r['hash'] for r in worker['events']}
    scientific=[r for r in worker['scientific_attempts'] if r['candidate']==attempt[0]['candidate']]
    assert len(scientific)==1 and scientific[0]['id']==interruption['scientific_attempt']['id']
    deployment=json.loads((root/'deployment.json').read_text());before=deployment['predecessors_before'];after=predecessors();assert before==after
    # Use sqlite's default tuple rows for the unchanged runtime snapshot helper.
    db.row_factory=None;ledger.verify(db);snapshot=runtime.snapshot(db,root,mailbox)
    raw=subprocess.run(['journalctl','-u','trendatlas-continuous-research.service','--since','2026-10-09 18:58:00','-o','json','--no-pager'],capture_output=True,text=True,check=True).stdout
    activations=[]
    for line in raw.splitlines():
        item=json.loads(line)
        try:message=json.loads(item.get('MESSAGE',''))
        except (ValueError,TypeError):continue
        if isinstance(message,dict) and 'unique_candidates_completed' in message:
            activations.append({'invocation_id':item.get('_SYSTEMD_INVOCATION_ID'),'timestamp_microseconds':item['__REALTIME_TIMESTAMP'],
                'state':message['state'],'completed':message['unique_candidates_completed'],'AI_completed':message['AI_candidates_completed'],
                'batches_closed':message['batches_closed'],'last_progress_utc':message['last_progress_utc']})
    value={'observed_utc':utc(),'ledger_snapshot_utc':snapshot_utc,'observer_shared_group':shared_group,'audit':snapshot,'worker':worker,'broker':paid,'wires':wires,'AI_lineage':ai,
        'automatic_activations':activations,'protocol_manifest':manifest,'predecessors_after':after,'deployment':deployment,
        'checks':{'hash_chain':'PASS','book_hashes':'PASS','original_source_binding':'PASS','protocol_binding':'PASS',
            'predecessors_unchanged':True,'global_gene_overlap':0,'freeze_before_evaluation':True,'AI_raw_provenance':'PASS',
            'wire_bounds_and_bindings':'PASS','interrupt_same_attempt_and_alpha':True,'interruption_prefix_retained':True}}
    db.rollback();api.rollback();db.close();api.close();return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True)
    p.add_argument('--root',type=Path,default=Path('/var/lib/trendatlas-continuous-research'))
    p.add_argument('--mailbox',type=Path,default=Path('/var/lib/trendatlas-continuous-mailbox'))
    a=p.parse_args();print(json.dumps(collect(a.release,a.root,a.mailbox),indent=2))
