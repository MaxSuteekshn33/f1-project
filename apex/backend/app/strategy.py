"""Tyre model, pit-loss estimation and pit-stop optimisation (OR-Tools CP-SAT).

Everything is fitted from lap times actually recorded in the session up to the as-of lap; where the
session does not yet hold enough clean laps, values shrink towards a prior fitted on earlier races at the
same circuit (a *historical estimate*) or, failing that, towards generic defaults (an *assumption*).
Each output says which of those it is.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from ortools.sat.python import cp_model
from . import db, racestate as rs
from .cache import cached

SLICKS = ["SOFT", "MEDIUM", "HARD"]
WETS = ["INTERMEDIATE", "WET"]
COMPOUNDS = SLICKS + WETS
GENERIC = {"deg": {"SOFT": 0.09, "MEDIUM": 0.06, "HARD": 0.04}, "offset": {"SOFT": -0.55, "MEDIUM": 0.0, "HARD": 0.45},
           "fuel": -0.055, "pit_loss": 22.0}
LIFE_FRAC = {"SOFT": 0.42, "MEDIUM": 0.62, "HARD": 0.85}      # assumption: usable life as share of race distance
WARMUP = {"SOFT": -0.3, "MEDIUM": 0.0, "HARD": 0.5, "INTERMEDIATE": 0.3, "WET": 0.5}  # assumption: out-lap delta (s)
CLIFF_MAX = 3.0                                                # assumption: cap of the cliff penalty (s/lap)
CLIFF = 0.025                                                  # assumption: s/lap² beyond usable life
SC_PIT_FACTOR = {"GREEN": 1.0, "VSC": 0.62, "SC": 0.45}        # assumption: share of green-flag pit loss


def clean_laps(d: dict, T: float) -> pd.DataFrame:
    """Representative racing laps known at time T: green-flag, no in/out laps, no lap 1, no outliers."""
    laps = d["laps"]
    k = laps[(laps.end <= T + 1e-6) & laps.lap_duration.notna()].copy()
    if not len(k) or not len(d["stints"]):
        return pd.DataFrame(columns=["driver_number", "lap_number", "lap_duration", "compound", "age", "raw"])
    st = d["stints"].dropna(subset=["lap_start"]).sort_values("lap_start")
    k = pd.merge_asof(k.sort_values("lap_number"), st[["driver_number", "lap_start", "compound", "tyre_age_at_start"]],
                      left_on="lap_number", right_on="lap_start", by="driver_number", direction="backward")
    k["age"] = k.tyre_age_at_start.fillna(0) + k.lap_number - k.lap_start + 1
    k["status"] = k.lap_number.map(d["lap_status"]).fillna("GREEN")
    k = k[(k.lap_number > 1) & (k.is_pit_out_lap == 0) & (k.is_pit_in_lap == 0) & (k.status == "GREEN") & k.compound.notna()]
    if not len(k):
        return k
    k["wet"] = k.compound.isin(WETS)
    med = k.groupby(["driver_number", "wet"])["lap_duration"].transform("median")
    return k[k.lap_duration < med * 1.06][["driver_number", "lap_number", "lap_duration", "compound", "age", "wet"]]


def _fit(cl: pd.DataFrame, prior: dict, strength: float = 1.0) -> dict:
    """Ridge least squares: lap = driver_base + offset[c] + deg[c]*age + fuel*lap, shrunk towards `prior`."""
    s = cl[cl.compound.isin(SLICKS)]
    comps = [c for c in SLICKS if (s.compound == c).sum() >= 1]
    drivers = sorted(s.driver_number.unique())
    out = {"n_laps": int(len(s)), "compounds": {}, "fuel": prior["fuel"], "base": {}, "sigma": {}, "sigma_all": 0.45}
    for c in SLICKS:
        out["compounds"][c] = {"deg": prior["deg"][c], "offset": prior["offset"][c], "n_laps": 0, "source": prior.get("label", "assumption")}
    if len(s) < 12 or not comps:
        return out
    ref = "MEDIUM" if "MEDIUM" in comps else comps[0]
    lapset = sorted(s.lap_number.unique())
    nd, nc, nl = len(drivers), len(comps), len(lapset)
    cols = nd + (nc - 1) + nc + nl
    di = {d: i for i, d in enumerate(drivers)}
    off_i = {c: nd + i for i, c in enumerate([c for c in comps if c != ref])}
    deg_i = {c: nd + nc - 1 + i for i, c in enumerate(comps)}
    lap_i = {l: nd + 2 * nc - 1 + i for i, l in enumerate(lapset)}
    A = np.zeros((len(s), cols)); y = s.lap_duration.to_numpy(float)
    rows = np.arange(len(s))
    A[rows, s.driver_number.map(di).to_numpy()] = 1
    # lap fixed effects absorb fuel burn AND track evolution (rubbering-in, drying), so tyre wear is
    # identified from cars on different tyre ages on the same lap
    A[rows, s.lap_number.map(lap_i).to_numpy()] = 1
    for c in comps:
        m = (s.compound == c).to_numpy()
        if c != ref: A[m, off_i[c]] = 1
        A[m, deg_i[c]] = s.age.to_numpy()[m]
    pri = np.zeros(cols); w = np.zeros(cols)
    for c in comps:
        if c != ref:
            pri[off_i[c]] = prior["offset"][c] - prior["offset"][ref]; w[off_i[c]] = 8 * strength
        pri[deg_i[c]] = prior["deg"][c]; w[deg_i[c]] = 600 * strength
    for l in lapset:
        w[lap_i[l]] = 0.05
    Aa = np.vstack([A, np.diag(np.sqrt(w))]); ya = np.concatenate([y, np.sqrt(w) * pri])
    theta, *_ = np.linalg.lstsq(Aa, ya, rcond=None)
    resid = y - A @ theta
    fe = np.array([theta[lap_i[l]] for l in lapset])
    out["fuel"] = float(np.polyfit(lapset, fe, 1)[0]) if nl >= 5 else prior["fuel"]
    out["lap_trend_note"] = "per-lap trend of lap fixed effects: fuel burn + track evolution"
    fe_mean = float(fe.mean())
    for c in comps:
        n = int((s.compound == c).sum())
        off = (theta[off_i[c]] if c != ref else 0.0) + prior["offset"][ref]
        deg, floor = float(theta[deg_i[c]]), 0.35 * prior["deg"][c]
        src = "fitted (this session)" if n >= 25 else f"blend: {n} laps + {prior.get('label', 'assumption')}"
        if deg < floor:  # improving track / drying surface masks wear: do not report zero degradation
            deg, src = floor, f"floor from {prior.get('label', 'assumption')} — track evolution masks wear in {n} laps"
        out["compounds"][c] = {"deg": float(min(deg, 0.4)), "offset": float(off), "n_laps": n, "source": src}
    for d_, i in di.items():
        out["base"][int(d_)] = float(theta[i] + fe_mean)
        r = resid[(s.driver_number == d_).to_numpy()]
        out["sigma"][int(d_)] = float(np.clip(r.std() if len(r) > 3 else 0.45, 0.2, 1.2))
    out["sigma_all"] = float(np.clip(resid.std(), 0.2, 1.2))
    out["n_by_driver"] = {int(k): int(v) for k, v in s.groupby("driver_number").size().items()}
    return out


def measured_pit_loss(d: dict, T: float) -> tuple[float | None, int]:
    """Green-flag pit loss = (in-lap + out-lap) − 2 × the driver's median clean lap, median over stops."""
    laps = d["laps"]
    k = laps[(laps.end <= T + 1e-6) & laps.lap_duration.notna()]
    cl = clean_laps(d, T)
    if not len(cl):
        return None, 0
    med = cl[~cl.wet].groupby("driver_number")["lap_duration"].median()
    out = k[(k.is_pit_out_lap == 1) & (k.lap_number > 2)]
    vals = []
    slick_laps = set(zip(cl[~cl.wet].driver_number, cl[~cl.wet].lap_number))
    idx = k.set_index(["driver_number", "lap_number"])["lap_duration"]
    for r in out.itertuples():
        if d["lap_status"].get(int(r.lap_number), "GREEN") != "GREEN" or d["lap_status"].get(int(r.lap_number) - 1, "GREEN") != "GREEN":
            continue
        inl = idx.get((r.driver_number, r.lap_number - 1))
        if inl is None or pd.isna(inl) or r.driver_number not in med.index:
            continue
        # only slick-to-slick stops: a tyre-class change on a wet/drying track is not a clean pit-loss sample
        if (r.driver_number, r.lap_number - 2) not in slick_laps or (r.driver_number, r.lap_number + 1) not in slick_laps:
            continue
        v = inl + r.lap_duration - 2 * med[r.driver_number]
        if 12 < v < 36:
            vals.append(v)
    return (float(np.median(vals)), len(vals)) if len(vals) >= 3 else (None, len(vals))


@cached(ttl=3600)
def circuit_prior(circuit_key: int, before: float) -> dict:
    """Historical estimate: tyre model + pit loss fitted on up to two earlier races at this circuit."""
    prior = dict(GENERIC, label="generic assumption")
    rows = db.q("SELECT session_key, year FROM of1_sessions WHERE circuit_key=:c AND session_name='Race' AND date_start < :b "
                "ORDER BY date_start DESC LIMIT 2", c=circuit_key, b=before - 86400)
    frames, losses, used = [], [], []
    for r in rows:
        try:
            d = rs.load(r["session_key"])
        except Exception:
            continue
        if not d["max_lap"]:
            continue
        cl = clean_laps(d, 9e12)
        cl = cl[~cl.wet] if len(cl) else cl
        if len(cl) >= 150:
            cl = cl.assign(driver_number=cl.driver_number + 1000 * len(frames)); frames.append(cl); used.append(r["year"])
        pl, n = measured_pit_loss(d, 9e12)
        if pl: losses.append(pl)
    if frames:
        m = _fit(pd.concat(frames), prior, strength=0.5)
        prior = {"deg": {c: m["compounds"][c]["deg"] for c in SLICKS}, "offset": {c: m["compounds"][c]["offset"] for c in SLICKS},
                 "fuel": m["fuel"], "pit_loss": float(np.median(losses)) if losses else GENERIC["pit_loss"],
                 "label": f"historical estimate ({', '.join(str(y) for y in used)} race{'s' if len(used) > 1 else ''} here)"}
    elif losses:
        prior["pit_loss"] = float(np.median(losses))
    return prior


def tyre_model(session_key: int, lap: int | None = None) -> dict:
    d = rs.load(session_key)
    st = rs.state(session_key, lap)
    return _tyre_model_cached(session_key, st["lap"], round(st["T"] or 0, 0))


@cached(ttl=120)
def _tyre_model_cached(session_key: int, lap: int, T: float) -> dict:
    d = rs.load(session_key)
    prior = circuit_prior(d["session"]["circuit_key"], d["session"]["date_start"])
    cl = clean_laps(d, T + 1)
    m = _fit(cl, prior)
    m["prior"] = prior["label"]
    pl, n = measured_pit_loss(d, T + 1)
    m["pit_loss"] = pl if pl else prior["pit_loss"]
    m["pit_loss_source"] = f"measured ({n} green-flag stops this session)" if pl else (
        prior["label"] if prior["pit_loss"] != GENERIC["pit_loss"] else "generic assumption (22.0 s)")
    wet = cl[cl.wet] if len(cl) else cl
    dry = cl[~cl.wet] if len(cl) else cl
    m["wet_laps"] = int(len(wet)); m["dry_laps"] = int(len(dry))
    m["wet_pace"] = {int(k): float(v) for k, v in wet.groupby("driver_number")["lap_duration"].median().items()} if len(wet) else {}
    m["observed_inter_vs_slick"] = (round(float(wet.lap_duration.median() / dry.lap_duration.median() - 1), 4)
                                    if len(wet) >= 20 and len(dry) >= 20 else None)
    # every driver needs a base pace: fitted, else inferred from wet-lap ranking, else field median
    field = float(np.median(list(m["base"].values()))) if m["base"] else (float(dry.lap_duration.median()) if len(dry) else None)
    if field is None:
        field = float(wet.lap_duration.median() / 1.12) if len(wet) else 90.0
        m["base_source"] = "assumption: dry pace inferred from wet laps (÷1.12)"
    else:
        m["base_source"] = "fitted from green-flag laps (fuel- and tyre-corrected)"
    wmed = float(np.median(list(m["wet_pace"].values()))) if m["wet_pace"] else None
    for dn in d["drivers"].driver_number if len(d["drivers"]) else []:
        dn = int(dn)
        if dn not in m["base"]:
            m["base"][dn] = field + ((m["wet_pace"][dn] - wmed) * 0.6 if dn in m["wet_pace"] else 0.6)
            m["sigma"][dn] = m["sigma_all"]
    m["field_base"] = field
    m["laps"] = cl
    return m


def stint_cost(m: dict, comp: str, age0: int, length: int, total_laps: int) -> np.ndarray:
    """Cumulative time cost (s, relative) of running `length` laps on `comp` starting at tyre age age0."""
    c = m["compounds"][comp]
    ages = age0 + np.arange(length)
    life = LIFE_FRAC[comp] * total_laps
    per = c["offset"] + c["deg"] * ages + np.minimum(CLIFF * np.clip(ages - life, 0, None) ** 2, CLIFF_MAX)
    return np.cumsum(per)


def optimise(m: dict, cur_lap: int, total_laps: int, comp: str | None, age: int, used: list[str], stops: int,
             pit_loss: float | None = None, forbid: list | None = None, allowed=SLICKS, min_stint: int = 4) -> dict | None:
    """CP-SAT: choose stop laps and compounds minimising expected remaining race time for exactly `stops` stops.
    Enforces the two-dry-compound rule when the driver has only used one slick compound so far."""
    R = total_laps - cur_lap
    if R < 1:
        return None
    pit_loss = m["pit_loss"] if pit_loss is None else pit_loss
    cur = comp if comp in SLICKS else None
    S = stops + 1
    if stops and R < stops * min_stint + (1 if cur else 0):
        return None
    SC = 1000  # ms resolution
    nC = len(allowed)
    # cost tables: first stint on current tyres (age), later stints on new tyres of each compound
    first = stint_cost(m, cur, age, R, total_laps) if cur else None
    fresh = {c: stint_cost(m, c, 0, R, total_laps) + WARMUP[c] for c in allowed}
    model = cp_model.CpModel()
    L = [model.NewIntVar((1 if cur else 0) if i == 0 else min(min_stint, R), R, f"l{i}") for i in range(S)]
    model.Add(sum(L) == R)
    C = [model.NewIntVar(0, nC - 1, f"c{i}") for i in range(1, S)]
    costs = []
    base = int(min(0, min(float(v.min()) for v in fresh.values()), float(first.min()) if first is not None else 0) * SC) - 1
    hi = int(max(max(float(v.max()) for v in fresh.values()), float(first.max()) if first is not None else 0) * SC) + 1
    if cur:
        c0 = model.NewIntVar(base, hi, "k0")
        model.AddElement(L[0], [0] + [int(v * SC) for v in first], c0)
        costs.append(c0)
    elif stops == 0:
        return None  # currently on wet-weather tyres: a dry strategy needs at least one stop
    else:
        model.Add(L[0] == 0)  # on wet-weather tyres: the dry plan starts with a stop at `cur_lap`
    table = [0] * ((R + 1) * nC)
    for ci, c in enumerate(allowed):
        for ln in range(1, R + 1):
            table[ci * (R + 1) + ln] = int(fresh[c][ln - 1] * SC)
    for i in range(1, S):
        idx = model.NewIntVar(0, (R + 1) * nC - 1, f"i{i}")
        model.Add(idx == C[i - 1] * (R + 1) + L[i])
        k = model.NewIntVar(base, hi, f"k{i}")
        model.AddElement(idx, table, k)
        costs.append(k)
    used_dry = set(u for u in used if u in SLICKS)
    wet_used = any(u in WETS for u in used)
    rule_ok = True
    if not wet_used and len(used_dry) < 2:
        only = next(iter(used_dry), cur)
        if stops == 0:
            rule_ok = False
        elif only in allowed:
            bs = []
            for i, cv in enumerate(C):
                b = model.NewBoolVar(f"b{i}")
                model.Add(cv != allowed.index(only)).OnlyEnforceIf(b)
                model.Add(cv == allowed.index(only)).OnlyEnforceIf(b.Not())
                bs.append(b)
            model.AddBoolOr(bs)
    if forbid and C:
        model.AddForbiddenAssignments(C, [tuple(allowed.index(c) for c in forbid)])
    model.Minimize(sum(costs))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3.0
    solver.parameters.num_workers = 1
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    lens = [solver.Value(x) for x in L]
    comps = [allowed[solver.Value(x)] for x in C]
    lap, plan, stints = cur_lap, [], []
    seq = ([cur] if cur else [comp]) + comps
    for i, ln in enumerate(lens):
        if ln == 0:
            plan.append({"lap": lap, "compound": comps[i]})
            continue
        stints.append({"compound": seq[i], "from_lap": lap + 1, "to_lap": lap + ln, "laps": ln,
                       "start_age": age if i == 0 else 0})
        lap += ln
        if i < stops:
            plan.append({"lap": lap, "compound": comps[i]})
    tyre_time = solver.ObjectiveValue() / SC
    deg = 0.0
    for s_ in stints:
        if s_["compound"] in SLICKS:
            c = m["compounds"][s_["compound"]]
            deg += float(c["deg"] * (s_["start_age"] * s_["laps"] + s_["laps"] * (s_["laps"] - 1) / 2))
    return {"stops": stops, "plan": plan, "stints": stints, "rel_time": tyre_time + stops * pit_loss,
            "pit_time_lost": stops * pit_loss, "deg_time": deg, "rule_ok": rule_ok}


def window(m: dict, plan: dict, cur_lap: int, total_laps: int, comp: str, age: int, tol: float = 1.0) -> dict | None:
    """Sensitivity of the first stop lap: the pit window is every lap within `tol` seconds of the optimum."""
    if not plan or not plan["plan"] or comp not in SLICKS:
        return None
    first, later = plan["plan"][0], plan["plan"][1:]
    nxt_end = later[0]["lap"] if later else total_laps
    curve = []
    for p in range(cur_lap + 1, nxt_end - 2):
        a = stint_cost(m, comp, age, p - cur_lap, total_laps)[-1]
        b = stint_cost(m, first["compound"], 0, nxt_end - p, total_laps)[-1]
        curve.append((p, float(a + b)))
    if not curve:
        return None
    best = min(c for _, c in curve)
    ok = [p for p, c in curve if c - best <= tol]
    return {"open": min(ok), "close": max(ok), "optimal": first["lap"], "tolerance_s": tol,
            "curve": [{"lap": p, "delta": round(c - best, 2)} for p, c in curve]}


_memo: dict = {}


def strategies(m: dict, cur_lap: int, total_laps: int, comp: str | None, age: int, used: list[str]) -> list[dict]:
    """A: one-stop, B: two-stop, C: three-stop, D: best alternative compound choice — counted from `cur_lap`.
    For a car on wet-weather tyres pass the lap at which slicks are expected to go on as `cur_lap`."""
    key = (id(m), cur_lap, total_laps, comp, age, tuple(used))
    if key in _memo:
        return _memo[key]
    if len(_memo) > 500:
        _memo.clear()
    out = _strategies(m, cur_lap, total_laps, comp, age, used)
    _memo[key] = out
    return out


def _strategies(m, cur_lap, total_laps, comp, age, used):
    out = []
    for label, k in (("A", 1), ("B", 2), ("C", 3)):
        p = optimise(m, cur_lap, total_laps, comp, age or 0, used, k)
        if p:
            p["label"] = label; p["name"] = f"{k}-stop" + ("" if k == 1 else "")
            out.append(p)
    p0 = optimise(m, cur_lap, total_laps, comp, age or 0, used, 0)
    if p0 and p0["rule_ok"]:
        p0["label"] = "0"; p0["name"] = "No further stop"; out.append(p0)
    legal = [p for p in out if p["rule_ok"]]
    if legal:
        best = min(legal, key=lambda p: p["rel_time"])
        if best["plan"]:
            alt = optimise(m, cur_lap, total_laps, comp, age or 0, used, best["stops"], forbid=[x["compound"] for x in best["plan"]])
            if alt:
                alt["label"] = "D"; alt["name"] = f"Alternative compounds ({best['stops']}-stop)"; out.append(alt)
        ref = best["rel_time"]
        for p in out:
            p["delta_vs_best"] = round(p["rel_time"] - ref, 2)
            p["optimal"] = p is best
    return out


def undercuts(st: dict, m: dict) -> list[dict]:
    """Undercut / overcut screening for each pair of consecutive running cars on slick tyres."""
    out = []
    rows = [r for r in st["rows"] if r["status"] == "RUNNING" and r["gap_s"] is not None]
    for ahead, me in zip(rows, rows[1:]):
        gap = me["gap_s"] - ahead["gap_s"]
        if not (0 < gap < 4.0) or me["compound"] not in SLICKS or ahead["compound"] not in SLICKS:
            continue
        best_new = min(SLICKS, key=lambda c: m["compounds"][c]["offset"])
        new = m["compounds"][best_new]
        ca = m["compounds"][ahead["compound"]]
        # undercut: I pit now; rival stays out N laps on old tyres while I run new ones
        per_lap = (ca["offset"] + ca["deg"] * (ahead["tyre_age"] or 0)) - (new["offset"] + new["deg"] * 1)
        gain2 = 2 * per_lap - WARMUP[best_new] - 0.5   # two laps of fresh-tyre advantage minus warm-up
        cm = m["compounds"][me["compound"]]
        mine_old = cm["offset"] + cm["deg"] * (me["tyre_age"] or 0)
        out.append({"driver": me["code"], "driver_number": me["driver_number"], "ahead": ahead["code"], "gap_s": round(gap, 2),
                    "fresh_tyre_gain_per_lap": round(per_lap, 2), "undercut_gain_2laps": round(gain2, 2),
                    "undercut_margin": round(gain2 - gap, 2), "undercut_on": gain2 > gap + 0.3,
                    "overcut_gain_per_lap": round((ca["offset"] + ca["deg"] * (ahead["tyre_age"] or 0)) - mine_old, 2),
                    "inputs": f"{ahead['code']} {ahead['compound']} age {ahead['tyre_age']}, {me['code']} {me['compound']} age {me['tyre_age']}"})
    return out
