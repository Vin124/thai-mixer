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

# A UNIQUE / foreign-key rule refused the write, from either database.
IntegrityError = (sqlite3.IntegrityError,) + ((psycopg2.IntegrityError,) if USE_PG else ())


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


def _add_column(table, column, ddl):
    if USE_PG:
        query(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
    elif column not in {c["name"] for c in query(f"PRAGMA table_info({table})")}:
        query(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _sqlite_drop_global_name_rule():
    """SQLite can't drop a column's UNIQUE, so rebuild an old players table
    without it (SQLite's documented copy-and-rename). Foreign keys are off
    for this so submissions pointing at the players aren't cascade-deleted."""
    with _sqlite_lock:
        conn = sqlite3.connect(SQLITE_PATH)
        try:
            for idx in conn.execute("PRAGMA index_list(mixer_players)").fetchall():
                cols = [c[2] for c in conn.execute(f"PRAGMA index_info('{idx[1]}')")]
                if idx[2] and idx[3] == "u" and cols == ["name_key"]:
                    break
            else:
                return
            conn.executescript("""
                PRAGMA foreign_keys = OFF;
                BEGIN;
                CREATE TABLE mixer_players_new (
                    id TEXT PRIMARY KEY, game_id TEXT NOT NULL, user_id TEXT,
                    name TEXT NOT NULL, name_key TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
                INSERT INTO mixer_players_new (id, game_id, user_id, name, name_key, role, created_at)
                    SELECT id, game_id, user_id, name, name_key, role, created_at FROM mixer_players;
                DROP TABLE mixer_players;
                ALTER TABLE mixer_players_new RENAME TO mixer_players;
                COMMIT;""")
        finally:
            conn.close()


def init_db():
    """Create tables if missing and bring older ones up to date. Safe to run
    on every start."""
    # One row per Google account (the Supabase Auth user id).
    query("""
        CREATE TABLE IF NOT EXISTS mixer_users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""")
    # A game is one party with its own join code and a copy of its pack
    # (JSON, see game.py). host_id NULL = only ADMIN_EMAILS can run it.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_games (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            host_id TEXT REFERENCES mixer_users(id) ON DELETE SET NULL,
            pack_id TEXT,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
    # Custom packs (see sets.py). public = 1 lists it for everyone.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_sets (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES mixer_users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL,
            public INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
    # A player is one person in one game. user_id is NULL for people who
    # joined the original Thai Club event by name, before Google sign-in.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_players (
            id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            user_id TEXT,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""")
    # Tables from before games existed: every existing player belonged to
    # the one event, which becomes game.LEGACY_ID ('thai-club').
    _add_column("mixer_players", "game_id", "TEXT NOT NULL DEFAULT 'thai-club'")
    _add_column("mixer_players", "user_id", "TEXT")
    if USE_PG:
        # New rows must always say which game they're in.
        query("ALTER TABLE mixer_players ALTER COLUMN game_id DROP DEFAULT")
        # Names were unique across the whole site; now only within a game.
        query("ALTER TABLE mixer_players DROP CONSTRAINT IF EXISTS mixer_players_name_key_key")
    else:
        _sqlite_drop_global_name_rule()
    query("CREATE UNIQUE INDEX IF NOT EXISTS mixer_players_game_name ON mixer_players (game_id, name_key)")
    query("CREATE UNIQUE INDEX IF NOT EXISTS mixer_players_game_user ON mixer_players (game_id, user_id)")
    # status: 'done' (no media, counts straight away), 'pending',
    # 'approved', 'rejected', 'hidden'. Points count for everything except
    # rejected; only approved media shows on the projector.
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
    # The original event's edited activities; read once to build the legacy
    # game (game.ensure_legacy), kept as-is.
    query("""
        CREATE TABLE IF NOT EXISTS mixer_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
    if USE_PG:
        # Supabase exposes public tables through its REST API using the
        # anon key. RLS with no policies shuts that door; this app connects
        # as the database owner, which RLS doesn't apply to.
        for table in ("mixer_users", "mixer_games", "mixer_sets", "mixer_players",
                      "mixer_submissions", "mixer_votes", "mixer_settings"):
            query(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
