"""TTL cache: Redis when REDIS_URL is set and reachable, otherwise in-process memory."""
import json, time, threading
from .config import REDIS_URL

_mem: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()
_redis = None
if REDIS_URL:
    try:
        import redis
        _redis = redis.Redis.from_url(REDIS_URL, socket_timeout=2)
        _redis.ping()
    except Exception:
        _redis = None

BACKEND = "redis" if _redis else "memory"


def get(key: str):
    if _redis:
        try:
            v = _redis.get("apex:" + key)
            return json.loads(v) if v else None
        except Exception:
            pass
    with _lock:
        hit = _mem.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        _mem.pop(key, None)
    return None


def put(key: str, value, ttl: float) -> None:
    if ttl <= 0:
        return
    if _redis:
        try:
            _redis.setex("apex:" + key, int(max(1, ttl)), json.dumps(value, default=str))
            return
        except Exception:
            pass
    with _lock:
        if len(_mem) > 600:
            now = time.time()
            for k in [k for k, (exp, _) in _mem.items() if exp < now]:
                _mem.pop(k, None)
            if len(_mem) > 600:
                _mem.clear()
        _mem[key] = (time.time() + ttl, value)


def cached(ttl: float):
    """Decorator caching a function on its positional/keyword args (in-memory objects allowed)."""
    def deco(fn):
        store: dict = {}
        def wrap(*a, **k):
            key = (a, tuple(sorted(k.items())))
            hit = store.get(key)
            if hit and hit[0] > time.time():
                return hit[1]
            val = fn(*a, **k)
            if len(store) > 300:
                store.clear()
            store[key] = (time.time() + ttl, val)
            return val
        wrap.clear = store.clear
        wrap.__name__ = fn.__name__
        return wrap
    return deco
