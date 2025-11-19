"""
⚙️ Global HTTP Client Customization (Cookbook)

Demonstrates how to define a single global `httpx.Client`
so that all agno Agents (OpenAI, Anthropic, internal models, etc.)
share consistent behavior: logging, headers, request IDs, and retries.

Use cases:
- Company-wide auth headers and tracking
- Unified logging and monitoring
- Production-grade instrumentation

Install:
    pip install agno openai httpx
"""

import logging
import uuid
from datetime import datetime

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.http import set_default_sync_client

# ----------------------------------------------------------------------------
# Logging Setup
# ----------------------------------------------------------------------------
# use debug so we can see httpx headers
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("agno.http")


# ----------------------------------------------------------------------------
# Example 1 — Request ID Injection
# ----------------------------------------------------------------------------


class RequestIDTransport(httpx.HTTPTransport):
    """Injects a unique request ID into each outgoing request."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        req_id = str(uuid.uuid4())
        request.headers["X-Request-ID"] = req_id
        logger.info(f"[{request.method}] {request.url} (ID={req_id})")

        response = super().handle_request(request)
        logger.info(f"[{response.status_code}] {request.url.host} (ID={req_id})")

        return response


request_id_client = httpx.Client(
    transport=RequestIDTransport(),
    timeout=httpx.Timeout(30.0),
)
set_default_sync_client(request_id_client)

agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Request-ID Agent")
agent.run("Hello!", stream=False)


# ----------------------------------------------------------------------------
# Example 2 — Global Company Headers
# ----------------------------------------------------------------------------


class HeaderInjectTransport(httpx.HTTPTransport):
    """Adds global company headers and authentication tokens."""

    def __init__(self, headers: dict, **kwargs):
        super().__init__(**kwargs)
        self.headers = headers

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.headers.update(self.headers)
        return super().handle_request(request)


company_headers = {
    "X-Company-ID": "agno",
    "X-Service": "agno-agents",
    "X-Environment": "production",
    "X-Version": "1.0.0",
    "X-Timestamp": datetime.now().isoformat(),
}

header_client = httpx.Client(
    transport=HeaderInjectTransport(company_headers),
    timeout=httpx.Timeout(30.0),
)
set_default_sync_client(header_client)

agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Header Agent")
agent.run("Inject company headers", stream=False)

print("Look at the httpx debug logs to see your headers added!")


# ----------------------------------------------------------------------------
# Example 3 — Production-Ready Combined Transport
# ----------------------------------------------------------------------------


class ProductionTransport(httpx.HTTPTransport):
    """Combines headers, request IDs, and error tracking."""

    def __init__(self, service_name: str, headers: dict):
        super().__init__()
        self.service_name = service_name
        self.headers = headers
        self.counter = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.counter += 1
        req_id = str(uuid.uuid4())

        # Inject headers
        request.headers.update(self.headers)
        request.headers.update(
            {
                "X-Service": self.service_name,
                "X-Request-ID": req_id,
                "X-Request-Number": str(self.counter),
            }
        )

        logger.info(
            f"[{self.service_name}] -> {request.url.host} (#{self.counter}, ID={req_id})"
        )

        try:
            response = super().handle_request(request)
            logger.info(
                f"[{self.service_name}] <- {response.status_code} (#{self.counter}, ID={req_id})"
            )
            return response
        except Exception as e:
            logger.error(
                f"[{self.service_name}] ERROR (#{self.counter}, ID={req_id}): {e}"
            )
            raise


prod_client = httpx.Client(
    transport=ProductionTransport("my-ai-app", company_headers),
    timeout=httpx.Timeout(60.0),
)
set_default_sync_client(prod_client)

prod_agents = [
    Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Prod OpenAI"),
    # Could also run with your own openai compat api, however due to ai.example.com not being a real domain... It will fail
    # Agent(model=OpenAILike(id="gpt-4o-mini", base_url="https://ai.example.com/v1"), name="Prod Internal"),
]

for agent in prod_agents:
    agent.run(f"Production request via {agent.name}", stream=False)
