import json
import os

try:
    import redis as _redis_module
    _has_redis = True
except ImportError:
    _has_redis = False

# Conversations inactive longer than this are evicted automatically by Redis.
_CONV_TTL = int(os.getenv("CONV_TTL_SECONDS", "86400"))  # 24 hours


class _InMemoryStore:
    """Dict-backed fallback when Redis is not configured."""

    def __init__(self):
        self._data: dict[str, dict] = {}

    def get(self, cid: str) -> dict | None:
        return self._data.get(cid)

    def save(self, cid: str, data: dict) -> None:
        self._data[cid] = data

    def __contains__(self, cid: str) -> bool:
        return cid in self._data

    def __getitem__(self, cid: str) -> dict:
        return self._data[cid]

    def __setitem__(self, cid: str, value: dict) -> None:
        self._data[cid] = value


class _RedisStore:
    """Redis-backed conversation store with TTL-based eviction.

    Each conversation is stored as a JSON string under the key
    ``hotel:conv:<conversation_id>`` with an expiry of _CONV_TTL seconds.
    The TTL is refreshed on every write, so active sessions never expire mid-flow.
    """

    def __init__(self, url: str):
        self._r = _redis_module.Redis.from_url(url, decode_responses=True)

    def _key(self, cid: str) -> str:
        return f"hotel:conv:{cid}"

    def get(self, cid: str) -> dict | None:
        raw = self._r.get(self._key(cid))
        return json.loads(raw) if raw else None

    def save(self, cid: str, data: dict) -> None:
        self._r.setex(self._key(cid), _CONV_TTL, json.dumps(data, default=str))

    def __contains__(self, cid: str) -> bool:
        return bool(self._r.exists(self._key(cid)))

    def __getitem__(self, cid: str) -> dict:
        result = self.get(cid)
        if result is None:
            raise KeyError(cid)
        return result

    def __setitem__(self, cid: str, value: dict) -> None:
        self.save(cid, value)


def _build_store() -> _RedisStore | _InMemoryStore:
    url = os.getenv("REDIS_URL")
    if url and _has_redis:
        try:
            store = _RedisStore(url)
            store._r.ping()
            return store
        except Exception as exc:
            import logging
            logging.getLogger("hotel_ai_assistant").warning(
                "Redis unavailable (%s) — falling back to in-memory session store", exc
            )
    return _InMemoryStore()


conversation_memory = _build_store()
