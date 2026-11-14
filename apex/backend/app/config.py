"""Central configuration. Everything is overridable through environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("APEX_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR = DATA_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# SQLite by default (zero setup). Point at PostgreSQL / TimescaleDB with e.g.
# DATABASE_URL=postgresql+psycopg2://apex:apex@localhost:5432/apex
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'apex.db'}")
REDIS_URL = os.getenv("REDIS_URL", "")

OPENF1_BASE = os.getenv("OPENF1_BASE", "https://api.openf1.org/v1")
# Optional paid OpenF1 account -> real-time access during sessions.
OPENF1_USERNAME = os.getenv("OPENF1_USERNAME", "")
OPENF1_PASSWORD = os.getenv("OPENF1_PASSWORD", "")
JOLPICA_BASE = os.getenv("JOLPICA_BASE", "https://api.jolpi.ca/ergast/f1")
OPENMETEO_BASE = os.getenv("OPENMETEO_BASE", "https://api.open-meteo.com/v1")
F1DB_ZIP_URL = os.getenv("F1DB_ZIP_URL", "https://github.com/f1db/f1db/releases/latest/download/f1db-csv.zip")

# Minimum seconds between requests, per provider (free-tier terms: OpenF1 3 req/s & 30 req/min;
# Jolpica 4 req/s & 500 req/h; Open-Meteo 600 req/min).
MIN_INTERVAL = {
    "openf1": float(os.getenv("OPENF1_MIN_INTERVAL", "2.1")),
    "jolpica": float(os.getenv("JOLPICA_MIN_INTERVAL", "0.5")),
    "openmeteo": float(os.getenv("OPENMETEO_MIN_INTERVAL", "0.2")),
    "f1db": 1.0,
    "fastf1": 1.0,
}
# Polling cadence of the live loop (seconds).
LIVE_POLL_SECONDS = float(os.getenv("LIVE_POLL_SECONDS", "8"))
IDLE_POLL_SECONDS = float(os.getenv("IDLE_POLL_SECONDS", "300"))
# A session is LIVE when in progress and the newest record is younger than this.
LIVE_FRESHNESS_SECONDS = float(os.getenv("LIVE_FRESHNESS_SECONDS", "90"))
MC_SIMS = int(os.getenv("MC_SIMS", "1000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
