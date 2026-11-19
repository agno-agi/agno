"""Disable proxy buffering for Server-Sent Events responses.

``AgentOS`` streams run events over SSE. nginx buffers proxied responses by
default (``proxy_buffering on``), which holds streamed chunks back until its
buffer fills or the response completes: clients then see events in delayed
bursts instead of token by token, and long running runs look like they hang.

nginx honours the ``X-Accel-Buffering: no`` response header, which turns
buffering off for that single response only. The header is inert for direct
connections and ignored by proxies that do not recognise it, so it is safe to
send unconditionally on SSE responses.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

EVENT_STREAM_MEDIA_TYPE = "text/event-stream"
ACCEL_BUFFERING_HEADER = "X-Accel-Buffering"
ACCEL_BUFFERING_VALUE = "no"


class SSEBufferingMiddleware:
    """Set ``X-Accel-Buffering: no`` on every ``text/event-stream`` response.

    Implemented as raw ASGI middleware rather than ``BaseHTTPMiddleware`` so
    the response body keeps streaming through untouched.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start" and is_event_stream(message):
                headers = MutableHeaders(scope=message)
                # setdefault: an explicitly configured value wins
                headers.setdefault(ACCEL_BUFFERING_HEADER, ACCEL_BUFFERING_VALUE)
            await send(message)

        await self.app(scope, receive, send_with_header)


def is_event_stream(message: Message) -> bool:
    """Whether an ``http.response.start`` message carries an SSE content type."""
    headers = MutableHeaders(raw=message.get("headers") or [])
    media_type = headers.get("content-type", "").split(";")[0].strip().lower()
    return media_type == EVENT_STREAM_MEDIA_TYPE
