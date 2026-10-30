"""Private SQLite catalog, browser-scoped choices, and expiring query snapshots."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager

class LibraryStore:
    def __init__(self,path,*,catalog_ttl=3600,snapshot_ttl=300,clock=time.time):
        self.path=Path(path);self.clock=clock
        self.catalog_ttl=catalog_ttl;self.snapshot_ttl=snapshot_ttl
        self.path.parent.mkdir(parents=True,exist_ok=True);self.path.parent.chmod(0o700)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT,year INTEGER,ambiguous INTEGER NOT NULL DEFAULT 0,source TEXT NOT NULL,fetched REAL NOT NULL,expires REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS entity_kind ON entities(kind,expires);
            CREATE TABLE IF NOT EXISTS discovery(id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS aliases(id TEXT NOT NULL,language TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(id,language,value));
            CREATE TABLE IF NOT EXISTS choices(profile TEXT NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,choice TEXT NOT NULL CHECK(choice IN ('like','curious')),updated REAL NOT NULL,PRIMARY KEY(profile,id));
            CREATE TABLE IF NOT EXISTS snapshots(profile TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,fetched REAL NOT NULL,expires REAL NOT NULL,PRIMARY KEY(profile,key));
            ''')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("INSERT OR IGNORE INTO discovery SELECT id FROM entities WHERE source='Qloo /search · editorial seed'")
        self.path.chmod(0o600)
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def put_entities(self,cards,source='Qloo /search',*,discovery=False):
        now=self.clock()
        with self.connect() as db:
            for card in cards:
                if not isinstance(card.get('id'),str) or not isinstance(card.get('name'),str) or card.get('entity_type') not in {'artist','movie','book'}:raise ValueError('Invalid catalog card')
                db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?,?,?,?)',(card['id'],card['name'],card['entity_type'],card.get('detail'),card.get('year'),bool(card.get('ambiguous')),source,now,now+self.catalog_ttl))
                if discovery or card.get('editorial') or source=='Qloo /search · editorial seed':db.execute('INSERT OR IGNORE INTO discovery VALUES(?)',(card['id'],))
                db.execute('DELETE FROM aliases WHERE id=?',(card['id'],))
                for alias in card.get('aliases',[]):
                    if isinstance(alias,dict) and isinstance(alias.get('language'),str) and isinstance(alias.get('value'),str) and len(alias['language'])<=20 and 0<len(alias['value'])<=150:
                        db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?,?)',(card['id'],alias['language'],alias['value']))
            db.execute('DELETE FROM entities WHERE expires<=?',(now,))
            db.execute('DELETE FROM aliases WHERE id NOT IN (SELECT id FROM entities)')
    @staticmethod
    def card(row):
        result={'id':row['id'],'name':row['name'],'entity_type':row['kind'],'fetched_at':row['fetched'],'expires_at':row['expires'],'source':row['source']}
        for key in ('detail','year','ambiguous'):
            if row[key]:result[key]=row[key]
        return result
    def browse(self,domain='all',query='',offset=0,limit=6,*,discovery_only=False):
        if domain not in {'all','music','movie','book'} or not isinstance(query,str) or len(query)>100 or type(offset) is not int or offset<0 or offset>10000:raise ValueError('Invalid local browse')
        clauses=['expires>?'];params=[self.clock()]
        if discovery_only:clauses.append('EXISTS (SELECT 1 FROM discovery d WHERE d.id=entities.id)')
        if domain!='all':clauses.append('kind=?');params.append('artist' if domain=='music' else domain)
        if query.strip():clauses.append('(instr(lower(name),lower(?))>0 OR instr(lower(coalesce(detail,\'\')),lower(?))>0 OR EXISTS (SELECT 1 FROM aliases a WHERE a.id=entities.id AND instr(lower(a.value),lower(?))>0))');params.extend([query.strip()]*3)
        where=' AND '.join(clauses)
        # One visible record per normalized name/type; other exact records remain addressable.
        sql='SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY lower(name),kind ORDER BY fetched DESC,coalesce(year,9999),id) AS dup FROM entities WHERE '+where+') WHERE dup=1'
        with self.connect() as db:
            db.execute('DELETE FROM entities WHERE expires<=?',(self.clock(),))
            db.execute('DELETE FROM aliases WHERE id NOT IN (SELECT id FROM entities)')
            count=db.execute('SELECT count(*) FROM ('+sql+')',params).fetchone()[0]
            rows=db.execute('SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY kind ORDER BY name COLLATE NOCASE) AS position FROM ('+sql+')) ORDER BY position,kind LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
            cards=[self.card(x) for x in rows]
            for card in cards:card['aliases']=[dict(x) for x in db.execute('SELECT language,value FROM aliases WHERE id=?',(card['id'],)).fetchall()]
        return {'cards':cards,'total':count,'offset':offset,'source':'sqlite'}
    def card_by_id(self,identifier):
        with self.connect() as db:row=db.execute('SELECT * FROM entities WHERE id=? AND expires>?',(identifier,self.clock())).fetchone()
        return self.card(row) if row else None
    def has_profile(self,profile):
        if not isinstance(profile,str):return False
        with self.connect() as db:return bool(db.execute('SELECT 1 FROM choices WHERE profile=? LIMIT 1',(profile,)).fetchone())
    def choices(self,profile):
        with self.connect() as db:rows=db.execute('SELECT * FROM choices WHERE profile=? ORDER BY updated,id',(profile,)).fetchall()
        return [dict(id=x['id'],name=x['name'],entity_type=x['kind'],choice=x['choice']) for x in rows]
    def choose(self,profile,card,choice):
        if choice not in {'like','curious','clear'}:raise ValueError('Invalid choice')
        with self.connect() as db:
            if choice=='clear':db.execute('DELETE FROM choices WHERE profile=? AND id=?',(profile,card['id']))
            else:
                db.execute('INSERT OR REPLACE INTO choices VALUES(?,?,?,?,?,?)',(profile,card['id'],card['name'],card['entity_type'],choice,self.clock()))
        return self.choices(profile)
    def clear(self,profile):
        with self.connect() as db:
            db.execute('DELETE FROM choices WHERE profile=?',(profile,));db.execute('DELETE FROM snapshots WHERE profile=?',(profile,))
    def merge_choices(self,profile,cards):
        # Exploration selects a subset; it must never erase the rest of the library
        # or reorder already saved interests merely because they were queried.
        with self.connect() as db:
            for card,choice in cards:
                db.execute("""INSERT INTO choices VALUES(?,?,?,?,?,?) ON CONFLICT(profile,id)
                    DO UPDATE SET name=excluded.name,kind=excluded.kind,choice=excluded.choice,updated=excluded.updated
                    WHERE choices.choice<>excluded.choice""",(profile,card['id'],card['name'],card['entity_type'],choice,self.clock()))
    @staticmethod
    def key(context):return hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def get_snapshot(self,profile,context):
        if not profile:return None
        now=self.clock()
        with self.connect() as db:
            db.execute('DELETE FROM snapshots WHERE expires<=?',(now,))
            row=db.execute('SELECT payload,fetched FROM snapshots WHERE profile=? AND key=?',(profile,self.key(context))).fetchone()
        if not row:return None
        result=json.loads(row['payload']);result['source']='cached_qloo';result['cache_origin']='sqlite';result['cached_at']=row['fetched']
        return result
    def put_snapshot(self,profile,context,result):
        if not profile:return
        if result.get('status') not in {'partial','empty','parallel'}:return
        # Store selected output and gate diagnostics, never raw Qloo records or credentials.
        keep={'status','cards','source','error','questions','trace','diagnostics','taste_inputs','recommendation_mode','rejections','run_id','created_at','versions'}
        value={k:v for k,v in result.items() if k in keep};now=self.clock()
        with self.connect() as db:
            db.execute('DELETE FROM snapshots WHERE expires<=?',(now,))
            db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?)',(profile,self.key(context),json.dumps(value,ensure_ascii=False),now,now+self.snapshot_ttl))
            db.execute('DELETE FROM snapshots WHERE profile=? AND key NOT IN (SELECT key FROM snapshots WHERE profile=? ORDER BY fetched DESC LIMIT 100)',(profile,profile))
