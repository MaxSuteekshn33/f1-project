"""Race state reconstruction: what was known at a given moment of a session.

`state(session_key, lap)` uses ONLY records timestamped at or before the moment the leader completed
`lap` — so replaying a past race and predicting a live one go through exactly the same leak-free path.
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from . import db
from .cache import cached
from .config import LIVE_FRESHNESS_SECONDS

TABLES = ["laps", "stints", "pit", "position", "weather", "race_control", "drivers", "session_result"]


def session_row(session_key: int) -> dict | None:
    r = db.q("SELECT * FROM of1_sessions WHERE session_key=:k", k=session_key)
    return r[0] if r else None


def f1db_race(sess: dict) -> dict | None:
    """Match an OpenF1 race session to its F1DB race (same year, race date within a day)."""
    day = time.strftime("%Y-%m-%d", time.gmtime(sess["date_start"]))
    rows = db.q("SELECT r.id AS race_id, r.year, r.round, r.date, r.laps, r.circuit_id, r.grand_prix_id, r.course_length, "
                "c.latitude, c.longitude, c.full_name AS circuit_name, g.full_name AS gp_name FROM f1db_races r "
                "JOIN f1db_circuits c ON c.id=r.circuit_id JOIN f1db_grands_prix g ON g.id=r.grand_prix_id WHERE r.year=:y", y=sess["year"])
    best = None
    for r in rows:
        d = abs(pd.Timestamp(r["date"]) - pd.Timestamp(day)).days
        if d <= 1 and (best is None or d < best[0]):
            best = (d, r)
    return best[1] if best else None


@cached(ttl=8)
def load(session_key: int) -> dict:
    """All stored datasets for a session + derived lap end times and per-lap track status."""
    sess = session_row(session_key)
    if not sess:
        raise KeyError(f"unknown session {session_key}")
    d = {"session": sess}
    for t in TABLES:
        d[t] = db.df(f"SELECT * FROM of1_{t} WHERE session_key=:k", k=session_key) if db.has_table(f"of1_{t}") else pd.DataFrame()
    laps = d["laps"].sort_values(["driver_number", "lap_number"]).reset_index(drop=True)
    if len(laps):
        nxt = laps.groupby("driver_number")["date_start"].shift(-1)
        same = laps.groupby("driver_number")["lap_number"].shift(-1) == laps.lap_number + 1
        laps["end"] = np.where(same & nxt.notna(), nxt, laps.date_start + laps.lap_duration)
        laps["lap_duration"] = laps.lap_duration.fillna(laps.end - laps.date_start)
        pit_in = laps.groupby("driver_number")["is_pit_out_lap"].shift(-1).fillna(0)
        laps["is_pit_in_lap"] = pit_in.astype(int)
    d["laps"] = laps
    d["f1db"] = f1db_race(sess)
    # leader timeline: time at which lap n was first completed
    lead = laps.dropna(subset=["end"]).groupby("lap_number")["end"].min() if len(laps) else pd.Series(dtype=float)
    d["lead_end"] = lead
    d["max_lap"] = int(lead.index.max()) if len(lead) else 0
    res = d["session_result"]
    total = d["f1db"]["laps"] if d["f1db"] and d["f1db"].get("laps") else None
    if (total is None or pd.isna(total)) and len(res):
        total = res.number_of_laps.max()
    d["total_laps"] = int(total) if total and not pd.isna(total) else None
    # track status events (time-ordered)
    ev = []
    rc = d["race_control"].sort_values("date") if len(d["race_control"]) else d["race_control"]
    for r in rc.itertuples():
        m = (r.message or "").upper()
        if r.category == "SafetyCar":
            if "VSC DEPLOYED" in m or "VIRTUAL SAFETY CAR DEPLOYED" in m: ev.append((r.date, "VSC"))
            elif "VSC ENDING" in m or "VIRTUAL SAFETY CAR ENDING" in m: ev.append((r.date + 12, "GREEN"))
            elif "SAFETY CAR DEPLOYED" in m: ev.append((r.date, "SC"))
            elif "SAFETY CAR IN THIS LAP" in m: ev.append((r.date, "SC_ENDING"))
        elif r.flag == "RED": ev.append((r.date, "RED"))
        elif r.flag == "GREEN" and r.scope == "Track": ev.append((r.date, "GREEN"))
        elif r.flag == "CHEQUERED": ev.append((r.date, "FINISHED"))
    d["status_events"] = ev
    d["grid"] = (d["position"].sort_values("date").groupby("driver_number")["position"].first().to_dict()
                 if len(d["position"]) else {})
    # status affecting each lap (any neutralisation overlapping the lap) -> used to exclude laps from pace fits
    lap_status = {}
    prev_t = sess["date_start"]
    for n, t in lead.items():
        st = track_status(ev, prev_t)
        for (et, s) in ev:
            if prev_t < et <= t and s in ("SC", "VSC", "RED"):
                st = s
        lap_status[int(n)] = "SC" if st == "SC_ENDING" else st
        prev_t = t
    d["lap_status"] = lap_status
    return d


def track_status(events: list, t: float) -> str:
    st = "GREEN"
    for et, s in events:
        if et > t:
            break
        if s == "GREEN" and st == "FINISHED":
            continue
        st = s
    return st


def mode(sess: dict, newest: float | None) -> dict:
    """LIVE / DELAYED / HISTORICAL label for a session, with the reason."""
    now = time.time()
    in_window = sess["date_start"] - 900 <= now <= (sess["date_end"] or sess["date_start"] + 7200) + 3600
    age = now - newest if newest else None
    if in_window and age is not None and age <= LIVE_FRESHNESS_SECONDS:
        return {"mode": "LIVE", "reason": "Session in progress; newest record is %.0fs old." % age, "data_age_s": age}
    if in_window:
        return {"mode": "DELAYED", "data_age_s": age,
                "reason": "Session in progress but the provider is not delivering real-time data (OpenF1 free tier publishes after the session)."}
    return {"mode": "HISTORICAL", "data_age_s": age, "reason": "Session finished — showing stored timing data. Use the lap control to replay it."}


def state(session_key: int, lap: int | None = None) -> dict:
    d = load(session_key)
    sess, laps, lead = d["session"], d["laps"], d["lead_end"]
    newest = float(laps.end.max()) if len(laps) and laps.end.notna().any() else None
    md = mode(sess, newest)
    if not d["max_lap"]:
        return {"session": sess, "mode": md, "lap": 0, "max_lap": 0, "total_laps": d["total_laps"], "rows": [],
                "track_status": "UNKNOWN", "weather": None, "T": None, "limitations": ["No lap data stored for this session yet."]}
    live_edge = lap is None or lap >= d["max_lap"]
    lap = d["max_lap"] if live_edge else max(1, int(lap))
    known_laps = lead.index[lead.index <= lap]      # some sessions miss a lap in the provider data
    lap = int(known_laps.max()) if len(known_laps) else int(lead.index.min())
    T = float(lead.loc[lap])
    if live_edge:  # newest stored record (or now, when the feed is live)
        T = time.time() if md["mode"] == "LIVE" else max(T, newest or T)
    known = laps[laps.end <= T + 1e-6]
    drivers = d["drivers"].set_index("driver_number").to_dict("index") if len(d["drivers"]) else {}
    stints, pits, res = d["stints"], d["pit"], d["session_result"]
    med_lap = float(known.lap_duration.median()) if len(known) else 90.0
    finished = track_status(d["status_events"], T) == "FINISHED" or (md["mode"] == "HISTORICAL" and lap >= d["max_lap"])
    rows = []
    all_numbers = sorted(set(drivers) | set(laps.driver_number.unique()))
    by_driver = {k: g for k, g in known.groupby("driver_number")}
    for dn in all_numbers:
        g = by_driver.get(dn)
        info = drivers.get(dn, {})
        n = int(g.lap_number.max()) if g is not None else 0
        last = g.iloc[-1] if g is not None else None
        st = stints[(stints.driver_number == dn) & (stints.lap_start <= n + 1)].sort_values("stint_number") if len(stints) else stints
        cur = st.iloc[-1] if len(st) else None
        age = None
        if cur is not None:
            age = int((cur.tyre_age_at_start or 0) + max(0, n - cur.lap_start + 1))
        pcount = int((pits[(pits.driver_number == dn)].date <= T).sum()) if len(pits) else (max(0, len(st) - 1) if len(st) else 0)
        row = {
            "driver_number": int(dn), "code": info.get("name_acronym") or str(dn), "name": info.get("full_name") or str(dn),
            "team": info.get("team_name"), "team_colour": info.get("team_colour"),
            "laps_done": n, "last_end": float(last.end) if last is not None else None,
            "last_lap": _f(last.lap_duration) if last is not None else None,
            "best_lap": _f(g.lap_duration.min()) if g is not None else None,
            "s1": _f(last.duration_sector_1) if last is not None else None,
            "s2": _f(last.duration_sector_2) if last is not None else None,
            "s3": _f(last.duration_sector_3) if last is not None else None,
            "compound": cur.compound if cur is not None else None, "tyre_age": age,
            "stint": int(cur.stint_number) if cur is not None else None, "pit_stops": pcount,
            "compounds_used": sorted(set(st.compound.dropna())) if len(st) else [],
            "grid": int(d["grid"][dn]) if dn in d["grid"] and not pd.isna(d["grid"][dn]) else None,
        }
        out = last is None or (T - row["last_end"] > 2.6 * med_lap and track_status(d["status_events"], T) != "RED")
        if finished and len(res):
            rr = res[res.driver_number == dn]
            out = bool(len(rr) and (rr.iloc[0].dnf or rr.iloc[0].dns or rr.iloc[0].dsq)) if len(rr) else out
        row["status"] = "OUT" if out and not (finished and not len(res)) else "RUNNING"
        if finished and row["status"] == "RUNNING":
            row["status"] = "FINISHED"
        rows.append(row)
    run = [r for r in rows if r["laps_done"] > 0]
    run.sort(key=lambda r: (r["status"] == "OUT", -r["laps_done"], r["last_end"]))
    rest = sorted([r for r in rows if r["laps_done"] == 0], key=lambda r: r["grid"] or 99)
    leader = run[0] if run else None
    lead_laps = laps[laps.driver_number == leader["driver_number"]].set_index("lap_number")["end"] if leader else None
    prev = None
    for i, r in enumerate(run + rest):
        r["position"] = i + 1
        r["gained"] = (r["grid"] - r["position"]) if r["grid"] else None
        if r["laps_done"] and leader:
            ref = lead_laps.get(r["laps_done"])
            r["gap_s"] = round(float(r["last_end"] - ref), 3) if ref is not None and not pd.isna(ref) else None
            behind = int((lead_laps <= r["last_end"] + 1e-6).sum()) - r["laps_done"]
            r["laps_behind"] = max(0, behind)
            r["gap"] = "LEADER" if i == 0 else (f"+{behind} LAP{'S' if behind > 1 else ''}" if behind >= 1
                                                else (f"+{r['gap_s']:.3f}" if r["gap_s"] is not None else None))
            r["interval_s"] = (round(r["gap_s"] - prev["gap_s"], 3) if prev and prev.get("gap_s") is not None
                               and r["gap_s"] is not None else None)
        else:
            r["gap_s"] = r["interval_s"] = None; r["gap"] = None; r["laps_behind"] = None
        if r["status"] == "OUT":
            r["gap"] = "OUT"
        prev = r
    ordered = run + rest
    fl = known.loc[known.lap_duration.idxmin()] if len(known) and known.lap_duration.notna().any() else None
    w = d["weather"]
    wk = w[w.date <= T].sort_values("date") if len(w) else w
    weather = None
    if len(wk):
        x = wk.iloc[-1]
        recent = wk[wk.date >= T - 900]
        weather = {"t": float(x.date), "air_temperature": _f(x.air_temperature), "track_temperature": _f(x.track_temperature),
                   "humidity": _f(x.humidity), "pressure": _f(x.pressure), "rainfall": int(x.rainfall or 0),
                   "wind_speed": _f(x.wind_speed), "wind_direction": _f(x.wind_direction),
                   "rain_share_15min": round(float((recent.rainfall > 0).mean()), 2) if len(recent) else None,
                   "track_temp_trend_15min": round(float(recent.track_temperature.iloc[-1] - recent.track_temperature.iloc[0]), 1) if len(recent) > 1 else None,
                   "source": "OpenF1 /weather (track-side sensor, ~1/min)"}
    lead_recent = laps[(laps.driver_number == leader["driver_number"]) & (laps.lap_number <= lap)].lap_duration.tail(3).median() if leader else None
    remaining = (d["total_laps"] - lap) if d["total_laps"] else None
    ts = track_status(d["status_events"], T)
    lim = []
    if not len(pits): lim.append("Pit-lane timing unavailable for this session; pit-stop count derived from stints.")
    if not len(w): lim.append("No track weather records for this session.")
    if not d["f1db"]: lim.append("Race not matched in F1DB; scheduled race distance unknown.")
    return {
        "session": sess, "f1db": d["f1db"], "mode": md, "lap": lap, "max_lap": d["max_lap"], "total_laps": d["total_laps"],
        "T": T, "rows": ordered, "track_status": ts,
        "neutralisations": {"SC": sum(1 for t, s in d["status_events"] if s == "SC" and t <= T),
                            "VSC": sum(1 for t, s in d["status_events"] if s == "VSC" and t <= T),
                            "RED": sum(1 for t, s in d["status_events"] if s == "RED" and t <= T)},
        "fastest_lap": ({"driver_number": int(fl.driver_number), "code": drivers.get(int(fl.driver_number), {}).get("name_acronym"),
                         "lap": int(fl.lap_number), "time": _f(fl.lap_duration)} if fl is not None else None),
        "weather": weather,
        "est_remaining_s": round(float(remaining * lead_recent), 0) if remaining is not None and lead_recent and not pd.isna(lead_recent) else None,
        "limitations": lim, "source": "OpenF1", "as_of": T,
    }


def _f(v):
    return None if v is None or pd.isna(v) else round(float(v), 3)


def race_sessions(limit: int = 400) -> list[dict]:
    if not db.has_table("of1_session_result"):
        return []
    return db.q("SELECT s.session_key, s.year, s.location, s.country_name, s.circuit_short_name, s.circuit_key, s.session_name, "
                "s.date_start, s.date_end FROM of1_sessions s WHERE s.session_name='Race' AND s.session_key IN "
                "(SELECT DISTINCT session_key FROM of1_laps) ORDER BY s.date_start DESC LIMIT :l", l=limit)


def driver_map(session_key: int) -> dict:
    """OpenF1 driver_number -> F1DB driver/constructor ids for this race (falls back to the abbreviation)."""
    d = load(session_key)
    out = {}
    if d["f1db"]:
        for r in db.q("SELECT driver_number, driver_id, constructor_id FROM f1db_race_results WHERE race_id=:r", r=d["f1db"]["race_id"]):
            try: out[int(r["driver_number"])] = (r["driver_id"], r["constructor_id"])
            except (TypeError, ValueError): pass
    missing = [int(n) for n in d["drivers"].driver_number if int(n) not in out] if len(d["drivers"]) else []
    if missing:
        yr = d["session"]["year"]
        recent = {r["abbreviation"]: (r["driver_id"], r["constructor_id"]) for r in db.q(
            "SELECT DISTINCT d.abbreviation, rr.driver_id, rr.constructor_id FROM f1db_race_results rr JOIN f1db_drivers d ON d.id=rr.driver_id "
            "WHERE rr.year IN (:y, :p) ORDER BY rr.race_id", y=yr, p=yr - 1)}
        info = d["drivers"].set_index("driver_number").name_acronym.to_dict()
        for n in missing:
            if info.get(n) in recent:
                out[n] = recent[info[n]]
    return out
