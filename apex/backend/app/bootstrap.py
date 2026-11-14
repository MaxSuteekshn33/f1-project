"""One-shot setup: load history, backfill lap-level race data, train all models.
    python -m app.bootstrap            (≈35 min: OpenF1's free tier allows 30 requests/min)
    python -m app.bootstrap --quick    (F1DB + latest race only, pre-race models; ≈4 min)
"""
import sys, time
from . import db, ingest, prerace, inrace

state = {"running": False, "step": None, "error": None, "finished": None}


def needed() -> bool:
    """True when the database has no history or no trained pre-race model yet."""
    db.init()
    if not db.has_table("f1db_race_results") or not db.has_table("of1_laps"):
        return True
    return not db.q("SELECT 1 AS x FROM model_registry WHERE name='pre_race' AND active=1 LIMIT 1")


def run(quick: bool = False, tune: bool = False) -> None:
    t = time.time()
    state.update(running=True, error=None, finished=None)
    try:
        db.init()
        state["step"] = "1/4 loading F1DB history"; print(state["step"], flush=True); print(ingest.ingest_f1db())
        state["step"] = "2/4 loading the latest race" if quick else "2/4 backfilling OpenF1 race data (rate-limited, ~25 min)"; print(state["step"], flush=True)
        if quick:
            ingest.ingest_sessions(); k = ingest.latest_race_key(); print(k, ingest.ingest_session(k))
        else:
            ingest.backfill()
        state["step"] = "3/4 training pre-race models"; print(state["step"], flush=True)
        for v in ("pre_race", "pre_quali"):
            m = prerace.train(v, tune=tune)
            print(v, m["winner"]["ensemble_final"])
        if not quick:
            state["step"] = "4/4 training in-race model"; print(state["step"], flush=True)
            print(inrace.train()["winner"])
        state["step"] = "done"
        print(f"done in {(time.time() - t) / 60:.1f} min")
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        state.update(running=False, finished=time.time())


if __name__ == "__main__":
    run(quick="--quick" in sys.argv, tune="--tune" in sys.argv)
