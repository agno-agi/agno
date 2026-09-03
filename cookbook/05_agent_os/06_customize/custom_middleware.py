"""
Add rate-limit and request-log middleware to AgentOS
====================================================

Custom Starlette middleware can wrap the FastAPI app returned by
``AgentOS.get_app()``. ``add_middleware`` is last-in, first-out: the logging
middleware added last is the outer layer and sees each request before the rate
limiter added first.

Prerequisites: none for the serve-and-curl flow below (OPENAI_API_KEY only
if you send the agent a run)
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/custom_middleware.py
Try: curl -i http://localhost:7777/config
"""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Create Custom Middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limit requests per client within a rolling in-memory window."""

    def __init__(
        self,
        app,
        requests_per_window: int = 10,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.request_history: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject requests after the configured per-client limit."""
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        history = self.request_history[client_ip]
        while history and now - history[0] > self.window_seconds:
            history.popleft()

        if len(history) >= self.requests_per_window:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )

        history.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(
            self.requests_per_window - len(history)
        )
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request order and add a request-count response header."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.request_count = 0

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Log one request around the next inner middleware."""
        self.request_count += 1
        started = time.monotonic()
        print(
            f"Request {self.request_count}: "
            f"{request.method} {request.url.path} entered logging middleware"
        )
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - started) * 1000
        print(
            f"Request {self.request_count}: "
            f"status={response.status_code} elapsed_ms={elapsed_ms:.1f}"
        )
        response.headers["X-Request-Count"] = str(self.request_count)
        return response


# ---------------------------------------------------------------------------
# Create Middleware-Wrapped AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="custom-middleware-db",
    db_file="tmp/agent_os_custom_middleware.db",
)

middleware_agent = Agent(
    id="custom-middleware-agent",
    name="Custom Middleware Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

agent_os = AgentOS(
    id="custom-middleware-os",
    db=db,
    agents=[middleware_agent],
)
app = agent_os.get_app()

# Middleware is LIFO. RequestLoggingMiddleware, added last, executes first.
app.add_middleware(
    RateLimitMiddleware,
    requests_per_window=10,
    window_seconds=60,
)
app.add_middleware(RequestLoggingMiddleware)

# ---------------------------------------------------------------------------
# Run Middleware-Wrapped AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
