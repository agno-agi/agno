"""
This example demonstrates how to add custom middleware to your AgentOS application.

We add two middleware:
- Rate Limiting: Limits requests per IP address
- Request/Response Logging: Logs requests and responses
"""

import time
from collections import defaultdict, deque
from typing import Dict

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# Rate Limiting Middleware
class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware that limits requests per IP address.
    """

    def __init__(self, app, requests_per_minute: int = 60, window_size: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.window_size = window_size
        # Store request timestamps per IP
        self.request_history: Dict[str, deque] = defaultdict(lambda: deque())

    async def dispatch(self, request: Request, call_next) -> Response:
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()

        # Clean old requests outside the window
        history = self.request_history[client_ip]
        while history and current_time - history[0] > self.window_size:
            history.popleft()

        # Check if rate limit exceeded
        if len(history) >= self.requests_per_minute:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {self.requests_per_minute} requests per minute.",
            )

        # Add current request to history
        history.append(current_time)

        # Add rate limit headers
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            self.requests_per_minute - len(history)
        )
        response.headers["X-RateLimit-Reset"] = str(
            int(current_time + self.window_size)
        )

        return response


# Request/Response Logging Middleware
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Request/response logging middleware with timing and basic info.
    """

    def __init__(self, app, log_body: bool = False, log_headers: bool = False):
        super().__init__(app)
        self.log_body = log_body
        self.log_headers = log_headers
        self.request_count = 0

    async def dispatch(self, request: Request, call_next) -> Response:
        self.request_count += 1
        start_time = time.time()

        # Basic request info
        client_ip = request.client.host if request.client else "unknown"
        print(
            f"🔍 Request #{self.request_count}: {request.method} {request.url.path} from {client_ip}"
        )

        # Optional: Log headers
        if self.log_headers:
            print(f"📋 Headers: {dict(request.headers)}")

        # Optional: Log request body
        if self.log_body and request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
            if body:
                print(f"📝 Body: {body.decode()}")

        # Process request
        response = await call_next(request)

        # Log response info
        duration = time.time() - start_time
        status_emoji = "✅" if response.status_code < 400 else "❌"
        print(
            f"{status_emoji} Response: {response.status_code} in {duration * 1000:.1f}ms"
        )

        # Add request count to response header
        response.headers["X-Request-Count"] = str(self.request_count)

        return response


# ✨ Clean Middleware Configuration ✨
RATE_LIMIT_MIDDLEWARE = (
    RateLimitMiddleware,
    {
        "requests_per_minute": 10,
        "window_size": 60,
    },
)

REQUEST_LOGGING_MIDDLEWARE = (
    RequestLoggingMiddleware,
    {
        "log_body": False,
        "log_headers": False,
    },
)

# Predefined collections
ESSENTIAL_MIDDLEWARE = [
    RATE_LIMIT_MIDDLEWARE,
    REQUEST_LOGGING_MIDDLEWARE,
]


def create_middleware_demo_app():
    """Create a demo app with rate limiting and logging middleware."""

    db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

    agent = Agent(
        id="demo-agent",
        name="Demo Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        tools=[DuckDuckGoTools()],
        markdown=True,
    )

    app = FastAPI(title="Essential Middleware Demo", version="1.0.0")

    @app.get("/")
    async def home():
        """Home endpoint"""
        return {
            "message": "Essential AgentOS Middleware Demo",
            "endpoints": [
                "/ - This endpoint",
                "/test - Test endpoint",
                "/rate-limit-test - Test rate limiting",
            ],
        }

    @app.get("/test")
    async def test_endpoint():
        """Simple test endpoint"""
        return {"message": "Test successful!", "timestamp": time.time()}

    @app.get("/rate-limit-test")
    async def rate_limit_test():
        """Test rate limiting - hit this multiple times quickly"""
        return {
            "message": "Rate limit test - hit me quickly to see rate limiting in action!"
        }

    agent_os = AgentOS(
        description="Essential middleware demo with rate limiting and logging",
        agents=[agent],
        fastapi_app=app,
        middleware=ESSENTIAL_MIDDLEWARE,
    )

    return agent_os.get_app()


# Create the app
app = create_middleware_demo_app()

if __name__ == "__main__":
    """
    Run the essential middleware demo.
    
    Features:
    1. Rate Limiting (10 requests/minute)
    2. Request/Response Logging
    
    Test commands:
    
    1. Basic request:
       curl http://localhost:7777/test
    
    2. Test rate limiting:
       for i in {1..15}; do curl http://localhost:7777/rate-limit-test; done
    
    4. Check rate limit headers:
       curl -v http://localhost:7777/test
    
    Look for:
    - Console logs showing request/response info
    - Rate limit headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
    - Request count header: X-Request-Count
    - 429 errors when rate limit exceeded
    """
    import uvicorn

    uvicorn.run(
        "fastapi_app_with_custom_middleware:app",
        host="localhost",
        port=7777,
        reload=True,
    )
