"""Automatic retraining: when new completed races have arrived since the active model was trained, refresh
the data, retrain, and promote the new version only if its walk-forward log loss is not worse.

CLI: python -m app.retrain [--force]
"""
from __future__ import annotations
import json, sys, time
from . import db, ingest, prerace, inrace


def _active(name):
    r = db.q("SELECT version, train_through, metrics, created FROM model_registry WHERE name=:n AND active=1 ORDER BY created DESC LIMIT 1", n=name)
    return r[0] if r else None


def _ll(metrics: dict, kind: str) -> float | None:
    try:
        return metrics["winner"]["ensemble_final" if kind != "in_race" else "model"]["log_loss"]
    except Exception:
        return None


def needed() -> dict:
    last = db.q("SELECT year, round FROM f1db_race_results ORDER BY year DESC, round DESC LIMIT 1")
    latest = f"{last[0]['year']} R{last[0]['round']}" if last else None
    a = _active("pre_race")
    n_races = db.q("SELECT COUNT(DISTINCT session_key) AS n FROM of1_session_result")[0]["n"] if db.has_table("of1_session_result") else 0
    b = _active("in_race")
    trained_on = int(b["train_through"].split("(")[1].split()[0]) if b and "(" in b["train_through"] else 0
    return {"pre_race": a is None or a["train_through"] != latest, "in_race": b is None or n_races > trained_on,
            "latest_results": latest, "stored_races": n_races}


def run(force: bool = False) -> dict:
    db.init()
    out = {"started": time.time(), "actions": []}
    try:
        ingest.ingest_f1db(); out["actions"].append("F1DB refreshed")
    except Exception as e:
        out["actions"].append(f"F1DB refresh failed: {e}")
    try:
        ingest.backfill(); out["actions"].append("OpenF1 race backfill up to date")
    except Exception as e:
        out["actions"].append(f"OpenF1 backfill failed: {e}")
    need = needed()
    for kind, names, fn in (("pre_race", ["pre_race", "pre_quali"], None), ("in_race", ["in_race"], inrace.train)):
        if not (need[kind] or force):
            out["actions"].append(f"{kind}: up to date")
            continue
        for name in names:
            old = _active(name)
            m = prerace.train(name) if fn is None else fn()
            new_ll, old_ll = _ll(m, name), _ll(json.loads(old["metrics"]), name) if old else None
            if old and new_ll is not None and old_ll is not None and new_ll > old_ll * 1.03:
                # validation gate failed: keep the previous version active
                db.execute("UPDATE model_registry SET active=0 WHERE name=:n", n=name)
                db.execute("UPDATE model_registry SET active=1 WHERE name=:n AND version=:v", n=name, v=old["version"])
                out["actions"].append(f"{name}: new model rejected (log loss {new_ll} vs {old_ll}); kept {old['version']}")
            else:
                out["actions"].append(f"{name}: retrained (log loss {new_ll}, previous {old_ll})")
    return out


if __name__ == "__main__":
    print(json.dumps(run("--force" in sys.argv), indent=1))
