"""Monte Carlo race simulator (vectorised over simulations).

Starts from the reconstructed race state and plays the remaining laps N times with stochastic lap-time
noise, pit-stop variation, retirements, safety cars and a wetness timeline. Parameters come from the tyre
model fitted on the session; scenario inputs are assumptions supplied by the caller and are echoed back.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import db, racestate as rs, strategy as sg
from .cache import cached
from .config import MC_SIMS

PTS = np.array([25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * 30)
CI = {c: i for i, c in enumerate(sg.COMPOUNDS)}
W_SLICK_TO_INTER, W_INTER_TO_SLICK, W_INTER_TO_WET = 0.27, 0.22, 0.66


def wet_penalty(comp_idx: np.ndarray, w) -> np.ndarray:
    """Lap-time penalty as a fraction of the dry lap, by tyre class and track wetness w∈[0,1]. ASSUMPTION
    (shape chosen so crossovers sit at w≈0.26 slick↔inter and w≈0.65 inter↔wet)."""
    w = np.asarray(w, float)
    slick = 0.55 * w ** 1.5
    inter = 0.07 + 0.45 * (w - 0.3) ** 2
    wet = 0.10 + 0.08 * (1 - w)
    return np.where(comp_idx <= 2, slick, np.where(comp_idx == 3, inter, wet))


def crossover_table() -> list[dict]:
    ws = np.round(np.arange(0, 1.01, 0.05), 2)
    return [{"wetness": float(w), "slick": float(wet_penalty(np.array(0), w)), "inter": float(wet_penalty(np.array(3), w)),
             "wet": float(wet_penalty(np.array(4), w))} for w in ws]


def wetness_path(w0: float, rain: list[float], track_temp: float | None, wind: float | None) -> np.ndarray:
    """Track wetness per lap from a rain-intensity timeline (0..1). ASSUMPTION: wetting 0.25·I^1.5 per lap; drying 0.02/lap at 25°C track, faster when hotter or windier."""
    dry = 0.02 * (1 + 0.03 * ((track_temp if track_temp is not None else 25) - 25)) * (1 + 0.02 * (wind or 0))
    dry = float(np.clip(dry, 0.006, 0.06))
    out, w = [], w0
    for r in rain:
        # light drizzle on a busy racing line barely wets it; heavy rain soaks it within a few laps
        w = w + 0.25 * r ** 1.5 - dry * (1 - min(1.0, r / 0.3))
        w = float(np.clip(w, 0, 1))
        out.append(w)
    return np.array(out)


def wetness_now(st: dict) -> dict:
    """Proxy for current track wetness from tyre choices of the field and the rain sensor. NOT a measurement."""
    run = [r for r in st["rows"] if r["status"] == "RUNNING" and r["compound"]]
    share_i = np.mean([r["compound"] == "INTERMEDIATE" for r in run]) if run else 0.0
    share_w = np.mean([r["compound"] == "WET" for r in run]) if run else 0.0
    wx = st["weather"] or {}
    rain = wx.get("rainfall") or 0
    rs15 = wx.get("rain_share_15min") or 0
    if share_w > 0.5: w = 0.85
    elif share_i + share_w > 0.5: w = 0.42 + 0.25 * rs15 + (0.08 if rain else 0)
    elif share_i + share_w > 0.15: w = 0.27 + 0.1 * rs15
    else: w = 0.22 * rs15 + (0.05 if rain else 0)
    return {"wetness": round(float(min(1, w)), 2), "share_on_inters": round(float(share_i), 2), "share_on_wets": round(float(share_w), 2),
            "rain_sensor": int(rain), "rain_share_15min": rs15,
            "method": "proxy from field tyre choice + trackside rain sensor (OpenF1); not a surface measurement"}


@cached(ttl=3600)
def hazards(circuit_key: int | None) -> dict:
    """Base rates per racing lap from stored race-control history (2023+) and F1DB retirements."""
    out = {"sc_per_lap": 0.012, "vsc_per_lap": 0.008, "source": "assumption (no race-control history stored)", "races": 0}
    if db.has_table("of1_race_control") and db.has_table("of1_session_result"):
        f = db.df("""SELECT rc.session_key, s.circuit_key, rc.message FROM of1_race_control rc JOIN of1_sessions s ON s.session_key=rc.session_key
                     WHERE s.session_name='Race' AND rc.category='SafetyCar' AND (rc.message LIKE '%DEPLOYED%')""")
        laps = db.df("SELECT r.session_key, s.circuit_key, MAX(r.number_of_laps) AS laps FROM of1_session_result r JOIN of1_sessions s "
                     "ON s.session_key=r.session_key WHERE s.session_name='Race' GROUP BY r.session_key, s.circuit_key")
        f["vsc"] = f.message.str.contains("VSC|VIRTUAL")
        def rate(fr, lp):
            tot = lp.laps.sum()
            return (float((~fr.vsc).sum() / tot), float(fr.vsc.sum() / tot)) if tot else (0.012, 0.008)
        if len(laps) >= 5:
            g_sc, g_vsc = rate(f, laps)
            out.update(sc_per_lap=g_sc, vsc_per_lap=g_vsc, races=int(len(laps)),
                       source=f"all {len(laps)} stored races (OpenF1 race control, 2023+)")
            lc = laps[laps.circuit_key == circuit_key]
            if len(lc) >= 3:   # shrink circuit rate towards the global rate
                c_sc, c_vsc = rate(f[f.circuit_key == circuit_key], lc)
                k = len(lc) / (len(lc) + 3)
                out.update(sc_per_lap=k * c_sc + (1 - k) * g_sc, vsc_per_lap=k * c_vsc + (1 - k) * g_vsc, circuit_races=int(len(lc)),
                           source=f"{len(lc)} races at this circuit blended with all {len(laps)} stored races (OpenF1, 2023+)")
            races_with = f[~f.vsc].session_key.nunique() / len(laps)
            out["share_races_with_sc"] = round(float(races_with), 3)
            out["share_races_with_vsc"] = round(float(f[f.vsc].session_key.nunique() / len(laps)), 3)
            out["share_races_red_flag"] = round(float(db.q(
                "SELECT COUNT(DISTINCT rc.session_key) AS n FROM of1_race_control rc JOIN of1_sessions s ON s.session_key=rc.session_key "
                "WHERE s.session_name='Race' AND rc.flag='RED'")[0]["n"] / len(laps)), 3)
    y = db.q("SELECT MAX(year) AS y FROM f1db_race_results")[0]["y"]
    r = db.q("SELECT AVG(CASE WHEN position_number IS NULL THEN 1.0 ELSE 0.0 END) AS dnf FROM f1db_race_results "
             "WHERE year >= :y AND position_text NOT IN ('DNS','DNQ','DNPQ','EX')", y=y - 1)[0]["dnf"]
    out["dnf_per_race"] = round(float(r or 0.1), 4)
    out["dnf_source"] = f"F1DB retirement rate, {y - 1}–{y}"
    return out


def context(session_key: int, lap: int | None = None) -> dict:
    """Everything the simulator needs at the as-of lap."""
    st = rs.state(session_key, lap)
    m = sg.tyre_model(session_key, st["lap"])
    hz = hazards(st["session"]["circuit_key"])
    return {"st": st, "m": m, "hz": hz, "wet": wetness_now(st)}


def default_plans(ctx: dict) -> dict:
    """Each running driver's own time-optimal plan (CP-SAT), used as the competitor baseline."""
    st, m = ctx["st"], ctx["m"]
    key = (st["session"]["session_key"], st["lap"])
    if _plans.get("key") == key:
        return _plans["val"]
    total, plans = st["total_laps"] or st["max_lap"], {}
    wx = st["weather"] or {}
    wpath = wetness_path(ctx["wet"]["wetness"], [0.3 if wx.get("rainfall") else 0.0] * max(1, total - st["lap"]),
                         wx.get("track_temperature"), wx.get("wind_speed"))
    dry_idx = np.nonzero(wpath < W_INTER_TO_SLICK - 0.03)[0]
    dry_lap = st["lap"] + 1 + int(dry_idx[0]) if len(dry_idx) else None   # lap at which slicks are expected to go on
    for r in st["rows"]:
        if r["status"] != "RUNNING":
            continue
        if r["compound"] in sg.WETS:
            if dry_lap is None or total - dry_lap < 3:
                plans[r["driver_number"]] = []
                continue
            opts = sg.strategies(m, dry_lap, total, None, 0, r["compounds_used"])
        else:
            opts = sg.strategies(m, st["lap"], total, r["compound"], r["tyre_age"] or 0, r["compounds_used"])
        opts = [p for p in opts if p["rule_ok"] and p["label"] != "D"]
        best = min(opts, key=lambda p: p["rel_time"]) if opts else None
        plans[r["driver_number"]] = [(x["lap"], x["compound"]) for x in best["plan"]] if best else []
    _plans.update(key=key, val=plans)
    return plans


_plans: dict = {}


def run(ctx: dict, plans: dict | None = None, scenario: dict | None = None, n: int = MC_SIMS, seed: int = 1,
        focus: int | None = None) -> dict:
    sc = scenario or {}
    st, m, hz = ctx["st"], ctx["m"], ctx["hz"]
    rows = [r for r in st["rows"] if r["status"] == "RUNNING" and r["gap_s"] is not None]
    D = len(rows)
    cur = int(sc.get("lap", st["lap"]))
    total = st["total_laps"] or st["max_lap"]
    R = total - cur
    if D == 0 or R <= 0:
        return {"error": "Race is not in progress at this lap — nothing left to simulate.", "drivers": []}
    rng = np.random.default_rng(seed)
    plans = dict(default_plans(ctx) if plans is None else plans)
    nums = [r["driver_number"] for r in rows]
    base = np.array([m["base"].get(d, m["field_base"] + 0.6) for d in nums])
    # A per-driver pace fitted on a handful of laps is noisy (and leaders manage their pace). Shrink each car's
    # pace towards the median of the cars running around it — race order already carries pace information —
    # with a weight that grows with the number of clean laps behind the estimate.
    nfit0 = m.get("n_by_driver", {})
    local = np.array([np.median(base[max(0, i - 3):i + 4]) for i in range(D)])
    wgt = np.array([nfit0.get(d, 0) / (nfit0.get(d, 0) + 12.0) for d in nums])
    base = wgt * base + (1 - wgt) * local
    sigma = np.array([m["sigma"].get(d, m["sigma_all"]) for d in nums])
    off = np.array([m["compounds"][c]["offset"] if c in sg.SLICKS else 0.0 for c in sg.COMPOUNDS])
    deg = np.array([m["compounds"][c]["deg"] if c in sg.SLICKS else 0.03 for c in sg.COMPOUNDS]) * (1 + 0.02 * sc.get("track_temp_delta", 0.0))
    life = np.array([sg.LIFE_FRAC.get(c, 0.6) * total for c in sg.COMPOUNDS])
    warm = np.array([sg.WARMUP[c] for c in sg.COMPOUNDS])
    pit_loss = float(sc.get("pit_loss") or m["pit_loss"]) + float(sc.get("pit_stop_extra", 0.0))
    comp0 = np.array([CI.get(r["compound"] or "MEDIUM", 1) for r in rows])
    age0 = np.array([r["tyre_age"] or 0 for r in rows], float)
    cum = np.tile(np.array([r["gap_s"] for r in rows], float), (n, 1))
    comp = np.tile(comp0, (n, 1)); age = np.tile(age0, (n, 1))
    alive = np.ones((n, D), bool)
    overrides = sc.get("overrides", {})          # {driver_number: {position, compound, tyre_age}}
    for i, d in enumerate(nums):
        o = overrides.get(d) or overrides.get(str(d))
        if o:
            if o.get("compound") in CI: comp[:, i] = CI[o["compound"]]
            if o.get("tyre_age") is not None: age[:, i] = float(o["tyre_age"])
            if o.get("gap_s") is not None: cum[:, i] = float(o["gap_s"])
    # plan arrays [D, K]
    K = max([len(p) for p in plans.values()] + [1])
    plan_lap = np.full((D, K), 10 ** 6); plan_comp = np.zeros((D, K), int)
    for i, d in enumerate(nums):
        for j, (pl, pc) in enumerate(sorted(plans.get(d, []))):
            plan_lap[i, j] = pl; plan_comp[i, j] = CI[pc]
    ptr = np.zeros((n, D), int)
    # manual drivers follow their forced plan; automatic weather/SC reactions resume once it is used up
    mset = set(int(x) for x in sc.get("manual", []))
    never = set(int(x) for x in sc.get("no_reaction", []))      # these drivers never react to weather/SC on their own
    manual_until = np.array([10 ** 6 if d in never else (len(plans.get(d, [])) if d in mset else 0) for d in nums])
    hold = {int(k): int(v) for k, v in (sc.get("hold") or {}).items()}   # {driver: lap} no automatic reaction up to that lap
    hold_until = np.array([hold.get(d, 0) for d in nums])
    # uncertainty about each car's true pace (larger when few clean laps were available to fit it)
    nfit = m.get("n_by_driver", {})
    base_sd = np.array([0.2 if nfit.get(d, 0) >= 8 else 0.35 for d in nums]) * float(sc.get("pace_uncertainty", 1.0))
    base = base + rng.normal(0, 1, (n, D)) * base_sd[None, :]
    sigma = sigma * float(sc.get("variability", 1.0))
    # wetness timeline
    w0 = float(sc["wetness"]) if sc.get("wetness") is not None else ctx["wet"]["wetness"]
    wx = st["weather"] or {}
    rain = list(sc.get("rain") or [])
    rain = (rain + [rain[-1] if rain else (0.3 if (wx.get("rainfall") and sc.get("rain") is None) else 0.0)] * R)[:R]
    wpath = wetness_path(w0, rain, (wx.get("track_temperature") or 25) + sc.get("track_temp_delta", 0.0), wx.get("wind_speed"))
    jitter = rng.integers(-int(sc.get("rain_uncertainty_laps", 0)), int(sc.get("rain_uncertainty_laps", 0)) + 1, size=n) if sc.get("rain_uncertainty_laps") else np.zeros(n, int)
    # neutralisations: forced by the scenario, otherwise drawn from historical base rates
    neut = np.zeros((n, R), int)   # 0 green, 1 VSC, 2 SC
    forced = sc.get("safety_car")
    if forced:
        a = max(0, int(forced["lap"]) - cur - 1)
        dur = int(forced.get("duration", 4 if forced.get("type", "SC") == "SC" else 2))
        neut[:, a:a + dur] = 2 if forced.get("type", "SC") == "SC" else 1
    elif sc.get("random_incidents", True):
        for kind, rate, code, lo, hi in (("SC", hz["sc_per_lap"], 2, 3, 6), ("VSC", hz["vsc_per_lap"], 1, 1, 3)):
            starts = rng.random((n, R)) < rate
            for s_i, l_i in zip(*np.nonzero(starts)):
                e = l_i + int(rng.integers(lo, hi))
                neut[s_i, l_i:e] = np.maximum(neut[s_i, l_i:e], code)
    hazard = (hz["dnf_per_race"] / max(total, 1)) if sc.get("random_incidents", True) else 0.0
    retire = {int(k): int(v) for k, v in (sc.get("retirements") or {}).items()}   # {driver_number: lap}
    thresh = float(sc.get("overtake_delta", 0.7))    # ASSUMPTION: pace advantage needed to pass (s/lap)
    stops = np.zeros((n, D), int); blocked_laps = np.zeros((n, D))
    pit_closed = set(int(x) for x in sc.get("pit_closed_laps", []))
    best_slick = int(np.argmin(off[:3] + deg[:3] * 8))
    idx_all = np.arange(n)[:, None]
    for li in range(R):
        lap = cur + li + 1
        nt = neut[:, li][:, None]
        wl = wpath[np.clip(li - jitter, 0, R - 1)][:, None]
        lt = (base + off[comp] + deg[comp] * age
              + np.minimum(sg.CLIFF * np.clip(age - life[comp], 0, None) ** 2, sg.CLIFF_MAX)
              + wet_penalty(comp, wl) * base + rng.normal(0, 1, (n, D)) * sigma[None, :] * (1 + 1.5 * wl))
        lt = np.where(nt == 2, base * 1.38, np.where(nt == 1, base * 1.28, lt))
        # pit decisions (taken at the end of this lap)
        cur_plan_lap = np.take_along_axis(np.broadcast_to(plan_lap, (n, D, K)), np.clip(ptr, 0, K - 1)[..., None], 2)[..., 0]
        cur_plan_comp = np.take_along_axis(np.broadcast_to(plan_comp, (n, D, K)), np.clip(ptr, 0, K - 1)[..., None], 2)[..., 0]
        has_plan = ptr < K
        auto = (ptr >= manual_until[None, :]) & (lap > hold_until[None, :])
        planned = has_plan & (cur_plan_lap == lap) & ~((comp >= 3) & (cur_plan_comp <= 2) & (wl >= W_INTER_TO_SLICK - 0.03) & auto)
        new_comp = np.where(planned, cur_plan_comp, comp)
        # weather reaction: switch tyre class one lap after the crossover is passed
        to_inter = auto & (comp <= 2) & (wl > W_SLICK_TO_INTER + 0.03)
        to_wet = auto & (comp == 3) & (wl > W_INTER_TO_WET + 0.04)
        to_slick = auto & (comp >= 3) & (wl < W_INTER_TO_SLICK - 0.03) & (R - li > 3)
        new_comp = np.where(to_inter, np.where(wl > W_INTER_TO_WET + 0.04, 4, 3), new_comp)
        new_comp = np.where(to_wet, 4, new_comp)
        new_comp = np.where(to_slick, np.where(has_plan & (cur_plan_comp <= 2), cur_plan_comp, best_slick), new_comp)
        # neutralisation reaction: bring a planned stop forward when it is within reach
        early = auto & has_plan & (nt >= 1) & (cur_plan_lap > lap) & (cur_plan_lap - lap <= 14) & (age > 5) & (R - li > 4)
        new_comp = np.where(early & ~(to_inter | to_wet | to_slick), cur_plan_comp, new_comp)
        pit = (planned | to_inter | to_wet | to_slick | early) & alive
        if lap in pit_closed:
            pit &= False
        factor = np.where(nt == 2, sg.SC_PIT_FACTOR["SC"], np.where(nt == 1, sg.SC_PIT_FACTOR["VSC"], 1.0))
        slow = (rng.random((n, D)) < 0.04) * rng.uniform(2, 9, (n, D))
        lt = lt + pit * (pit_loss * factor + np.abs(rng.normal(0, 0.5, (n, D))) + slow + warm[new_comp])
        ptr = ptr + (planned | early)
        # a slick stop planned for a lap that turned out too wet is postponed, not dropped
        late = has_plan & (cur_plan_lap == lap) & ~planned
        if late.any():
            plan_lap = np.broadcast_to(plan_lap, (n, D, K)).copy() if plan_lap.ndim == 2 else plan_lap
            np.put_along_axis(plan_lap, np.clip(ptr, 0, K - 1)[..., None], np.where(late, lap + 1, cur_plan_lap)[..., None], 2)
        # weather-forced stops consume the next planned stop if it was imminent
        ptr = ptr + ((to_inter | to_wet | to_slick) & has_plan & ~planned & ~early & (cur_plan_lap - lap <= 6))
        stops += pit
        prev = cum.copy()
        cum = cum + lt
        # retirements
        dead_now = alive & (rng.random((n, D)) < hazard)
        for i, d in enumerate(nums):
            if retire.get(d) == lap:
                dead_now[:, i] = alive[:, i]
        alive &= ~dead_now
        cum = np.where(dead_now, 1e6 - lap * 1e3, cum)
        # on-track order: a car is held up behind the car it followed unless it is clearly faster / someone pitted
        order = np.argsort(prev, axis=1)
        c_o = np.take_along_axis(cum, order, 1); p_o = np.take_along_axis(prev, order, 1)
        l_o = np.take_along_axis(lt, order, 1); pit_o = np.take_along_axis(pit, order, 1)
        b_o = np.zeros((n, D))
        green = (nt[:, 0] == 0)
        for k in range(1, D):
            held = green & (c_o[:, k] < c_o[:, k - 1] + 0.3) & (c_o[:, k] < 5e5) & (c_o[:, k - 1] < 5e5) & ~pit_o[:, k] & ~pit_o[:, k - 1] \
                   & ((l_o[:, k - 1] - l_o[:, k]) < thresh) & (p_o[:, k] - p_o[:, k - 1] < 3.0)
            c_o[:, k] = np.where(held, c_o[:, k - 1] + 0.3, c_o[:, k])
            b_o[:, k] = held
        # safety car: the field closes up behind the leader
        scm = (nt[:, 0] == 2)
        if scm.any():
            so = np.argsort(c_o, axis=1)
            cs = np.take_along_axis(c_o, so, 1)
            target = cs[:, :1] + np.arange(D)[None, :] * 0.9
            closed = np.where(cs < 5e5, np.minimum(cs, np.maximum(target, cs - (cs - target) * 0.75)), cs)
            cs = np.where(scm[:, None], closed, cs)
            np.put_along_axis(c_o, so, cs, 1)
        np.put_along_axis(cum, order, c_o, 1)
        blk = np.zeros((n, D)); np.put_along_axis(blk, order, b_o, 1)
        blocked_laps += blk
        age = np.where(pit, 0, age + 1)
        comp = np.where(pit, new_comp, comp)
    pos = np.argsort(np.argsort(cum, axis=1), axis=1) + 1
    lead_time = cum.min(axis=1, keepdims=True)
    res = []
    for i, r in enumerate(rows):
        p = pos[:, i]
        t = cum[:, i][alive[:, i]]
        res.append({"driver_number": r["driver_number"], "code": r["code"], "team_colour": r["team_colour"],
                    "p_win": float((p == 1).mean()), "p_podium": float((p <= 3).mean()), "p_top5": float((p <= 5).mean()),
                    "exp_pos": float(p.mean()), "pos_p10": int(np.percentile(p, 10)), "pos_p90": int(np.percentile(p, 90)),
                    "p_dnf": float((~alive[:, i]).mean()), "mean_stops": float(stops[:, i].mean()),
                    "exp_points": float(PTS[p - 1].mean()),
                    "exp_time": float(t.mean()) if len(t) else None, "time_sd": float(t.std()) if len(t) else None,
                    "blocked_laps": float(blocked_laps[:, i].mean()),
                    "exp_gap_to_winner": float((cum[:, i] - lead_time[:, 0])[alive[:, i]].mean()) if len(t) else None})
    out = {"n_sims": n, "from_lap": cur, "total_laps": total, "drivers": res,
           "wetness_path": [round(float(x), 3) for x in wpath],
           "inputs": {"pit_loss_s": round(pit_loss, 2), "pit_loss_source": m["pit_loss_source"], "overtake_delta_s": thresh,
                      "sc_per_lap": round(hz["sc_per_lap"], 4), "vsc_per_lap": round(hz["vsc_per_lap"], 4), "hazard_source": hz["source"],
                      "dnf_per_race": hz["dnf_per_race"], "start_wetness": w0, "random_incidents": bool(sc.get("random_incidents", True)) and not forced}}
    if focus is not None and focus in nums:
        i = nums.index(focus)
        p = pos[:, i]
        se = lambda x: float(np.sqrt(max(x * (1 - x), 1e-9) / n))
        out["focus"] = dict(res[i], pos_hist=[float((p == k).mean()) for k in range(1, D + 1)],
                            p_win_se=se(res[i]["p_win"]), p_podium_se=se(res[i]["p_podium"]),
                            risk=float(p.std()), sims_time=cum[:, i], sims_alive=alive[:, i])
    return out
