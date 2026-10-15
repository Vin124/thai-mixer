"""
db.py — the database. With DATABASE_URL set (Supabase Postgres) it uses that;
without it, a local SQLite file (mixer.db) so you can try things offline.

Queries are written with `?` placeholders and converted for Postgres.
"""

import os
import sqlite3
import threading

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = bool(DATABASE_URL)
SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mixer.db")

if USE_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL)
else:
    _sqlite_lock = threading.Lock()


def query(sql, params=(), one=False):
    """Run one statement; returns a list of dicts (or one dict / None)."""
    if USE_PG:
        try:
            conn, pooled = _pool.getconn(), True
        except psycopg2.pool.PoolError:
            # Busy moment: use a one-off connection rather than failing.
            conn, pooled = psycopg2.connect(DATABASE_URL), False
        broken = False
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql.replace("?", "%s"), params)
                rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            conn.commit()
        except Exception:
            broken = conn.closed != 0
            if not broken:
                conn.rollback()
            raise
        finally:
            if pooled:
                _pool.putconn(conn, close=broken)
            else:
                conn.close()
    else:
        with _sqlite_lock:
            conn = sqlite3.connect(SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys = ON")
                cur = conn.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()] if cur.description else []
                conn.commit()
            finally:
                conn.close()
    if one:
        return rows[0] if rows else None
    return rows


def init_db():
    """Create tables if missing. Safe to run on every start."""
    query("""
        CREATE TABLE IF NOT EXISTS mixer_players (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""")
    # status: 'done' (no media, counts straight away), 'pending',
    # 'approved', 'rejected'. Points count for everything except rejected;
    # only approved media shows on the projector.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_submissions (
            id TEXT PRIMARY KEY,
            player_id TEXT NOT NULL REFERENCES mixer_players(id) ON DELETE CASCADE,
            activity_id TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            media_key TEXT,
            media_type TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE (player_id, activity_id)
        )""")
    # One row per (photo, voter): value is +1 or -1. Votes go with the
    # submission when it's deleted; api_submit clears them on a replace.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_votes (
            submission_id TEXT NOT NULL REFERENCES mixer_submissions(id) ON DELETE CASCADE,
            player_id TEXT NOT NULL REFERENCES mixer_players(id) ON DELETE CASCADE,
            value INTEGER NOT NULL CHECK (value IN (-1, 1)),
            created_at TEXT NOT NULL,
            PRIMARY KEY (submission_id, player_id)
        )""")
    # Activities edited from /admin/content (JSON), see game.py.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
    if USE_PG:
        query("ALTER TABLE mixer_settings ENABLE ROW LEVEL SECURITY")
        # Supabase exposes public tables through its REST API using the
        # anon key. RLS with no policies shuts that door; this app connects
        # as the database owner, which RLS doesn't apply to.
        query("ALTER TABLE mixer_players ENABLE ROW LEVEL SECURITY")
        query("ALTER TABLE mixer_submissions ENABLE ROW LEVEL SECURITY")
        query("ALTER TABLE mixer_votes ENABLE ROW LEVEL SECURITY")
