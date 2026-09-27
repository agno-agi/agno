from agno.vectordb.redis.redisdb import RedisDb, SearchType

# Alias to disambiguate from the RedisDb storage adapter in agno.db.redis
RedisVectorDb = RedisDb

# Backwards-compat alias (deprecated, use RedisDb)
RedisDB = RedisDb

__all__ = [
    "RedisVectorDb",
    "RedisDb",
    "RedisDB",
    "SearchType",
]
