"""Offline unit tests (no network, no database rows needed)."""
import numpy as np
import pandas as pd
from app import strategy as sg, sim
from app.prerace import normalise, wilson, pl_sample, ece
from app.connectors.openf1 import to_epoch


def model(pit=22.0):
    return {"compounds": {"SOFT": {"deg": 0.10, "offset": -0.6}, "MEDIUM": {"deg": 0.06, "offset": 0.0}, "HARD": {"deg": 0.035, "offset": 0.5}},
            "pit_loss": pit}


def test_timestamps_normalise_to_utc_epoch():
    s = pd.Series(["2026-11-08T17:00:00+00:00", "2026-11-08T14:00:00-03:00", None])
    e = to_epoch(s)
    assert e[0] == e[1] and np.isnan(e[2])


def test_optimiser_respects_two_compound_rule_and_distance():
    p = sg.optimise(model(), cur_lap=10, total_laps=60, comp="MEDIUM", age=10, used=["MEDIUM"], stops=1)
    assert p and p["rule_ok"] and len(p["plan"]) == 1
    assert p["plan"][0]["compound"] != "MEDIUM"                      # must run a second dry compound
    assert sum(s["laps"] for s in p["stints"]) == 50                 # covers exactly the remaining laps
    assert 10 < p["plan"][0]["lap"] < 60


def test_no_stop_is_illegal_with_one_compound_and_more_stops_cost_pit_time():
    m = model()
    p0 = sg.optimise(m, 10, 60, "MEDIUM", 10, ["MEDIUM"], 0)
    assert p0 is not None and not p0["rule_ok"]
    p1, p2 = sg.optimise(m, 10, 60, "MEDIUM", 10, ["MEDIUM"], 1), sg.optimise(m, 10, 60, "MEDIUM", 10, ["MEDIUM"], 2)
    assert p2["pit_time_lost"] == 2 * m["pit_loss"] and p1["pit_time_lost"] == m["pit_loss"]


def test_cheaper_pit_lane_favours_more_stops():
    cheap, dear = model(pit=8.0), model(pit=35.0)
    best = lambda m: min((sg.optimise(m, 5, 60, "SOFT", 5, ["SOFT"], k) for k in (1, 2, 3)), key=lambda p: p["rel_time"])["stops"]
    assert best(cheap) >= best(dear)


def test_pit_window_contains_the_optimum():
    m = model()
    p = sg.optimise(m, 10, 60, "MEDIUM", 10, ["MEDIUM"], 1)
    w = sg.window(m, p, 10, 60, "MEDIUM", 10)
    assert w["open"] <= w["optimal"] <= w["close"]


def test_wet_penalty_crossovers():
    f = lambda c, w: float(sim.wet_penalty(np.array(c), w))
    assert f(0, 0.0) == 0 and f(0, 0.1) < f(3, 0.1)                  # dry: slicks faster
    assert f(3, 0.45) < f(0, 0.45) and f(3, 0.45) < f(4, 0.45)       # damp: intermediates fastest
    assert f(4, 0.95) < f(3, 0.95) < f(0, 0.95)                      # soaked: full wets fastest
    assert f(0, sim.W_SLICK_TO_INTER - 0.05) < f(3, sim.W_SLICK_TO_INTER - 0.05)
    assert f(0, sim.W_SLICK_TO_INTER + 0.05) > f(3, sim.W_SLICK_TO_INTER + 0.05)


def test_wetness_path_wets_then_dries():
    path = sim.wetness_path(0.0, [0.8] * 5 + [0.0] * 30, 30, 2)
    assert path[4] > 0.5 and path[-1] < path[4] and (np.diff(path[5:]) <= 0).all()


def test_probability_helpers():
    p = normalise(np.array([0.2, 0.2, 0.1, 0.5, 0.5]), np.array([1, 1, 1, 2, 2]), 1.0)
    assert abs(p[:3].sum() - 1) < 1e-9 and abs(p[3:].sum() - 1) < 1e-2
    lo, hi = wilson(5, 50)
    assert 0 < lo < 0.1 < hi < 0.25
    pos = pl_sample(np.log(np.array([0.7, 0.2, 0.1])), 4000, np.random.default_rng(0))
    assert (pos == 1).mean(0)[0] > 0.6 and sorted(pos[0].tolist()) == [1, 2, 3]
    assert ece(np.array([0.1] * 100), np.array([1] * 10 + [0] * 90)) < 1e-9
