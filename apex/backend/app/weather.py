"""Weather intelligence: measured track weather (OpenF1), area forecast (Open-Meteo), wetness proxy,
tyre-class crossover and the three adaptive scenarios. A forecast is never treated as a track measurement:
every block is tagged observed / forecast / model / assumption."""
from __future__ import annotations
import json, math, time
import numpy as np
from . import db, racestate as rs, sim, strategy as sg
from .connectors.others import openmeteo
from .connectors.base import SourceError


def series(session_key: int, T: float) -> list[dict]:
    w = rs.load(session_key)["weather"]
    if not len(w):
        return []
    w = w[w.date <= T].sort_values("date")
    step = max(1, len(w) // 160)
    return [{"t": float(r.date), "air": r.air_temperature, "track": r.track_temperature, "humidity": r.humidity,
             "rain": int(r.rainfall or 0), "wind": r.wind_speed, "wind_dir": r.wind_direction} for r in w.iloc[::step].itertuples()]


def forecast(lat: float, lon: float, t0: float, t1: float, circuit_id: str = "") -> dict:
    """Open-Meteo data covering [t0, t1]. For past windows this is model analysis retrieved afterwards."""
    now = time.time()
    past = int(min(92, max(0, math.ceil((now - t0) / 86400) + 1))) if t0 < now else 0
    ahead = int(min(16, max(1, math.ceil((t1 - now) / 86400) + 1)))
    if now - t0 > 90 * 86400:
        return {"available": False, "reason": "Session is older than Open-Meteo's ~3-month past window on the forecast endpoint.", "rows": []}
    try:
        j = openmeteo.forecast(lat, lon, past_days=past, forecast_days=ahead)
    except SourceError as e:
        # fall back to the newest stored snapshot for this circuit that covers the window — labelled as stale
        snap = db.q("SELECT ts, payload FROM weather_forecast_snapshots WHERE circuit_id=:c ORDER BY ts DESC LIMIT 5", c=circuit_id) if circuit_id else []
        for sn in snap:
            rows = [r for r in json.loads(sn["payload"]) if t0 - 3600 <= r["t"] <= t1 + 3600]
            if rows:
                return {"available": True, "rows": rows, "kind": "analysis" if t1 < now else "forecast", "retrieved": sn["ts"], "stale": True,
                        "source": "Open-Meteo (stored snapshot)",
                        "caveat": f"Open-Meteo is unavailable right now ({str(e).split(chr(32) + chr(40) + chr(104))[0]}). Showing the stored snapshot retrieved "
                                  f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(sn['ts']))}. Area model data — not a track measurement."}
        return {"available": False, "reason": f"Open-Meteo unavailable: {e}. No stored snapshot covers this window; no forecast values are substituted.", "rows": []}
    h, m = j.get("hourly", {}), j.get("minutely_15", {})
    hp = dict(zip(h.get("time", []), h.get("precipitation_probability", [])))
    hg = dict(zip(h.get("time", []), h.get("wind_gusts_10m", [])))
    rows = []
    for i, t in enumerate(m.get("time", [])):
        if t0 - 3600 <= t <= t1 + 3600:
            hr = t - t % 3600
            rows.append({"t": t, "precip_mm_15": m["precipitation"][i], "rain_mm_15": m["rain"][i], "temp": m["temperature_2m"][i],
                         "wind": m["wind_speed_10m"][i], "wind_dir": m["wind_direction_10m"][i],
                         "precip_prob": hp.get(hr), "gusts": hg.get(hr)})
    kind = "forecast" if t0 > now else ("analysis" if t1 < now else "nowcast")
    out = {"available": True, "rows": rows, "kind": kind, "retrieved": now, "lat": j.get("latitude"), "lon": j.get("longitude"),
           "source": "Open-Meteo forecast API (15-minute + hourly), numerical weather model for the circuit area",
           "caveat": ("Model data for a past window, retrieved after the event — NOT the forecast that was available at the time, "
                      "and not a track measurement." if kind == "analysis" else
                      "Area forecast from a numerical weather model — not a measurement of the track surface.")}
    try:
        db.execute("INSERT INTO weather_forecast_snapshots (ts,circuit_id,lat,lon,payload) VALUES (:t,:c,:la,:lo,:p)",
                   t=now, c=circuit_id, la=lat, lo=lon, p=json.dumps(rows[:400]))
    except Exception:
        pass
    return out


def rain_timeline(fc: dict, T: float, R: int, lap_s: float) -> tuple[list[float], dict]:
    """Per-lap rain intensity (0..1; 1 ≈ ≥4 mm/h) for the remaining laps from the 15-minute forecast rows."""
    rows = fc.get("rows") or []
    if not rows:
        return [0.0] * R, {"max_prob": None, "total_mm": None, "first_rain_min": None}
    ts = np.array([r["t"] for r in rows]); mm = np.array([r["precip_mm_15"] or 0 for r in rows], float)
    out = []
    for i in range(R):
        t = T + (i + 0.5) * lap_s
        j = int(np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 1))
        out.append(float(min(1.0, mm[j] * 4 / 4.0)))
    win = [r for r in rows if T <= r["t"] <= T + R * lap_s + 900]
    probs = [r["precip_prob"] for r in win if r["precip_prob"] is not None]
    first = next((r["t"] for r in win if (r["precip_mm_15"] or 0) > 0.05), None)
    return out, {"max_prob": max(probs) if probs else None, "total_mm": round(float(sum(r["precip_mm_15"] or 0 for r in win)), 2),
                 "first_rain_min": round((first - T) / 60, 0) if first else None}


def compare(ctx: dict, focus: int, options: list[dict], scenario: dict, n: int | None = None) -> list[dict]:
    """Run the same simulated futures (common random numbers) for each candidate decision of `focus`."""
    base_plans = sim.default_plans(ctx)
    out = []
    for o in options:
        plans = dict(base_plans)
        sc = dict(scenario)
        if o.get("plan") is not None:
            plans[focus] = [(int(a), b) for a, b in o["plan"]]
            sc["manual"] = list(set(sc.get("manual", [])) | {focus})
        sc.update(o.get("scenario", {}))
        kw = {"n": n} if n else {}
        r = sim.run(ctx, plans, sc, seed=7, focus=focus, **kw)
        if "focus" not in r:
            continue
        f = r["focus"]
        out.append({"label": o["label"], "plan": [{"lap": a, "compound": b} for a, b in plans.get(focus, [])], "exp_pos": round(f["exp_pos"], 2),
                    "p_win": round(f["p_win"], 4), "p_podium": round(f["p_podium"], 4), "p_win_se": round(f["p_win_se"], 4),
                    "risk_pos_sd": round(f["risk"], 2), "pos_p10": f["pos_p10"], "pos_p90": f["pos_p90"],
                    "blocked_laps": round(f["blocked_laps"], 1), "pos_hist": [round(x, 4) for x in f["pos_hist"]],
                    "exp_time": f["exp_time"], "_t": f["sims_time"], "_a": f["sims_alive"], "n_sims": r["n_sims"],
                    "wetness_path": r["wetness_path"], "inputs": r["inputs"]})
    if out:
        ok = np.all([o["_a"] for o in out], axis=0)
        means = [float(o["_t"][ok].mean()) if ok.any() else None for o in out]
        best = min(x for x in means if x is not None) if any(x is not None for x in means) else None
        ref = means[0]
        for o, mu in zip(out, means):
            o["time_vs_best"] = round(mu - best, 2) if mu is not None else None
            o["time_vs_first"] = round(mu - ref, 2) if mu is not None and ref is not None else None
            o["paired_se"] = round(float((o["_t"][ok] - out[0]["_t"][ok]).std() / math.sqrt(max(1, ok.sum()))), 2) if ok.any() else None
        for o in out:
            o.pop("_t"); o.pop("_a")
    return out


def _confidence(opts: list[dict], best: dict, forecast_conf: float) -> dict:
    """Confidence = how clearly the best option beats the runner-up (in paired standard errors), capped by
    how much the weather input itself can be trusted."""
    others = sorted([o for o in opts if o is not best], key=lambda o: o["exp_pos"])
    if not others:
        return {"score": round(forecast_conf, 2), "level": "LOW"}
    gap = abs(others[0]["exp_pos"] - best["exp_pos"])
    tgap = abs((others[0].get("time_vs_best") or 0) - (best.get("time_vs_best") or 0))
    sep = min(1.0, max(gap / 0.35, tgap / 6.0))
    score = round(float(np.clip(0.25 + 0.75 * sep, 0, 1) * forecast_conf), 2)
    return {"score": score, "level": "HIGH" if score >= 0.7 else "MEDIUM" if score >= 0.45 else "LOW",
            "basis": f"best vs next option: {gap:.2f} expected positions, {tgap:.1f} s; weather-input trust {forecast_conf:.2f}"}


def intelligence(session_key: int, lap: int | None, focus: int | None, what_if: dict | None = None) -> dict:
    """Current conditions + forecast + automatically selected scenario (A dry→wet, B wet→dry) with a decision table."""
    ctx = sim.context(session_key, lap)
    st, m = ctx["st"], ctx["m"]
    total = st["total_laps"] or st["max_lap"]
    R = total - st["lap"]
    rows = [r for r in st["rows"] if r["status"] == "RUNNING"]
    if focus is None and rows:
        focus = rows[0]["driver_number"]
    me = next((r for r in rows if r["driver_number"] == focus), None)
    f1 = st.get("f1db") or {}
    lap_s = float(np.median([r["last_lap"] for r in rows if r["last_lap"]])) if rows else 90.0
    fc = forecast(f1["latitude"], f1["longitude"], st["session"]["date_start"], st["session"]["date_end"] or st["T"] + 7200,
                  f1.get("circuit_id", "")) if f1.get("latitude") is not None else {"available": False, "reason": "Circuit coordinates unknown.", "rows": []}
    rain, fsum = rain_timeline(fc, st["T"], max(R, 0), lap_s)
    wi = what_if or {}
    assumptions = []
    wx0 = st["weather"] or {}
    mismatch = None
    if rain and rain[0] > 0.02 and not wx0.get("rainfall") and not (wx0.get("rain_share_15min") or 0):
        # the area model shows precipitation but the trackside sensor has been dry for 15 minutes: trust the sensor for the near term
        rain = [r * (0.3 if i < int(600 / lap_s) else 1.0) for i, r in enumerate(rain)]
        mismatch = ("Open-Meteo shows precipitation over the circuit area right now, but the trackside rain sensor (OpenF1) has reported none "
                    "for 15 minutes. Near-term rain intensity is down-weighted; the forecast is not a track measurement.")
    if wi.get("rain_in_min") is not None:          # user what-if overrides the forecast
        start = int(round(float(wi["rain_in_min"]) * 60 / lap_s))
        dur = int(round(float(wi.get("rain_duration_min", 20)) * 60 / lap_s))
        inten = float(wi.get("rain_intensity", 0.6))
        rain = [inten if start <= i < start + dur else 0.0 for i in range(max(R, 0))]
        assumptions.append(f"Scenario assumption: rain intensity {inten:.2f} starting in {wi['rain_in_min']} min for {wi.get('rain_duration_min', 20)} min.")
    if wi.get("rain_stops"):
        rain = [0.0] * max(R, 0)
        assumptions.append("Scenario assumption: no further rain.")
    scn = {"rain": rain, "random_incidents": False, "rain_uncertainty_laps": 2 if any(r > 0 for r in rain) else 0}
    if wi.get("wetness") is not None:
        scn["wetness"] = float(wi["wetness"]); assumptions.append(f"Scenario assumption: track wetness set to {float(wi['wetness']):.2f}.")
    if wi.get("track_temp_delta"):
        scn["track_temp_delta"] = float(wi["track_temp_delta"]); assumptions.append(f"Scenario assumption: track temperature {float(wi['track_temp_delta']):+.0f}°C (wear ±2%/°C).")
    if wi.get("crosswind"):
        scn["variability"] = 1.25; assumptions.append("Scenario assumption: strong/shifting crosswind modelled as +25% lap-time variability.")
    wx = st["weather"] or {}
    w0 = scn.get("wetness", ctx["wet"]["wetness"])
    wpath = sim.wetness_path(w0, rain, (wx.get("track_temperature") or 25) + scn.get("track_temp_delta", 0), wx.get("wind_speed")) if R > 0 else np.array([])
    on_wet = bool(me and me["compound"] in sg.WETS)
    up = np.nonzero(wpath > sim.W_SLICK_TO_INTER)[0]
    down = np.nonzero(wpath < sim.W_INTER_TO_SLICK)[0]
    scenario_type, cross_lap, options = None, None, []
    best_slick = min(sg.SLICKS, key=lambda c: m["compounds"][c]["offset"] + 8 * m["compounds"][c]["deg"])
    if me and R > 2:
        if not on_wet and len(up):
            scenario_type, cross_lap = "A", st["lap"] + 1 + int(up[0])
            tyre = "WET" if wpath.max() > sim.W_INTER_TO_WET + 0.05 else "INTERMEDIATE"
            cand = sorted({max(st["lap"] + 1, cross_lap + k) for k in (-2, -1, 0, 1, 3)} | {st["lap"] + 1})
            options = [{"label": f"Box for {tyre.lower()}s on lap {c}" + (" (now)" if c == st["lap"] + 1 else ""), "plan": [(c, tyre)]}
                       for c in cand if c < total]
            if tyre == "WET" and cross_lap < total:
                options.append({"label": f"Box for intermediates on lap {cross_lap}", "plan": [(cross_lap, "INTERMEDIATE")]})
            options.append({"label": "Stay on slicks to the flag", "plan": [], "scenario": {"no_reaction": [focus]}})
        elif on_wet and len(down):
            scenario_type, cross_lap = "B", st["lap"] + 1 + int(down[0])
            cand = sorted({max(st["lap"] + 1, cross_lap + k) for k in (-3, -1, 0, 1, 3)} | {st["lap"] + 1})
            options = [{"label": f"Switch to {best_slick.lower()}s on lap {c}" + (" (now)" if c == st["lap"] + 1 else ""), "plan": [(c, best_slick)]}
                       for c in cand if c < total - 1]
        elif on_wet:
            scenario_type = "B-hold"
    table = compare(ctx, focus, options, scn) if options else []
    rec = None
    kind = fc.get("kind")
    fconf = 0.9 if wi else (0.75 if kind == "nowcast" else 0.6 if kind == "forecast" else 0.5)
    if fsum["max_prob"] is not None and not wi:
        fconf *= 0.6 + 0.4 * abs(fsum["max_prob"] - 50) / 50
    if table:
        best = min(table, key=lambda o: (o["exp_pos"], o["time_vs_best"] or 0))
        alt = sorted([o for o in table if o is not best], key=lambda o: o["exp_pos"])[0]
        slick_pen = float(sim.wet_penalty(np.array(0), wpath.max()) * m["field_base"])
        risks = []
        if scenario_type == "A":
            risks = ["Rain arrives later or lighter than modelled: an early stop costs a full pit loss plus slow laps on intermediates on a dry track.",
                     "Rain arrives earlier: every lap on slicks beyond the crossover costs about %.1f s at peak modelled wetness." % slick_pen,
                     "Wetness is a proxy (tyre choice + rain sensor), not a surface measurement."]
        else:
            risks = ["Switching before the racing line is dry risks very slow out-laps on cold slicks or an off.",
                     "Switching late gives up time to cars already on slicks (undercut).",
                     "Drying rate is an assumption (0.02 wetness/lap at 25°C track, scaled by temperature and wind)."]
        aqua = float(np.clip(max(rain or [0]) * 0.6 + wpath.max() * 0.4, 0, 1)) if len(wpath) else 0.0
        rec = {"scenario": scenario_type, "crossover_lap": cross_lap, "recommended": best["label"], "alternative": alt["label"],
               "expected_gain_s": round((alt["time_vs_best"] or 0) - (best["time_vs_best"] or 0), 1),
               "expected_gain_positions": round(alt["exp_pos"] - best["exp_pos"], 2),
               "confidence": _confidence(table, best, fconf), "risks": risks,
               "time_lost_per_lap_on_slicks_at_peak_s": round(slick_pen, 1) if scenario_type == "A" else None,
               "aquaplaning_risk_index": round(aqua, 2),
               "aquaplaning_note": "Proxy index 0–1 from modelled rain intensity and wetness — standing-water depth is not measured.",
               "competitor_reaction": "Simulated rivals change tyre class one lap after the modelled crossover (and bring planned stops forward).",
               "text": _weather_text(scenario_type, st, me, fsum, best, alt, cross_lap, wi)}
    elif scenario_type == "B-hold":
        rec = {"scenario": "B", "recommended": "Stay on wet-weather tyres", "alternative": "None viable yet",
               "confidence": {"score": round(fconf, 2), "level": "MEDIUM"},
               "text": "Track is not modelled to dry below the slick crossover within the remaining laps — stay on the current tyres and re-evaluate each lap.",
               "risks": ["Drying rate is an assumption; a faster-drying line would open the slick window earlier."]}
    return {
        "lap": st["lap"], "total_laps": total, "focus": focus, "focus_code": me["code"] if me else None,
        "current": {"observed": wx, "wetness_proxy": ctx["wet"], "tag": "OBSERVED (OpenF1 track-side) + PROXY (wetness)"},
        "series": series(session_key, st["T"]),
        "forecast": {**{k: v for k, v in fc.items() if k != "rows"}, "summary": fsum, "tag": "FORECAST / MODEL (Open-Meteo)",
                     "rows": [r for r in fc.get("rows", []) if r["t"] >= st["T"] - 1800][:40]},
        "wetness_path": [{"lap": st["lap"] + 1 + i, "wetness": round(float(w), 3), "rain": rain[i]} for i, w in enumerate(wpath)],
        "crossover": {"slick_to_inter": sim.W_SLICK_TO_INTER, "inter_to_slick": sim.W_INTER_TO_SLICK, "inter_to_wet": sim.W_INTER_TO_WET,
                      "curve": sim.crossover_table(), "observed_inter_vs_slick": m["observed_inter_vs_slick"], "tag": "MODEL ASSUMPTION"},
        "scenario_type": scenario_type, "options": table, "recommendation": rec, "assumptions": assumptions + [
            "Wet-penalty curves, wetting (0.25/lap at full intensity) and drying (0.02/lap at 25°C) rates are modelling assumptions.",
            "Localised wet sections are not modelled: no reliable per-sector surface data is available from the sources."],
        "what_if": wi or None, "forecast_observation_mismatch": mismatch,
    }


def _weather_text(kind, st, me, fsum, best, alt, cross_lap, wi) -> str:
    left = (st["total_laps"] or st["max_lap"]) - st["lap"]
    head = ("User scenario: " if wi else "")
    if kind == "A":
        src = (f"rain in ~{fsum['first_rain_min']:.0f} min" if fsum.get("first_rain_min") is not None and not wi else "rain per the scenario")
        prob = f" (max precipitation probability {fsum['max_prob']:.0f}%)" if fsum.get("max_prob") is not None and not wi else ""
        return (f"{head}{src}{prob}. {me['code']} is on {me['compound'].lower()} tyres ({me['tyre_age']} laps old) with {left} laps remaining. "
                f"Modelled slick→intermediate crossover: lap {cross_lap}. Simulated best call: {best['label']} "
                f"(expected position {best['exp_pos']:.1f}, win {best['p_win'] * 100:.0f}%); next best: {alt['label']} "
                f"({alt['time_vs_best']:+.1f} s, expected position {alt['exp_pos']:.1f}).")
    return (f"{head}Track modelled to dry through the intermediate→slick crossover on lap {cross_lap}. {me['code']} is on "
            f"{me['compound'].lower()}s ({me['tyre_age']} laps) with {left} laps remaining. Simulated best call: {best['label']} "
            f"(expected position {best['exp_pos']:.1f}); next best: {alt['label']} ({alt['time_vs_best']:+.1f} s).")


def next_race_forecast() -> dict:
    """Forecast for the next scheduled Grand Prix start (from the F1DB calendar)."""
    today = time.strftime("%Y-%m-%d")
    r = db.q("SELECT r.id AS race_id, r.year, r.round, r.date, r.time, c.latitude, c.longitude, c.id AS circuit_id, g.full_name AS gp_name, "
             "c.full_name AS circuit_name FROM f1db_races r JOIN f1db_circuits c ON c.id=r.circuit_id JOIN f1db_grands_prix g ON g.id=r.grand_prix_id "
             "WHERE r.date >= :t ORDER BY r.date LIMIT 1", t=today)
    if not r:
        return {"available": False, "reason": "No upcoming race in the stored calendar."}
    r = r[0]
    start = time.mktime(time.strptime(f"{r['date']} {r['time'] or '13:00'}", "%Y-%m-%d %H:%M")) - time.timezone
    fc = forecast(r["latitude"], r["longitude"], start - 3600, start + 3 * 3600, r["circuit_id"])
    days = (start - time.time()) / 86400
    if days > 15:
        fc = {"available": False, "reason": f"Race is {days:.0f} days away — beyond the 16-day forecast horizon.", "rows": []}
    return {"race": r, "start": start, "days_ahead": round(days, 1), **fc}
