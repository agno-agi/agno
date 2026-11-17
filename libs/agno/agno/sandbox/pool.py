"""HTTP clients pooled per event loop, for providers whose sync methods each run a loop of their own."""

import asyncio
import threading
import weakref
from contextlib import suppress
from typing import Any, Callable, Dict, Tuple

_Entries = Dict[asyncio.AbstractEventLoop, Tuple[Any, "asyncio.Task[None]"]]


async def _close_with_loop(owner: "weakref.ReferenceType[LoopClients]", client: Any) -> None:
    loop = asyncio.get_running_loop()
    try:
        while True:
            # The loop holds tasks only weakly; this pending timer is what keeps the closer alive,
            # and closing the loop drops it, so nothing outlives the loop.
            await asyncio.sleep(3600)
    except GeneratorExit:
        # Collected after its loop closed; no loop is left to close the client on.
        raise
    except BaseException:
        clients = owner()
        if clients is not None:
            with clients._lock:
                if clients._entries.get(loop, (None,))[0] is client:
                    del clients._entries[loop]
        await client.aclose()
        raise


def _cancel_closers(entries: _Entries, lock: threading.Lock) -> None:
    with lock:
        closers = list(entries.items())
    for loop, (_, task) in closers:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)


class LoopClients:
    """One client per event loop, built by ``factory`` and closed when that loop shuts down."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._entries: _Entries = {}
        # Sync calls from several threads share the cache, and each loop's closer removes its own entry.
        self._lock = threading.Lock()
        # Clients discarded while their loop still runs are closed on that loop.
        weakref.finalize(self, _cancel_closers, self._entries, self._lock)

    def get(self) -> Any:
        loop = asyncio.get_running_loop()
        with self._lock:
            for stale in [item for item in self._entries if item.is_closed()]:
                del self._entries[stale]
            entry = self._entries.get(loop)
            if entry is None:
                client = self._factory()
                # asyncio.run cancels pending tasks before closing its loop, so each sync call closes its client.
                closer = loop.create_task(_close_with_loop(weakref.ref(self), client))
                entry = self._entries[loop] = (client, closer)
        return entry[0]
