"""Thin SQLAlchemy layer that works unchanged on SQLite and PostgreSQL/TimescaleDB."""
from __future__ import annotations
import pandas as pd
from sqlalchemy import create_engine, text, inspect, event
from .config import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True,
                       connect_args={"timeout": 60, "check_same_thread": False} if IS_SQLITE else {})

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=60000")
        cur.close()


def has_table(name: str) -> bool:
    return inspect(engine).has_table(name)


def df(sql: str, **params) -> pd.DataFrame:
    with engine.connect() as c:
        return pd.read_sql(text(sql), c, params=params)


def q(sql: str, **params) -> list[dict]:
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params)]


def execute(sql: str, **params) -> None:
    with engine.begin() as c:
        c.execute(text(sql), params)


def replace_rows(table: str, frame: pd.DataFrame, where: dict | None = None) -> int:
    """Idempotent write: delete rows matching `where`, then append `frame` (removes duplicates
    on re-ingest). With where=None the whole table is replaced."""
    with engine.begin() as c:
        if where is None:
            frame.to_sql(table, c, if_exists="replace", index=False, chunksize=5000)
            return len(frame)
        if inspect(c).has_table(table):
            cond = " AND ".join(f"{k} = :{k}" for k in where)
            c.execute(text(f"DELETE FROM {table} WHERE {cond}"), where)
        if len(frame):
            frame.to_sql(table, c, if_exists="append", index=False, chunksize=5000)
    return len(frame)


def index(table: str, cols: str) -> None:
    name = f"ix_{table}_{cols.replace(',', '_').replace(' ', '')}"
    try:
        execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
    except Exception:
        pass


def init() -> None:
    execute("""CREATE TABLE IF NOT EXISTS source_health (
        source TEXT PRIMARY KEY, status TEXT, last_success DOUBLE PRECISION, last_attempt DOUBLE PRECISION,
        last_error TEXT, last_error_at DOUBLE PRECISION, requests INTEGER, failures INTEGER)""")
    execute("""CREATE TABLE IF NOT EXISTS source_errors (
        ts DOUBLE PRECISION, source TEXT, url TEXT, error TEXT)""")
    execute("""CREATE TABLE IF NOT EXISTS ingest_log (
        ts DOUBLE PRECISION, source TEXT, dataset TEXT, scope TEXT, n_rows INTEGER, rejected INTEGER, note TEXT)""")
    execute("""CREATE TABLE IF NOT EXISTS model_registry (
        name TEXT, version TEXT, created DOUBLE PRECISION, train_through TEXT, n_rows INTEGER,
        metrics TEXT, path TEXT, active INTEGER)""")
    execute("""CREATE TABLE IF NOT EXISTS prediction_snapshots (
        ts DOUBLE PRECISION, kind TEXT, scope TEXT, lap INTEGER, model_version TEXT, payload TEXT)""")
    execute("""CREATE TABLE IF NOT EXISTS weather_forecast_snapshots (
        ts DOUBLE PRECISION, circuit_id TEXT, lat DOUBLE PRECISION, lon DOUBLE PRECISION, payload TEXT)""")
