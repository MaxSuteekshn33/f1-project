"""Application services: assemble module outputs into API payloads. Every payload labels its parts as
OBSERVED (provider data), HISTORICAL (estimates from past races), MODEL (predictions) or ASSUMPTION."""
from __future__ import annotations
import json, math, time
import numpy as np
import pandas as pd
from . import db, cache, racestate as rs, strategy as sg, sim, prerace, inrace, weather
from .cache import cached
from .connectors.openf1 import openf1, iso
from .connectors.others import jolpica
from .connectors.base import SourceError, SOURCES


def clean(o):
    """JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, np.ndarray): return clean(o.tolist())
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (float, np.floating)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if o is pd.NaT or o is pd.NA: return None
    return o


# ---------------------------------------------------------------- reference data
@cached(ttl=1800)
def colours() -> dict:
    """F1DB driver/constructor id -> team colour & code, from the newest stored OpenF1 driver lists."""
    out = {"driver": {}, "constructor": {}}
    for s in rs.race_sessions(3)[::-1]:
        d = rs.load(s["session_key"])
        info = d["drivers"].set_index("driver_number").to_dict("index") if len(d["drivers"]) else {}
        for n, (did, cid) in rs.driver_map(s["session_key"]).items():
            if n in info:
                out["driver"][did] = {"colour": info[n]["team_colour"], "code": info[n]["name_acronym"], "team": info[n]["team_name"], "number": n}
                out["constructor"][cid] = {"colour": info[n]["team_colour"], "team": info[n]["team_name"]}
    return out


def _names() -> tuple[dict, dict]:
    d = {r["id"]: r for r in db.q("SELECT id, name, abbreviation FROM f1db_drivers")}
    c = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM f1db_constructors")}
    return d, c


# ---------------------------------------------------------------- 1. command centre
def command(session_key: int, lap: int | None = None) -> dict:
    st = rs.state(session_key, lap)
    in_progress = st["total_laps"] and 1 < st["lap"] < st["total_laps"]
    pred = None
    if in_progress:
        try:
            pred = inrace.predict(session_key, st["lap"])
        except Exception:
            pred = None
    pm = {int(r.driver_number): r for r in pred.itertuples()} if pred is not None else {}
    for r in st["rows"]:
        p = pm.get(r["driver_number"])
        r["pred_pos"] = int(p.ml_pred_pos) if p is not None else (r["position"] if r["status"] == "FINISHED" else None)
        r["p_win"] = float(p.ml_win) if p is not None else None
    st["prediction_note"] = ("Predicted finish: in-race model (MODEL)." if pm else
                             "Predicted finish is shown only while a race is in progress (laps 2 … n-1)." if not in_progress else
                             "In-race model not trained yet.")
    f = st.get("f1db") or {}
    st["title"] = f.get("gp_name") or f"{st['session']['location']} {st['session']['session_name']}"
    st["circuit"] = f.get("circuit_name") or st["session"]["circuit_short_name"]
    return st


@cached(ttl=30)
def contenders() -> list[str]:
    """Driver codes still mathematically in the title fight (F1DB standings + races left)."""
    y = db.q("SELECT MAX(year) AS y FROM f1db_driver_standings")[0]["y"]
    last = db.q("SELECT MAX(race_id) AS r FROM f1db_driver_standings WHERE year=:y", y=y)[0]["r"]
    st = db.q("SELECT s.driver_id, s.points, d.abbreviation FROM f1db_driver_standings s JOIN f1db_drivers d ON d.id=s.driver_id "
              "WHERE s.race_id=:r ORDER BY s.points DESC", r=last)
    left = db.q("SELECT COUNT(*) AS n, SUM(CASE WHEN sprint_race_date IS NOT NULL THEN 1 ELSE 0 END) AS sp FROM f1db_races WHERE year=:y AND id>:r", y=y, r=last)[0]
    avail = (left["n"] or 0) * 25 + (left["sp"] or 0) * 8
    return [r["abbreviation"] for r in st if st and st[0]["points"] - r["points"] <= avail]


# ---------------------------------------------------------------- 5. predictions
def _next_race() -> dict | None:
    r = db.q("SELECT r.id AS race_id, r.year, r.round, r.date, r.time, r.circuit_id, g.full_name AS gp_name, c.full_name AS circuit_name "
             "FROM f1db_races r JOIN f1db_grands_prix g ON g.id=r.grand_prix_id JOIN f1db_circuits c ON c.id=r.circuit_id "
             "WHERE r.id NOT IN (SELECT DISTINCT race_id FROM f1db_race_results) ORDER BY r.year, r.round LIMIT 1")
    return r[0] if r else None


def _race(race_id: int) -> dict:
    return db.q("SELECT r.id AS race_id, r.year, r.round, r.date, r.time, r.circuit_id, g.full_name AS gp_name, c.full_name AS circuit_name "
                "FROM f1db_races r JOIN f1db_grands_prix g ON g.id=r.grand_prix_id JOIN f1db_circuits c ON c.id=r.circuit_id WHERE r.id=:i", i=race_id)[0]


@cached(ttl=600)
def prerace_prediction(race_id: int | None = None) -> dict:
    race = _race(race_id) if race_id else _next_race()
    if not race:
        return {"available": False, "reason": "No upcoming race in the stored calendar."}
    done = db.q("SELECT COUNT(*) AS n FROM f1db_race_results WHERE race_id=:r", r=race["race_id"])[0]["n"] > 0
    dn, cn = _names()
    col = colours()
    notes, extra, grid_source = [], None, None
    if not done:
        last = db.q("SELECT MAX(race_id) AS r FROM f1db_race_results WHERE year=:y", y=race["year"])[0]["r"] or \
               db.q("SELECT MAX(race_id) AS r FROM f1db_race_results")[0]["r"]
        ent = db.df("SELECT driver_id, constructor_id FROM f1db_race_results WHERE race_id=:r", r=last)
        ent["race_id"] = race["race_id"]
        ent["grid"] = np.nan; ent["q_pos"] = np.nan; ent["q_ms"] = np.nan
        notes.append("Entry list assumed equal to the most recent race (HISTORICAL).")
        try:   # qualifying, if it has happened (Jolpica is refreshed sooner than the F1DB release)
            q = jolpica.qualifying(race["year"], race["round"])
            if q:
                def ms(s):
                    if not s: return np.nan
                    m, sec = s.split(":") if ":" in s else (0, s)
                    return (int(m) * 60 + float(sec)) * 1000
                qm = {x["Driver"]["driverId"].replace("_", "-"): (int(x["position"]), np.nanmin([ms(x.get(k)) for k in ("Q1", "Q2", "Q3")] or [np.nan])) for x in q}
                ent["q_pos"] = ent.driver_id.map(lambda d: qm.get(d, (np.nan, np.nan))[0])
                ent["q_ms"] = ent.driver_id.map(lambda d: qm.get(d, (np.nan, np.nan))[1])
                ent["grid"] = ent.q_pos
                grid_source = "Jolpica qualifying classification (grid penalties not applied)"
        except SourceError:
            notes.append("Jolpica unavailable — qualifying result could not be checked.")
        extra = ent
    f = prerace.build_frame(extra)
    rows = f[f.race_id == race["race_id"]].reset_index(drop=True)
    if not len(rows):
        return {"available": False, "reason": "No entries found for this race.", "race": race}
    variant = "pre_race" if rows.grid.notna().mean() > 0.7 else "pre_quali"
    b = prerace.load(variant)
    if not b:
        return {"available": False, "reason": "Pre-race models have not been trained yet (run `python -m app.prerace train`).", "race": race}
    if done:
        notes.append("This race has been run: the probabilities shown are the walk-forward backtest predictions made with a model "
                     "trained only on earlier seasons." )
    p = prerace.predict(rows, variant)
    oof = {}
    if done and db.has_table("prerace_oof"):
        oof = {r["driver_id"]: r for r in db.q("SELECT * FROM prerace_oof WHERE race_id=:r AND variant=:v", r=race["race_id"], v=variant)}
    # championship context
    prev = db.q("SELECT MAX(race_id) AS r FROM f1db_driver_standings WHERE race_id < :r AND year=:y", r=race["race_id"], y=race["year"])[0]["r"]
    pts = {r["driver_id"]: r["points"] for r in db.q("SELECT driver_id, points FROM f1db_driver_standings WHERE race_id=:r", r=prev)} if prev else {}
    leader_pts = max(pts.values()) if pts else 0
    drivers = []
    for i, r in p.iterrows():
        src = rows.iloc[i]
        o = oof.get(r.driver_id)
        c = col["driver"].get(r.driver_id, {})
        drivers.append({
            "driver_id": r.driver_id, "name": dn.get(r.driver_id, {}).get("name", r.driver_id), "code": dn.get(r.driver_id, {}).get("abbreviation"),
            "constructor": cn.get(r.constructor_id, r.constructor_id), "colour": c.get("colour") or col["constructor"].get(r.constructor_id, {}).get("colour"),
            "grid": None if pd.isna(src.grid) else int(src.grid),
            "p_win": o["win_cal"] if o else r.p_win, "p_podium": o["podium_cal"] if o else r.p_podium,
            "p_top5": o["top5_cal"] if o else r.p_top5, "p_fastest_lap": o["fl_cal"] if o else r.p_fl,
            "pred_pos": int(r.pred_pos), "ci": r.ci, "model_spread": r.model_spread, "explain": r.explain,
            "exp_points": r.exp_points, "points_before": pts.get(r.driver_id, 0.0),
            "gap_to_leader_before": leader_pts - pts.get(r.driver_id, 0.0),
            "pos_dist": [round(float(x), 4) for x in r.pos_dist[:10]],
            "actual_pos": None if not done or pd.isna(src.position_number) else int(src.position_number),
            "actual_text": src.position_text if done else None})
    if done and oof:   # rank predicted positions from the backtest score, not the final model
        order = sorted(drivers, key=lambda d: oof.get(d["driver_id"], {}).get("order_pred", 99))
        for i, d in enumerate(order): d["pred_pos"] = i + 1
    top = max(d["exp_points"] for d in drivers)
    for d in drivers:
        d["exp_points_vs_top"] = d["exp_points"] - top
        d["projected_points"] = d["points_before"] + d["exp_points"]
    drivers.sort(key=lambda d: -d["p_win"])
    cons = {}
    for d in drivers:
        c = cons.setdefault(d["constructor"], {"constructor": d["constructor"], "colour": d["colour"], "p_win": 0.0, "exp_points": 0.0, "p_podium_any": 1.0})
        c["p_win"] += d["p_win"]; c["exp_points"] += d["exp_points"]; c["p_podium_any"] *= (1 - d["p_podium"])
    for c in cons.values(): c["p_podium_any"] = 1 - c["p_podium_any"]
    try:
        db.execute("INSERT INTO prediction_snapshots (ts,kind,scope,lap,model_version,payload) VALUES (:t,'pre_race',:s,0,:v,:p)",
                   t=time.time(), s=str(race["race_id"]), v=b["version"],
                   p=json.dumps([{k: d[k] for k in ("driver_id", "p_win", "p_podium", "pred_pos")} for d in drivers]))
    except Exception:
        pass
    return {"available": True, "race": race, "completed": done, "variant": variant, "model_version": b["version"], "train_through": b["train_through"],
            "grid_source": grid_source or ("F1DB starting grid" if variant == "pre_race" else None),
            "drivers": drivers, "constructors": sorted(cons.values(), key=lambda c: -c["p_win"]), "top5": drivers[:5], "notes": notes,
            "method": {"win/podium": "mean of XGBoost, LightGBM, CatBoost and logistic regression, normalised per race",
                       "ci": "95% Wilson interval of the observed win frequency for this probability band in the walk-forward backtest",
                       "points": f"expected points from 5,000 Plackett–Luce samples of the finishing order (temperature {b['pl_alpha']})",
                       "explain": "SHAP values (log-odds) of the XGBoost winner model"},
            "tags": {"p_win": "MODEL", "grid": "OBSERVED" if variant == "pre_race" else "UNAVAILABLE", "points_before": "OBSERVED (F1DB)"}}


def inrace_prediction(session_key: int, lap: int | None = None) -> dict:
    ctx = sim.context(session_key, lap)
    st = ctx["st"]
    total = st["total_laps"] or st["max_lap"]
    if st["lap"] >= total or st["lap"] < 2:
        return {"available": False, "lap": st["lap"], "total_laps": total,
                "reason": "In-race predictions are produced for laps 2 … n-1 of a race. Move the lap control to a lap during the race."}
    ml = inrace.predict(session_key, st["lap"])
    mc = sim.run(ctx, n=1000, seed=3)
    mcm = {d["driver_number"]: d for d in mc.get("drivers", [])}
    b = inrace.load()
    out = []
    info = {r["driver_number"]: r for r in st["rows"]}
    mlm = {int(r.driver_number): r for r in ml.itertuples()} if ml is not None else {}
    for dn_, r in info.items():
        if r["status"] != "RUNNING" or dn_ not in mcm:
            continue
        m_, s_ = mlm.get(dn_), mcm[dn_]
        pw = [x for x in ([float(m_.ml_win)] if m_ is not None else []) + [s_["p_win"]]]
        pp = [x for x in ([float(m_.ml_podium)] if m_ is not None else []) + [s_["p_podium"]]]
        p = float(np.mean(pw))
        se = math.sqrt(max(s_["p_win"] * (1 - s_["p_win"]), 1e-6) / mc["n_sims"])
        out.append({"driver_number": dn_, "code": r["code"], "name": r["name"], "team": r["team"], "team_colour": r["team_colour"],
                    "position": r["position"], "gap": r["gap"], "compound": r["compound"], "tyre_age": r["tyre_age"],
                    "p_win": p, "p_podium": float(np.mean(pp)), "p_top5": s_["p_top5"],
                    "ml_win": float(m_.ml_win) if m_ is not None else None, "mc_win": s_["p_win"],
                    "range_lo": max(0.0, min(pw) - 1.96 * se), "range_hi": min(1.0, max(pw) + 1.96 * se),
                    "pred_pos": int(m_.ml_pred_pos) if m_ is not None else None, "mc_exp_pos": s_["exp_pos"],
                    "pos_p10": s_["pos_p10"], "pos_p90": s_["pos_p90"], "exp_points": s_["exp_points"], "p_dnf": s_["p_dnf"],
                    "explain": m_.explain if m_ is not None else []})
    out.sort(key=lambda d: -d["p_win"])
    return {"available": True, "lap": st["lap"], "total_laps": total, "track_status": st["track_status"], "drivers": out, "top5": out[:5],
            "model_version": b["version"] if b else None, "n_sims": mc["n_sims"], "sim_inputs": mc["inputs"],
            "method": {"p_win": "mean of the in-race gradient-boosting model (LightGBM + XGBoost) and the Monte Carlo race simulation",
                       "range": "span between the two estimators ± 1.96 Monte Carlo standard errors — a model-disagreement range, not a frequentist CI",
                       "fastest_lap": "not predicted in-race (no validated model); see the pre-race prediction",
                       "leakage": "features and simulation inputs use only records timestamped up to this lap"},
            "tags": {"position/gap/tyres": "OBSERVED", "ml_win": "MODEL", "mc_win": "MODEL + ASSUMPTIONS (simulator)"}}


# ---------------------------------------------------------------- 6. strategy
def strategy_view(session_key: int, lap: int | None, driver: int | None) -> dict:
    ctx = sim.context(session_key, lap)
    st, m = ctx["st"], ctx["m"]
    total = st["total_laps"] or st["max_lap"]
    run = [r for r in st["rows"] if r["status"] == "RUNNING"]
    me = next((r for r in run if r["driver_number"] == driver), run[0] if run else None)
    d = rs.load(session_key)
    stints = d["stints"]
    hist = [{"driver_number": int(s.driver_number), "stint": int(s.stint_number), "compound": s.compound, "from": int(s.lap_start),
             "to": int(min(s.lap_end if not pd.isna(s.lap_end) else st["lap"], st["lap"]))}
            for s in stints.itertuples() if not pd.isna(s.lap_start) and s.lap_start <= st["lap"] + 1] if len(stints) else []
    cl = m["laps"]
    deg_points = []
    if len(cl):
        g = cl[~cl.wet].groupby(["compound", "age"])["lap_duration"].median().reset_index()
        deg_points = [{"compound": r.compound, "age": int(r.age), "lap_time": round(float(r.lap_duration), 3)} for r in g.itertuples() if r.age <= 45]
    out = {"lap": st["lap"], "total_laps": total, "focus": me and me["driver_number"], "focus_code": me and me["code"],
           "tyre_model": {"compounds": m["compounds"], "lap_trend_s_per_lap": m["fuel"], "lap_trend_note": m.get("lap_trend_note"),
                          "n_clean_laps": m["n_laps"], "prior": m["prior"], "base_source": m["base_source"],
                          "observed_inter_vs_slick": m["observed_inter_vs_slick"]},
           "pit_loss": {"seconds": round(m["pit_loss"], 2), "source": m["pit_loss_source"],
                        "under_sc": round(m["pit_loss"] * sg.SC_PIT_FACTOR["SC"], 2), "under_vsc": round(m["pit_loss"] * sg.SC_PIT_FACTOR["VSC"], 2),
                        "neutralised_note": "SC/VSC pit loss uses assumed factors (0.45 / 0.62 of the green-flag loss)."},
           "stints": hist, "deg_points": deg_points, "drivers": [{"driver_number": r["driver_number"], "code": r["code"], "position": r["position"],
                                                               "team_colour": r["team_colour"]} for r in st["rows"]],
           "assumptions": [f"Usable tyre life: {int(sg.LIFE_FRAC['SOFT'] * 100)}/{int(sg.LIFE_FRAC['MEDIUM'] * 100)}/{int(sg.LIFE_FRAC['HARD'] * 100)}% of race distance (S/M/H), then a wear cliff.",
                           "Out-lap warm-up deltas: S −0.3 s, M 0, H +0.5 s.", "Only new tyre sets are considered for future stints."],
           "strategies": [], "window": None, "undercuts": sg.undercuts(st, m), "competitors": []}
    if not me or st["lap"] >= total - 1 or st["lap"] < 1:
        out["note"] = "No strategy to optimise at this lap (race not in progress)."
        return out
    plans = sim.default_plans(ctx)
    out["competitors"] = [{"code": r["code"], "driver_number": r["driver_number"], "position": r["position"], "compound": r["compound"],
                           "tyre_age": r["tyre_age"], "next_stop": plans.get(r["driver_number"], [(None, None)])[0][0] if plans.get(r["driver_number"]) else None,
                           "next_compound": plans.get(r["driver_number"], [(None, None)])[0][1] if plans.get(r["driver_number"]) else None}
                          for r in run]
    on_wet = me["compound"] in sg.WETS
    start_lap = st["lap"]
    if on_wet:
        nxt = plans.get(me["driver_number"])
        if not nxt:
            out["note"] = ("Car is on wet-weather tyres and the track is not modelled to dry in the remaining laps — "
                           "tyre-class timing is handled in Weather Intelligence.")
            return out
        start_lap = nxt[0][0]
        out["note"] = f"Car is on wet-weather tyres: dry strategies start from the modelled slick crossover (lap {start_lap}). See Weather Intelligence."
    opts = sg.strategies(m, start_lap, total, None if on_wet else me["compound"], me["tyre_age"] or 0, me["compounds_used"])
    scn = {"random_incidents": True}
    table = weather.compare(ctx, me["driver_number"], [{"label": o["label"], "plan": [(x["lap"], x["compound"]) for x in o["plan"]]} for o in opts], scn)
    tm = {t["label"]: t for t in table}
    for o in opts:
        t = tm.get(o["label"], {})
        nxt = o["plan"][0]["lap"] if o["plan"] else None
        out["strategies"].append({
            "label": o["label"], "name": o["name"], "plan": o["plan"], "stints": o["stints"], "rule_ok": o["rule_ok"],
            "recommended_pit_lap": nxt, "pit_time_lost": round(o["pit_time_lost"], 1), "deg_time": round(o["deg_time"], 1),
            "deterministic_delta": o.get("delta_vs_best"), "optimal_deterministic": o.get("optimal", False),
            "exp_time_delta": t.get("time_vs_best"), "exp_pos": t.get("exp_pos"), "p_win": t.get("p_win"), "p_podium": t.get("p_podium"),
            "traffic_laps": t.get("blocked_laps"), "pos_p10": t.get("pos_p10"), "pos_p90": t.get("pos_p90"), "pos_hist": t.get("pos_hist")})
    legal = [s for s in out["strategies"] if s["rule_ok"] and s["exp_pos"] is not None]
    if legal:
        best = min(legal, key=lambda s: (round(s["exp_pos"], 1), s["exp_time_delta"] or 0))
        best["recommended"] = True
        bo = next(o for o in opts if o["label"] == best["label"])
        if not on_wet:
            out["window"] = sg.window(m, bo, st["lap"], total, me["compound"], me["tyre_age"] or 0)
    out["n_sims"] = table[0]["n_sims"] if table else None
    out["method"] = ("Stop laps and compounds: OR-Tools CP-SAT minimising modelled remaining race time per stop count. "
                     "Expected position / win probability / traffic: Monte Carlo over the whole field with rivals on their own optimal plans.")
    return out


# ---------------------------------------------------------------- 8. safety car & incidents
def safety_car(session_key: int, lap: int | None, driver: int | None, body: dict | None = None) -> dict:
    body = body or {}
    ctx = sim.context(session_key, lap)
    st, m, hz = ctx["st"], ctx["m"], ctx["hz"]
    total = st["total_laps"] or st["max_lap"]
    run = [r for r in st["rows"] if r["status"] == "RUNNING"]
    me = next((r for r in run if r["driver_number"] == driver), run[0] if run else None)
    out = {"lap": st["lap"], "total_laps": total, "focus": me and me["driver_number"], "focus_code": me and me["code"],
           "base_rates": hz, "track_status": st["track_status"],
           "disclaimer": "Incident timing cannot be predicted. Base rates describe how often neutralisations happened historically; "
                         "the comparisons below are conditional on an incident occurring now."}
    if not me or total - st["lap"] < 3 or st["lap"] < 1:
        out["note"] = "Not enough race distance left to evaluate neutralisation strategy at this lap."
        return out
    nxt = st["lap"] + 1
    best_new = min(sg.SLICKS, key=lambda c: m["compounds"][c]["offset"] + m["compounds"][c]["deg"] * (total - nxt) / 2) if me["compound"] not in sg.WETS else me["compound"]
    alt = next((c for c in sg.SLICKS if c != me["compound"]), best_new)
    new = best_new if (len(set(x for x in me["compounds_used"] if x in sg.SLICKS)) >= 2 or best_new != me["compound"] or me["compound"] in sg.WETS) else alt
    dur = int(body.get("duration", 4))
    sc = {"safety_car": {"lap": nxt, "type": "SC", "duration": dur}}
    vsc = {"safety_car": {"lap": nxt, "type": "VSC", "duration": max(1, dur // 2)}}
    extra = {}
    if body.get("retire"):
        extra["retirements"] = {int(body["retire"]): nxt}
    if body.get("pit_closed"):
        extra["pit_closed_laps"] = [nxt]
    options = [
        {"label": f"Pit under Safety Car (lap {nxt}, {new.lower()})", "plan": [(nxt, new)], "scenario": {**sc, **extra}},
        {"label": "Stay out under Safety Car (keep track position)", "plan": None, "scenario": {**sc, **extra, "hold": {me["driver_number"]: nxt + dur}}},
        {"label": f"Pit under VSC (lap {nxt}, {new.lower()})", "plan": [(nxt, new)], "scenario": {**vsc, **extra}},
        {"label": "Stay out under VSC", "plan": None, "scenario": {**vsc, **extra, "hold": {me["driver_number"]: nxt + dur}}},
        {"label": f"Pit under green (lap {nxt}, {new.lower()})", "plan": [(nxt, new)], "scenario": {"random_incidents": False}},
        {"label": "Stay out under green (own optimal plan)", "plan": None, "scenario": {"random_incidents": False}},
    ]
    table = weather.compare(ctx, me["driver_number"], options, {"random_incidents": False})
    pl = m["pit_loss"]
    out.update(options=table, pit_loss={"green": round(pl, 1), "sc": round(pl * sg.SC_PIT_FACTOR["SC"], 1), "vsc": round(pl * sg.SC_PIT_FACTOR["VSC"], 1),
                                        "saved_sc": round(pl * (1 - sg.SC_PIT_FACTOR["SC"]), 1), "saved_vsc": round(pl * (1 - sg.SC_PIT_FACTOR["VSC"]), 1),
                                        "source": m["pit_loss_source"], "factor_note": "ASSUMPTION: a stop costs 45% (SC) / 62% (VSC) of the green-flag loss."})
    pairs = {"sc": (table[0], table[1]), "vsc": (table[2], table[3]), "green": (table[4], table[5])} if len(table) == 6 else {}
    out["verdicts"] = {k: {"pit_minus_stay_positions": round(a["exp_pos"] - b["exp_pos"], 2), "better": "PIT" if a["exp_pos"] < b["exp_pos"] else "STAY OUT",
                           "pit": a["label"], "stay": b["label"]} for k, (a, b) in pairs.items()}
    out["extras"] = {"red_flag": "A red flag allows a free tyre change for everyone, which removes the advantage of having pitted — not simulated lap-by-lap; treat as neutralising any pit-stop gap.",
                     "restart": "After the Safety Car the field restarts bunched (0.9 s spacing in the simulator); cars on fresher tyres attack immediately.",
                     "pit_lane_closure": "Set `pit_closed` to block stops on the first neutralised lap.", "retirement": "Set `retire` to a driver number to remove that car as the trigger incident."}
    return out


# ---------------------------------------------------------------- 9. simulation lab
def lab(session_key: int, body: dict) -> dict:
    """Run and compare user-defined scenarios. Each scenario: {name, lap, driver, pit_laps:[{lap,compound}], keep_plan,
    rain_in_min, rain_intensity, rain_duration_min, wetness, track_temp_delta, safety_car:{lap,type,duration},
    pit_duration_delta, overrides:{position/compound/tyre_age}, rival:{driver, pit_laps|stay_out}, random_incidents}."""
    results = []
    for i, s in enumerate(body.get("scenarios", [])[:4]):
        ctx = sim.context(session_key, s.get("lap"))
        st = ctx["st"]
        total = st["total_laps"] or st["max_lap"]
        run = [r for r in st["rows"] if r["status"] == "RUNNING"]
        me = next((r for r in run if r["driver_number"] == s.get("driver")), run[0] if run else None)
        name = s.get("name") or f"Scenario {i + 1}"
        if not me or total - st["lap"] < 1:
            results.append({"name": name, "error": "Race not in progress at this lap."})
            continue
        lap_s = float(np.median([r["last_lap"] for r in run if r["last_lap"]]) or 90)
        R = total - st["lap"]
        scn: dict = {"random_incidents": bool(s.get("random_incidents", True))}
        assumptions = []
        if s.get("rain_in_min") is not None:
            a = int(round(float(s["rain_in_min"]) * 60 / lap_s)); dur = int(round(float(s.get("rain_duration_min", 20)) * 60 / lap_s))
            inten = float(s.get("rain_intensity", 0.6))
            scn["rain"] = [inten if a <= j < a + dur else 0.0 for j in range(R)]
            scn["rain_uncertainty_laps"] = 2
            assumptions.append(f"Rain intensity {inten:.2f} from lap {st['lap'] + 1 + a} for {dur} laps (±2 laps timing uncertainty).")
        elif s.get("rain_intensity"):
            scn["rain"] = [float(s["rain_intensity"])] * R
            assumptions.append(f"Rain intensity {float(s['rain_intensity']):.2f} from now to the flag.")
        else:
            scn["rain"] = [0.0] * R
        if s.get("wetness") is not None: scn["wetness"] = float(s["wetness"]); assumptions.append(f"Track wetness set to {scn['wetness']:.2f}.")
        if s.get("track_temp_delta"): scn["track_temp_delta"] = float(s["track_temp_delta"]); assumptions.append(f"Track temperature {scn['track_temp_delta']:+.0f}°C → wear {scn['track_temp_delta'] * 2:+.0f}%.")
        if s.get("safety_car"): scn["safety_car"] = s["safety_car"]; assumptions.append(f"{s['safety_car'].get('type', 'SC')} deployed on lap {s['safety_car']['lap']}.")
        if s.get("pit_duration_delta"): scn["pit_stop_extra"] = float(s["pit_duration_delta"]); assumptions.append(f"Pit stops {float(s['pit_duration_delta']):+.1f} s vs measured loss (all cars).")
        ov = {}
        o = s.get("overrides") or {}
        if o.get("compound") or o.get("tyre_age") is not None or o.get("position"):
            x = {k: o[k] for k in ("compound", "tyre_age") if o.get(k) is not None}
            if o.get("position"):
                tgt = next((r for r in run if r["position"] == int(o["position"])), None)
                if tgt: x["gap_s"] = (tgt["gap_s"] or 0) + (0.4 if tgt["driver_number"] != me["driver_number"] else 0)
            ov[me["driver_number"]] = x
            assumptions.append(f"{me['code']} state overridden: {x}.")
        if ov: scn["overrides"] = ov
        plans = dict(sim.default_plans(ctx))
        manual = []
        if s.get("pit_laps") is not None and not s.get("keep_plan"):
            plans[me["driver_number"]] = [(int(p["lap"]), p["compound"]) for p in s["pit_laps"] if int(p["lap"]) > st["lap"]]
            manual.append(me["driver_number"])
        rv = s.get("rival") or {}
        if rv.get("driver"):
            if rv.get("stay_out"):
                plans[int(rv["driver"])] = []; scn.setdefault("no_reaction", []).append(int(rv["driver"]))
                assumptions.append(f"Rival #{rv['driver']} stays out to the flag.")
            elif rv.get("pit_laps"):
                plans[int(rv["driver"])] = [(int(p["lap"]), p["compound"]) for p in rv["pit_laps"]]; manual.append(int(rv["driver"]))
                assumptions.append(f"Rival #{rv['driver']} plan forced: {rv['pit_laps']}.")
        scn["manual"] = manual
        r = sim.run(ctx, plans, scn, n=int(body.get("n_sims", 1000)), seed=11, focus=me["driver_number"])
        if "focus" not in r:
            results.append({"name": name, "error": r.get("error", "simulation failed")}); continue
        f = r["focus"]
        ok = f["sims_alive"]
        results.append({"name": name, "driver": me["code"], "driver_number": me["driver_number"], "lap": st["lap"], "total_laps": total,
                        "plan": [{"lap": a, "compound": b} for a, b in plans.get(me["driver_number"], [])],
                        "exp_pos": round(f["exp_pos"], 2), "p_win": round(f["p_win"], 4), "p_podium": round(f["p_podium"], 4),
                        "p_win_se": round(f["p_win_se"], 4), "risk_pos_sd": round(f["risk"], 2), "pos_p10": f["pos_p10"], "pos_p90": f["pos_p90"],
                        "p_dnf": round(f["p_dnf"], 3), "exp_race_time_remaining": round(float(f["sims_time"][ok].mean() - (me["gap_s"] or 0)), 1) if ok.any() else None,
                        "time_p10": round(float(np.percentile(f["sims_time"][ok], 10) - (me["gap_s"] or 0)), 1) if ok.any() else None,
                        "time_p90": round(float(np.percentile(f["sims_time"][ok], 90) - (me["gap_s"] or 0)), 1) if ok.any() else None,
                        "pos_hist": [round(x, 4) for x in f["pos_hist"]], "blocked_laps": round(f["blocked_laps"], 1),
                        "field": sorted([{"code": d["code"], "p_win": round(d["p_win"], 3), "exp_pos": round(d["exp_pos"], 1), "team_colour": d["team_colour"]}
                                         for d in r["drivers"]], key=lambda d: d["exp_pos"])[:8],
                        "assumptions": assumptions, "inputs": r["inputs"], "n_sims": r["n_sims"], "_t": f["sims_time"], "_ok": ok})
    good = [r for r in results if "error" not in r]
    if good:
        ref = good[0]
        for r in good:
            both = r["_ok"] & ref["_ok"] if len(r["_t"]) == len(ref["_t"]) and r["lap"] == ref["lap"] else None
            r["time_vs_first"] = round(float((r["_t"][both] - ref["_t"][both]).mean()), 2) if both is not None and both.any() else None
        best = min(good, key=lambda r: (r["exp_pos"], -(r["p_win"])))
        for r in good:
            r["best"] = r is best
            r["best_alternative"] = None if r is best else best["name"]
    for r in results:
        r.pop("_t", None); r.pop("_ok", None)
    return {"results": results, "note": "Scenario inputs are ASSUMPTIONS; starting positions, gaps and tyres are OBSERVED at the chosen lap; "
                                        "pace, wear and pit loss are fitted from laps recorded up to that lap."}


# ---------------------------------------------------------------- 4. telemetry
def lap_table(session_key: int, lap: int | None = None) -> dict:
    """Lap times, sectors, stint/compound per lap and the position trace — all up to the as-of lap."""
    d = rs.load(session_key)
    st = rs.state(session_key, lap)
    laps = d["laps"]
    if not len(laps):
        return {"available": False, "reason": "No lap data stored for this session."}
    k = laps[laps.end <= (st["T"] or 0) + 1e-6]
    stn = d["stints"].dropna(subset=["lap_start"]).sort_values("lap_start") if len(d["stints"]) else None
    if stn is not None and len(k):
        k = pd.merge_asof(k.sort_values("lap_number"), stn[["driver_number", "lap_start", "compound", "stint_number"]], left_on="lap_number",
                          right_on="lap_start", by="driver_number", direction="backward")
    else:
        k = k.assign(compound=None, stint_number=None)
    k = k.sort_values(["driver_number", "lap_number"])
    # position per lap from line-crossing order
    k["pos"] = k.groupby("lap_number")["end"].rank(method="first")
    info = {r["driver_number"]: r for r in st["rows"]}
    drivers = []
    for dn_, g in k.groupby("driver_number"):
        r = info.get(int(dn_), {})
        drivers.append({"driver_number": int(dn_), "code": r.get("code"), "team": r.get("team"), "team_colour": r.get("team_colour"),
                        "position": r.get("position"),
                        "laps": [{"lap": int(x.lap_number), "t": x.lap_duration, "s1": x.duration_sector_1, "s2": x.duration_sector_2,
                                  "s3": x.duration_sector_3, "compound": x.compound, "stint": x.stint_number, "pos": int(x.pos),
                                  "pit": int(x.is_pit_out_lap or x.is_pit_in_lap), "st": x.st_speed,
                                  "status": d["lap_status"].get(int(x.lap_number), "GREEN")} for x in g.itertuples()]})
    drivers.sort(key=lambda x: x["position"] or 99)
    best = {c: (float(k[c].min()) if k[c].notna().any() else None) for c in ("duration_sector_1", "duration_sector_2", "duration_sector_3", "lap_duration")}
    return {"available": True, "lap": st["lap"], "drivers": drivers, "best": best, "source": "OpenF1 /laps, /stints", "tag": "OBSERVED"}


def _channel(session_key: int, driver: int, lap: int, table: str) -> pd.DataFrame:
    """Car telemetry / location for one lap; fetched from OpenF1 on first use, then served from the database."""
    d = rs.load(session_key)
    row = d["laps"][(d["laps"].driver_number == driver) & (d["laps"].lap_number == lap)]
    if not len(row) or pd.isna(row.iloc[0].date_start) or pd.isna(row.iloc[0].end):
        raise LookupError("Lap not found or without timestamps.")
    t0, t1 = float(row.iloc[0].date_start), float(row.iloc[0].end)
    name = f"of1_{table}"
    if db.has_table(name):
        f = db.df(f"SELECT * FROM {name} WHERE session_key=:k AND driver_number=:d AND date>=:a AND date<=:b ORDER BY date", k=session_key, d=driver, a=t0, b=t1)
        if len(f) > 20:
            return f
    f, _ = openf1.fetch(table, f"session_key={session_key}&driver_number={driver}&date>={iso(t0)}&date<={iso(t1)}")
    if len(f):
        with db.engine.begin() as c:
            f.to_sql(name, c, if_exists="append", index=False)
        db.index(name, "session_key,driver_number,date")
    return f.sort_values("date")


def _trace(session_key: int, driver: int, lap: int) -> dict:
    f = _channel(session_key, driver, lap, "car_data")
    if len(f) < 20:
        raise LookupError("No car telemetry published for this lap.")
    t = (f.date - f.date.iloc[0]).to_numpy()
    v = f.speed.to_numpy(float) / 3.6
    dist = np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(t))])
    return {"t": t, "dist": dist, "speed": f.speed.to_numpy(float), "throttle": f.throttle.to_numpy(float), "brake": f.brake.to_numpy(float),
            "gear": f.n_gear.to_numpy(float), "rpm": f.rpm.to_numpy(float), "drs": f.drs.to_numpy(float)}


def telemetry_compare(session_key: int, d1: int, l1: int, d2: int | None = None, l2: int | None = None) -> dict:
    out = {"available": True, "source": "OpenF1 /car_data (~3.7 Hz)", "tag": "OBSERVED", "traces": [], "limitations": [
        "Distance is integrated from speed samples (no GPS odometer) — expect ±1% alignment error.",
        "DRS codes: 10/12/14 = open, 8 = eligible, 0/1 = closed (OpenF1 raw codes)."]}
    codes = {r["driver_number"]: r for r in rs.state(session_key)["rows"]}
    sel = [(d1, l1)] + ([(d2, l2)] if d2 and l2 else [])
    traces = []
    for dn_, lp in sel:
        try:
            traces.append((dn_, lp, _trace(session_key, int(dn_), int(lp))))
        except (LookupError, SourceError) as e:
            out["limitations"].append(f"#{dn_} lap {lp}: telemetry unavailable ({e}). No values are substituted.")
    if not traces:
        return {**out, "available": False, "reason": "Telemetry unavailable for the selected laps."}
    L = min(tr["dist"][-1] for _, _, tr in traces)
    grid = np.linspace(0, L, 260)
    pts = [{"d": round(float(x), 0)} for x in grid]
    for i, (dn_, lp, tr) in enumerate(traces):
        key = "a" if i == 0 else "b"
        for ch in ("speed", "throttle", "brake", "gear", "rpm"):
            vals = np.interp(grid, tr["dist"], tr[ch])
            for p, v in zip(pts, vals): p[f"{ch}_{key}"] = round(float(v), 1)
        drs = np.interp(grid, tr["dist"], (tr["drs"] >= 10).astype(float))
        tt = np.interp(grid, tr["dist"], tr["t"])
        for p, v, x in zip(pts, drs, tt): p[f"drs_{key}"] = int(v > 0.5); p[f"t_{key}"] = float(x)
        r = codes.get(int(dn_), {})
        out["traces"].append({"key": key, "driver_number": int(dn_), "lap": int(lp), "code": r.get("code"), "team_colour": r.get("team_colour"),
                              "lap_time": round(float(tr["t"][-1]), 3), "top_speed": float(tr["speed"].max()),
                              "full_throttle_pct": round(float((tr["throttle"] >= 98).mean() * 100), 1),
                              "brake_pct": round(float((tr["brake"] > 0).mean() * 100), 1), "gear_changes": int((np.diff(tr["gear"]) != 0).sum()),
                              "max_rpm": float(tr["rpm"].max()), "drs_pct": round(float((tr["drs"] >= 10).mean() * 100), 1)})
    if len(traces) == 2:
        for p in pts: p["delta"] = round(p["t_b"] - p["t_a"], 3)
    out["points"] = pts
    return out


def track_map(session_key: int, lap: int | None = None) -> dict:
    """Circuit outline from one lap of car positions, sector boundaries, and car positions at the as-of time."""
    d = rs.load(session_key)
    st = rs.state(session_key, lap)
    laps = d["laps"]
    ref = laps[(laps.lap_number > 1) & laps.lap_duration.notna() & laps.duration_sector_1.notna() & laps.duration_sector_2.notna()
               & (laps.is_pit_out_lap == 0) & (laps.is_pit_in_lap == 0)]
    if not len(ref):
        return {"available": False, "reason": "No complete timed lap to draw the circuit from."}
    r = ref.loc[ref.lap_duration.idxmin()]
    key = f"track:{session_key}"
    outline = cache.get(key)
    if outline is None:
        try:
            f = _channel(session_key, int(r.driver_number), int(r.lap_number), "location")
        except (LookupError, SourceError) as e:
            return {"available": False, "reason": f"Car position data unavailable from OpenF1 ({e}). No positions are generated."}
        f = f[(f.x != 0) | (f.y != 0)]
        if len(f) < 50:
            return {"available": False, "reason": "OpenF1 published no usable position samples for this session."}
        t = f.date.to_numpy() - float(r.date_start)
        step = max(1, len(f) // 400)
        s1, s2 = float(r.duration_sector_1), float(r.duration_sector_1 + r.duration_sector_2)
        outline = {"pts": [[float(x), float(y), 1 if tt < s1 else 2 if tt < s2 else 3] for x, y, tt in zip(f.x[::step], f.y[::step], t[::step])],
                   "ref": f"{int(r.driver_number)} lap {int(r.lap_number)}"}
        cache.put(key, outline, 86400)
    cars, note = [], None
    if st["T"]:
        ck = f"cars:{session_key}:{st['lap']}"
        cars = cache.get(ck)
        if cars is None:
            try:
                f, _ = openf1.fetch("location", f"session_key={session_key}&date>={iso(st['T'] - 0.6)}&date<={iso(st['T'] + 0.6)}")
                info = {x["driver_number"]: x for x in st["rows"]}
                last = f.sort_values("date").groupby("driver_number").last()
                cars = [{"driver_number": int(n), "x": float(v.x), "y": float(v.y), "code": info.get(int(n), {}).get("code"),
                         "team_colour": info.get(int(n), {}).get("team_colour"), "position": info.get(int(n), {}).get("position")}
                        for n, v in last.iterrows() if (v.x != 0 or v.y != 0) and info.get(int(n), {}).get("status") == "RUNNING"]
                cache.put(ck, cars, 3600)
            except SourceError as e:
                cars, note = [], f"Car positions unavailable ({e}); none are generated."
    return {"available": True, "outline": outline["pts"], "outline_ref": outline["ref"], "cars": cars or [], "note": note,
            "track_status": st["track_status"], "lap": st["lap"],
            "source": "OpenF1 /location (car x/y in the F1 timing coordinate system, not geographic lat/lon)", "tag": "OBSERVED",
            "limitations": ["Positions are provider x/y coordinates, so a geographic base map (MapLibre) cannot be aligned without a calibrated transform — the circuit is drawn from the cars' own trace instead."]}


def pace_comparison(session_key: int, lap: int | None = None) -> dict:
    """Race pace by compound/stint for every driver + qualifying-vs-race pace when the qualifying session is stored."""
    st = rs.state(session_key, lap)
    m = sg.tyre_model(session_key, st["lap"])
    cl = m["laps"]
    info = {r["driver_number"]: r for r in st["rows"]}
    rows = []
    if len(cl):
        for (dn_, comp), g in cl.groupby(["driver_number", "compound"]):
            r = info.get(int(dn_), {})
            rows.append({"driver_number": int(dn_), "code": r.get("code"), "team": r.get("team"), "team_colour": r.get("team_colour"), "compound": comp,
                         "laps": int(len(g)), "median": round(float(g.lap_duration.median()), 3), "best": round(float(g.lap_duration.min()), 3)})
    quali = {}
    q = db.q("SELECT session_key FROM of1_sessions WHERE meeting_key=:m AND session_name='Qualifying'", m=st["session"]["meeting_key"])
    note = None
    if q and db.has_table("of1_laps"):
        if not db.q("SELECT 1 AS x FROM of1_laps WHERE session_key=:k LIMIT 1", k=q[0]["session_key"]):
            try:   # fetch the meeting's qualifying laps on first use
                from . import ingest
                ingest.ingest_session(q[0]["session_key"], ["laps"])
            except Exception:
                pass
        ql = db.df("SELECT driver_number, MIN(lap_duration) AS best FROM of1_laps WHERE session_key=:k GROUP BY driver_number", k=q[0]["session_key"])
        quali = {int(r.driver_number): float(r.best) for r in ql.itertuples() if not pd.isna(r.best)}
    if not quali:
        note = "Qualifying laps for this meeting are not stored (ingest the Qualifying session to enable the comparison)."
    race = {}
    if len(cl):
        race = {int(k): float(v) for k, v in cl[~cl.wet].groupby("driver_number")["lap_duration"].median().items()}
    qr = [{"driver_number": n, "code": info.get(n, {}).get("code"), "team_colour": info.get(n, {}).get("team_colour"),
           "quali_best": round(quali[n], 3), "race_median": round(race[n], 3), "ratio": round(race[n] / quali[n], 4)}
          for n in quali if n in race]
    team = {}
    for r in st["rows"]:
        team.setdefault(r["team"], []).append(r)
    mates = []
    for t, rr in team.items():
        if len(rr) == 2 and all(x["driver_number"] in race for x in rr):
            a, b = rr
            mates.append({"team": t, "team_colour": a["team_colour"], "a": a["code"], "b": b["code"],
                          "race_pace_delta": round(race[a["driver_number"]] - race[b["driver_number"]], 3),
                          "quali_delta": round(quali[a["driver_number"]] - quali[b["driver_number"]], 3) if a["driver_number"] in quali and b["driver_number"] in quali else None})
    return {"by_compound": rows, "quali_vs_race": sorted(qr, key=lambda x: x["ratio"]), "teammates": mates, "note": note,
            "tag": "OBSERVED (green-flag laps only)", "lap": st["lap"]}


# ---------------------------------------------------------------- 10. history
def history_overview() -> dict:
    s = db.q("SELECT MIN(year) AS first, MAX(year) AS last, COUNT(*) AS races FROM f1db_races WHERE id IN (SELECT DISTINCT race_id FROM f1db_race_results)")[0]
    return {"coverage": s, "seasons": [r["year"] for r in db.q("SELECT DISTINCT year FROM f1db_races ORDER BY year DESC")],
            "circuits": db.q("SELECT c.id, c.full_name AS name, c.type, c.total_races_held AS races FROM f1db_circuits c ORDER BY c.total_races_held DESC"),
            "openf1_races": len(rs.race_sessions()), "source": "F1DB (results, grids, pit stops 1994+) · OpenF1 (weather, tyres, race control 2023+)"}


def search(text: str) -> dict:
    t = f"%{text.lower()}%"
    return {"drivers": db.q("SELECT id, name, total_race_wins AS wins, total_race_starts AS starts, total_championship_wins AS titles FROM f1db_drivers "
                            "WHERE LOWER(name) LIKE :t OR LOWER(id) LIKE :t ORDER BY total_race_starts DESC LIMIT 12", t=t),
            "constructors": db.q("SELECT id, name, total_race_wins AS wins, total_race_starts AS starts FROM f1db_constructors WHERE LOWER(name) LIKE :t "
                                 "ORDER BY total_race_starts DESC LIMIT 8", t=t),
            "circuits": db.q("SELECT id, full_name AS name, total_races_held AS races FROM f1db_circuits WHERE LOWER(full_name) LIKE :t OR LOWER(place_name) LIKE :t OR LOWER(id) LIKE :t OR LOWER(name) LIKE :t LIMIT 8", t=t),
            "races": db.q("SELECT r.id, r.year, r.round, g.full_name AS name FROM f1db_races r JOIN f1db_grands_prix g ON g.id=r.grand_prix_id "
                          "WHERE LOWER(g.full_name) LIKE :t OR LOWER(r.official_name) LIKE :t ORDER BY r.year DESC LIMIT 12", t=t)}


def season(year: int) -> dict:
    last = db.q("SELECT MAX(race_id) AS r FROM f1db_driver_standings WHERE year=:y", y=year)[0]["r"]
    ds = db.q("SELECT s.position_number AS pos, d.name, d.abbreviation AS code, s.driver_id, s.points FROM f1db_driver_standings s "
              "JOIN f1db_drivers d ON d.id=s.driver_id WHERE s.race_id=:r ORDER BY s.position_display_order", r=last) if last else []
    cs = db.q("SELECT s.position_number AS pos, c.name, s.constructor_id, s.points FROM f1db_constructor_standings s "
              "JOIN f1db_constructors c ON c.id=s.constructor_id WHERE s.race_id=:r ORDER BY s.position_display_order", r=last) if last else []
    races = db.q("""SELECT r.id AS race_id, r.round, r.date, g.name AS gp, r.circuit_id, w.driver_id AS winner_id, d.name AS winner, c.name AS constructor,
                           w.grid_position_number AS winner_grid, w.pit_stops AS winner_stops,
                           (SELECT COUNT(*) FROM f1db_race_results x WHERE x.race_id=r.id AND x.position_number IS NULL AND x.position_text NOT IN ('DNS','DNQ','DNPQ','EX')) AS dnfs
                    FROM f1db_races r JOIN f1db_grands_prix g ON g.id=r.grand_prix_id
                    LEFT JOIN f1db_race_results w ON w.race_id=r.id AND w.position_number=1
                    LEFT JOIN f1db_drivers d ON d.id=w.driver_id LEFT JOIN f1db_constructors c ON c.id=w.constructor_id
                    WHERE r.year=:y ORDER BY r.round""", y=year)
    prog = db.df("SELECT s.round, s.driver_id, s.points FROM f1db_driver_standings s WHERE s.year=:y", y=year)
    top = [d["driver_id"] for d in ds[:6]]
    progression = []
    if len(prog):
        piv = prog[prog.driver_id.isin(top)].pivot_table(index="round", columns="driver_id", values="points").reset_index()
        progression = piv.to_dict("records")
    col = colours()["driver"]
    return {"year": year, "drivers": ds, "constructors": cs, "races": races, "progression": progression,
            "progression_keys": [{"driver_id": d["driver_id"], "code": d["code"], "colour": col.get(d["driver_id"], {}).get("colour")} for d in ds[:6]],
            "source": "F1DB", "tag": "OBSERVED"}


def circuit(circuit_id: str) -> dict:
    c = db.q("SELECT * FROM f1db_circuits WHERE id=:c", c=circuit_id)
    if not c:
        return {"available": False, "reason": "Unknown circuit."}
    races = db.q("""SELECT r.id AS race_id, r.year, g.name AS gp, d.name AS winner, k.name AS constructor, w.grid_position_number AS winner_grid,
                           w.pit_stops AS winner_stops, w.time AS race_time,
                           (SELECT COUNT(*) FROM f1db_race_results x WHERE x.race_id=r.id AND x.position_number IS NULL AND x.position_text NOT IN ('DNS','DNQ','DNPQ','EX')) AS dnfs,
                           (SELECT AVG(p.stops) FROM (SELECT MAX(stop) AS stops FROM f1db_pit_stops ps WHERE ps.race_id=r.id GROUP BY ps.driver_id) p) AS avg_stops,
                           (SELECT MIN(f.time_millis) FROM f1db_fastest_laps f WHERE f.race_id=r.id) AS fastest_ms
                    FROM f1db_races r JOIN f1db_grands_prix g ON g.id=r.grand_prix_id
                    JOIN f1db_race_results w ON w.race_id=r.id AND w.position_number=1
                    JOIN f1db_drivers d ON d.id=w.driver_id JOIN f1db_constructors k ON k.id=w.constructor_id
                    WHERE r.circuit_id=:c ORDER BY r.year DESC LIMIT 40""", c=circuit_id)
    grid = db.q("""SELECT w.grid_position_number AS grid, COUNT(*) AS wins FROM f1db_races r JOIN f1db_race_results w ON w.race_id=r.id AND w.position_number=1
                   WHERE r.circuit_id=:c AND w.grid_position_number IS NOT NULL GROUP BY w.grid_position_number ORDER BY grid""", c=circuit_id)
    first = db.q("""SELECT r.year, AVG(p.lap) AS first_stop_lap, COUNT(*) AS n FROM f1db_pit_stops p JOIN f1db_races r ON r.id=p.race_id
                    WHERE r.circuit_id=:c AND p.stop=1 AND r.year>=2011 GROUP BY r.year ORDER BY r.year DESC LIMIT 12""", c=circuit_id)
    ov = db.q("""SELECT r.year, AVG(ABS(x.positions_gained)) AS avg_abs_change FROM f1db_race_results x JOIN f1db_races r ON r.id=x.race_id
                 WHERE r.circuit_id=:c AND x.positions_gained IS NOT NULL AND r.year>=2000 GROUP BY r.year ORDER BY r.year DESC LIMIT 12""", c=circuit_id)
    wins = db.q("""SELECT d.name, COUNT(*) AS wins FROM f1db_races r JOIN f1db_race_results w ON w.race_id=r.id AND w.position_number=1
                   JOIN f1db_drivers d ON d.id=w.driver_id WHERE r.circuit_id=:c GROUP BY d.name ORDER BY wins DESC LIMIT 8""", c=circuit_id)
    return {"available": True, "circuit": c[0], "races": races, "wins_by_grid": grid, "first_stop": first, "position_change": ov, "most_wins": wins,
            "notes": ["Position change = mean |grid − finish| per classified car (a proxy for overtaking; true on-track passes are not in the sources).",
                      "Pit-stop data starts in 1994; first-stop laps shown from 2011 (refuelling ban era)."], "source": "F1DB", "tag": "OBSERVED"}


def driver_history(driver_id: str) -> dict:
    d = db.q("SELECT * FROM f1db_drivers WHERE id=:d", d=driver_id)
    if not d:
        return {"available": False, "reason": "Unknown driver."}
    seasons = db.q("""SELECT x.year, COUNT(*) AS starts, SUM(CASE WHEN x.position_number=1 THEN 1 ELSE 0 END) AS wins,
                             SUM(CASE WHEN x.position_number<=3 THEN 1 ELSE 0 END) AS podiums, SUM(COALESCE(x.points,0)) AS points,
                             AVG(x.grid_position_number) AS avg_grid, AVG(x.position_number) AS avg_finish,
                             SUM(CASE WHEN x.position_number IS NULL THEN 1 ELSE 0 END) AS dnfs, AVG(x.positions_gained) AS avg_gain
                      FROM f1db_race_results x WHERE x.driver_id=:d AND x.position_text NOT IN ('DNS','DNQ','DNPQ','EX') GROUP BY x.year ORDER BY x.year""", d=driver_id)
    circuits = db.q("""SELECT r.circuit_id, c.name, COUNT(*) AS starts, AVG(x.position_number) AS avg_finish, AVG(x.grid_position_number) AS avg_grid,
                              SUM(CASE WHEN x.position_number=1 THEN 1 ELSE 0 END) AS wins
                       FROM f1db_race_results x JOIN f1db_races r ON r.id=x.race_id JOIN f1db_circuits c ON c.id=r.circuit_id
                       WHERE x.driver_id=:d AND x.position_text NOT IN ('DNS','DNQ','DNPQ','EX') GROUP BY r.circuit_id, c.name HAVING COUNT(*)>=2 ORDER BY avg_finish LIMIT 30""", d=driver_id)
    return {"available": True, "driver": d[0], "seasons": seasons, "circuits": circuits, "source": "F1DB", "tag": "OBSERVED"}


@cached(ttl=900)
def race_profiles() -> pd.DataFrame:
    """One feature row per stored race (OpenF1, 2023+) for similarity search."""
    if not db.has_table("of1_weather"):
        return pd.DataFrame()
    s = db.df("SELECT session_key, year, location, circuit_key, circuit_short_name, date_start FROM of1_sessions WHERE session_name='Race'")
    w = db.df("SELECT session_key, AVG(track_temperature) AS track_temp, AVG(air_temperature) AS air_temp, AVG(humidity) AS humidity, "
              "AVG(wind_speed) AS wind, AVG(CASE WHEN rainfall>0 THEN 1.0 ELSE 0.0 END) AS rain_share FROM of1_weather GROUP BY session_key")
    rc = db.df("SELECT session_key, SUM(CASE WHEN message LIKE '%SAFETY CAR DEPLOYED%' AND message NOT LIKE '%VIRTUAL%' THEN 1 ELSE 0 END) AS sc, "
               "SUM(CASE WHEN message LIKE '%VSC DEPLOYED%' OR message LIKE '%VIRTUAL SAFETY CAR DEPLOYED%' THEN 1 ELSE 0 END) AS vsc, "
               "SUM(CASE WHEN flag='RED' THEN 1 ELSE 0 END) AS red FROM of1_race_control GROUP BY session_key")
    st = db.df("SELECT session_key, driver_number, MAX(stint_number)-1 AS stops FROM of1_stints GROUP BY session_key, driver_number")
    stops = st.groupby("session_key")["stops"].mean().rename("avg_stops").reset_index()
    win = db.df("SELECT r.session_key, r.driver_number AS winner_number, d.name_acronym AS winner FROM of1_session_result r "
                "LEFT JOIN of1_drivers d ON d.session_key=r.session_key AND d.driver_number=r.driver_number WHERE r.position=1")
    ws = db.df("SELECT session_key, driver_number, stint_number, compound, lap_start, lap_end FROM of1_stints")
    strat, first = {}, {}
    for r in win.itertuples():
        g = ws[(ws.session_key == r.session_key) & (ws.driver_number == r.winner_number)].sort_values("stint_number")
        strat[r.session_key] = " → ".join(f"{(x.compound or '?')[0]}{'' if pd.isna(x.lap_end) or pd.isna(x.lap_start) else int(x.lap_end - x.lap_start + 1)}" for x in g.itertuples())
        first[r.session_key] = float(g.iloc[0].lap_end) if len(g) > 1 and not pd.isna(g.iloc[0].lap_end) else None
    f = s.merge(w, on="session_key").merge(rc, on="session_key", how="left").merge(stops, on="session_key", how="left").merge(win, on="session_key", how="left")
    f["winner_strategy"] = f.session_key.map(strat); f["winner_first_stop"] = f.session_key.map(first)
    return f


def similar(session_key: int, lap: int | None = None, k: int = 6) -> dict:
    """Stored races most similar to the current conditions (weather so far + circuit). Similarity is not prophecy."""
    f = race_profiles()
    st = rs.state(session_key, lap)
    d = rs.load(session_key)
    if not len(f):
        return {"available": False, "reason": "No OpenF1 race history stored yet."}
    w = d["weather"]
    wk = w[w.date <= (st["T"] or 0)] if len(w) else w
    if not len(wk):
        return {"available": False, "reason": "No weather observations for this session to compare with."}
    cur = {"track_temp": float(wk.track_temperature.mean()), "air_temp": float(wk.air_temperature.mean()), "humidity": float(wk.humidity.mean()),
           "wind": float(wk.wind_speed.mean()), "rain_share": float((wk.rainfall > 0).mean())}
    dims = ["track_temp", "air_temp", "humidity", "wind", "rain_share"]
    wts = {"track_temp": 1.0, "air_temp": 0.6, "humidity": 0.5, "wind": 0.5, "rain_share": 2.0}
    pool = f[(f.session_key != session_key) & (f.date_start < d["session"]["date_start"])].dropna(subset=dims).copy()
    if not len(pool):
        return {"available": False, "reason": "No earlier races stored to compare with."}
    sd = f[dims].std().replace(0, 1)
    pool["distance"] = np.sqrt(sum(wts[c] * ((pool[c] - cur[c]) / sd[c]) ** 2 for c in dims))
    same = pool.circuit_key == d["session"]["circuit_key"]
    pool["score"] = pool.distance - 0.8 * same
    pool["same_circuit"] = same
    cols = ["session_key", "year", "location", "circuit_short_name", "same_circuit", "distance", "track_temp", "air_temp", "rain_share", "humidity",
            "wind", "sc", "vsc", "red", "avg_stops", "winner", "winner_strategy", "winner_first_stop"]
    top = pool.sort_values("score").head(k)[cols].to_dict("records")
    here = pool[same].sort_values("year", ascending=False)[cols].to_dict("records")
    f1 = d["f1db"]
    prev5 = []
    if f1:
        prev5 = db.q("""SELECT r.year, dr.name AS winner, k.name AS constructor, w.grid_position_number AS winner_grid, w.pit_stops AS winner_stops,
                        (SELECT COUNT(*) FROM f1db_race_results x WHERE x.race_id=r.id AND x.position_number IS NULL AND x.position_text NOT IN ('DNS','DNQ','DNPQ','EX')) AS dnfs
                        FROM f1db_races r JOIN f1db_race_results w ON w.race_id=r.id AND w.position_number=1 JOIN f1db_drivers dr ON dr.id=w.driver_id
                        JOIN f1db_constructors k ON k.id=w.constructor_id WHERE r.circuit_id=:c AND r.year<:y ORDER BY r.year DESC LIMIT 5""",
                     c=f1["circuit_id"], y=f1["year"])
    # starting-grid similarity: overlap of the constructors on the first three rows
    grid_now = {r["team"] for r in st["rows"] if r["grid"] and r["grid"] <= 6}
    for t in top + here:
        g = db.q("SELECT d.team_name FROM of1_position p JOIN of1_drivers d ON d.session_key=p.session_key AND d.driver_number=p.driver_number "
                 "WHERE p.session_key=:k AND p.date=(SELECT MIN(date) FROM of1_position WHERE session_key=:k) AND p.position<=6", k=t["session_key"]) if db.has_table("of1_position") else []
        teams = {x["team_name"] for x in g}
        t["grid_overlap"] = round(len(teams & grid_now) / max(1, len(teams | grid_now)), 2) if teams and grid_now else None
    return {"available": True, "current": cur, "lap": st["lap"], "similar": top, "same_circuit": here, "previous_at_circuit_f1db": prev5,
            "method": "Standardised weighted Euclidean distance on observed track temperature, air temperature, humidity, wind and rain share "
                      "(up to the as-of lap for the current race), with a bonus for the same circuit.",
            "caveat": "Similar conditions do not imply a similar outcome — cars, tyres and regulations differ between seasons. Use as context, not as a forecast.",
            "tag": "OBSERVED (OpenF1 2023+) + HISTORICAL comparison"}


# ---------------------------------------------------------------- 7b. analytics
@cached(ttl=900)
def analytics(year: int | None = None) -> dict:
    year = year or db.q("SELECT MAX(year) AS y FROM f1db_race_results")[0]["y"]
    col = colours()
    r = db.df("""SELECT x.race_id, x.round, x.driver_id, x.constructor_id, x.position_number, x.grid_position_number, x.points, x.positions_gained,
                        x.reason_retired, x.position_text, x.qualification_position_number AS q FROM f1db_race_results x WHERE x.year=:y""", y=year)
    r = r[~r.position_text.isin(["DNS", "DNQ", "DNPQ", "EX"])]
    dn, cn = _names()
    drivers = []
    for did, g in r.groupby("driver_id"):
        mate = r[(r.constructor_id.isin(g.constructor_id.unique())) & (r.driver_id != did)]
        j = g.merge(mate[["race_id", "constructor_id", "q", "position_number"]], on=["race_id", "constructor_id"], suffixes=("", "_m"))
        qh = j.dropna(subset=["q", "q_m"]); rh = j.dropna(subset=["position_number", "position_number_m"])
        drivers.append({"driver_id": did, "name": dn.get(did, {}).get("name", did), "code": dn.get(did, {}).get("abbreviation"),
                        "constructor": cn.get(g.constructor_id.iloc[-1]), "colour": col["driver"].get(did, {}).get("colour"),
                        "starts": int(len(g)), "wins": int((g.position_number == 1).sum()), "podiums": int((g.position_number <= 3).sum()),
                        "points": float(g.points.fillna(0).sum()), "avg_grid": float(g.grid_position_number.mean()), "avg_quali": float(g.q.mean()),
                        "avg_finish": float(g.position_number.mean()), "avg_gain": float(g.positions_gained.mean()),
                        "finish_sd": float(g.position_number.std()), "dnfs": int(g.position_number.isna().sum()),
                        "quali_h2h": f"{int((qh.q < qh.q_m).sum())}–{int((qh.q > qh.q_m).sum())}" if len(qh) else None,
                        "race_h2h": f"{int((rh.position_number < rh.position_number_m).sum())}–{int((rh.position_number > rh.position_number_m).sum())}" if len(rh) else None})
    drivers.sort(key=lambda d: -d["points"])
    pit = db.df("SELECT constructor_id, time_millis FROM f1db_pit_stops WHERE year=:y AND time_millis < 60000", y=year)
    pmed = pit.groupby("constructor_id")["time_millis"].agg(["median", "count"]) if len(pit) else pd.DataFrame()
    retired = r.reason_retired.fillna("").str.lower()
    r["mech"] = (retired != "") & ~retired.str.contains("|".join(prerace.NON_MECH))
    speed = {}
    last = rs.race_sessions(1)
    if last:
        sk = last[0]["session_key"]
        sp = db.df("SELECT l.driver_number, MAX(l.st_speed) AS top, d.team_name FROM of1_laps l JOIN of1_drivers d ON d.session_key=l.session_key AND "
                   "d.driver_number=l.driver_number WHERE l.session_key=:k GROUP BY l.driver_number, d.team_name", k=sk)
        tm = {v["team"]: k for k, v in col["constructor"].items()}
        speed = {tm.get(t): float(v) for t, v in sp.groupby("team_name")["top"].max().items() if tm.get(t)}
    cons = []
    for cid, g in r.groupby("constructor_id"):
        cons.append({"constructor_id": cid, "name": cn.get(cid, cid), "colour": col["constructor"].get(cid, {}).get("colour"),
                     "points": float(g.points.fillna(0).sum()), "wins": int((g.position_number == 1).sum()), "podiums": int((g.position_number <= 3).sum()),
                     "avg_finish": float(g.position_number.mean()), "avg_quali": float(g.q.mean()), "dnf_rate": float(g.position_number.isna().mean()),
                     "mech_dnf_rate": float(g.mech.mean()),
                     "pit_median_s": float(pmed.loc[cid, "median"] / 1000) if cid in pmed.index else None,
                     "pit_stops_n": int(pmed.loc[cid, "count"]) if cid in pmed.index else 0, "speed_trap_kmh": speed.get(cid)})
    cons.sort(key=lambda c: -c["points"])
    return {"year": year, "drivers": drivers, "constructors": cons, "speed_trap_session": last[0]["location"] if last else None,
            "notes": ["Pit time = total pit-lane time from F1DB (entry to exit), not the stationary time.",
                      "Speed trap = fastest speed-trap reading per team in the most recent stored race (OpenF1) — depends on wing level and slipstream.",
                      "Cornering performance is not available from these sources as a clean metric and is not estimated.",
                      "Wet-weather form needs wet races in the lap-level history (2023+) and is small-sample; see Historical Race Intelligence."],
            "source": "F1DB + OpenF1", "tag": "OBSERVED"}


# ---------------------------------------------------------------- 11. advisor
def advisor(session_key: int, lap: int | None, driver: int | None) -> dict:
    """Plain-English recommendations assembled only from computed module outputs — nothing is invented."""
    ctx = sim.context(session_key, lap)
    st, m = ctx["st"], ctx["m"]
    total = st["total_laps"] or st["max_lap"]
    run = [r for r in st["rows"] if r["status"] == "RUNNING"]
    me = next((r for r in run if r["driver_number"] == driver), run[0] if run else None)
    out = {"lap": st["lap"], "total_laps": total, "focus": me and me["driver_number"], "focus_code": me and me["code"], "recommendations": [],
           "guardrails": "Built from observed timing data, fitted models and labelled assumptions. No team radio, telemetry or incidents are invented; "
                         "if an input is missing the related recommendation is omitted."}
    if not me or total - st["lap"] < 2 or st["lap"] < 2:
        out["note"] = "Recommendations are generated while a race is in progress (move the lap control to a lap during the race)."
        return out
    recs = []
    conf = lambda s: {"score": round(float(np.clip(s, 0.05, 0.95)), 2), "level": "HIGH" if s >= 0.7 else "MEDIUM" if s >= 0.45 else "LOW"}
    sv = strategy_view(session_key, st["lap"], me["driver_number"])
    # 1 weather
    try:
        wi = weather.intelligence(session_key, st["lap"], me["driver_number"])
        rec = wi.get("recommendation")
        if rec and wi["scenario_type"] in ("A", "B"):
            fs = wi["forecast"]["summary"]
            recs.append({"type": "WEATHER", "title": "Tyre-class transition" if wi["scenario_type"] == "A" else "Switch back to slicks",
                         "situation": rec["text"],
                         "supporting": [f"OBSERVED · track {st['weather']['track_temperature']}°C, rain sensor {'ON' if st['weather']['rainfall'] else 'off'}, wetness proxy {ctx['wet']['wetness']}" if st["weather"] else "OBSERVED · no track weather",
                                        f"FORECAST · Open-Meteo max precipitation probability {fs['max_prob']}%, {fs['total_mm']} mm in window" if fs.get("max_prob") is not None else "FORECAST · unavailable",
                                        f"MODEL · crossover on lap {rec.get('crossover_lap')}"],
                         "decision": rec["recommended"], "advantage": f"{rec.get('expected_gain_s', 0):+.1f} s and {rec.get('expected_gain_positions', 0):+.2f} positions vs “{rec['alternative']}”",
                         "risk": rec["risks"][0], "confidence": rec["confidence"]})
            if wi.get("forecast_observation_mismatch"):
                recs.append({"type": "DATA", "title": "Forecast and track sensor disagree", "situation": wi["forecast_observation_mismatch"],
                             "supporting": ["OBSERVED · OpenF1 rain sensor", "FORECAST · Open-Meteo area model"], "decision": "Weight the trackside sensor for the next few laps; keep watching the radar trend.",
                             "advantage": "Avoids a premature stop for wet-weather tyres.", "risk": "A sensor at one point of the circuit can miss a shower elsewhere.", "confidence": conf(0.55)})
    except Exception as e:
        out.setdefault("omitted", []).append(f"Weather recommendation omitted: {e}")
    # 2 neutralisation in progress
    if st["track_status"] in ("SC", "VSC"):
        sc = safety_car(session_key, st["lap"], me["driver_number"])
        v = (sc.get("verdicts") or {}).get("sc" if st["track_status"] == "SC" else "vsc")
        if v:
            recs.append({"type": "SAFETY CAR", "title": f"{st['track_status']} deployed — cheap stop available",
                         "situation": f"Race control shows {st['track_status']} on lap {st['lap']}. {me['code']} is P{me['position']} on {me['compound']} tyres ({me['tyre_age']} laps).",
                         "supporting": [f"OBSERVED · race control status {st['track_status']}", f"HISTORICAL · green-flag pit loss {sc['pit_loss']['green']} s ({sc['pit_loss']['source']})",
                                        f"ASSUMPTION · stop costs {sc['pit_loss']['sc' if st['track_status'] == 'SC' else 'vsc']} s under {st['track_status']}"],
                         "decision": "Pit this lap" if v["better"] == "PIT" else "Stay out and keep track position",
                         "advantage": f"{-v['pit_minus_stay_positions']:+.2f} expected positions for pitting vs staying out",
                         "risk": "Neutralisation length is unknown; a short one reduces the saving." if v["better"] == "PIT" else "Rivals on fresh tyres attack at the restart.",
                         "confidence": conf(0.4 + min(0.5, abs(v["pit_minus_stay_positions"]) / 2))})
    # 3 pit window / track position
    strat = [s for s in sv.get("strategies", []) if s.get("exp_pos") is not None and s["rule_ok"]]
    best = next((s for s in strat if s.get("recommended")), None)
    if best and me["compound"] in sg.SLICKS:
        w = sv.get("window")
        nxt = best["recommended_pit_lap"]
        if nxt and w:
            opts = weather.compare(ctx, me["driver_number"], [
                {"label": "now", "plan": [(st["lap"] + 1, best["plan"][0]["compound"])] + [(x["lap"], x["compound"]) for x in best["plan"][1:]]},
                {"label": "optimal", "plan": [(x["lap"], x["compound"]) for x in best["plan"]]}], {"random_incidents": False})
            if len(opts) == 2:
                now, opt = opts
                in_window = w["open"] <= st["lap"] + 1 <= w["close"]
                dpos = now["exp_pos"] - opt["exp_pos"]
                if nxt - st["lap"] <= 1 or (in_window and dpos < -0.05):
                    decision = f"Box this lap for {best['plan'][0]['compound'].lower()}s"
                elif now["blocked_laps"] > opt["blocked_laps"] + 0.5 and dpos > 0.05:
                    decision = f"Extend the stint to lap {nxt} — pitting now rejoins in traffic"
                else:
                    decision = f"Stay out; target lap {nxt} (window laps {w['open']}–{w['close']})"
                recs.append({"type": "PIT WINDOW" if "Extend" not in decision else "TRACK POSITION",
                             "title": "Pit window open" if in_window else f"Pit window opens on lap {w['open']}",
                             "situation": f"{me['code']} P{me['position']} on {me['compound'].lower()}s, {me['tyre_age']} laps old, {total - st['lap']} laps to go. "
                                          f"Optimiser's best plan: {best['name']} — next stop lap {nxt} ({best['plan'][0]['compound'].lower()}).",
                             "supporting": [f"OBSERVED · tyre age {me['tyre_age']}, gap ahead {me['interval_s']} s",
                                            f"MODEL · {me['compound'].lower()} wear {m['compounds'][me['compound']]['deg']:.3f} s/lap ({m['compounds'][me['compound']]['source']})",
                                            f"MODEL · pit loss {sv['pit_loss']['seconds']} s ({sv['pit_loss']['source']})",
                                            f"MODEL · pit now: expected P{now['exp_pos']:.1f}, {now['blocked_laps']} laps in traffic; pit lap {nxt}: expected P{opt['exp_pos']:.1f}, {opt['blocked_laps']} laps in traffic"],
                             "decision": decision, "advantage": f"{abs(dpos):.2f} expected positions and {abs(now['time_vs_first'] - opt['time_vs_first']):.1f} s between the two options",
                             "risk": "A Safety Car before the planned lap would make the later stop cheaper; one after an early stop costs track position.",
                             "confidence": conf(0.35 + min(0.5, abs(dpos)) + (0.1 if m["n_laps"] > 150 else 0))})
        alt = sorted([s for s in strat if s is not best], key=lambda s: s["exp_pos"])
        if alt:
            a = alt[0]
            recs.append({"type": "STRATEGY", "title": f"Recommended: {best['name']}",
                         "situation": f"Across {sv.get('n_sims')} simulated races, {best['name']} gives {me['code']} the best expected finish.",
                         "supporting": [f"MODEL · {best['name']}: expected P{best['exp_pos']:.1f}, win {best['p_win'] * 100:.0f}%, podium {best['p_podium'] * 100:.0f}%",
                                        f"MODEL · {a['name']}: expected P{a['exp_pos']:.1f}, win {a['p_win'] * 100:.0f}%, {a['exp_time_delta']:+.1f} s",
                                        f"MODEL · tyre model on {m['n_laps']} green-flag laps; prior: {m['prior']}"],
                         "decision": " then ".join(f"lap {x['lap']} → {x['compound'].lower()}" for x in best["plan"]) or "No further stop",
                         "advantage": f"{a['exp_pos'] - best['exp_pos']:+.2f} expected positions vs {a['name']}",
                         "risk": f"Finish range P{best['pos_p10']}–P{best['pos_p90']} (10th–90th percentile of simulations).",
                         "confidence": conf(0.3 + min(0.6, (a["exp_pos"] - best["exp_pos"]) * 1.5))})
    # 4 undercut attack / defence
    for u in sv.get("undercuts", []):
        if u["driver_number"] == me["driver_number"] or u["ahead"] == me["code"]:
            attack = u["driver_number"] == me["driver_number"]
            if not attack and not u["undercut_on"]:
                continue
            recs.append({"type": "UNDERCUT" if attack else "DEFEND UNDERCUT",
                         "title": (f"Undercut on {u['ahead']} is {'ON' if u['undercut_on'] else 'not on'}" if attack else f"{u['driver']} can undercut"),
                         "situation": f"{u['driver']} is {u['gap_s']} s behind {u['ahead']}. Fresh tyres are worth {u['fresh_tyre_gain_per_lap']} s/lap against {u['ahead']}'s current set.",
                         "supporting": [f"OBSERVED · gap {u['gap_s']} s; {u['inputs']}", f"MODEL · two-lap undercut gain {u['undercut_gain_2laps']} s (after warm-up) vs gap → margin {u['undercut_margin']} s"],
                         "decision": ("Pit now to undercut" if u["undercut_on"] else "Do not pit for the undercut — extend and look at the overcut") if attack else "Cover: pit the lap they pit, or respond next lap",
                         "advantage": f"{u['undercut_margin']:+.1f} s margin over the gap" , "risk": "Rejoining in traffic or a slow stop erases a margin under ~1 s.",
                         "confidence": conf(0.4 + min(0.45, abs(u["undercut_margin"]) / 3))})
    # 5 tyre life
    if me["compound"] in sg.SLICKS and me["tyre_age"] is not None and me["tyre_age"] > sg.LIFE_FRAC[me["compound"]] * total:
        recs.append({"type": "TYRE LIFE", "title": "Tyres beyond modelled life", "situation": f"{me['code']}'s {me['compound'].lower()}s are {me['tyre_age']} laps old; modelled usable life here is ~{int(sg.LIFE_FRAC[me['compound']] * total)} laps.",
                     "supporting": ["OBSERVED · tyre age from OpenF1 stints", "ASSUMPTION · usable-life share of race distance"], "decision": "Bring the stop forward unless track position is decisive",
                     "advantage": "Avoids the wear cliff (modelled up to 3 s/lap).", "risk": "Life is an assumption — watch the actual lap-time trend.", "confidence": conf(0.4)})
    # explanation of the win probability
    try:
        ml = inrace.predict(session_key, st["lap"])
        if ml is not None:
            row = ml[ml.driver_number == me["driver_number"]]
            if len(row):
                out["win_explanation"] = {"p_win_ml": float(row.iloc[0].ml_win), "factors": row.iloc[0].explain,
                                          "note": "SHAP contributions (log-odds) of the in-race XGBoost winner model for this driver at this lap."}
    except Exception:
        pass
    order = {"SAFETY CAR": 0, "WEATHER": 1, "PIT WINDOW": 2, "TRACK POSITION": 2, "UNDERCUT": 3, "DEFEND UNDERCUT": 3, "STRATEGY": 4, "TYRE LIFE": 5, "DATA": 6}
    out["recommendations"] = sorted(recs, key=lambda r: order.get(r["type"], 9))
    return out


# ---------------------------------------------------------------- 16. data health & models
def sources() -> dict:
    now = time.time()
    h = {r["source"]: r for r in db.q("SELECT * FROM source_health")}
    errs = db.q("SELECT ts, source, url, error FROM source_errors ORDER BY ts DESC LIMIT 40")
    ing = db.q("SELECT source, dataset, MAX(ts) AS last, SUM(n_rows) AS n_rows, SUM(rejected) AS rejected, COUNT(*) AS runs FROM ingest_log GROUP BY source, dataset ORDER BY source, dataset")
    cov = {}
    cov["f1db"] = db.q("SELECT MIN(year) AS first, MAX(year) AS last, COUNT(DISTINCT race_id) AS races, COUNT(*) AS n_rows FROM f1db_race_results")[0] if db.has_table("f1db_race_results") else None
    if db.has_table("of1_laps"):
        cov["openf1"] = db.q("SELECT MIN(s.year) AS first, MAX(s.year) AS last, COUNT(DISTINCT l.session_key) AS races, COUNT(*) AS n_rows FROM of1_laps l JOIN of1_sessions s ON s.session_key=l.session_key")[0]
    out = []
    for k, meta in SOURCES.items():
        r = h.get(k, {})
        age = now - r["last_success"] if r.get("last_success") else None
        out.append({"source": k, **meta, "status": r.get("status", "not used yet"), "last_success": r.get("last_success"), "last_attempt": r.get("last_attempt"),
                    "freshness_s": age, "requests": r.get("requests", 0), "failures": r.get("failures", 0), "last_error": r.get("last_error"),
                    "last_error_at": r.get("last_error_at"), "stored": cov.get(k),
                    "datasets": [x for x in ing if x["source"] == k]})
    missing = []
    if db.has_table("of1_sessions") and db.has_table("of1_laps"):
        n = db.q("SELECT COUNT(*) AS n FROM of1_sessions WHERE session_name='Race' AND date_end < :t AND session_key NOT IN (SELECT DISTINCT session_key FROM of1_laps)", t=now)[0]["n"]
        if n: missing.append(f"{n} past race session(s) listed by OpenF1 have no laps stored (not yet backfilled or not published).")
        for t, label in (("of1_pit", "pit-lane timing"), ("of1_weather", "track weather"), ("of1_stints", "tyre stints")):
            if db.has_table(t):
                n = db.q(f"SELECT COUNT(*) AS n FROM (SELECT DISTINCT session_key FROM of1_laps) l WHERE session_key NOT IN (SELECT DISTINCT session_key FROM {t})")[0]["n"]
                if n: missing.append(f"{n} stored race(s) have no {label}.")
    missing += ["Lap-by-lap timing, tyres and weather exist only from 2023 (OpenF1); earlier seasons have results-level data (F1DB).",
                "No source provides track-surface wetness, tyre temperatures/pressures, fuel load or team radio."]
    return {"sources": out, "errors": errs, "missing": missing, "cache_backend": cache.BACKEND, "database": db.engine.url.get_backend_name(), "now": now}


def models() -> dict:
    rows = db.q("SELECT name, version, created, train_through, n_rows, metrics, active FROM model_registry ORDER BY created DESC")
    for r in rows:
        r["metrics"] = json.loads(r["metrics"]) if r["metrics"] else {}
    snaps = db.q("SELECT kind, COUNT(*) AS n, MAX(ts) AS last FROM prediction_snapshots GROUP BY kind")
    return {"models": rows, "prediction_snapshots": snaps,
            "retraining": "Models are retrained by `python -m app.retrain` (also run on backend start-up when new completed races exist); a new version "
                          "only replaces the active one if its backtest log loss is not worse.",
            "validation": "Walk-forward by season (train on seasons < S, test on S). No random splits. Pre-race features use only earlier races; "
                          "in-race features only records up to the lap."}
