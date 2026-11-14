# APEX F1 Intelligence

Race prediction, pit-stop and tyre strategy optimisation, weather-adaptive decisions and race replay,
built on real Formula 1 data. FastAPI + Python models on the back end, Next.js on the front end.

The platform answers three questions for any lap of any stored race (or a live one, when the provider
delivers data): **what is happening**, **what is likely to happen next**, and **what is the best decision**.

## Quick start

```bash
cd apex
make install          # Python venv + npm packages
make bootstrap        # load history, backfill races, train models (~35 min, see below)
make api              # http://localhost:8000  (terminal 1)
make web              # http://localhost:3000  (terminal 2)
```

`make quick` is a 4-minute alternative (F1DB + the latest race, pre-race models only; no in-race model).
`make bootstrap` is slow only because OpenF1's free tier allows 30 requests per minute and the backfill
needs about 750. It is resumable — run it again if interrupted.

With Docker (PostgreSQL/TimescaleDB image + Redis):

```bash
docker compose up --build -d
docker compose run --rm backend python -m app.bootstrap
```

### Hosting: Vercel (front end) + a Python host (API)

Vercel runs the Next.js front end. It cannot run the API: the Python models, the database and the
WebSocket loop need a long-running server, so the API is deployed separately (a Render blueprint is in
`render.yaml`; any Docker host works).

1. **API** — on Render choose *New → Blueprint* and pick this repository. The first start loads the data
   and trains the models in the background (about 35 minutes; `GET /api/health` shows progress). Note the
   service URL, e.g. `https://apex-f1-backend.onrender.com`.
2. **Front end** — on Vercel choose *Add New → Project*, import the repository and set
   **Root Directory** to `apex/frontend` (or `frontend` if `apex/` is the repo root). Add two environment
   variables, then deploy:
   - `BACKEND_URL` = the API URL from step 1
   - `NEXT_PUBLIC_WS_URL` = the same host with `wss://` and `/ws/live`, e.g. `wss://apex-f1-backend.onrender.com/ws/live`

The hosted setup has not been deployed or tested from this repository.

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file in `apex/data/` | e.g. `postgresql+psycopg2://apex:apex@localhost:5432/apex` |
| `REDIS_URL` | unset → in-process cache | HTTP response cache |
| `OPENF1_USERNAME` / `OPENF1_PASSWORD` | unset | paid OpenF1 account → real-time data during sessions |
| `LIVE_POLL_SECONDS` / `IDLE_POLL_SECONDS` | 8 / 300 | live-loop cadence |
| `OPENF1_MIN_INTERVAL` etc. | 2.1 s | per-provider request spacing |
| `MC_SIMS` | 1000 | Monte Carlo runs per scenario |
| `APEX_BOOTSTRAP` | 0 | 1 = build the database and models on first start (`quick` = latest race only) |
| `APEX_AUTO_RETRAIN` | 0 | 1 = refresh data and retrain on start-up when new races exist |
| `BACKEND_URL`, `NEXT_PUBLIC_WS_URL` | localhost:8000 | front end → API proxy and WebSocket |

## The ten sections

| # | Section | What it does |
|---|---|---|
| 1 | Race Command Centre | Session header, weather, neutralisations, timing tower (gaps, tyres, stints, pits, positions gained, predicted finish), team/driver/contender filters |
| 2 | Live Timing & Telemetry | Circuit map with car positions and sectors, two-lap telemetry comparison (speed, throttle, brake, gear, RPM, DRS, time delta), lap and position traces, pace by compound, qualifying vs race, teammates |
| 3 | AI Race Predictor | In-race win/podium/top-5/expected finish per lap; pre-race winner, podium, top-5, fastest lap, expected points and championship projection; SHAP factors |
| 4 | Pit Stop & Tyre Strategy | Fitted tyre model, measured pit loss, 1/2/3-stop and alternative-compound plans (OR-Tools), pit window, undercut screen, rivals' windows |
| 5 | Weather Intelligence | Track sensor vs Open-Meteo forecast, wetness model, tyre-class crossover, scenarios A (dry→wet), B (wet→dry), C (disruption) with a decision table |
| 6 | Race Simulation Lab | Up to four user scenarios side by side with finishing-position distributions; Safety Car / VSC / green pit comparison |
| 7 | Historical Race Intelligence | Search 1950→today; seasons, circuits, drivers; races most similar to current conditions |
| 8 | Driver & Constructor Analytics | Season form, qualifying vs race, teammate head-to-heads, reliability, pit-lane times, speed trap |
| 9 | AI Strategic Recommendations | Plain-English calls (situation, data, decision, advantage, risk, confidence) assembled from the other modules |
| 10 | Data Sources & Model Performance | Per-source status, freshness, coverage, limits, errors; backtests vs baselines; model versions |

The header's **lap control** replays any stored race: every module then uses only records timestamped up
to that lap. That is also how in-race models are validated without leakage.

## Data

| Source | Used for | Notes |
|---|---|---|
| [OpenF1](https://openf1.org/docs/) | laps, stints, pits, positions, track weather, race control, car telemetry, car x/y | 2023 onwards. Free tier publishes after the session; real-time needs a paid account |
| [F1DB](https://github.com/f1db/f1db) | results, qualifying, grids, pit stops (1994+), standings, 1950→today | bulk release, loaded into the database |
| [Jolpica](https://github.com/jolpica/jolpica-f1) | qualifying result for the upcoming race, before the F1DB release catches up | Ergast-compatible |
| [Open-Meteo](https://open-meteo.com/) | 15-minute precipitation, probability, wind for the circuit area | a weather model, never treated as a track measurement; snapshots are stored and reused if the API is unavailable |
| [FastF1](https://github.com/theOehrly/Fast-F1) | optional connector (laps back to 2018) | wired and health-tracked, not used by default |

Each connector is independent (`app/connectors/`), rate-limited, retried with back-off, and records
status, last success and errors to the database. Ingestion normalises timestamps to UTC epoch seconds,
coerces units, rejects rows without keys, removes duplicates and is idempotent per session.

The header shows **LIVE**, **DELAYED** (session running but the provider is not real-time) or
**HISTORICAL**. Nothing is simulated to fill gaps; every panel carries a provenance tag: OBSERVED,
HISTORICAL, MODEL, ASSUMPTION or FORECAST.

## Models and how well they do

All validation is walk-forward by season: train on seasons before S, test on S. No random splits.

**Pre-race** (`app/prerace.py`) — XGBoost, LightGBM, CatBoost and logistic regression, averaged and
normalised per race; XGBoost tuned with Optuna. Features are built only from earlier races (rolling form,
circuit history, constructor form, reliability, pit-lane time) plus this weekend's qualifying. Tested on
172 races, 2019–2026:

| | Winner accuracy | Log loss | Brier |
|---|---|---|---|
| Ensemble, after qualifying | 55.2% | 0.0975 | 0.0293 |
| Baseline: pole-sitter / grid frequency | 55.2% | 0.1135 | 0.0319 |
| Baseline: championship leader | 47.7% | 0.1295 | 0.0369 |
| Ensemble, before qualifying | 48.3% | 0.1182 | 0.0346 |

The ensemble picks the winner about as often as "pole wins" but assigns better probabilities (14% lower
log loss). Finishing-position error is 3.31 places against 3.47 for grid order. For the podium, the
model's top-three hit rate (67.6%) is slightly below simply taking the first three on the grid (68.4%).

**In-race** (`app/inrace.py`) — LightGBM, XGBoost and logistic regression on race states rebuilt lap by
lap from 90 stored races (98,582 rows), with the out-of-fold pre-race probability as a prior. Tested on
2024–2026: log loss 0.0731 against 0.0839 for "win frequency from this position at this race phase";
winner accuracy is the same as that baseline (73.2%). It is blended with the Monte Carlo simulator, and
the dashboard shows both and the range between them.

**Tyre model** (`app/strategy.py`) — per session, ridge regression of green-flag lap times on driver,
lap fixed effects (fuel and track evolution), compound offset and tyre age, shrunk towards last year's
race at the same circuit. **Pit loss** is measured from in/out laps when enough clean stops exist.

**Optimiser** — OR-Tools CP-SAT chooses stop laps and compounds per stop count, enforcing the
two-dry-compound rule. **Simulator** (`app/sim.py`) — vectorised Monte Carlo over the whole field with
lap-time noise, pace uncertainty, traffic, pit variation, retirements, Safety Car/VSC at historical base
rates and a track-wetness timeline.

`python -m app.retrain` refreshes data and retrains when new races exist; a new version replaces the
active one only if its backtest log loss is not more than 3% worse. Versions and metrics are stored in
`model_registry`.

## Known limits

- **Live data**: the live loop and WebSocket push are implemented but have only been exercised against
  finished sessions; real-time behaviour during a race needs a paid OpenF1 account and has not been tested.
- **Wetness and tyre-class crossover** are modelled, not measured: the penalty curves and wetting/drying
  rates are stated assumptions. No source provides track-surface wetness.
- **Safety Car pit-loss factors** (45% / 62% of the green-flag loss), tyre life shares and the pass
  threshold are assumptions, listed on the pages that use them.
- **Circuit map** is drawn from car x/y traces rather than MapLibre: OpenF1 positions are not geographic.
- **TimescaleDB**: the app runs on the Timescale image, but tables are plain PostgreSQL tables (no
  hypertables). The service layer was smoke-tested on PostgreSQL 16; the Docker images were not built here.
- **Not available from the sources**: cornering performance, tyre temperatures, fuel loads, team radio,
  weather before 2023. Wet-weather skill is therefore not a model input.
- **Advisor** is rule-based over the platform's own numbers; it is not a language model and takes no
  free-text questions.
- Three 2026/2023 sessions (Jeddah, Sakhir round 2026, Imola 2023) have no laps in OpenF1 and are skipped.

## Layout

```
apex/backend/app/   config, db, cache, connectors/, ingest, racestate, strategy, sim, weather,
                    prerace, inrace, service, live, retrain, bootstrap, main (FastAPI)
apex/backend/tests/ offline unit tests           apex/frontend/  Next.js app (app/, components/, lib/)
apex/data/          database, downloads, models (git-ignored, rebuilt by bootstrap)
```
