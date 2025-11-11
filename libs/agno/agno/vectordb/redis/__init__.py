from agno.vectordb.redis.redisdb import RedisDB

# Backward compatibility alias
RedisVectorDb = RedisDB

__all__ = [
    "RedisVectorDb",
    "RedisDB",
]
