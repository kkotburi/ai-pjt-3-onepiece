import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).with_name("planner.sqlite")


@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


with connection() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, sid TEXT, episode INTEGER,
      start TEXT, end TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, sid TEXT, kind TEXT,
      payload TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS memory(sid TEXT PRIMARY KEY, data TEXT);
    """)


def log_event(sid, kind, payload):
    with connection() as db:
        db.execute("INSERT INTO events(sid,kind,payload) VALUES(?,?,?)",
                   (sid, kind, json.dumps(payload, ensure_ascii=False)))


def remember(sid, data=None):
    with connection() as db:
        if data is None:
            row = db.execute("SELECT data FROM memory WHERE sid=?", (sid,)).fetchone()
            return json.loads(row[0]) if row else {}
        db.execute("INSERT OR REPLACE INTO memory VALUES(?,?)", (sid, json.dumps(data)))
