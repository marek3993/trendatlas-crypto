"""Crash-safe, append-only attempt/lineage accounting. SQLite is the authority."""
import json
import gzip
import sqlite3
from pathlib import Path
from .protocol import atomic, utc, digest, CONTRACT
from .vendor.common import canonical, cid

class Store:
    def __init__(self, root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        from .mailbox import Mailbox
        self.mailbox=Mailbox(self.root/'mailbox');self.mail=self.mailbox.db
        self.db=sqlite3.connect(self.root/'candidates.sqlite',timeout=30)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,genes TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,cache_key TEXT,started TEXT,finished TEXT,status TEXT,scope TEXT);
          CREATE TABLE IF NOT EXISTS evaluations(cache_key TEXT PRIMARY KEY,request TEXT NOT NULL,metrics TEXT NOT NULL,daily TEXT NOT NULL,episodes TEXT NOT NULL,orders TEXT NOT NULL,folds TEXT NOT NULL,audit TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS populations(run TEXT,generation INTEGER,body TEXT NOT NULL,PRIMARY KEY(run,generation));
          CREATE TABLE IF NOT EXISTS trials(slot TEXT PRIMARY KEY,run TEXT,generation INTEGER,candidate TEXT,parent TEXT,source TEXT,hypothesis TEXT,created TEXT);
          CREATE TABLE IF NOT EXISTS scores(run TEXT,generation INTEGER,candidate TEXT,body TEXT NOT NULL,PRIMARY KEY(run,generation,candidate));
          CREATE TABLE IF NOT EXISTS finalists(run TEXT,slot TEXT,body TEXT NOT NULL,PRIMARY KEY(run,slot));
        ''');self.db.commit()

    def meta(self,key,default=None):
        r=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self,key,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,canonical(value)))

    def candidate(self,c):
        i=cid(c)
        with self.db:self.db.execute('INSERT OR IGNORE INTO candidates VALUES(?,?)',(i,canonical(c)))
        return i

    def add_trial(self,slot,run,generation,genes,parent=None,source='seed',hypothesis='Frozen seed hypothesis'):
        if self.meta('outer_opened',False):raise RuntimeError('Outer terminal barrier: mutations/trials forbidden')
        i=self.candidate(genes)
        count=self.db.execute("SELECT COUNT(*) FROM trials WHERE source NOT IN ('survivor','plateau')").fetchone()[0]
        exists=self.db.execute('SELECT 1 FROM trials WHERE slot=?',(slot,)).fetchone()
        if not exists and source not in ('survivor','plateau') and count>=CONTRACT['budget']['max_candidate_slots']:
            raise RuntimeError('Candidate slot budget exhausted')
        with self.db:self.db.execute('INSERT OR IGNORE INTO trials VALUES(?,?,?,?,?,?,?,?)',
            (slot,run,generation,i,parent,source,hypothesis,utc()))
        return i

    def reserve(self,key,scope):
        count=self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
        if count>=CONTRACT['budget']['max_evaluation_attempts']:raise RuntimeError('Frozen attempt budget exhausted')
        if scope in ('inner_train','inner_validation') and self.meta('outer_opened',False):
            raise RuntimeError('Historical search closed; outer cannot feed another evaluation')
        with self.db:
            r=self.db.execute('INSERT INTO attempts(cache_key,started,status,scope) VALUES(?,?,?,?)',(key,utc(),'RUNNING',scope))
        return r.lastrowid

    def cached(self,key):
        r=self.db.execute('SELECT * FROM evaluations WHERE cache_key=?',(key,)).fetchone()
        if r:
            self.set('cache_hits',self.meta('cache_hits',0)+1)
            return {k:json.loads(gzip.decompress(r[k]) if isinstance(r[k],bytes) else r[k]) for k in ('request','metrics','daily','episodes','orders','folds','audit')}

    def save(self,key,attempt,value):
        with self.db:
            self.db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?)',
                (key,)+(tuple(gzip.compress(canonical(value[k]).encode(),6) if k in ('daily','episodes','orders') else canonical(value[k]) for k in ('request','metrics','daily','episodes','orders','folds','audit'))))
            self.db.execute("UPDATE attempts SET status='COMPLETE',finished=? WHERE id=?",(utc(),attempt))
            self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('checkpoint',canonical(dict(utc=utc(),evaluation=key,attempt=attempt))))

    def counts(self):
        result={t:self.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in
                ('candidates','trials','attempts','evaluations','finalists')}
        result['proposals']=self.mail.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]
        return result

    def population(self,run,generation,body=None):
        if body is None:
            r=self.db.execute('SELECT body FROM populations WHERE run=? AND generation=?',(run,generation)).fetchone()
            return json.loads(r[0]) if r else None
        if self.meta('outer_opened',False):raise RuntimeError('Outer terminal barrier')
        with self.db:self.db.execute('INSERT INTO populations VALUES(?,?,?)',(run,generation,canonical(body)))

    def status(self,**kw):
        usage=[json.loads(r[0]) for r in self.mail.execute('SELECT usage FROM proposals WHERE usage IS NOT NULL')]
        proposals=[dict(r) for r in self.mail.execute('SELECT state,COUNT(*) n FROM proposals GROUP BY state')]
        result=dict(status=self.meta('status','RUNNING'),experiment_id=self.meta('experiment_id'),
          phase=self.meta('phase','SEARCH'),generation=self.meta('generation',0),run=self.meta('run'),
          counts=self.counts(),checkpoint=self.meta('checkpoint'),cache_hits=self.meta('cache_hits',0),
          deepseek=dict(calls=sum(x.get('api_call',0) for x in usage),tokens=sum(x.get('total_tokens',0) for x in usage),
                        usd=sum(x.get('usd',0) for x in usage),proposals=proposals),
          best_development=self.meta('best_development'),outer_results=self.meta('decision') if self.meta('status')=='SEALED' else None,
          prospective=dict(start='2026-09-27',status=self.meta('prospective_status','NOT_YET_FROZEN'),independent_history=False),
          reject_reasons=self.meta('reject_reasons',[]),resources=self.meta('resources'),
          next_allowed_cycle=self.meta('next_refit','2027-01-01'),pause_reason=self.meta('pause_reason'),utc=utc())
        result['failure']=self.meta('failure')
        result.update(kw);atomic(self.root/'status.json',result)
        return result

    def export_lineage(self):
        atomic(self.root/'mutation_lineage.json',[dict(r) for r in self.db.execute('SELECT * FROM trials ORDER BY created,slot')])
        atomic(self.root/'candidate_genes.json',[dict(id=r[0],genes=json.loads(r[1])) for r in self.db.execute('SELECT * FROM candidates ORDER BY id')])

    def close(self):
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.db.close();self.mailbox.close()
