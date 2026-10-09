"""Shared daily/monthly reservations; every retry is a separately charged attempt."""
import json
import os
import re
import sqlite3
import urllib.request
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from .common import canonical,digest,utc,instant,period,atomic,lease
from .contract import load
from .ledger import immutable
from .schema import wire_body


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect_forbidden')


def opener():return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())


class Cells(HTMLParser):
    def __init__(self):super().__init__();self.on=False;self.text='';self.cells=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('th','td'):self.on=True;self.text=''
    def handle_data(self,value):
        if self.on:self.text+=value
    def handle_endtag(self,tag):
        if tag in ('th','td'):self.on=False;self.cells.append(self.text)


def parse_tariff(html):
    p=Cells();p.feed(html);cells=p.cells
    if cells[:2]!=['MODEL','deepseek-flash(1)']:raise ValueError('unrecognized_price_model')
    rates={}
    for key,label in [('hit','1M INPUT TOKENS(CACHE HIT)'),('input','1M INPUT TOKENS(CACHE MISS)'),('output','1M OUTPUT TOKENS')]:
        i=cells.index(label)
        if cells[i+1]!='OFF-PEAK' or cells[i+4]!='PEAK':raise ValueError('price_table_shape')
        amounts=[cells[i+2],cells[i+5]]
        if not all(re.fullmatch(r'\$\d+(?:\.\d+)?',a) for a in amounts):raise ValueError('price_value')
        # USD / million tokens -> integer nano-USD / token, rounding upward.
        rates[key]=int((max(Decimal(a[1:]) for a in amounts)*1000).to_integral_value(rounding='ROUND_CEILING'))
    if min(rates.values())<=0:raise ValueError('invalid_tariff')
    return {'rates_nano_per_token':rates,'source':load()['api']['pricing_source'],'html_sha256':__import__('hashlib').sha256(html.encode()).hexdigest()}


def fetch_tariff():
    with opener().open(load()['api']['pricing_source'],timeout=20) as r:raw=r.read(500001)
    if len(raw)>500000:raise ValueError('price_response_size')
    return parse_tariff(raw.decode('utf-8'))


def connect(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'api.sqlite',timeout=30);db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,body TEXT);
    CREATE TABLE IF NOT EXISTS tariffs(id INTEGER PRIMARY KEY,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS reservations(id INTEGER PRIMARY KEY AUTOINCREMENT,request TEXT,ordinal INTEGER,day TEXT,month TEXT,nanousd INTEGER,body TEXT,utc TEXT,UNIQUE(request,ordinal));
    CREATE TABLE IF NOT EXISTS results(attempt INTEGER PRIMARY KEY,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS finals(request TEXT PRIMARY KEY,wire TEXT,body TEXT,utc TEXT);
    ''');immutable(db,('meta','tariffs','reservations','results','finals'))
    c=load();identity=canonical({'id':c['api']['budget_id'],'policy':c['api']})
    row=db.execute("SELECT body FROM meta WHERE key='identity'").fetchone()
    if row and row[0]!=identity:raise ValueError('shared_budget_changed')
    if not row:db.execute('INSERT INTO meta VALUES(?,?)',('identity',identity))
    db.commit();return db


def budget(db,now=None):
    day,month=period(now);a=load()['api']
    daily=db.execute('SELECT COUNT(*),COALESCE(SUM(nanousd),0) FROM reservations WHERE day=?',(day,)).fetchone()
    monthly=db.execute('SELECT COALESCE(SUM(nanousd),0) FROM reservations WHERE month=?',(month,)).fetchone()[0]
    lifetime=db.execute('SELECT COUNT(*),COALESCE(SUM(nanousd),0) FROM reservations').fetchone()
    return {'day':day,'month':month,'timezone':a['budget_timezone'],'attempts_today':daily[0],
            'attempts_remaining_today':max(0,a['attempts_per_day']-daily[0]),'reserved_usd_today':daily[1]/1e9,
            'remaining_usd_today':max(0,int(a['usd_per_day']*1e9)-daily[1])/1e9,
            'reserved_usd_month':monthly/1e9,'remaining_usd_month':max(0,int(a['usd_per_month']*1e9)-monthly)/1e9,
            'lifetime_new_attempts':lifetime[0],'lifetime_reserved_usd':lifetime[1]/1e9,'accounting':'conservative reservations, not invoice'}


def reserve(db,request,ordinal,tariff,bound,now=None):
    now=now or utc();a=load()['api'];rates=tariff['rates_nano_per_token']
    cost=a['input_tokens_per_request']*rates['input']+a['output_tokens_per_request']*rates['output']
    db.execute('BEGIN IMMEDIATE')
    try:
        existing=db.execute('SELECT id FROM reservations WHERE request=? AND ordinal=?',(request,ordinal)).fetchone()
        if existing:raise ValueError('transport_already_reserved')
        b=budget(db,now)
        reason=('WAIT_DAILY_API_BUDGET' if b['attempts_remaining_today']<1 or round(b['remaining_usd_today']*1e9)<cost else
                'WAIT_MONTHLY_API_BUDGET' if round(b['remaining_usd_month']*1e9)<cost else None)
        if reason:db.rollback();return None,reason
        if bound>a['input_tokens_per_request']:raise ValueError('input_ceiling')
        body={'input_token_upper_bound':bound,'reserved_input_tokens':a['input_tokens_per_request'],
              'reserved_output_tokens':a['output_tokens_per_request'],'tariff':tariff,'budget_id':a['budget_id']}
        cur=db.execute('INSERT INTO reservations(request,ordinal,day,month,nanousd,body,utc) VALUES(?,?,?,?,?,?,?)',
                       (request,ordinal,b['day'],b['month'],cost,canonical(body),now));db.commit();return cur.lastrowid,None
    except BaseException:db.rollback();raise


def transport(body):
    directory=os.environ.get('CREDENTIALS_DIRECTORY')
    if not directory:raise ValueError('missing_systemd_credential')
    secret=(Path(directory)/'deepseek-key').read_text().strip()
    if not secret:raise ValueError('empty_systemd_credential')
    request=urllib.request.Request('https://api.deepseek.com/chat/completions',data=canonical(body).encode(),
                                  headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
    with opener().open(request,timeout=load()['api']['timeout_seconds']) as response:raw=response.read(100001)
    if len(raw)>100000:raise ValueError('provider_response_size')
    return json.loads(raw)


def receipt(reply):
    usage=reply.get('usage',{});a=load()['api'];content=reply['choices'][0]['message']['content']
    if not isinstance(content,str) or len(content.encode())>24000:raise ValueError('provider_content_bound')
    known=all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens'))
    violation=known and (usage['prompt_tokens']>a['input_tokens_per_request'] or usage['completion_tokens']>a['output_tokens_per_request'])
    return {'state':'COMPLETE','content':content,'model':reply.get('model'),'provider_request_id':reply.get('id'),
            'finish_reason':reply['choices'][0].get('finish_reason'),'usage':usage,'usage_known':known,
            'budget_violation':bool(violation),'raw_reply_hash':digest(reply)}


def finish(db,root,rid,wire,value):
    body={**value,'request':rid,'wire_hash':wire,'utc':utc()}
    with db:db.execute('INSERT INTO finals VALUES(?,?,?,?)',(rid,wire,canonical(body),utc()))
    atomic(Path(root)/'responses'/f'{rid}.json',body)
    return body['state']


def once(root,send=transport,quote=fetch_tariff,now=None):
    # Separate OS lock also covers the uncertainty window around HTTP transport.
    from research.phase2_v2.broker import broker_lock
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with broker_lock(root):
        db=connect(root)
        try:
            state=_once(db,root,send,quote,now or utc())
            atomic(root/'status.json',{'utc':utc(),'state':state,'budget':budget(db,now)})
            lease(root,'WAIT' if state.startswith('WAIT') else 'DONE',state=state)
            return state
        finally:db.close()


def _once(db,root,send,quote,now):
    a=load()['api']
    if db.execute("SELECT 1 FROM results WHERE json_extract(body,'$.budget_violation')=1 LIMIT 1").fetchone():return 'WAIT_PROVIDER_USAGE_VIOLATION'
    for path in sorted((root/'requests').glob('*.json')):
        req=json.loads(path.read_text());rid=path.stem
        if set(req)!={'id','payload','created_utc'} or digest(req['payload'])!=rid or req['id']!=rid:raise ValueError('request_binding')
        prior=db.execute('SELECT body FROM finals WHERE request=?',(rid,)).fetchone()
        if prior:
            # Repair an interrupted DB -> file handoff without another paid call.
            if not (root/'responses'/path.name).exists():atomic(root/'responses'/path.name,json.loads(prior[0]))
            continue
        body=wire_body(req['payload']);wire=digest(body);bound=len(canonical(body).encode())+256
        rows=db.execute('SELECT id,ordinal,utc FROM reservations WHERE request=? ORDER BY ordinal',(rid,)).fetchall()
        for aid,ordinal,started in rows:
            outcome=db.execute('SELECT body FROM results WHERE attempt=?',(aid,)).fetchone()
            if not outcome:
                value={'state':'UNCERTAIN','error':'interrupted_transport_not_retried','usage_known':False,'attempt':aid}
                with db:db.execute('INSERT INTO results VALUES(?,?,?)',(aid,canonical(value),utc()))
                return finish(db,root,rid,wire,value)
        if rows:
            last=json.loads(db.execute('SELECT body FROM results WHERE attempt=?',(rows[-1][0],)).fetchone()[0])
            if last['state']!='RETRYABLE' or len(rows)>=a['transport_attempts_per_request']:
                return finish(db,root,rid,wire,last)
            if (instant(now)-instant(rows[-1][2])).total_seconds()<a['retry_after_seconds']:return 'WAIT_RETRY_BACKOFF'
        else:
            cached=db.execute("SELECT body FROM finals WHERE wire=? AND json_extract(body,'$.state')='COMPLETE' LIMIT 1",(wire,)).fetchone()
            if cached:return finish(db,root,rid,wire,{**json.loads(cached[0]),'cache_reuse':True,'new_api_attempts':0})
        b=budget(db,now)
        if not b['attempts_remaining_today']:return 'WAIT_DAILY_API_BUDGET'
        if not b['remaining_usd_month']:return 'WAIT_MONTHLY_API_BUDGET'
        tariff_row=db.execute('SELECT body,utc FROM tariffs ORDER BY id DESC LIMIT 1').fetchone()
        if not tariff_row or (instant(now)-instant(tariff_row[1])).total_seconds()>a['tariff_cache_seconds']:
            try:value=quote()
            except Exception:return 'WAIT_VERIFIED_TARIFF'
            with db:db.execute('INSERT INTO tariffs(body,utc) VALUES(?,?)',(canonical(value),now))
        else:value=json.loads(tariff_row[0])
        if send is transport:
            directory=os.environ.get('CREDENTIALS_DIRECTORY')
            if not directory or not (Path(directory)/'deepseek-key').is_file():return 'WAIT_CREDENTIAL'
        aid,reason=reserve(db,rid,len(rows),value,bound,now)
        if reason:return reason
        lease(root,'AI_TRANSPORT',request=rid,attempt=aid)
        try:result={**receipt(send(body)),'attempt':aid}
        except Exception as exc:
            code=getattr(exc,'code',None)
            result={'state':'RETRYABLE' if code in a['retry_http_statuses'] else 'UNCERTAIN',
                    'error_type':type(exc).__name__,'http_status':code,'usage_known':False,'attempt':aid}
        with db:db.execute('INSERT INTO results VALUES(?,?,?)',(aid,canonical(result),utc()))
        if result['state']=='RETRYABLE' and len(rows)+1<a['transport_attempts_per_request']:return 'WAIT_RETRY_BACKOFF'
        return finish(db,root,rid,wire,result)
    return 'WAIT_REQUEST'
