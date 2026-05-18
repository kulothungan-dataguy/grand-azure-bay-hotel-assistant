import re
import hashlib
import diskcache

# statistics=True enables hit/miss tracking via .stats()
rag_cache = diskcache.Cache(".rag_cache", statistics=True)

_FALLBACK_PHRASES = [
    "i don't have that information",
    "please contact our front desk",
    "i could not find that information",
]


def make_cache_key(query: str) -> str:
    normalized = re.sub(r"[^\w\s]", "", query.lower().strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()


def is_cacheable(response: str) -> bool:
    lower = response.lower()
    return not any(phrase in lower for phrase in _FALLBACK_PHRASES)
