"""One-shot setup: load history, backfill lap-level race data, train all models.
    python -m app.bootstrap            (≈35 min: OpenF1's free tier allows 30 requests/min)
    python -m app.bootstrap --quick    (F1DB + latest race only, pre-race models; ≈4 min)
"""
import sys, time
from . import db, ingest, prerace, inrace

if __name__ == "__main__":
    quick = "--quick" in sys.argv
    t = time.time()
    db.init()
    print("1/4 F1DB history …", flush=True); print(ingest.ingest_f1db())
    print("2/4 OpenF1 sessions + races …", flush=True)
    if quick:
        ingest.ingest_sessions(); k = ingest.latest_race_key(); print(k, ingest.ingest_session(k))
    else:
        ingest.backfill()
    print("3/4 pre-race models (walk-forward backtest) …", flush=True)
    for v in ("pre_race", "pre_quali"):
        m = prerace.train(v, tune="--tune" in sys.argv)
        print(v, m["winner"]["ensemble_final"])
    if not quick:
        print("4/4 in-race model …", flush=True)
        print(inrace.train()["winner"])
    else:
        print("4/4 skipped (--quick): the in-race model needs the full race backfill.")
    print(f"done in {(time.time() - t) / 60:.1f} min")
