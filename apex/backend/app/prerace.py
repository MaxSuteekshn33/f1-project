"""Pre-race prediction models (winner / podium / top-5 / fastest lap / finishing position).

Leakage control: every historical feature is computed from rows strictly BEFORE the race being
predicted (groupby + shift). Validation is walk-forward by season — never a random split.
Two variants: `pre_quali` (no grid information) and `pre_race` (after qualifying).

CLI: python -m app.prerace train [--tune]
"""
from __future__ import annotations
import json, sys, time, warnings
import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from . import db
from .config import MODEL_DIR

warnings.filterwarnings("ignore")
POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
QUALI_FEATURES = ["grid", "q_pos", "q_gap_pct", "q_vs_teammate"]
HIST_FEATURES = [
    "d_win10", "d_pod10", "d_avgfin10", "d_gain10", "d_std10", "d_dnf10", "d_fl10", "d_q_avg5", "d_career_win",
    "d_starts", "d_pts_share", "d_prev_share", "d_rank", "d_circ_avgfin", "d_circ_starts", "d_circ_wins",
    "c_avgfin5", "c_win10", "c_pod10", "c_mech_dnf20", "c_pts_share", "c_q_best5", "c_pit_rel10",
    "circ_street", "circ_road", "round_frac", "field",
]
FEATURES = {"pre_race": QUALI_FEATURES + HIST_FEATURES, "pre_quali": HIST_FEATURES}
FEATURE_LABELS = {
    "grid": "Starting grid position", "q_pos": "Qualifying position", "q_gap_pct": "Qualifying gap to pole (%)",
    "q_vs_teammate": "Qualifying vs teammate", "d_win10": "Driver win rate (last 10)", "d_pod10": "Driver podium rate (last 10)",
    "d_avgfin10": "Driver avg finish (last 10)", "d_gain10": "Positions gained per race (last 10)",
    "d_std10": "Finish consistency (std, last 10)", "d_dnf10": "Driver DNF rate (last 10)", "d_fl10": "Fastest-lap rate (last 10)",
    "d_q_avg5": "Avg qualifying position (last 5)", "d_career_win": "Career win rate", "d_starts": "Career starts",
    "d_pts_share": "Share of leader's points (season)", "d_prev_share": "Share of leader's points (prev. season)",
    "d_rank": "Championship position", "d_circ_avgfin": "Avg finish at this circuit", "d_circ_starts": "Starts at this circuit",
    "d_circ_wins": "Wins at this circuit", "c_avgfin5": "Constructor avg finish (last 5)", "c_win10": "Constructor win rate (last 10)",
    "c_pod10": "Constructor podium rate (last 10)", "c_mech_dnf20": "Constructor mechanical DNF rate (last 20)",
    "c_pts_share": "Constructor share of leader's points", "c_q_best5": "Constructor best qualifying (last 5)",
    "c_pit_rel10": "Pit-stop time vs field (last 10)", "circ_street": "Street circuit", "circ_road": "Road circuit",
    "round_frac": "Season progress", "field": "Field size",
}
NON_MECH = ("accident", "collision", "spun", "crash", "disqualif", "injur", "driver", "withdr", "fatal", "damage", "illness")


def build_frame(extra: pd.DataFrame | None = None, year_from: int = 1988) -> pd.DataFrame:
    """One row per driver per race with leak-free features. `extra` appends not-yet-run entries
    (race_id, driver_id, constructor_id, grid, q_pos, q_ms) so the upcoming race gets features too."""
    res = db.df("""SELECT race_id, driver_id, constructor_id, position_number, position_display_order, position_text,
                          points, grid_position_number AS grid, reason_retired, fastest_lap
                   FROM f1db_race_results WHERE year >= :y""", y=year_from)
    res = res[~res.position_text.isin(["DNQ", "DNPQ", "DNS", "DNP", "EX"])]
    ql = db.df("SELECT race_id, driver_id, position_number AS q_pos, time_millis, q1_millis, q2_millis, q3_millis "
               "FROM f1db_qualifying WHERE year >= :y", y=year_from)
    ql["q_ms"] = ql[["time_millis", "q1_millis", "q2_millis", "q3_millis"]].min(axis=1)
    res = res.merge(ql[["race_id", "driver_id", "q_pos", "q_ms"]].drop_duplicates(["race_id", "driver_id"]),
                    on=["race_id", "driver_id"], how="left")
    res["done"] = 1
    if extra is not None and len(extra):
        e = extra.copy()
        e["done"] = 0
        res = pd.concat([res, e], ignore_index=True)
    races = db.df("SELECT id AS race_id, year, round, date, grand_prix_id, circuit_id, circuit_type FROM f1db_races")
    f = res.merge(races, on="race_id").sort_values(["year", "round", "race_id"]).reset_index(drop=True)
    f["seq"] = f.groupby(["year", "round"]).ngroup()
    done = f.done == 1
    f["order"] = f.position_display_order.where(done)
    f["win"] = (f.position_number == 1).astype(float).where(done)
    f["podium"] = (f.position_number <= 3).astype(float).where(done)
    f["top5"] = (f.position_number <= 5).astype(float).where(done)
    f["fl"] = f.fastest_lap.map(lambda v: 1.0 if v in (True, "true", 1, "True") else 0.0).where(done)
    retired = f.reason_retired.fillna("").str.lower()
    f["dnf"] = (f.position_number.isna()).astype(float).where(done)
    f["mech_dnf"] = ((retired != "") & ~retired.str.contains("|".join(NON_MECH))).astype(float).where(done)
    f["gain"] = (f.grid - f.order).where(done)
    f["points"] = f.points.fillna(0.0).where(done, 0.0)

    def roll(key, col, n, fn="mean", mp=1):
        g = f.groupby(key)[col]
        return g.transform(lambda s: getattr(s.shift().rolling(n, min_periods=mp), fn)())

    f["d_win10"], f["d_pod10"] = roll("driver_id", "win", 10), roll("driver_id", "podium", 10)
    f["d_avgfin10"], f["d_gain10"] = roll("driver_id", "order", 10), roll("driver_id", "gain", 10)
    f["d_std10"], f["d_dnf10"] = roll("driver_id", "order", 10, "std", 3), roll("driver_id", "dnf", 10)
    f["d_fl10"], f["d_q_avg5"] = roll("driver_id", "fl", 10), roll("driver_id", "q_pos", 5)
    f["d_career_win"] = f.groupby("driver_id")["win"].transform(lambda s: s.shift().expanding().mean())
    f["d_starts"] = f.groupby("driver_id").cumcount()
    gc = f.groupby(["driver_id", "circuit_id"])
    f["d_circ_avgfin"] = gc["order"].transform(lambda s: s.shift().expanding().mean())
    f["d_circ_starts"] = gc.cumcount()
    f["d_circ_wins"] = gc["win"].transform(lambda s: s.shift().expanding().sum()).fillna(0)
    # season-to-date points before this race, as a share of the leader's
    f["d_pts_before"] = f.groupby(["driver_id", "year"])["points"].transform(lambda s: s.shift().cumsum()).fillna(0)
    mx = f.groupby("race_id")["d_pts_before"].transform("max")
    f["d_pts_share"] = np.where(mx > 0, f.d_pts_before / mx.replace(0, np.nan), np.nan)
    f["d_rank"] = f.groupby("race_id")["d_pts_before"].rank(ascending=False, method="min").where(mx > 0)
    season = f[done].groupby(["year", "driver_id"])["points"].sum().reset_index()
    season["share"] = season.points / season.groupby("year")["points"].transform("max").replace(0, np.nan)
    season["year"] += 1
    f = f.merge(season[["year", "driver_id", "share"]].rename(columns={"share": "d_prev_share"}), on=["year", "driver_id"], how="left")
    # constructor: aggregate per race, roll over previous races, map back
    c = f.groupby(["constructor_id", "seq", "race_id", "year"]).agg(
        c_fin=("order", "mean"), c_win=("win", "max"), c_pod=("podium", "mean"), c_mech=("mech_dnf", "mean"),
        c_pts=("points", "sum"), c_q=("q_pos", "min")).reset_index().sort_values("seq")
    pit = db.df("SELECT race_id, constructor_id, time_millis FROM f1db_pit_stops WHERE year >= :y AND time_millis < 60000", y=year_from)
    if len(pit):
        pit["rel"] = pit.time_millis / pit.groupby("race_id")["time_millis"].transform("median")
        c = c.merge(pit.groupby(["race_id", "constructor_id"])["rel"].median().reset_index(), on=["race_id", "constructor_id"], how="left")
    else:
        c["rel"] = np.nan
    g = c.groupby("constructor_id")
    for name, col, n in [("c_avgfin5", "c_fin", 5), ("c_win10", "c_win", 10), ("c_pod10", "c_pod", 10),
                         ("c_mech_dnf20", "c_mech", 20), ("c_q_best5", "c_q", 5), ("c_pit_rel10", "rel", 10)]:
        c[name] = g[col].transform(lambda s: s.shift().rolling(n, min_periods=1).mean())
    c["c_pts_before"] = c.groupby(["constructor_id", "year"])["c_pts"].transform(lambda s: s.shift().cumsum()).fillna(0)
    cm = c.groupby("race_id")["c_pts_before"].transform("max")
    c["c_pts_share"] = np.where(cm > 0, c.c_pts_before / cm.replace(0, np.nan), np.nan)
    f = f.merge(c[["race_id", "constructor_id", "c_avgfin5", "c_win10", "c_pod10", "c_mech_dnf20", "c_q_best5",
                   "c_pit_rel10", "c_pts_share"]], on=["race_id", "constructor_id"], how="left")
    # this-race qualifying information (known before lights out)
    f["q_gap_pct"] = ((f.q_ms / f.groupby("race_id")["q_ms"].transform("min") - 1) * 100).clip(upper=6)
    tm = f.groupby(["race_id", "constructor_id"])["q_pos"].transform("sum") - f.q_pos
    n_tm = f.groupby(["race_id", "constructor_id"])["q_pos"].transform("count")
    f["q_vs_teammate"] = np.where(n_tm == 2, f.q_pos - tm, np.nan)
    f["circ_street"] = (f.circuit_type == "STREET").astype(int)
    f["circ_road"] = (f.circuit_type == "ROAD").astype(int)
    f["round_frac"] = f["round"] / f.groupby("year")["round"].transform("max")
    f["field"] = f.groupby("race_id")["driver_id"].transform("count")
    return f


def make_models(xgb_params: dict | None = None) -> dict:
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    from catboost import CatBoostClassifier
    xp = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=5)
    xp.update(xgb_params or {})
    return {
        "xgboost": XGBClassifier(**xp, n_jobs=4, verbosity=0, eval_metric="logloss"),
        "lightgbm": LGBMClassifier(n_estimators=300, num_leaves=15, learning_rate=0.04, subsample=0.8, subsample_freq=1,
                                   colsample_bytree=0.8, min_child_samples=30, verbose=-1, n_jobs=4),
        "catboost": CatBoostClassifier(iterations=350, depth=5, learning_rate=0.05, verbose=0, thread_count=4, allow_writing_files=False),
        "logistic": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=3000)),
    }


def lgbm(reg=False):
    from lightgbm import LGBMClassifier, LGBMRegressor
    cls = LGBMRegressor if reg else LGBMClassifier
    return cls(n_estimators=250, num_leaves=15, learning_rate=0.04, subsample=0.8, subsample_freq=1,
               colsample_bytree=0.8, min_child_samples=30, verbose=-1, n_jobs=4)


def normalise(p: np.ndarray, race: np.ndarray, total: float) -> np.ndarray:
    """Scale probabilities so they sum to `total` within each race (1 winner, 3 podium places...)."""
    s = pd.Series(p).groupby(race).transform("sum").to_numpy()
    return np.clip(p * total / np.where(s > 0, s, 1), 0, 0.995)


def ece(p, y, bins=10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))


def scores(p, y, race) -> dict:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    d = pd.DataFrame({"p": p, "y": y, "r": race})
    top = d.loc[d.groupby("r")["p"].idxmax()]
    return {"accuracy": round(float(top.y.mean()), 4),
            "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4),
            "brier": round(float(((p - y) ** 2).mean()), 4), "ece": round(ece(p, y), 4), "n_races": int(d.r.nunique())}


def top3_hit(p, y, race) -> float:
    d = pd.DataFrame({"p": p, "y": y, "r": race})
    return round(float(d.sort_values("p", ascending=False).groupby("r").head(3).y.mean()), 4)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def pl_sample(logw: np.ndarray, n: int, rng) -> np.ndarray:
    """Plackett–Luce sampling via the Gumbel trick. Returns finishing positions [n, drivers] (1-based)."""
    g = rng.gumbel(size=(n, len(logw)))
    order = np.argsort(-(logw + g), axis=1)
    pos = np.empty_like(order)
    np.put_along_axis(pos, order, np.arange(1, len(logw) + 1)[None, :].repeat(n, 0), axis=1)
    return pos


def tune_xgb(f: pd.DataFrame, feats: list[str], trials: int = 25) -> dict:
    """Optuna search, validated on later seasons than it trains on."""
    import optuna
    from xgboost import XGBClassifier
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    last = int(f.year.max())
    tr, va = f[f.year < last - 4], f[(f.year >= last - 4) & (f.year < last - 1)]

    def obj(t):
        m = XGBClassifier(n_estimators=t.suggest_int("n_estimators", 150, 500), max_depth=t.suggest_int("max_depth", 2, 6),
                          learning_rate=t.suggest_float("learning_rate", 0.02, 0.15, log=True),
                          subsample=t.suggest_float("subsample", 0.6, 1.0), colsample_bytree=t.suggest_float("colsample_bytree", 0.5, 1.0),
                          min_child_weight=t.suggest_int("min_child_weight", 1, 12), reg_lambda=t.suggest_float("reg_lambda", 0.5, 8),
                          n_jobs=4, verbosity=0)
        m.fit(tr[feats], tr.win)
        return scores(normalise(m.predict_proba(va[feats])[:, 1], va.race_id.to_numpy(), 1), va.win, va.race_id.to_numpy())["log_loss"]

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=7))
    study.optimize(obj, n_trials=trials)
    return study.best_params


def train(variant: str, tune: bool = False, first_train_year: int = 1996, first_test_year: int = 2016) -> dict:
    feats = FEATURES[variant]
    f = build_frame()
    f = f[(f.year >= first_train_year) & (f.done == 1)].reset_index(drop=True)
    params_file = MODEL_DIR / f"xgb_params_{variant}.json"
    if tune:
        params_file.write_text(json.dumps(tune_xgb(f[f.year < int(f.year.max()) - 1], feats)))
    xgb_params = json.loads(params_file.read_text()) if params_file.exists() else None
    names = list(make_models())
    oof = []
    for season in range(first_test_year, int(f.year.max()) + 1):
        tr, te = f[f.year < season], f[f.year == season]
        if not len(te):
            continue
        o = te[["race_id", "year", "round", "driver_id", "win", "podium", "top5", "fl", "order", "grid", "d_rank"]].copy()
        r = te.race_id.to_numpy()
        for tgt, tot in (("win", 1), ("podium", 3)):
            for nm, m in make_models(xgb_params).items():
                m.fit(tr[feats], tr[tgt])
                o[f"{tgt}_{nm}"] = normalise(m.predict_proba(te[feats])[:, 1], r, tot)
            o[f"{tgt}_ens"] = normalise(o[[f"{tgt}_{n}" for n in names]].mean(axis=1).to_numpy(), r, tot)
        for tgt, tot in (("top5", 5), ("fl", 1)):
            o[f"{tgt}_ens"] = normalise(lgbm().fit(tr[feats], tr[tgt]).predict_proba(te[feats])[:, 1], r, tot)
        o["order_pred"] = lgbm(True).fit(tr[feats], tr["order"]).predict(te[feats])
        # baselines from the training window only
        for base, col in (("grid", "grid"), ("standings", "d_rank")):
            rate = tr.groupby(tr[col].round())["win"].mean()
            o[f"win_base_{base}"] = normalise(te[col].round().map(rate).fillna(tr.win.mean() / 5).to_numpy() + 1e-4, r, 1)
        oof.append(o)
        print(f"  {variant} fold {season}: {len(tr)} train rows, {te.race_id.nunique()} races", flush=True)
    oof = pd.concat(oof, ignore_index=True)
    # calibration: the calibrator applied to season S is fitted on out-of-fold predictions of seasons < S
    eval_from = first_test_year + 3
    cal = {}
    for tgt, tot in (("win", 1), ("podium", 3), ("top5", 5), ("fl", 1)):
        oof[f"{tgt}_cal"] = oof[f"{tgt}_ens"]
        for season in sorted(oof.year.unique()):
            prev, cur = oof[oof.year < season], oof.year == season
            if season >= eval_from:
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(prev[f"{tgt}_ens"], prev[tgt])
                oof.loc[cur, f"{tgt}_cal"] = normalise(iso.predict(oof.loc[cur, f"{tgt}_ens"]) + 1e-5, oof.loc[cur, "race_id"].to_numpy(), tot)
        cal[tgt] = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[f"{tgt}_ens"], oof[tgt])
    # keep isotonic calibration only where it improves out-of-sample log loss; otherwise use the raw ensemble
    applied = {}
    for tgt in list(cal):
        e = oof[oof.year >= eval_from]
        better = scores(e[f"{tgt}_cal"], e[tgt], e.race_id.to_numpy())["log_loss"] < scores(e[f"{tgt}_ens"], e[tgt], e.race_id.to_numpy())["log_loss"]
        applied[tgt] = bool(better)
        if not better:
            cal[tgt] = None
            oof[f"{tgt}_cal"] = oof[f"{tgt}_ens"]
    ev = oof[oof.year >= eval_from]
    r = ev.race_id.to_numpy()
    metrics = {"isotonic_calibration_applied": applied, "evaluated_seasons": f"{eval_from}–{int(oof.year.max())}", "n_races": int(ev.race_id.nunique()),
               "n_rows": int(len(ev)), "winner": {}, "podium": {}}
    for nm in names + ["cal", "base_grid", "base_standings"]:
        label = {"cal": "ensemble_final", "base_grid": "baseline_grid", "base_standings": "baseline_standings"}.get(nm, nm)
        metrics["winner"][label] = scores(ev[f"win_{nm}"], ev.win, r)
        if f"podium_{nm}" in ev:
            s = scores(ev[f"podium_{nm}"], ev.podium, r)
            s["top3_hit_rate"] = top3_hit(ev[f"podium_{nm}"], ev.podium, r)
            s.pop("accuracy")
            metrics["podium"][label] = s
    gpod = ev.assign(p=-ev.grid.fillna(99))
    metrics["podium"]["baseline_grid"] = {"top3_hit_rate": top3_hit(gpod.p, gpod.podium, r)}
    metrics["top5"] = {k: v for k, v in scores(ev.top5_cal, ev.top5, r).items() if k != "accuracy"}
    metrics["fastest_lap"] = scores(ev.fl_cal, ev.fl, r)
    ev = ev.assign(pred_rank=ev.groupby("race_id")["order_pred"].rank(method="first"))
    metrics["finishing_position"] = {
        "mae_model": round(float((ev.pred_rank - ev.order).abs().mean()), 3),
        "mae_baseline_grid": round(float((ev.grid.fillna(20) - ev.order).abs().mean()), 3),
        "spearman": round(float(ev.groupby("race_id").apply(lambda g: g.pred_rank.corr(g.order, method="spearman")).mean()), 3)}
    metrics["by_season"] = [
        {"season": int(y), "races": int(g.race_id.nunique()),
         "winner_accuracy": scores(g.win_cal, g.win, g.race_id.to_numpy())["accuracy"],
         "baseline_grid_accuracy": scores(g.win_base_grid, g.win, g.race_id.to_numpy())["accuracy"],
         "log_loss": scores(g.win_cal, g.win, g.race_id.to_numpy())["log_loss"]} for y, g in ev.groupby("year")]
    # reliability curve + Wilson intervals per probability band (used as the confidence interval)
    edges = [0, .02, .05, .1, .2, .35, .5, .7, 1.0001]
    bands = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = ev[(ev.win_cal >= lo) & (ev.win_cal < hi)]
        w = wilson(b.win.sum(), len(b))
        bands.append({"lo": lo, "hi": min(hi, 1), "n": int(len(b)), "predicted": round(float(b.win_cal.mean()), 4) if len(b) else None,
                      "observed": round(float(b.win.mean()), 4) if len(b) else None, "ci_lo": round(w[0], 4), "ci_hi": round(w[1], 4)})
    metrics["calibration_bands"] = bands
    # Plackett–Luce temperature: chosen so sampled finishing orders reproduce observed podium frequency
    rng = np.random.default_rng(11)
    best = (9, 1.0)
    for a in (0.5, 0.65, 0.8, 1.0, 1.2):
        err = []
        for _, g in ev.groupby("race_id"):
            pos = pl_sample(a * np.log(g.win_cal.to_numpy() + 1e-4), 400, rng)
            err.append((((pos <= 3).mean(0) - g.podium.to_numpy()) ** 2).mean())
        if np.mean(err) < best[0]:
            best = (float(np.mean(err)), a)
    metrics["pl_alpha"] = best[1]
    # final fit on everything available
    version = time.strftime("%Y%m%d-%H%M%S")
    final = {"win": {}, "podium": {}}
    for tgt in ("win", "podium"):
        for nm, m in make_models(xgb_params).items():
            final[tgt][nm] = m.fit(f[feats], f[tgt])
    final["top5"], final["fl"] = lgbm().fit(f[feats], f.top5), lgbm().fit(f[feats], f.fl)
    final["order"] = lgbm(True).fit(f[feats], f["order"])
    last = f.sort_values(["year", "round"]).iloc[-1]
    bundle = {"variant": variant, "version": version, "features": feats, "models": final, "calibrators": cal,
              "bands": bands, "pl_alpha": best[1], "train_through": f"{int(last.year)} R{int(last['round'])}",
              "xgb_params": xgb_params, "metrics": metrics}
    path = MODEL_DIR / f"{variant}_{version}.joblib"
    joblib.dump(bundle, path, compress=3)
    db.init()
    db.execute("UPDATE model_registry SET active=0 WHERE name=:n", n=variant)
    db.execute("INSERT INTO model_registry (name,version,created,train_through,n_rows,metrics,path,active) "
               "VALUES (:n,:v,:c,:t,:r,:m,:p,1)", n=variant, v=version, c=time.time(), t=bundle["train_through"],
               r=len(f), m=json.dumps(metrics), p=str(path))
    keep = ["race_id", "year", "round", "driver_id", "win", "podium", "order", "grid", "win_cal", "podium_cal", "top5_cal",
            "fl_cal", "order_pred", "win_base_grid"]
    db.replace_rows("prerace_oof", oof[keep].assign(variant=variant), {"variant": variant})
    db.index("prerace_oof", "race_id")
    return metrics


_bundles: dict = {}


def load(variant: str) -> dict | None:
    row = db.q("SELECT path, version FROM model_registry WHERE name=:n AND active=1 ORDER BY created DESC LIMIT 1", n=variant)
    if not row:
        return None
    if _bundles.get(variant, {}).get("version") != row[0]["version"]:
        _bundles[variant] = joblib.load(row[0]["path"])
    return _bundles[variant]


def _cal(c, p):
    return p if c is None else c.predict(p) + 1e-5


def predict(rows: pd.DataFrame, variant: str, n_sims: int = 5000) -> pd.DataFrame:
    """Score feature rows of ONE race. Adds calibrated probabilities, per-model spread, backtest-based
    confidence interval, SHAP drivers of the win prediction, expected points via Plackett–Luce sampling."""
    b = load(variant)
    feats, r = b["features"], np.zeros(len(rows))
    X = rows[feats].astype(float)
    out = rows[["driver_id", "constructor_id"]].copy()
    for tgt, tot in (("win", 1), ("podium", 3)):
        per = {nm: normalise(m.predict_proba(X)[:, 1], r, tot) for nm, m in b["models"][tgt].items()}
        ens = normalise(np.mean(list(per.values()), axis=0), r, tot)
        out[f"p_{tgt}"] = normalise(_cal(b["calibrators"][tgt], ens), r, tot)
        if tgt == "win":
            out["model_spread"] = [{k: round(float(v[i]), 4) for k, v in per.items()} for i in range(len(rows))]
    out["p_top5"] = normalise(_cal(b["calibrators"]["top5"], normalise(b["models"]["top5"].predict_proba(X)[:, 1], r, 5)), r, 5)
    out["p_fl"] = normalise(_cal(b["calibrators"]["fl"], normalise(b["models"]["fl"].predict_proba(X)[:, 1], r, 1)), r, 1)
    out["order_score"] = b["models"]["order"].predict(X)
    out["pred_pos"] = out.order_score.rank(method="first").astype(int)
    ci = []
    for p in out.p_win:
        band = next((x for x in b["bands"] if x["lo"] <= p < x["hi"] or (x["hi"] == 1 and p >= x["lo"])), None)
        ci.append({"lo": band["ci_lo"], "hi": band["ci_hi"], "n": band["n"]} if band and band["n"] >= 20 else None)
    out["ci"] = ci
    pos = pl_sample(b["pl_alpha"] * np.log(out.p_win.to_numpy() + 1e-4), n_sims, np.random.default_rng(5))
    pts = np.array(POINTS + [0] * 30)[pos - 1]
    out["exp_points"] = pts.mean(0)
    out["pos_dist"] = [np.bincount(pos[:, i], minlength=len(rows) + 1)[1:].astype(float) / n_sims for i in range(len(rows))]
    try:
        import shap
        sv = shap.TreeExplainer(b["models"]["win"]["xgboost"]).shap_values(X)
        ex = []
        for i in range(len(rows)):
            top = np.argsort(-np.abs(sv[i]))[:5]
            ex.append([{"feature": feats[j], "label": FEATURE_LABELS[feats[j]], "shap": round(float(sv[i][j]), 3),
                        "value": None if pd.isna(X.iloc[i, j]) else round(float(X.iloc[i, j]), 3)} for j in top])
        out["explain"] = ex
    except Exception as e:  # explanation is optional; never block a prediction
        out["explain"] = [[] for _ in range(len(rows))]
    return out


if __name__ == "__main__":
    tune = "--tune" in sys.argv
    for v in ("pre_race", "pre_quali"):
        t = time.time()
        m = train(v, tune=tune)
        print(v, f"{time.time() - t:.0f}s", json.dumps({k: m[k] for k in ("winner", "podium", "finishing_position", "pl_alpha")}, indent=1))
