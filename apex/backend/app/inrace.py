"""In-race prediction model: P(win), P(podium) and final position given the race state at a lap.

Training rows are race states reconstructed lap by lap from stored OpenF1 data (2023+), i.e. exactly what
was observable at that lap. The pre-race prior fed to the model is the *out-of-fold* pre-race prediction,
so no information from the race's own outcome leaks in. Validation is by season.

CLI: python -m app.inrace train
"""
from __future__ import annotations
import json, sys, time, warnings
import joblib
import numpy as np
import pandas as pd
from . import db, racestate as rs
from .config import MODEL_DIR
from .prerace import scores, normalise, wilson

warnings.filterwarnings("ignore")
FEATS = ["position", "gap_s", "interval_s", "laps_remaining", "frac_done", "tyre_age", "c_soft", "c_medium", "c_hard",
         "c_inter", "c_wet", "pit_stops", "grid", "gained", "needs_stop", "sc", "vsc", "rain", "pace_rel5",
         "prior_win", "prior_podium", "running", "laps_behind", "lead", "log_gap", "gap_x_frac", "lead_x_frac"]
LABELS = {"position": "Current position", "gap_s": "Gap to leader (s)", "interval_s": "Gap to car ahead (s)",
          "laps_remaining": "Laps remaining", "frac_done": "Race distance completed", "tyre_age": "Tyre age (laps)",
          "c_soft": "On soft tyres", "c_medium": "On medium tyres", "c_hard": "On hard tyres", "c_inter": "On intermediates",
          "c_wet": "On wet tyres", "pit_stops": "Pit stops made", "grid": "Grid position", "gained": "Positions gained",
          "needs_stop": "Still owes a mandatory stop", "sc": "Safety Car out", "vsc": "Virtual Safety Car", "rain": "Rain sensor active",
          "pace_rel5": "Pace vs field (last 5 laps, s)", "prior_win": "Pre-race win probability",
          "prior_podium": "Pre-race podium probability", "running": "Cars still running", "laps_behind": "Laps behind leader", "lead": "Leading the race",
          "log_gap": "Gap to leader (log)", "gap_x_frac": "Gap × race progress", "lead_x_frac": "Leading × race progress"}


def features(st: dict, d: dict, prior: dict) -> pd.DataFrame:
    """Feature rows for every running driver at this state. `prior`: driver_number -> (p_win, p_podium)."""
    laps, T, lap = d["laps"], st["T"], st["lap"]
    k = laps[(laps.end <= T + 1e-6) & (laps.lap_number > lap - 6) & (laps.is_pit_out_lap == 0) & (laps.is_pit_in_lap == 0)]
    med = k.groupby("driver_number")["lap_duration"].median() if len(k) else pd.Series(dtype=float)
    field = med.median() if len(med) else np.nan
    total = st["total_laps"] or st["max_lap"]
    run = [r for r in st["rows"] if r["status"] == "RUNNING" and r["laps_done"] > 0]
    out = []
    for r in run:
        dry_used = [c for c in r["compounds_used"] if c in ("SOFT", "MEDIUM", "HARD")]
        wet_used = any(c in ("INTERMEDIATE", "WET") for c in r["compounds_used"])
        c = r["compound"]
        pw, pp = prior.get(r["driver_number"], (np.nan, np.nan))
        out.append({"driver_number": r["driver_number"], "position": r["position"], "gap_s": min(r["gap_s"] or 0, 150),
                    "interval_s": min(r["interval_s"], 60) if r["interval_s"] is not None else np.nan,
                    "laps_remaining": total - lap, "frac_done": lap / total, "tyre_age": r["tyre_age"] if r["tyre_age"] is not None else np.nan,
                    "c_soft": int(c == "SOFT"), "c_medium": int(c == "MEDIUM"), "c_hard": int(c == "HARD"),
                    "c_inter": int(c == "INTERMEDIATE"), "c_wet": int(c == "WET"), "pit_stops": r["pit_stops"],
                    "grid": r["grid"] if r["grid"] else np.nan, "gained": r["gained"] if r["gained"] is not None else np.nan,
                    "needs_stop": int(len(set(dry_used)) < 2 and not wet_used), "sc": int(st["track_status"] in ("SC", "SC_ENDING")),
                    "vsc": int(st["track_status"] == "VSC"), "rain": int((st["weather"] or {}).get("rainfall") or 0),
                    "pace_rel5": float(med.get(r["driver_number"], np.nan) - field), "prior_win": pw, "prior_podium": pp,
                    "running": len(run), "laps_behind": r["laps_behind"] or 0})
    f = pd.DataFrame(out)
    if len(f):
        f["lead"] = (f.position == 1).astype(int)
        f["log_gap"] = np.log1p(f.gap_s.clip(lower=0))
        f["gap_x_frac"] = f.gap_s * f.frac_done
        f["lead_x_frac"] = f.lead * f.frac_done
    return f


def prior_for(session_key: int) -> dict:
    """Pre-race probabilities per driver_number: out-of-fold backtest predictions when the race is in the
    backtest, otherwise the live pre-race model output."""
    d = rs.load(session_key)
    if not d["f1db"]:
        return {}
    dm = rs.driver_map(session_key)
    rows = db.q("SELECT driver_id, win_cal, podium_cal FROM prerace_oof WHERE race_id=:r AND variant='pre_race'", r=d["f1db"]["race_id"]) \
        if db.has_table("prerace_oof") else []
    by = {r["driver_id"]: (r["win_cal"], r["podium_cal"]) for r in rows}
    if not by:
        try:
            from . import service
            p = service.prerace_prediction(d["f1db"]["race_id"])
            by = {x["driver_id"]: (x["p_win"], x["p_podium"]) for x in p["drivers"]}
        except Exception:
            by = {}
    return {n: by[i[0]] for n, i in dm.items() if i[0] in by}


def build_dataset(step: int = 1) -> pd.DataFrame:
    frames = []
    sessions = rs.race_sessions()
    for i, s in enumerate(sessions):
        sk = s["session_key"]
        try:
            d = rs.load(sk)
        except Exception:
            continue
        res = d["session_result"]
        if not d["max_lap"] or not len(res) or not d["total_laps"]:
            continue
        final = {int(r.driver_number): (r.position if not pd.isna(r.position) else 99) for r in res.itertuples()}
        prior = prior_for(sk)
        for lap in range(2, d["max_lap"], step):
            try:
                st = rs.state(sk, lap)
                f = features(st, d, prior)
            except Exception:
                continue
            if not len(f) or st["lap"] != lap:
                continue
            f["session_key"], f["lap"], f["year"] = sk, lap, s["year"]
            f["final"] = f.driver_number.map(final).fillna(99)
            frames.append(f)
        print(f"  dataset {i + 1}/{len(sessions)} {s['year']} {s['location']}", flush=True)
    f = pd.concat(frames, ignore_index=True)
    f["win"] = (f.final == 1).astype(int); f["podium"] = (f.final <= 3).astype(int)
    f["final_pos"] = f.final.clip(upper=20)
    f["grp"] = f.session_key * 1000 + f.lap
    return f


def _models():
    """Deliberately small, heavily regularised learners: laps of one race are highly correlated, so the
    effective sample is the number of races (dozens), not the number of rows."""
    from lightgbm import LGBMClassifier, LGBMRegressor
    from xgboost import XGBClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    kw = dict(n_estimators=150, num_leaves=6, learning_rate=0.03, subsample=0.5, subsample_freq=1, colsample_bytree=0.6,
              min_child_samples=600, reg_lambda=20, verbose=-1, n_jobs=4)
    return {"lightgbm": lambda: LGBMClassifier(**kw),
            "xgboost": lambda: XGBClassifier(n_estimators=150, max_depth=3, learning_rate=0.04, subsample=0.5, colsample_bytree=0.6,
                                             min_child_weight=300, reg_lambda=20, n_jobs=4, verbosity=0),
            "logistic": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.05, max_iter=3000)),
            "reg": lambda: LGBMRegressor(**kw)}


CLS = ("lightgbm", "xgboost", "logistic")


def _fit_predict(tr, te):
    mk = _models()
    out = {}
    for tgt, tot in (("win", 1), ("podium", 3)):
        ps = [mk[n]().fit(tr[FEATS], tr[tgt]).predict_proba(te[FEATS])[:, 1] for n in CLS]
        out[tgt] = normalise(np.mean(ps, axis=0), te.grp.to_numpy(), tot)
    out["pos"] = mk["reg"]().fit(tr[FEATS], tr.final_pos).predict(te[FEATS])
    return out


def train() -> dict:
    cache_file = MODEL_DIR / "inrace_dataset.pkl"
    if "--cached" in sys.argv and cache_file.exists():
        f = pd.read_pickle(cache_file)
    else:
        f = build_dataset()
        f.to_pickle(cache_file)
    years = sorted(f.year.unique())
    folds, ev = [], []
    for y in years[1:]:
        tr, te = f[f.year < y], f[f.year == y].copy()
        if tr.session_key.nunique() < 10 or not len(te):
            continue
        p = _fit_predict(tr, te)
        te["p_win"], te["p_podium"], te["pred"] = p["win"], p["podium"], p["pos"]
        # baseline: frequency of winning from this position at this race phase, learned on the training seasons
        tr = tr.assign(ph=(tr.frac_done * 4).astype(int).clip(0, 3)); te["ph"] = (te.frac_done * 4).astype(int).clip(0, 3)
        tab = tr.groupby(["ph", "position"])["win"].mean()
        te["base"] = normalise(np.array([tab.get((a, b), 0.001) for a, b in zip(te.ph, te.position)]) + 1e-4, te.grp.to_numpy(), 1)
        ev.append(te)
        folds.append(int(y))
    metrics = {"validation": "walk-forward by season", "test_seasons": folds, "n_races_total": int(f.session_key.nunique()),
               "n_rows_total": int(len(f))}
    bands = []
    if ev:
        e = pd.concat(ev)
        g = e.grp.to_numpy()
        metrics["winner"] = {"model": scores(e.p_win, e.win, g), "baseline_position": scores(e.base, e.win, g)}
        pod = scores(e.p_podium, e.podium, g); pod.pop("accuracy")
        metrics["podium"] = pod
        metrics["by_phase"] = []
        for ph, name in enumerate(["0–25%", "25–50%", "50–75%", "75–100%"]):
            x = e[e.ph == ph]
            if len(x):
                metrics["by_phase"].append({"phase": name, "winner_accuracy": scores(x.p_win, x.win, x.grp.to_numpy())["accuracy"],
                                            "baseline_leader_accuracy": scores(x.base, x.win, x.grp.to_numpy())["accuracy"],
                                            "log_loss": scores(x.p_win, x.win, x.grp.to_numpy())["log_loss"],
                                            "position_mae": round(float((x.groupby("grp")["pred"].rank(method="first") - x.final_pos).abs().mean()), 3),
                                            "position_mae_baseline_current": round(float((x.position - x.final_pos).abs().mean()), 3)})
        for lo, hi in zip([0, .02, .05, .1, .2, .35, .5, .7, .9], [.02, .05, .1, .2, .35, .5, .7, .9, 1.0001]):
            b = e[(e.p_win >= lo) & (e.p_win < hi)]
            # rows within a race are highly correlated: use races (not rows) as the effective sample size
            neff = int(b.session_key.nunique() * 3)
            w = wilson(b.win.mean() * neff if len(b) else 0, neff)
            bands.append({"lo": lo, "hi": min(hi, 1), "n": int(len(b)), "n_eff": neff, "predicted": round(float(b.p_win.mean()), 4) if len(b) else None,
                          "observed": round(float(b.win.mean()), 4) if len(b) else None, "ci_lo": round(w[0], 4), "ci_hi": round(w[1], 4)})
        metrics["calibration_bands"] = bands
    mk = _models()
    final = {"win": {n: mk[n]().fit(f[FEATS], f.win) for n in CLS},
             "podium": {n: mk[n]().fit(f[FEATS], f.podium) for n in CLS},
             "pos": mk["reg"]().fit(f[FEATS], f.final_pos)}
    version = time.strftime("%Y%m%d-%H%M%S")
    path = MODEL_DIR / f"in_race_{version}.joblib"
    last = db.q("SELECT year, location FROM of1_sessions WHERE session_key=:k", k=int(f.sort_values('session_key').session_key.iloc[-1]))
    through = max(f.year)
    joblib.dump({"version": version, "features": FEATS, "models": final, "bands": bands, "metrics": metrics}, path, compress=3)
    db.init()
    db.execute("UPDATE model_registry SET active=0 WHERE name='in_race'")
    db.execute("INSERT INTO model_registry (name,version,created,train_through,n_rows,metrics,path,active) VALUES "
               "('in_race',:v,:c,:t,:r,:m,:p,1)", v=version, c=time.time(), t=f"{through} ({f.session_key.nunique()} races)",
               r=len(f), m=json.dumps(metrics), p=str(path))
    return metrics


def _has_parquet() -> bool:
    try:
        import pyarrow  # noqa
        return True
    except Exception:
        return False


_bundle: dict = {}


def load():
    row = db.q("SELECT path, version FROM model_registry WHERE name='in_race' AND active=1 ORDER BY created DESC LIMIT 1")
    if not row:
        return None
    if _bundle.get("version") != row[0]["version"]:
        _bundle.clear(); _bundle.update(joblib.load(row[0]["path"]))
    return _bundle


def predict(session_key: int, lap: int | None = None) -> pd.DataFrame | None:
    b = load()
    if not b:
        return None
    d = rs.load(session_key)
    st = rs.state(session_key, lap)
    f = features(st, d, prior_for(session_key))
    if not len(f):
        return None
    z = np.zeros(len(f))
    X = f[FEATS].astype(float)
    f["ml_win"] = normalise(np.mean([m.predict_proba(X)[:, 1] for m in b["models"]["win"].values()], axis=0), z, 1)
    f["ml_podium"] = normalise(np.mean([m.predict_proba(X)[:, 1] for m in b["models"]["podium"].values()], axis=0), z, 3)
    f["ml_pos_score"] = b["models"]["pos"].predict(X)
    f["ml_pred_pos"] = f.ml_pos_score.rank(method="first").astype(int)
    try:
        import shap
        sv = shap.TreeExplainer(b["models"]["win"]["xgboost"]).shap_values(X)
        f["explain"] = [[{"feature": FEATS[j], "label": LABELS[FEATS[j]], "shap": round(float(sv[i][j]), 3),
                          "value": None if pd.isna(X.iloc[i, j]) else round(float(X.iloc[i, j]), 3)}
                         for j in np.argsort(-np.abs(sv[i]))[:5]] for i in range(len(f))]
    except Exception:
        f["explain"] = [[] for _ in range(len(f))]
    return f


if __name__ == "__main__":
    t = time.time()
    m = train()
    print(f"{time.time() - t:.0f}s", json.dumps({k: v for k, v in m.items() if k != "calibration_bands"}, indent=1))
