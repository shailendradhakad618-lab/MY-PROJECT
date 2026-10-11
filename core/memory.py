import sqlite3, json, time
class Memory:
    def __init__(self, path):
        self.path=str(path); self._init()
    def _conn(self): return sqlite3.connect(self.path)
    def _init(self):
        with self._conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, kind TEXT, key TEXT, value TEXT, ts REAL)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_mem_key ON memories(key)')
    def put(self, kind, key, value):
        with self._conn() as c: c.execute('INSERT INTO memories(kind,key,value,ts) VALUES(?,?,?,?)',(kind,key,json.dumps(value,ensure_ascii=False),time.time()))
    def get(self,key,limit=5):
        with self._conn() as c: rows=c.execute('SELECT kind,value FROM memories WHERE key=? ORDER BY id DESC LIMIT ?',(key,limit)).fetchall()
        return [(k,json.loads(v)) for k,v in rows]
    def recent(self,limit=20):
        with self._conn() as c: return c.execute('SELECT kind,key,value,ts FROM memories ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
