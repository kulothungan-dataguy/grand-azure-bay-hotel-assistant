import diskcache

# statistics=True enables hit/miss tracking via .stats()
rag_cache = diskcache.Cache(".rag_cache", statistics=True)
