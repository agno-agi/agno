"""Redis Streams event stream: cross-container background run events.

Events are XADDed to a per-run stream, so any container can replay (XRANGE) and
live-tail (XREAD) them — the producer's process is no longer the only place a
run can be observed from. This is what makes ``/resume`` work behind a load
balancer: the reconnect can land on any replica.

Design notes (see the queue design doc for rationale):
- Redis is TTL'd transport, not the source of truth. Terminal state and final
  output live in the database; replay after TTL falls back to the DB path.
- One stream per run across retry attempts (key layout keeps a fixed ``:1:``
  segment for compatibility). A retry supersedes a contradicted attempt via
  ``reset_run_events``: events are dropped, the INCR counter survives, so the
  client-facing index stays monotonic across attempts and reconnecting clients
  never filter out the retry's real output.
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
from agno.utils.log import log_debug, log_warning

# Writer-generation fence scripts. The INCR script refuses when the stored generation is
# NEWER than the writer's, establishes it when absent (first fenced writer, or
# an expired key - fail-open restamp; the TTL hazard predates the fence), and
# self-heals forward when the writer's is newer. The XADD script re-checks at
# append time: index INCR and XADD are separate roundtrips (the SSE payload
# embeds the index and is formatted client-side), and a newer attempt can
# begin between them - a refused append leaves an index gap, covered by the
# monotonic-not-gapless contract.
_FENCED_INCR_LUA = """
local gen = redis.call('GET', KEYS[1])
if gen == false then
  redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
elseif tonumber(gen) > tonumber(ARGV[1]) then
  return -1
elseif tonumber(gen) < tonumber(ARGV[1]) then
  redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
end
return redis.call('INCR', KEYS[2])
"""

_FENCED_XADD_LUA = """
local gen = redis.call('GET', KEYS[1])
if gen ~= false and tonumber(gen) > tonumber(ARGV[1]) then
  return 0
end
redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*', 'idx', ARGV[3], 'sse', ARGV[4])
return 1
"""

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
            Mirrors the wired in-memory buffer's cleanup interval (1800s) -
            actually mirrors it: the old default of 3600 diverged.
        maxlen: Approximate max events retained per stream (XADD MAXLEN ~).
            Mirrors the wired in-memory buffer's max_events_per_run (10000).
            The old default of 1000 silently cut how far a reconnecting
            /resume client could fall behind by 10x when switching backends.
        block_ms: How long ``tail()`` blocks per XREAD before re-checking run
            status. Bounds how long a tail can outlive a dead producer.
    """

    def __init__(
        self,
        async_redis_client: Union["AsyncRedis", "AsyncRedisCluster"],
        key_prefix: str = "agno:os:events:",
        ttl_seconds: int = 1800,
        maxlen: int = 10000,
        block_ms: int = 15000,
    ):
        if not _redis_available:
            raise ImportError(_redis_import_error)
        # Same rejection (and reason) as the job-queue store: per-run keys are
        # not hash-tagged, so reopen_run's WATCH/MULTI and the multi-key TTL /
        # terminal pipelines issue cross-slot operations that fail on
        # RedisCluster - confusingly, at runtime, mid-continuation. Reject up
        # front instead. (The Redis cancellation manager deliberately does NOT
        # reject cluster clients: every one of its pipelines is single-key -
        # audited - and cluster support there is advertised.) Hash-tagging
        # {run_id} into the keys would make this stream cluster-safe, but the
        # queue store rejects cluster anyway, so that work is parked until
        # cluster support is a stack-wide goal - validate with
        # redis.crc.key_slot in tests if ever built, not fakeredis.
        if type(async_redis_client).__name__ == "RedisCluster":
            raise ValueError(
                "RedisEventStream requires a standalone (non-cluster) Redis client: its per-run "
                "keys are not hash-tagged, so multi-key transactions (reopen, TTL refresh, "
                "terminal writes) are cross-slot and fail on RedisCluster. Use a standalone "
                "Redis or Valkey instance for the event stream, matching the job-queue store."
            )
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
        # Writer-generation fence: Lua gives gen-check + INCR (and gen-check +
        # XADD) single-roundtrip atomicity on the hot per-event path. Scripts
        # register lazily; a server without scripting (fakeredis, restricted
        # managed Redis) degrades FAIL-OPEN to the unfenced legacy path with
        # one warning - the stream is coordination, not truth.
        self._fenced_incr_script: Optional[Any] = None
        self._fenced_xadd_script: Optional[Any] = None
        self._scripting_unavailable = False
        self._fence_refusals_logged: set = set()

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------

    def _stream_key(self, run_id: str) -> str:
        # Single stream per run across retry attempts: reset_run_events clears
        # a contradicted attempt's events while the counter keeps indices
        # monotonic, so tails and resumes never rewind. (The :1: segment is a
        # fixed layout artifact, kept for key compatibility.)
        return f"{self._prefix}{run_id}:1:events"

    def _status_key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}:status"

    def _counter_key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}:idx"

    def _gen_key(self, run_id: str) -> str:
        # The stream's writer generation: the newest attempt that
        # called begin_attempt. add_event calls carrying an older generation
        # are refused atomically in Lua.
        return f"{self._prefix}{run_id}:gen"

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

    async def _fenced_lifecycle(self, run_id: str, generation: Optional[int], build) -> bool:
        """Run a lifecycle mutation atomically UNDER the generation fence.

        WATCH the gen key; refuse (False) when the stored writer generation
        is NEWER than the caller's; otherwise queue ``build(pipe)`` after
        MULTI and execute - the WATCH aborts if a newer attempt began in
        between. Equal generations pass (same-attempt finished-work-wins);
        a newer caller's generation is recorded forward. generation=None
        runs the mutation unfenced (legacy single-writer callers)."""
        from redis.exceptions import WatchError

        gen_key = self._gen_key(run_id)
        if generation is None:
            pipe = self._redis.pipeline()
            build(pipe)
            await pipe.execute()
            return True
        for _ in range(10):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(gen_key)
                    raw = _to_str(await pipe.get(gen_key))
                    if raw is not None and int(raw) > generation:
                        await pipe.unwatch()
                        self._log_fence_refusal(run_id, generation)
                        return False
                    pipe.multi()
                    if raw is None or int(raw) < generation:
                        pipe.set(gen_key, generation, ex=self._ttl)
                    build(pipe)
                    await pipe.execute()
                    return True
            except WatchError:
                continue
        return False

    async def set_run_status(self, run_id: str, status: RunStatus, generation: Optional[int] = None) -> None:
        applied = await self._fenced_lifecycle(
            run_id,
            generation,
            lambda pipe: pipe.set(self._status_key(run_id), status.value, ex=self._ttl),
        )
        if applied and status == RunStatus.running:
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
        terminal_values = {RunStatus.completed.value, RunStatus.error.value, RunStatus.cancelled.value}
        while self._active_runs:
            await asyncio.sleep(interval)
            for run_id in list(self._active_runs):
                try:
                    # Cross-replica handoff check: the replica that parked a
                    # run as PAUSED keeps refreshing it, but the continuation
                    # may execute AND finish on another replica - the Redis
                    # status is the shared truth. Once it is terminal (or the
                    # keys are gone), stop refreshing so the TTL can reap the
                    # keys instead of this process renewing them forever.
                    # PAUSED and PENDING/RUNNING keep refreshing: parked and
                    # reopened-awaiting-claim runs are exactly what the
                    # refresher exists for.
                    raw_status = _to_str(await self._redis.get(self._status_key(run_id)))
                    if raw_status is None or raw_status in terminal_values:
                        self._active_runs.discard(run_id)
                        self._last_ttl_refresh.pop(run_id, None)
                        continue
                    pipe = self._redis.pipeline()
                    pipe.expire(self._stream_key(run_id), self._ttl)
                    pipe.expire(self._status_key(run_id), self._ttl)
                    pipe.expire(self._counter_key(run_id), self._ttl)
                    pipe.expire(self._gen_key(run_id), self._ttl)
                    await pipe.execute()
                except Exception:
                    # Fail-open on Redis faults: keep the run enrolled and let
                    # the next tick retry - a blip must not drop a live run
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

    async def complete_run(self, run_id: str, status: RunStatus, generation: Optional[int] = None) -> None:
        if status not in (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused):
            # Contract: this call MARKS TERMINAL (see in-memory twin)
            status = RunStatus.completed

        # Status first, then the sentinel: a tail woken by the sentinel must
        # observe the terminal status. Under the generation fence: a zombie
        # attempt's sentinel must not close the live attempt's tails (equal
        # generations pass - same-attempt finished-work-wins).
        def build(pipe: Any) -> None:
            pipe.set(self._status_key(run_id), status.value, ex=self._ttl)
            pipe.xadd(
                self._stream_key(run_id),
                {"terminal": status.value},
                maxlen=self._maxlen,
                approximate=True,
            )
            pipe.expire(self._stream_key(run_id), self._ttl)
            pipe.expire(self._counter_key(run_id), self._ttl)

        applied = await self._fenced_lifecycle(run_id, generation, build)
        if not applied:
            return
        if status == RunStatus.paused:
            # Paused is terminal-for-the-stream but resumable: keep refreshing
            # its keys so the counter/stream survive until the approval, else
            # a continue re-registers the counter at zero and reconnecting
            # clients dedup away all post-approval events.
            self._active_runs.add(run_id)
            self._ensure_refresher()
        else:
            self._active_runs.discard(run_id)
            # Bookkeeping dies with the run: without this, per-run refresh
            # timestamps accumulate for the process lifetime
            self._last_ttl_refresh.pop(run_id, None)

    async def reopen_run(self, run_id: str, include_error: bool = False, floor: Optional[int] = None) -> bool:
        """Atomically reopen a PAUSED run for a continuation leg.

        WATCH/MULTI CAS on the status key: the flip to PENDING only lands if
        the status is still PAUSED (or the keys expired), so a racing
        worker's terminal write is never overwritten. The same transaction
        appends a "reopen" marker to the stream - tails end on a sentinel
        only when NOTHING follows it, so the marker invalidates the pause
        sentinel and a tail attached before the leg's first event stays
        open instead of closing empty. Markers carry no idx and are skipped
        by replay and tail alike. include_error is the worker-redrive
        variant (see BaseEventStream.reopen_run).
        """
        from redis.exceptions import WatchError

        # PENDING is reopenable alongside PAUSED (and missing keys, handled
        # below): the guard protects NEWER states - RUNNING and terminals -
        # and PENDING is pre-execution, where the flip is idempotent. The
        # expired-state path depends on it: register_run re-creates PENDING
        # before the reopen, and declining there would drop the counter seed.
        reopenable = (
            (RunStatus.paused.value, RunStatus.error.value, RunStatus.pending.value)
            if include_error
            else (RunStatus.paused.value, RunStatus.pending.value)
        )
        status_key = self._status_key(run_id)
        stream_key = self._stream_key(run_id)
        for _ in range(10):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(status_key)
                    current = _to_str(await pipe.get(status_key))
                    if current is not None and current not in reopenable:
                        await pipe.unwatch()
                        return False
                    seed_target: Optional[int] = None
                    if floor is not None:
                        # Seed the counter to at least floor+1 (the durable
                        # floor comes from the run row's stored event_index):
                        # a paused run outliving the TTL across a deploy lost
                        # its counter, and INCR restarting at 0 makes resuming
                        # clients dedup away every post-approval event. A live
                        # counter is never regressed - the run is PAUSED
                        # (settled, no producer), and the WATCH on the status
                        # key aborts this whole CAS if anything raced.
                        raw_counter = await pipe.get(self._counter_key(run_id))
                        current_counter = int(raw_counter) if raw_counter is not None else 0
                        if floor + 1 > current_counter:
                            seed_target = floor + 1
                    pipe.multi()
                    pipe.set(status_key, RunStatus.pending.value, ex=self._ttl)
                    if seed_target is not None:
                        pipe.set(self._counter_key(run_id), seed_target, ex=self._ttl)
                    pipe.xadd(stream_key, {"reopen": "1"}, maxlen=self._maxlen, approximate=True)
                    pipe.expire(stream_key, self._ttl)
                    pipe.expire(self._counter_key(run_id), self._ttl)
                    await pipe.execute()
                    return True
            except WatchError:
                continue  # status changed under us; re-evaluate it
        return False

    async def cleanup_run(self, run_id: str) -> None:
        self._last_ttl_refresh.pop(run_id, None)
        self._active_runs.discard(run_id)
        self._fence_refusals_logged.discard(run_id)
        await self._redis.delete(
            self._stream_key(run_id),
            self._status_key(run_id),
            self._counter_key(run_id),
            self._gen_key(run_id),
        )

    async def reset_run_events(self, run_id: str, generation: Optional[int] = None) -> None:
        # Events go; counter and status stay - indices remain monotonic across
        # retry attempts (see BaseEventStream.reset_run_events). Fenced: a
        # worker that stalled before its leg entry and woke after a reclaim
        # must not delete the reclaiming attempt's events.
        await self._fenced_lifecycle(run_id, generation, lambda pipe: pipe.delete(self._stream_key(run_id)))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def begin_attempt(self, run_id: str, generation: int) -> None:
        """Record this attempt as the stream's writer generation (monotonic
        CAS - an older attempt's late begin never regresses it)."""
        from redis.exceptions import WatchError

        gen_key = self._gen_key(run_id)
        for _ in range(10):
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(gen_key)
                    current_raw = _to_str(await pipe.get(gen_key))
                    if current_raw is not None and int(current_raw) >= generation:
                        await pipe.unwatch()
                        with contextlib.suppress(Exception):
                            await self._redis.expire(gen_key, self._ttl)
                        return
                    pipe.multi()
                    pipe.set(gen_key, generation, ex=self._ttl)
                    await pipe.execute()
                    return
            except WatchError:
                continue

    def _log_fence_refusal(self, run_id: str, generation: int) -> None:
        # First refusal per run at WARNING; a streaming zombie can produce
        # hundreds more - those go to DEBUG
        if run_id not in self._fence_refusals_logged:
            self._fence_refusals_logged.add(run_id)
            log_warning(
                f"Event stream: refused event for run {run_id} from stale generation "
                f"{generation} - zombie writer fenced out (further refusals logged at DEBUG)"
            )
        else:
            log_debug(f"Event stream: refused event for run {run_id} from stale generation {generation}")

    async def _fenced_add_event(self, run_id: str, event: Any, generation: int) -> Optional[int]:
        """Lua path: gen-check + INCR, then gen-check + XADD. Returns the
        index, -1 (refused), or None when scripting is unavailable and the
        caller must degrade to the unfenced legacy path."""
        from redis.exceptions import ResponseError

        from agno.os.utils import format_sse_event_with_index

        try:
            if self._fenced_incr_script is None:
                self._fenced_incr_script = self._redis.register_script(_FENCED_INCR_LUA)
                self._fenced_xadd_script = self._redis.register_script(_FENCED_XADD_LUA)
            next_count = await self._fenced_incr_script(
                keys=[self._gen_key(run_id), self._counter_key(run_id)],
                args=[generation, self._ttl],
            )
        except ResponseError as e:
            message = str(e).lower()
            if "unknown command" in message or "not supported" in message or "unsupported" in message:
                self._scripting_unavailable = True
                log_warning(
                    "Event stream: Redis server does not support scripting - the writer "
                    "generation fence is DISABLED (events publish unfenced, legacy behavior)"
                )
                return None
            raise
        if int(next_count) == -1:
            self._log_fence_refusal(run_id, generation)
            return -1
        event_index = int(next_count) - 1
        with contextlib.suppress(Exception):
            event.event_index = event_index
        sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=run_id)
        appended = await self._fenced_xadd_script(  # type: ignore[misc]
            keys=[self._gen_key(run_id), self._stream_key(run_id)],
            args=[generation, self._maxlen, event_index, sse_data],
        )
        if self._ttl_refresh_due(run_id):
            pipe = self._redis.pipeline()
            pipe.expire(self._stream_key(run_id), self._ttl)
            pipe.expire(self._status_key(run_id), self._ttl)
            pipe.expire(self._counter_key(run_id), self._ttl)
            pipe.expire(self._gen_key(run_id), self._ttl)
            await pipe.execute()
        if int(appended) == 0:
            self._log_fence_refusal(run_id, generation)
            return -1
        return event_index

    async def add_event(self, run_id: str, event: Any, generation: Optional[int] = None) -> int:
        if run_id not in self._active_runs:
            self._active_runs.add(run_id)
            self._ensure_refresher()
        from agno.os.utils import format_sse_event_with_index

        if generation is not None and not self._scripting_unavailable:
            fenced = await self._fenced_add_event(run_id, event, generation)
            if fenced is not None:
                return fenced
            # Scripting unavailable: fall through to the unfenced legacy path

        # INCR assigns the monotonic index atomically (single producer today;
        # safe for multi-attempt producers later).
        next_count = await self._redis.incr(self._counter_key(run_id))
        event_index = int(next_count) - 1
        # Stamp the index onto the event OBJECT: the component accumulates
        # these same references into run_response.events, so its session save
        # persists the real index - the durable substrate the DB replay
        # fallback and post-expiry reopen seeding rely on. Fail-open: an
        # exotic event object must not kill the publish.
        with contextlib.suppress(Exception):
            event.event_index = event_index
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
        # Count only idx-bearing entries (the discriminator replay uses):
        # coordination markers - pause/terminal sentinels and reopen markers,
        # including STALE mid-stream ones a pause/continue cycle leaves behind
        # - are stream entries but not client-facing events. The old
        # XLEN-minus-trailing-sentinel arithmetic counted every mid-stream
        # marker, inflating the number by 2+ per pause cycle. O(stream) like
        # replay, MAXLEN-bounded; the count feeds display metadata, and no
        # O(1) primitive can discriminate (XLEN cannot see fields; the INCR
        # counter survives resets/trims so it diverges from buffer contents
        # exactly when the number matters). Restores in-memory parity - that
        # buffer never holds markers, so its counts were already right.
        count = 0
        entries = await self._redis.xrange(self._stream_key(run_id)) or []
        for _entry_id, fields in entries:
            if fields is None:
                continue
            if fields.get(b"idx", fields.get("idx")) is not None:
                count += 1
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

        # ONE consecutive-failure counter shared by the XREAD and the status
        # probe: they are the same outage, and pacing must cover the pair.
        # When the connection fails FAST, block_ms never paces the loop - so
        # the backoff below is what keeps a Redis outage from turning every
        # tail into a busy loop. Capped, and reset on the first success.
        consecutive_failures = 0
        while True:
            try:
                # redis-py types the XREAD response too loosely to destructure cleanly
                response: Any = await self._redis.xread({stream_key: from_id}, block=self._block_ms, count=100)
                consecutive_failures = 0
            except (RedisTimeoutError, RedisConnectionError):
                # A client-level socket_timeout below block_ms (redis-py >= 8
                # defaults Redis(...) to 5s) or a transient outage must not
                # kill the tail: treat as an idle pass and re-check status.
                response = None
                consecutive_failures += 1
            if not response:
                # Idle: producer may have died without a sentinel, or the run
                # may be unknown/terminal. Never block forever.
                try:
                    status = await self.get_run_status(run_id)
                    consecutive_failures = 0
                except (RedisTimeoutError, RedisConnectionError):
                    # The SAME outage the XREAD guard above absorbs - it must
                    # not escape the loop here, and it must not read as
                    # "unknown run" either (status None closes a live tail).
                    # Skip the terminal decision entirely this pass.
                    consecutive_failures += 1
                    await asyncio.sleep(min(0.1 * (2 ** min(consecutive_failures, 6)), 5.0))
                    continue
                if consecutive_failures:
                    await asyncio.sleep(min(0.1 * (2 ** min(consecutive_failures, 6)), 5.0))
                if status is None or status in _TERMINAL_STATUSES:
                    return
                # Dead-producer bound: only the producing process refreshes the
                # status key TTL (every ttl/3 via its refresher). A remaining
                # TTL below one refresh window means at least two windows were
                # missed - the producer is gone; do not wait for full expiry.
                # RUNNING-only: a PENDING run has no producer yet by design
                # (accept-side registration deliberately does not refresh), so
                # a long queue wait must not be read as a dead producer.
                if status == RunStatus.running:
                    with contextlib.suppress(Exception):
                        ttl_remaining = int(await self._redis.ttl(self._status_key(run_id)))
                        if 0 <= ttl_remaining < self._ttl // _TTL_REFRESH_FRACTION:
                            log_warning(
                                f"Run {run_id}: status key TTL not refreshed (producer presumed dead); ending tail"
                            )
                            return
                continue
            for _stream, batch in response:
                for batch_position, (entry_id, fields) in enumerate(batch):
                    from_id = _to_str(entry_id) or from_id
                    if fields.get(b"terminal", fields.get("terminal")) is not None:
                        # A sentinel ends the tail only when NOTHING follows it
                        # in the STREAM - not merely in this batch. XREAD reads
                        # count-bounded batches, so a lagging tail's batch can
                        # end exactly on a stale pause sentinel while the
                        # reopen marker and continuation events sit in the next
                        # batch; the old batch-position rule closed the tail
                        # mid-continuation for any consumer lagging >= one
                        # batch across a pause/resume. Peek one entry past the
                        # sentinel before honoring it. (The replay path keeps
                        # the positional rule: its XRANGE is unbounded, so
                        # list-final there genuinely means stream-final.)
                        if batch_position == len(batch) - 1:
                            sentinel_id = _to_str(entry_id) or "0-0"
                            ms, _, seq = sentinel_id.partition("-")
                            after_sentinel = f"{ms}-{int(seq or 0) + 1}"
                            following = await self._redis.xrange(stream_key, min=after_sentinel, max="+", count=1)
                            if not following:
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
