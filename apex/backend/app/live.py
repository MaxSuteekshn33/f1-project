"""Live loop: discovers the current session, polls OpenF1 at a configurable cadence, stores new records
and notifies WebSocket subscribers. Outside a session it idles and only refreshes the session list."""
from __future__ import annotations
import asyncio, time
from . import db, ingest, racestate as rs
from .config import LIVE_POLL_SECONDS, IDLE_POLL_SECONDS
from .connectors.base import SourceError

subscribers: set = set()
state = {"current": None, "last_poll": None, "last_error": None, "weather_flag": None, "polls": 0}
LIVE_ENDPOINTS = ["laps", "stints", "pit", "position", "weather", "race_control", "drivers"]


def current_session() -> dict | None:
    """A session (any type) whose scheduled window contains now (with 15 min lead / 60 min overrun)."""
    if not db.has_table("of1_sessions"):
        return None
    now = time.time()
    r = db.q("SELECT * FROM of1_sessions WHERE date_start - 900 <= :n AND COALESCE(date_end, date_start + 7200) + 3600 >= :n "
             "ORDER BY date_start DESC LIMIT 1", n=now)
    return r[0] if r else None


def next_session() -> dict | None:
    if not db.has_table("of1_sessions"):
        return None
    r = db.q("SELECT * FROM of1_sessions WHERE date_start > :n ORDER BY date_start LIMIT 1", n=time.time())
    return r[0] if r else None


async def broadcast(msg: dict) -> None:
    dead = []
    for ws in list(subscribers):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        subscribers.discard(ws)


def _poll_once() -> dict | None:
    cur = current_session()
    state["current"] = cur
    if not cur:
        return None
    before = db.q("SELECT COUNT(*) AS n FROM of1_laps WHERE session_key=:k", k=cur["session_key"])[0]["n"] if db.has_table("of1_laps") else 0
    ingest.ingest_session(cur["session_key"], LIVE_ENDPOINTS)
    rs.load.clear()
    after = db.q("SELECT COUNT(*) AS n FROM of1_laps WHERE session_key=:k", k=cur["session_key"])[0]["n"]
    st = rs.state(cur["session_key"])
    rain = (st.get("weather") or {}).get("rainfall")
    changed_weather = state["weather_flag"] is not None and rain != state["weather_flag"]
    state["weather_flag"] = rain
    return {"session_key": cur["session_key"], "new_laps": after - before, "lap": st["lap"], "mode": st["mode"]["mode"],
            "track_status": st["track_status"], "weather_changed": changed_weather, "rainfall": rain}


async def loop() -> None:
    last_sessions = 0.0
    while True:
        delay = IDLE_POLL_SECONDS
        try:
            if time.time() - last_sessions > 6 * 3600:
                await asyncio.to_thread(ingest.ingest_sessions, time.gmtime().tm_year)
                last_sessions = time.time()
            res = await asyncio.to_thread(_poll_once)
            state["last_poll"] = time.time(); state["polls"] += 1; state["last_error"] = None
            if res:
                delay = LIVE_POLL_SECONDS
                if res["new_laps"] or res["weather_changed"]:
                    await broadcast({"type": "update", **res})          # clients refetch -> timing tower updates
                if res["weather_changed"]:
                    await broadcast({"type": "weather_alert", "rainfall": res["rainfall"], "session_key": res["session_key"],
                                     "message": "Track rain sensor changed state — weather scenarios recalculated."})
            else:
                nxt = next_session()
                if nxt:
                    delay = max(LIVE_POLL_SECONDS, min(IDLE_POLL_SECONDS, nxt["date_start"] - 900 - time.time()))
        except (SourceError, Exception) as e:
            state["last_error"] = f"{type(e).__name__}: {e}"
        await asyncio.sleep(delay)
