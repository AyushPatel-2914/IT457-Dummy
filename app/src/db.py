"""Tiny database layer that works with Postgres (S0-S2) and SQLite (tests, quick local runs).

DATABASE_URL examples:
    postgresql://minix:minix@db:5432/minix
    sqlite:///minix.db
"""
import hashlib
import os
import random
import sqlite3
import threading
import time
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///minix.db")
IS_PG = DATABASE_URL.startswith("postgres")

GENRES = ["Action", "Comedy", "Drama", "Horror", "Sci-Fi", "Romance", "Thriller", "Documentary", "Animation", "Crime"]
N_MOVIES = 1000
N_USERS = 100

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg2.pool import ThreadedConnectionPool
                _pool = ThreadedConnectionPool(1, int(os.environ.get("DB_POOL_MAX", "8")), DATABASE_URL, connect_timeout=3)
    return _pool


@contextmanager
def connection():
    if IS_PG:
        pool = _get_pool()
        conn = pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            # Drop broken connections (e.g. after an RDS failover) instead of reusing them.
            pool.putconn(conn, close=True)
            conn = None
            raise
        finally:
            if conn is not None:
                pool.putconn(conn)
    else:
        conn = sqlite3.connect(DATABASE_URL.removeprefix("sqlite:///"), timeout=5)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def query(sql, params=(), one=False):
    """Run a query written with %s placeholders; return rows as dicts."""
    if not IS_PG:
        sql = sql.replace("%s", "?")
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        if cur.description is None:
            return None
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def hash_password(username, password):
    # Toy hashing for a demo app with fake users; not for real credentials.
    return hashlib.sha256(f"{username}:{password}".encode()).hexdigest()


def _seed_rows():
    rng = random.Random(42)
    adjectives = ["Silent", "Last", "Hidden", "Broken", "Golden", "Lost", "Final", "Dark", "Bright", "Endless", "Frozen", "Wild"]
    nouns = ["Empire", "River", "Signal", "Garden", "Machine", "Kingdom", "Code", "Harbor", "Orbit", "Echo", "Frontier", "Mirror"]
    movies = []
    for i in range(1, N_MOVIES + 1):
        title = f"The {rng.choice(adjectives)} {rng.choice(nouns)} {i}"
        genre = rng.choice(GENRES)
        movies.append((i, title, genre, rng.randint(1970, 2025), round(rng.uniform(4.0, 9.8), 1),
                       f"A {genre.lower()} film about a {rng.choice(nouns).lower()}."))
    users = [(i, f"user{i}", hash_password(f"user{i}", "password")) for i in range(1, N_USERS + 1)]
    return movies, users


def init(retries=30):
    """Create tables and seed data. Idempotent and safe when several instances start at once."""
    for attempt in range(retries):
        try:
            _create_and_seed()
            return
        except Exception as exc:  # DB container or RDS may not be ready yet
            if attempt == retries - 1:
                raise
            print(f"db.init: waiting for database ({exc.__class__.__name__}: {exc})", flush=True)
            time.sleep(2)


def _create_and_seed():
    movies, users = _seed_rows()
    with connection() as conn:
        cur = conn.cursor()
        if IS_PG:
            cur.execute("SELECT pg_advisory_xact_lock(457)")
        cur.execute("""CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, genre TEXT NOT NULL,
            year INTEGER NOT NULL, rating REAL NOT NULL, description TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_movies_genre_rating ON movies (genre, rating)")
        cur.execute("SELECT COUNT(*) FROM movies")
        if cur.fetchone()[0] < N_MOVIES:
            ph = "%s" if IS_PG else "?"
            cur.executemany(f"INSERT INTO movies VALUES ({ph},{ph},{ph},{ph},{ph},{ph}) ON CONFLICT (id) DO NOTHING", movies)
            cur.executemany(f"INSERT INTO users VALUES ({ph},{ph},{ph}) ON CONFLICT (id) DO NOTHING", users)


def ping():
    query("SELECT 1 AS ok", one=True)
