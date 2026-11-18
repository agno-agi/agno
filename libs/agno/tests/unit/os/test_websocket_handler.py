"""WebSocketHandler disconnect behavior: a closed socket must disarm the
handler (one debug line, no per-event warning flood)."""

from typing import Any

import pytest

from agno.os.managers import WebSocketHandler


class ClosedSocket:
    """Raises starlette's post-close RuntimeError on every send."""

    def __init__(self):
        self.attempts = 0

    async def send_text(self, text: str) -> None:
        self.attempts += 1
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class FakeEvent:
    def to_dict(self) -> Any:
        return {"event": "RunContent", "content": "x"}


@pytest.mark.asyncio
async def test_closed_socket_disarms_handler():
    ws = ClosedSocket()
    handler = WebSocketHandler(websocket=ws)  # type: ignore[arg-type]

    await handler.handle_event(FakeEvent(), event_index=0, run_id="r1")  # type: ignore[arg-type]
    assert handler.websocket is None, "first close-type failure must disarm the handler"
    assert ws.attempts == 1

    # Subsequent events return early: no further send attempts on a dead socket
    for i in range(5):
        await handler.handle_event(FakeEvent(), event_index=i + 1, run_id="r1")  # type: ignore[arg-type]
    assert ws.attempts == 1
