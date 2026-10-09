import sqlite3
from pathlib import Path
from .common import canonical,digest,utc

TABLES=('meta','genes','hypotheses','proposals','batches','members','closed','discoveries','inbox','candidates',
        'scientific_attempts','attempts','backtests','statistics','feedback','requests','ingested','proposal_receipts','events')


def immutable(db,tables):
    for table in tables:
        for action in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END")


def connect(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'research.sqlite',timeout=30)
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS genes(id TEXT PRIMARY KEY,source TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS hypotheses(id TEXT PRIMARY KEY,kind TEXT,body TEXT,source TEXT);
    CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,gene TEXT UNIQUE,body TEXT,origin TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS members(proposal TEXT PRIMARY KEY,batch INTEGER,position INTEGER);
    CREATE TABLE IF NOT EXISTS closed(batch INTEGER PRIMARY KEY,utc TEXT);
    CREATE TABLE IF NOT EXISTS discoveries(id TEXT PRIMARY KEY,body TEXT,source TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,batch INTEGER,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,proposal TEXT UNIQUE,batch INTEGER,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS scientific_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,candidate TEXT UNIQUE,day TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT UNIQUE,candidate TEXT,phase TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS backtests(key TEXT PRIMARY KEY,candidate TEXT,phase TEXT,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS statistics(candidate TEXT PRIMARY KEY,alpha_index INTEGER UNIQUE,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS feedback(candidate TEXT PRIMARY KEY,batch INTEGER,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,trigger_batch INTEGER UNIQUE,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS ingested(id TEXT PRIMARY KEY,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS proposal_receipts(id INTEGER PRIMARY KEY,receipt_key TEXT UNIQUE,request TEXT,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,body TEXT,previous TEXT,hash TEXT UNIQUE);
    ''');immutable(db,TABLES);db.commit();return db


def event(db,kind,**fields):
    prior=db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone();prior=prior[0] if prior else 'GENESIS'
    body=canonical({'utc':utc(),'kind':kind,**fields})
    db.execute('INSERT INTO events(body,previous,hash) VALUES(?,?,?)',(body,prior,digest([body,prior])))


def meta(db,key):return __import__('json').loads(db.execute('SELECT body FROM meta WHERE key=?',(key,)).fetchone()[0])


def verify(db):
    prior='GENESIS'
    for body,previous,value in db.execute('SELECT body,previous,hash FROM events ORDER BY id'):
        if previous!=prior or digest([body,previous])!=value:raise ValueError('hash_chain_failure')
        prior=value
    return prior
