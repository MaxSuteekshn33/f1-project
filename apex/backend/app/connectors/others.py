"""Jolpica (Ergast-compatible), Open-Meteo, F1DB and FastF1 connectors."""
from __future__ import annotations
import io, time, zipfile
import pandas as pd
from .base import Connector, record
from ..config import JOLPICA_BASE, OPENMETEO_BASE, F1DB_ZIP_URL, DATA_DIR


class Jolpica(Connector):
    name = "jolpica"
    base_url = JOLPICA_BASE

    def table(self, path: str, key: str, ttl: float = 900) -> list[dict]:
        data = self.get(f"{path}.json", "limit=100", ttl=ttl)
        return data["MRData"][key]

    def schedule(self, season="current"):
        return self.table(f"{season}", "RaceTable")["Races"]

    def driver_standings(self, season="current"):
        lists = self.table(f"{season}/driverstandings", "StandingsTable")["StandingsLists"]
        return lists[0] if lists else {}

    def constructor_standings(self, season="current"):
        lists = self.table(f"{season}/constructorstandings", "StandingsTable")["StandingsLists"]
        return lists[0] if lists else {}

    def qualifying(self, season, rnd):
        races = self.table(f"{season}/{rnd}/qualifying", "RaceTable")["Races"]
        return races[0]["QualifyingResults"] if races else []

    def results(self, season, rnd):
        races = self.table(f"{season}/{rnd}/results", "RaceTable")["Races"]
        return races[0]["Results"] if races else []


class OpenMeteo(Connector):
    name = "openmeteo"
    base_url = OPENMETEO_BASE
    timeout = 15.0
    max_backoff = 3.0      # interactive requests: never stall the dashboard on a slow forecast
    HOURLY = "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,rain,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover"
    M15 = "temperature_2m,precipitation,rain,wind_speed_10m,wind_direction_10m"

    def forecast(self, lat: float, lon: float, past_days: int = 0, forecast_days: int = 3, ttl: float = 600) -> dict:
        qs = (f"latitude={lat:.4f}&longitude={lon:.4f}&hourly={self.HOURLY}&minutely_15={self.M15}"
              f"&current=temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m,wind_direction_10m"
              f"&wind_speed_unit=ms&timeformat=unixtime&timezone=UTC&past_days={past_days}&forecast_days={forecast_days}")
        return self.get("forecast", qs, ttl=ttl, retries=2)


class F1DB(Connector):
    name = "f1db"
    base_url = ""
    timeout = 180.0

    def download(self) -> dict[str, pd.DataFrame]:
        """Download the latest F1DB CSV release and return its tables keyed by file stem."""
        try:
            r = self.client.get(F1DB_ZIP_URL)
            r.raise_for_status()
        except Exception as e:
            record("f1db", False, F1DB_ZIP_URL, f"{type(e).__name__}: {e}")
            raise
        record("f1db", True)
        (DATA_DIR / "f1db-csv.zip").write_bytes(r.content)
        out = {}
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in z.namelist():
                if n.endswith(".csv"):
                    out[n.rsplit("/", 1)[-1][5:-4]] = pd.read_csv(z.open(n), low_memory=False)
        return out


class FastF1Source:
    """Optional: FastF1 gives lap/telemetry data back to 2018 from the F1 live-timing archive.
    Loaded lazily; any failure is reported to the health table instead of being papered over."""
    name = "fastf1"

    def laps(self, year: int, gp: str | int, session: str = "R") -> pd.DataFrame:
        try:
            import fastf1
            cache_dir = DATA_DIR / "fastf1_cache"
            cache_dir.mkdir(exist_ok=True)
            fastf1.Cache.enable_cache(str(cache_dir))
            s = fastf1.get_session(year, gp, session)
            s.load(telemetry=False, weather=False, messages=False)
            laps = s.laps[["Driver", "DriverNumber", "LapNumber", "LapTime", "Compound", "TyreLife", "Stint", "Position"]].copy()
            laps["LapTime"] = laps["LapTime"].dt.total_seconds()
            record("fastf1", True)
            return laps
        except Exception as e:
            record("fastf1", False, f"{year}/{gp}/{session}", f"{type(e).__name__}: {e}")
            raise


jolpica, openmeteo, f1db, fastf1_source = Jolpica(), OpenMeteo(), F1DB(), FastF1Source()
