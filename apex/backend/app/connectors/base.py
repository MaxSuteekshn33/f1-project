"""Shared HTTP plumbing for all providers: rate limiting, retries with backoff, caching and
health/error bookkeeping (persisted so the data-health dashboard sees every process)."""
from __future__ import annotations
import time, threading, os
import httpx
from .. import cache, db
from ..config import MIN_INTERVAL

SOURCES = {
    "openf1": {"label": "OpenF1 API", "url": "https://openf1.org/docs/",
               "coverage": "2023 → present: laps, stints, pits, positions, intervals, weather, race control, car telemetry, location",
               "limits": "Free tier: 3 req/s, 30 req/min; data is published after sessions. Real-time access during a session needs a paid OpenF1 account (OPENF1_USERNAME/PASSWORD)."},
    "jolpica": {"label": "Jolpica F1 (Ergast-compatible)", "url": "https://github.com/jolpica/jolpica-f1",
                "coverage": "1950 → present: schedule, results, qualifying, standings",
                "limits": "4 req/s burst, 500 req/h sustained. No live timing."},
    "f1db": {"label": "F1DB", "url": "https://github.com/f1db/f1db",
             "coverage": "1950 → present: races, results, qualifying, grids, pit stops (1994+), standings, fastest laps",
             "limits": "Bulk release, updated after each race weekend. No lap-by-lap timing, no weather."},
    "openmeteo": {"label": "Open-Meteo", "url": "https://open-meteo.com/",
                  "coverage": "Forecast up to 16 days; 15-minute precipitation; past ~3 months via past_days",
                  "limits": "Free non-commercial use, ~10,000 calls/day. Numerical weather model for the area — not a track-surface measurement."},
    "fastf1": {"label": "FastF1", "url": "https://github.com/theOehrly/Fast-F1",
               "coverage": "2018 → present via F1 live-timing archive: laps, telemetry, tyre data",
               "limits": "Optional connector, loaded on demand; depends on livetiming.formula1.com availability. Live stream needs F1TV credentials."},
}

_last_call: dict[str, float] = {}
_cooldown: dict[str, tuple[float, str]] = {}   # source -> (until epoch, reason): provider asked us to back off
_locks: dict[str, threading.Lock] = {k: threading.Lock() for k in SOURCES}


def record(source: str, ok: bool, url: str = "", error: str = "") -> None:
    now = time.time()
    try:
        row = db.q("SELECT * FROM source_health WHERE source=:s", s=source)
        r = row[0] if row else {"requests": 0, "failures": 0, "last_success": None, "last_error": None, "last_error_at": None}
        db.execute("DELETE FROM source_health WHERE source=:s", s=source)
        db.execute("""INSERT INTO source_health (source,status,last_success,last_attempt,last_error,last_error_at,requests,failures)
                      VALUES (:s,:st,:ls,:la,:le,:lea,:rq,:fl)""",
                   s=source, st="ok" if ok else "error", ls=now if ok else r["last_success"], la=now,
                   le=r["last_error"] if ok else error[:500], lea=r["last_error_at"] if ok else now,
                   rq=(r["requests"] or 0) + 1, fl=(r["failures"] or 0) + (0 if ok else 1))
        if not ok:
            db.execute("INSERT INTO source_errors (ts,source,url,error) VALUES (:t,:s,:u,:e)",
                       t=now, s=source, u=url[:300], e=error[:500])
    except Exception:
        pass  # health bookkeeping must never break a data request


class SourceError(RuntimeError):
    pass


class Connector:
    name = "base"
    base_url = ""
    timeout = 45.0
    max_backoff = 30.0

    def __init__(self):
        self.client = httpx.Client(timeout=self.timeout, follow_redirects=True,
                                   verify=os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE") or True,
                                   headers={"User-Agent": "apex-f1-intelligence/1.0", "Accept": "application/json"})

    def headers(self) -> dict:
        return {}

    def _throttle(self):
        gap = MIN_INTERVAL.get(self.name, 0.5)
        with _locks[self.name]:
            wait = _last_call.get(self.name, 0) + gap - time.time()
            if wait > 0:
                time.sleep(wait)
            _last_call[self.name] = time.time()

    def get(self, path: str, query: str = "", ttl: float = 0, retries: int = 4, empty_404: bool = False):
        """GET base_url/path?query. `query` is passed verbatim (OpenF1 uses operators like date>=...)."""
        url = f"{self.base_url}/{path.lstrip('/')}" + (f"?{query}" if query else "")
        key = f"http:{url}"
        if ttl:
            hit = cache.get(key)
            if hit is not None:
                return hit
        err = ""
        cd = _cooldown.get(self.name)
        if cd and cd[0] > time.time():
            raise SourceError(f"{self.name}: {cd[1]} — not retried until {time.strftime('%H:%M UTC', time.gmtime(cd[0]))}")
        for attempt in range(retries):
            self._throttle()
            try:
                r = self.client.get(url, headers=self.headers())
                if r.status_code == 404 and empty_404:
                    record(self.name, True)
                    return []
                if r.status_code == 429 or r.status_code >= 500:
                    err = f"HTTP {r.status_code}"
                    ra = float(r.headers.get("Retry-After", 0) or 0)
                    if ra > 30:   # quota exhausted: fail fast and respect the provider's back-off instead of blocking a request
                        reason = ""
                        try: reason = r.json().get("reason", "")
                        except Exception: pass
                        err = f"HTTP 429 rate limited ({reason or 'quota exhausted'})"
                        _cooldown[self.name] = (time.time() + min(ra, 6 * 3600), err)
                        break
                    time.sleep(ra or min(self.max_backoff, 2 * 2 ** attempt))
                    continue
                if r.status_code >= 400:
                    err = f"HTTP {r.status_code}: {r.text[:200]}"
                    break
                data = r.json()
                record(self.name, True)
                if ttl:
                    cache.put(key, data, ttl)
                return data
            except (httpx.HTTPError, ValueError) as e:
                err = f"{type(e).__name__}: {e}"
                time.sleep(min(30, 2 * 2 ** attempt))
        record(self.name, False, url, err)
        raise SourceError(f"{self.name}: {err} ({url})")
