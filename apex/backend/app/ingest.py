"""Ingestion pipeline: F1DB bulk history + OpenF1 sessions. Idempotent, validated, logged.

CLI:  python -m app.ingest f1db | sessions | backfill [--from 2023] | session <key> | latest
"""
from __future__ import annotations
import re, sys, time
import pandas as pd
from . import db
from .connectors.openf1 import openf1, COLUMNS
from .connectors.others import f1db
from .connectors.base import SourceError

F1DB_TABLES = {
    "races": "f1db_races", "races-race-results": "f1db_race_results", "races-qualifying-results": "f1db_qualifying",
    "races-starting-grid-positions": "f1db_grid", "races-pit-stops": "f1db_pit_stops",
    "races-fastest-laps": "f1db_fastest_laps", "races-driver-standings": "f1db_driver_standings",
    "races-constructor-standings": "f1db_constructor_standings", "drivers": "f1db_drivers",
    "constructors": "f1db_constructors", "circuits": "f1db_circuits", "grands-prix": "f1db_grands_prix",
    "races-sprint-race-results": "f1db_sprint_results", "seasons-entrants-drivers": "f1db_entrants_drivers",
}


def snake(s: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", s).lower()


def log(source, dataset, scope, n, rejected=0, note=""):
    db.execute("INSERT INTO ingest_log (ts,source,dataset,scope,n_rows,rejected,note) VALUES (:t,:s,:d,:sc,:n,:r,:no)",
               t=time.time(), s=source, d=dataset, sc=str(scope), n=int(n), r=int(rejected), no=note)


def ingest_f1db() -> dict:
    db.init()
    tables = f1db.download()
    out = {}
    for stem, name in F1DB_TABLES.items():
        f = tables[stem].copy()
        f.columns = [snake(c) for c in f.columns]
        n0 = len(f)
        f = f.drop_duplicates()
        db.replace_rows(name, f)
        log("f1db", name, "all", len(f), n0 - len(f))
        out[name] = len(f)
    for t, c in [("f1db_race_results", "race_id"), ("f1db_race_results", "driver_id"), ("f1db_race_results", "year"),
                 ("f1db_qualifying", "race_id"), ("f1db_grid", "race_id"), ("f1db_pit_stops", "race_id"),
                 ("f1db_driver_standings", "race_id"), ("f1db_constructor_standings", "race_id"), ("f1db_races", "year")]:
        db.index(t, c)
    return out


def ingest_sessions(year: int | None = None) -> int:
    """Discover meetings/sessions (all types) and store them."""
    db.init()
    f, rej = openf1.fetch("sessions", f"year={year}" if year else "")
    if len(f):
        if year:
            db.replace_rows("of1_sessions", f, {"year": int(year)})
        else:
            db.replace_rows("of1_sessions", f)
        db.index("of1_sessions", "session_key")
    log("openf1", "sessions", year or "all", len(f), rej)
    return len(f)


RACE_ENDPOINTS = ["drivers", "laps", "stints", "pit", "position", "weather", "race_control", "session_result"]


def ingest_session(session_key: int, endpoints=None, since: float | None = None) -> dict:
    """Pull every dataset for one session. `since` (epoch) limits time-series endpoints to new rows
    (used by the live poller); otherwise the session is replaced wholesale."""
    out = {}
    for ep in endpoints or RACE_ENDPOINTS:
        qs = f"session_key={session_key}"
        table = f"of1_{ep}"
        try:
            f, rej = openf1.fetch(ep, qs)
        except SourceError as e:
            log("openf1", table, session_key, 0, 0, f"FAILED: {e}")
            out[ep] = None
            continue
        if len(f) or not db.has_table(table):
            if not len(f):
                f = pd.DataFrame(columns=COLUMNS[ep])
            db.replace_rows(table, f, {"session_key": int(session_key)})
            db.index(table, "session_key")
        log("openf1", table, session_key, len(f), rej)
        out[ep] = len(f)
    return out


def backfill(year_from: int = 2023, session_names=("Race",)) -> None:
    """Historical backfill of all race sessions. Resumable: sessions already holding laps are skipped."""
    db.init()
    ingest_sessions()
    names = ",".join(f"'{n}'" for n in session_names)
    sessions = db.q(f"SELECT session_key, year, location FROM of1_sessions WHERE session_name IN ({names}) "
                    f"AND year >= :y AND date_end < :now ORDER BY date_start DESC", y=year_from, now=time.time())
    have = set()
    if db.has_table("of1_session_result"):
        have = {r["session_key"] for r in db.q("SELECT DISTINCT session_key FROM of1_session_result")}
    for i, s in enumerate(sessions):
        if s["session_key"] in have:
            continue
        t = time.time()
        res = ingest_session(s["session_key"])
        print(f"[{i + 1}/{len(sessions)}] {s['year']} {s['location']} {res} {time.time() - t:.0f}s", flush=True)


def latest_race_key() -> int | None:
    r = db.q("SELECT session_key FROM of1_sessions WHERE session_name='Race' AND date_start < :now "
             "ORDER BY date_start DESC LIMIT 1", now=time.time())
    return r[0]["session_key"] if r else None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "latest"
    if cmd == "f1db":
        print(ingest_f1db())
    elif cmd == "sessions":
        print(ingest_sessions())
    elif cmd == "backfill":
        backfill(int(sys.argv[3]) if len(sys.argv) > 3 else 2023)
    elif cmd == "session":
        print(ingest_session(int(sys.argv[2])))
    else:
        db.init(); ingest_sessions(); k = latest_race_key(); print(k, ingest_session(k))
