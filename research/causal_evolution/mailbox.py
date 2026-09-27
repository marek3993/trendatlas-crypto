"""Only sanitized development JSON crosses this filesystem boundary."""
import sqlite3
from pathlib import Path

class Mailbox:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'proposals.sqlite',timeout=30);self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,run TEXT,generation INTEGER,payload TEXT NOT NULL,state TEXT NOT NULL,response TEXT,validation TEXT,usage TEXT,created TEXT NOT NULL);''');self.db.commit()
    def close(self):self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.db.close()
