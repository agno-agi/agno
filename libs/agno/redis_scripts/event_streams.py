"""Writer-generation fence scripts for ``RedisEventStream``.

Source for the generated ``agno/os/event_streams/_redis_lua.py``. Not shipped:
edit here, then regenerate from ``libs/agno`` with
``python -m redis_lua_py generate redis_scripts.event_streams --out agno/os/event_streams/_redis_lua.py``.

``fenced_incr`` refuses when the stored generation is NEWER than the writer's,
establishes it when absent (first fenced writer, or an expired key - fail-open
restamp; the TTL hazard predates the fence), and self-heals forward when the
writer's is newer. ``fenced_xadd`` re-checks at append time: index INCR and
XADD are separate roundtrips (the SSE payload embeds the index and is
formatted client-side), and a newer attempt can begin between them - a
refused append leaves an index gap, covered by the monotonic-not-gapless
contract.
"""

from redis_lua_py import Key, redis, script


@script
def fenced_incr(gen_key: Key, counter_key: Key, generation: int, ttl: int) -> int:
    """Return the incremented counter, or -1 when a newer generation owns the stream."""
    gen = redis.get(gen_key)
    if gen is None:
        redis.set(gen_key, generation, "EX", ttl)
    elif int(gen) > generation:
        return -1
    elif int(gen) < generation:
        redis.set(gen_key, generation, "EX", ttl)
    return redis.incr(counter_key)


@script
def fenced_xadd(gen_key: Key, stream_key: Key, generation: int, maxlen: int, idx: int, sse: str) -> int:
    """Append the event and return 1, or 0 when a newer generation owns the stream."""
    gen = redis.get(gen_key)
    if gen is not None and int(gen) > generation:
        return 0
    redis.xadd(stream_key, "MAXLEN", "~", maxlen, "*", "idx", idx, "sse", sse)
    return 1
