"""Redis Streams event stream: cross-container background run events.

Events are XADDed to a per-run stream, so any container can replay (XRANGE) and
live-tail (XREAD) them — the producer's process is no longer the only place a
run can be observed from. This is what makes ``/resume`` work behind a load
balancer: the reconnect can land on any replica.

Design notes (see the queue design doc for rationale):
- Redis is TTL'd transport, not the source of truth. Terminal state and final
  output live in the database; replay after TTL falls back to the DB path.
- Streams are keyed per attempt (``{prefix}{run_id}:{attempt}:events``) so a
  future checkpoint-resumed execution can supersede a stale attempt's events by
  switching streams (stream entries cannot be deleted). Attempt is 1 today.
- ``tail()`` blocks with a bounded timeout and re-checks run status on idle: a
  producer that died without writing a terminal sentinel must not hang tails.
- Consumers should multiplex: one ``tail()`` per (run, container) fanned out to
  local subscribers, not one blocked Redis connection per client.

Configure together with ``RedisRunCancellationManager`` using the same clients:
cancellation carries client intent in, the event stream carries events out.
"""

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from agno.os.event_streams.base import BaseEventStream
from agno.run.base import RunStatus
from agno.utils.log import log_warning

_redis_available = True
_redis_import_error: Optional[str] = None

try:
    from redis.asyncio import Redis as AsyncRedis
    from redis.asyncio import RedisCluster as AsyncRedisCluster
except ImportError:
    _redis_available = False
    _redis_import_error = "`redis` not installed. Please install it using `pip install redis`"
    if TYPE_CHECKING:
        from redis.asyncio import Redis as AsyncRedis
        from redis.asyncio import RedisCluster as AsyncRedisCluster
    else:
        AsyncRedis = Any
        AsyncRedisCluster = Any

_TERMINAL_STATUSES = (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused)

# Refresh key TTLs when at least this fraction of ttl_seconds has elapsed
# since the last refresh (time-based, so slow producers with long gaps between
# events cannot have live keys expire mid-run; a lone EXPIRE per XADD would
# double command traffic for no benefit).
_TTL_REFRESH_FRACTION = 3


def _to_str(value: Union[str, bytes, None]) -> Optional[str]:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


class RedisEventStream(BaseEventStream):
    """Event stream backed by Redis Streams.

    Args:
        async_redis_client: Async Redis client (``Redis`` or ``RedisCluster``).
        key_prefix: Prefix for all keys. Defaults to ``agno:os:events:``.
        ttl_seconds: TTL for per-run keys, refreshed while the run is active.
            Mirrors the in-memory buffer's cleanup interval. Defaults to 3600.
        maxlen: Approximate max events retained per stream (XADD MAXLEN ~).
            Mirrors the in-memory buffer's max_events_per_run. Defaults to 1000.
        block_ms: How long ``tail()`` blocks per XREAD before re-checking run
            status. Bounds how long a tail can outlive a dead producer.
    """

    def __init__(
        self,
        async_redis_client: Union["AsyncRedis", "AsyncRedisCluster"],
        key_prefix: str = "agno:os:events:",
        ttl_seconds: int = 3600,
        maxlen: int = 1000,
        block_ms: int = 15000,
    ):
        if not _redis_available:
            raise ImportError(_redis_import_error)
        self._redis = async_redis_client
        self._prefix = key_prefix
        self._ttl = ttl_seconds
        self._maxlen = maxlen
        self._block_ms = block_ms
        # Per-run monotonic timestamp of the last TTL refresh (process-local;
        # a missed refresh from another process only causes an extra EXPIRE)
        self._last_ttl_refresh: Dict[str, float] = {}
        # Runs registered in this process whose keys must stay alive even when
        # the producer is silent (long tool calls produce no events). A single
        # background task refreshes their TTLs periodically and exits when no
        # runs remain active.
        self._active_runs: set = set()
        self._refresher_task: Optional["asyncio.Task"] = None

    # ------------------------------------------------------------------
    # Keys — per-attempt stream keys; attempt is 1 until checkpoint resume lands
    # ------------------------------------------------------------------

    def _stream_key(self, run_id: str, attempt: int = 1) -> str:
        return f"{self._prefix}{run_id}:{attempt}:events"

    def _status_key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}:status"

    def _counter_key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}:idx"

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def register_run(self, run_id: str, status: RunStatus = RunStatus.pending) -> None:
        # NX keeps registration idempotent: a reconnect must not reset state.
        # Deliberately NOT enrolled in the TTL refresher: accept-side replicas
        # register runs that some other replica's worker will execute, and only
        # the PRODUCER may keep the keys alive - an accept-side refresher would
        # renew a finished run's keys forever (and defeat dead-producer TTL
        # detection). Enrollment happens on the producing replica via
        # set_run_status(RUNNING) / add_event.
        await self._redis.set(self._status_key(run_id), status.value, nx=True, ex=self._ttl)

    async def set_run_status(self, run_id: str, status: RunStatus) -> None:
        await self._redis.set(self._status_key(run_id), status.value, ex=self._ttl)
        if status == RunStatus.running:
            # The transition to RUNNING happens on the executing replica: this
            # process is the producer, so it owns keeping the keys alive
            self._active_runs.add(run_id)
            self._ensure_refresher()

    async def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        value = _to_str(await self._redis.get(self._status_key(run_id)))
        if value is None:
            return None
        try:
            return RunStatus(value)
        except ValueError:
            # The key EXISTS but this replica cannot parse its value (e.g. a
            # newer release added a RunStatus member). None means "unknown run"
            # and routes resume to the DB fallback - wrong for a live run.
            # Treat as active so tails keep working across version skew.
            log_warning(f"Unknown run status value {value!r} for run {run_id}; treating as running")
            return RunStatus.running

    def _ensure_refresher(self) -> None:
        if self._refresher_task is None or self._refresher_task.done():
            self._refresher_task = asyncio.get_running_loop().create_task(self._refresh_active_runs())

    async def _refresh_active_runs(self) -> None:
        """Keep keys of active runs alive independent of write activity.

        A quiet run (a long tool call producing no events for longer than the
        TTL) would otherwise lose its status/stream/counter keys mid-run,
        breaking /resume and resetting the counter. Exits when no runs remain
        active in this process; a crashed process stops refreshing and the
        keys expire per TTL, which is the intended cleanup.
        """
        interval = max(1.0, self._ttl / _TTL_REFRESH_FRACTION)
        while self._active_runs:
            await asyncio.sleep(interval)
            for run_id in list(self._active_runs):
                try:
                    pipe = self._redis.pipeline()
                    pipe.expire(self._stream_key(run_id), self._ttl)
                    pipe.expire(self._status_key(run_id), self._ttl)
                    pipe.expire(self._counter_key(run_id), self._ttl)
                    await pipe.execute()
                except Exception:
                    pass

    async def aclose(self) -> None:
        """Stop the refresher task (tests / graceful shutdown)."""
        self._active_runs.clear()
        if self._refresher_task is not None:
            self._refresher_task.cancel()
            try:
                await self._refresher_task
            except (asyncio.CancelledError, Exception):
                pass
            self._refresher_task = None

    async def complete_run(self, run_id: str, status: RunStatus) -> None:
        if status == RunStatus.paused:
            # Paused is terminal-for-the-stream but resumable: keep refreshing
            # its keys so the counter/stream survive until the approval, else
            # a continue re-registers the counter at zero and reconnecting
            # clients dedup away all post-approval events.
            self._active_runs.add(run_id)
            self._ensure_refresher()
        else:
            self._active_runs.discard(run_id)
        # Status first, then the sentinel: a tail woken by the sentinel must
        # observe the terminal status.
        pipe = self._redis.pipeline()
        pipe.set(self._status_key(run_id), status.value, ex=self._ttl)
        pipe.xadd(
            self._stream_key(run_id),
            {"terminal": status.value},
            maxlen=self._maxlen,
            approximate=True,
        )
        pipe.expire(self._stream_key(run_id), self._ttl)
        pipe.expire(self._counter_key(run_id), self._ttl)
        await pipe.execute()

    async def cleanup_run(self, run_id: str) -> None:
        self._last_ttl_refresh.pop(run_id, None)
        self._active_runs.discard(run_id)
        await self._redis.delete(
            self._stream_key(run_id),
            self._status_key(run_id),
            self._counter_key(run_id),
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def add_event(self, run_id: str, event: Any) -> int:
        if run_id not in self._active_runs:
            self._active_runs.add(run_id)
            self._ensure_refresher()
        from agno.os.utils import format_sse_event_with_index

        # INCR assigns the monotonic index atomically (single producer today;
        # safe for multi-attempt producers later).
        next_count = await self._redis.incr(self._counter_key(run_id))
        event_index = int(next_count) - 1
        sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=run_id)

        pipe = self._redis.pipeline()
        pipe.xadd(
            self._stream_key(run_id),
            {"idx": event_index, "sse": sse_data},
            maxlen=self._maxlen,
            approximate=True,
        )
        if self._ttl_refresh_due(run_id):
            pipe.expire(self._stream_key(run_id), self._ttl)
            pipe.expire(self._status_key(run_id), self._ttl)
            pipe.expire(self._counter_key(run_id), self._ttl)
        await pipe.execute()
        return event_index

    def _ttl_refresh_due(self, run_id: str) -> bool:
        import time as _time

        now = _time.monotonic()
        last = self._last_ttl_refresh.get(run_id)
        if last is None or (now - last) >= self._ttl / _TTL_REFRESH_FRACTION:
            self._last_ttl_refresh[run_id] = now
            return True
        return False

    async def replay(self, run_id: str, last_event_index: Optional[int] = None) -> List[Tuple[int, Any]]:
        """Replay from the stream. Payloads are SSE-formatted strings.

        O(stream length) by design: entries are filtered by the embedded idx,
        not by stream id, because idx is the client contract and survives
        backend swaps. MAXLEN bounds the cost.
        """
        floor = last_event_index if last_event_index is not None else -1
        results: List[Tuple[int, Any]] = []
        entries = await self._redis.xrange(self._stream_key(run_id)) or []
        for _entry_id, fields in entries:
            if fields is None:
                continue
            idx_raw = fields.get(b"idx", fields.get("idx"))
            if idx_raw is None:
                continue  # terminal sentinel
            event_index = int(idx_raw)
            if event_index > floor:
                sse = _to_str(fields.get(b"sse", fields.get("sse")))
                results.append((event_index, sse))
        return results

    async def get_last_index(self, run_id: str) -> int:
        value = await self._redis.get(self._counter_key(run_id))
        return int(value) - 1 if value is not None else -1

    async def get_event_count(self, run_id: str) -> int:
        count = int(await self._redis.xlen(self._stream_key(run_id)))
        if count == 0:
            return 0
        # The terminal sentinel is a stream entry but not a client-facing
        # event: exclude it so counts match the in-memory implementation
        last = await self._redis.xrevrange(self._stream_key(run_id), count=1)
        if last:
            _entry_id, fields = last[0]
            if fields is not None and fields.get(b"terminal", fields.get("terminal")) is not None:
                return count - 1
        return count

    # ------------------------------------------------------------------
    # Live tail
    # ------------------------------------------------------------------

    async def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        """XRANGE the prefix, then XREAD from the last seen stream id.

        Gap-free by construction: XREAD starts from the exact stream id the
        replay ended at, so events arriving between the two calls are not
        missed and not duplicated — no subscribe-first locking needed.
        """
        stream_key = self._stream_key(run_id)
        last_yielded = last_event_index if last_event_index is not None else -1
        from_id = "0-0"

        # Replay the buffered prefix, tracking the last stream id we saw
        entries = await self._redis.xrange(stream_key) or []
        for position, (entry_id, fields) in enumerate(entries):
            from_id = _to_str(entry_id) or from_id
            if fields is None:
                continue
            if fields.get(b"terminal", fields.get("terminal")) is not None:
                # A sentinel ends the tail only when NOTHING follows it:
                # continue-runs append events behind a paused sentinel, so a
                # mid-stream sentinel is stale by definition and is skipped
                if position == len(entries) - 1:
                    return
                continue
            idx_raw = fields.get(b"idx", fields.get("idx"))
            if idx_raw is None:
                continue
            event_index = int(idx_raw)
            if event_index > last_yielded:
                sse = _to_str(fields.get(b"sse", fields.get("sse")))
                if sse is not None:
                    yield event_index, sse
                    last_yielded = event_index

        # Live tail from the exact position the replay ended at
        from redis.exceptions import ConnectionError as RedisConnectionError
        from redis.exceptions import TimeoutError as RedisTimeoutError

        while True:
            try:
                # redis-py types the XREAD response too loosely to destructure cleanly
                response: Any = await self._redis.xread({stream_key: from_id}, block=self._block_ms, count=100)
            except (RedisTimeoutError, RedisConnectionError):
                # A client-level socket_timeout below block_ms (redis-py >= 8
                # defaults Redis(...) to 5s) or a transient outage must not
                # kill the tail: treat as an idle pass and re-check status.
                response = None
            if not response:
                # Idle: producer may have died without a sentinel, or the run
                # may be unknown/terminal. Never block forever.
                status = await self.get_run_status(run_id)
                if status is None or status in _TERMINAL_STATUSES:
                    return
                # Dead-producer bound: only the producing process refreshes the
                # status key TTL (every ttl/3 via its refresher). A remaining
                # TTL below one refresh window means at least two windows were
                # missed - the producer is gone; do not wait for full expiry.
                with contextlib.suppress(Exception):
                    ttl_remaining = int(await self._redis.ttl(self._status_key(run_id)))
                    if 0 <= ttl_remaining < self._ttl // _TTL_REFRESH_FRACTION:
                        log_warning(f"Run {run_id}: status key TTL not refreshed (producer presumed dead); ending tail")
                        return
                continue
            for _stream, batch in response:
                for batch_position, (entry_id, fields) in enumerate(batch):
                    from_id = _to_str(entry_id) or from_id
                    if fields.get(b"terminal", fields.get("terminal")) is not None:
                        # Same positional rule as replay: only a batch-final
                        # sentinel ends the tail (an instant continue can put
                        # events behind a paused sentinel within one batch)
                        if batch_position == len(batch) - 1:
                            return
                        continue
                    idx_raw = fields.get(b"idx", fields.get("idx"))
                    if idx_raw is None:
                        continue
                    event_index = int(idx_raw)
                    if event_index <= last_yielded:
                        continue
                    sse = _to_str(fields.get(b"sse", fields.get("sse")))
                    if sse is not None:
                        yield event_index, sse
                        last_yielded = event_index
            await asyncio.sleep(0)  # yield control between batches
