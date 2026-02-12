from agno.vectordb.redis.redisdb import RedisDB, SearchType

# Backward compatibility alias
RedisVectorDb = RedisDB

__all__ = [
    "RedisVectorDb",
    "RedisDB",
    "SearchType",
]
