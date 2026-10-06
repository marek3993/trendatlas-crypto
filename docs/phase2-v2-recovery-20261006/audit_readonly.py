import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime,timezone
release=Path('/opt/trendatlas-research/phase2-v2/releases/continuation-25c3e61f95085e6c')
sys.path.insert(0,str(release))
from research.phase2_v2 import runtime as r,continuation as c
root=Path('/var/lib/trendatlas-research-v2')
db=sqlite3.connect('file:'+str(root/'v2.sqlite')+'?mode=ro',uri=True)
db.execute('BEGIN')
report=c.status(db)
report['observed_utc']=datetime.now(timezone.utc).isoformat()
report['sqlite_integrity']=db.execute('PRAGMA quick_check').fetchone()[0]
report['duplicate_evaluations']=db.execute('SELECT count(*)-count(DISTINCT key) FROM evaluations').fetchone()[0]
report['duplicate_genes']=db.execute('SELECT count(*)-count(DISTINCT genes) FROM candidates').fetchone()[0]
prior='GENESIS'
for stamp,kind,body,previous,rowhash in db.execute('SELECT utc,kind,body,previous_hash,row_hash FROM events ORDER BY id'):
    assert previous==prior and r.digest([stamp,kind,body,previous])==rowhash
    prior=rowhash
report['audit_chain_valid']=True
backup=sqlite3.connect('file:'+str(root/'recovery-checkpoint-25c3e61f95085e6c.sqlite')+'?mode=ro',uri=True)
preserved={}
for table in ('candidates','evaluations','selections','test_books','events'):
    before=backup.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
    current={x[0]:x for x in db.execute('SELECT * FROM '+table)}
    preserved[table]=len(before) if all(current.get(x[0])==x for x in before) else False
    assert preserved[table] is not False
report['original_rows_preserved']=preserved
report['same_cycle']=backup.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()==db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()
report['same_evaluator_binding']=backup.execute("SELECT value FROM meta WHERE key='binding'").fetchone()==db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
report['last_checkpoint_events']=[{'utc':t,'kind':k} for t,k in db.execute('SELECT utc,kind FROM events ORDER BY id DESC LIMIT 5')]
report['terminal_tests']=[json.loads(x[0]) for x in db.execute('SELECT receipt FROM terminal_test_failures ORDER BY origin')]
responses=[json.loads(p.read_text()) for p in (root/'mailbox/responses').glob('*.json')]
calls=[x for x in responses if x.get('usage',{}).get('api_call',0)>0]
calls.sort(key=lambda x:x.get('utc',''))
latest=calls[-1]
report['provider_calls']=sum(x['usage'].get('api_call',0) for x in calls)
report['provider_tokens']=sum(x['usage'].get('total_tokens',0) or 0 for x in calls)
report['last_deepseek_response']={k:v for k,v in latest.items() if k not in ('content','payload')}
report['last_broker_response']={k:v for k,v in max(responses,key=lambda x:x.get('utc','')).items() if k not in ('content','payload')}
report['mailbox_unanswered']=sum(not (root/'mailbox/responses'/p.name).exists() for p in (root/'mailbox/requests').glob('*.json'))
print(json.dumps(report,sort_keys=True))
