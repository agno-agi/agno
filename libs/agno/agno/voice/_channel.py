"""Messages and audio sent to the voice client over its WebSocket."""

import asyncio
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from fastapi import WebSocket

_SEND_TIMEOUT = 5


class _ClientChannel:
    """Serializes everything sent to one client.

    Conditional sends check their condition while holding the send lock, so a
    reply event can never follow the ``stop_playback`` that interrupted it.
    """

    def __init__(self, websocket: "WebSocket") -> None:
        self._ws = websocket
        self._lock = asyncio.Lock()

    async def send(self, kind: str, **data: Any) -> None:
        async with self._lock:
            await asyncio.wait_for(self._ws.send_json({"type": kind, **data}), timeout=_SEND_TIMEOUT)

    async def send_while(self, still_valid: Callable[[], bool], kind: str, **data: Any) -> bool:
        """Send only if ``still_valid()`` holds once the lock is taken; report whether it was sent."""
        async with self._lock:
            if not still_valid():
                return False
            await asyncio.wait_for(self._ws.send_json({"type": kind, **data}), timeout=_SEND_TIMEOUT)
            return True

    async def send_audio_while(self, still_valid: Callable[[], bool], packet: bytes) -> bool:
        async with self._lock:
            if not still_valid():
                return False
            await asyncio.wait_for(self._ws.send_bytes(packet), timeout=_SEND_TIMEOUT)
            return True
