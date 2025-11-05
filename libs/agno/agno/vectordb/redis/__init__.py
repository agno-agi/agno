from agno.vectordb.redis.redisdb import RedisVectorDb

# Backward compatibility alias
RedisDB = RedisVectorDb

__all__ = [
    "RedisVectorDb",
    "RedisDB",
]
