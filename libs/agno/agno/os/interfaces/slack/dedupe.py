from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

from slack_bolt.request.async_request import AsyncBoltRequest
from slack_bolt.response import BoltResponse


class EventDeduplicator:
    """Remembers recently seen Slack ``event_id`` values.

    Slack retries an event when it does not get a 200 within three seconds, and the
    retry carries the same ``event_id``. Processing it again would run the agent
    twice; dropping every retry loses the message whenever the first delivery never
    reached the handler. Remembering ids for longer than Slack's final retry window
    (five minutes) gives exactly-once handling in the common case.

    The set is per process. Under several workers a retry can land on a worker that
    has not seen the id, which then runs the event a second time.
    """

    TTL_SECONDS = 600.0
    MAX_ENTRIES = 4096

    def __init__(self, ttl_seconds: float = TTL_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def is_duplicate(self, key: str) -> bool:
        now = time.monotonic()
        while self._seen:
            oldest_key, oldest_ts = next(iter(self._seen.items()))
            if now - oldest_ts <= self._ttl:
                break
            del self._seen[oldest_key]

        if key in self._seen:
            return True

        self._seen[key] = now
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._seen)


def make_dedupe_middleware(dedupe: EventDeduplicator) -> Callable[..., Awaitable[Any]]:
    """Bolt global middleware that answers duplicates with a 200 without dispatching.

    Registered with ``app.use`` so it runs after Bolt's request verification: only a
    signed request can mark an id as seen. Interaction payloads have no ``event_id``;
    for those a retry header is the only signal, and such retries are dropped as before.
    """

    async def _dedupe(req: AsyncBoltRequest, resp: BoltResponse, next_: Callable[[], Awaitable[Any]]) -> Any:
        body = req.body if isinstance(req.body, dict) else {}
        event_id = body.get("event_id")
        if isinstance(event_id, str) and event_id:
            if dedupe.is_duplicate(event_id):
                return BoltResponse(status=200, body="")
            return await next_()

        if req.headers.get("x-slack-retry-num"):
            return BoltResponse(status=200, body="")
        return await next_()

    return _dedupe
