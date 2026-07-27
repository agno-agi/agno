"""
Observe AgentOS run responses without private response classes
==============================================================

This middleware captures non-streaming JSON bodies and streaming SSE content
for ``POST .../runs`` requests carrying ``X-APP-UUID``. A public ASGI ``send``
wrapper observes response body frames without rebuilding the response, so no
private Starlette response import or type check is needed.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/response_middleware.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json
from typing import Any

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ---------------------------------------------------------------------------
# Create Response Middleware
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "response-middleware-agent"


def event_content(event_text: str) -> str:
    """Extract RunContent text from one complete SSE event."""
    content_parts: list[str] = []
    for line in event_text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if data.get("event") == "RunContent" and data.get("content"):
            content_parts.append(str(data["content"]))
    return "".join(content_parts)


class ContentCaptureMiddleware:
    """Observe response body frames while forwarding the original ASGI messages."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Capture only run endpoints explicitly correlated by a request header."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = dict(scope.get("headers") or [])
        app_uuid_bytes = request_headers.get(b"x-app-uuid")
        is_run_request = scope.get("method") == "POST" and str(
            scope.get("path", "")
        ).endswith("/runs")
        if not app_uuid_bytes or not is_run_request:
            await self.app(scope, receive, send)
            return

        app_uuid = app_uuid_bytes.decode("utf-8")
        body = bytearray()
        streaming = False
        notified = False

        async def capture_send(message: Message) -> None:
            nonlocal notified, streaming
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers") or [])
                content_type = ""
                for name, value in response_headers:
                    if name.lower() == b"content-type":
                        content_type = value.decode("latin-1")
                        break
                streaming = content_type.startswith("text/event-stream")
                response_headers.append((b"x-content-capture", b"enabled"))
                message = {**message, "headers": response_headers}

            if message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                stream_finished = streaming and b"event: RunCompleted" in body
                response_finished = not message.get("more_body", False)
                if not notified and (stream_finished or response_finished):
                    self.notify_from_body(
                        app_uuid=app_uuid,
                        body=bytes(body),
                        streaming=streaming,
                    )
                    notified = True

            await send(message)

        await self.app(scope, receive, capture_send)

    @classmethod
    def notify_from_body(
        cls,
        app_uuid: str,
        body: bytes,
        streaming: bool,
    ) -> None:
        """Extract captured content and pass it to the notification stand-in."""
        text = body.decode("utf-8")
        if streaming:
            captured_content = "".join(
                event_content(event_text) for event_text in text.split("\n\n")
            )
        else:
            try:
                payload: Any = json.loads(text)
                captured_content = str(payload.get("content", payload))
            except (json.JSONDecodeError, AttributeError):
                captured_content = text
        cls.send_notification(
            app_uuid=app_uuid,
            content=captured_content,
            streaming=streaming,
        )

    @staticmethod
    def send_notification(
        app_uuid: str,
        content: str,
        streaming: bool,
    ) -> None:
        """Stand in for a notification integration after capture completes."""
        mode = "streaming" if streaming else "non-streaming"
        print(f"Notification app={app_uuid} mode={mode} content={content}")


# ---------------------------------------------------------------------------
# Create Response-Aware AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="response-middleware-db",
    db_file="tmp/agent_os_response_middleware.db",
)

response_agent = Agent(
    id=AGENT_ID,
    name="Response Middleware Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer in one short sentence.",
)

agent_os = AgentOS(
    id="response-middleware-os",
    db=db,
    agents=[response_agent],
)
app = agent_os.get_app()
app.add_middleware(ContentCaptureMiddleware)


def run_demo() -> None:
    """Exercise both response shapes through the checked-in middleware."""
    headers = {"X-APP-UUID": "cookbook-app"}
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/agents/{AGENT_ID}/runs",
            headers=headers,
            data={
                "message": "Say that non-streaming capture works.",
                "session_id": "response-middleware-json",
                "stream": "false",
            },
        )
        response.raise_for_status()
        if response.headers.get("X-Content-Capture") != "enabled":
            raise RuntimeError("Non-streaming response bypassed the middleware")
        print(f"Non-streaming status: {response.json()['status']}")

        with client.stream(
            "POST",
            f"/agents/{AGENT_ID}/runs",
            headers=headers,
            data={
                "message": "Say that streaming capture works.",
                "session_id": "response-middleware-sse",
                "stream": "true",
            },
        ) as stream_response:
            stream_response.raise_for_status()
            if stream_response.headers.get("X-Content-Capture") != "enabled":
                raise RuntimeError("Streaming response bypassed the middleware")
            event_count = sum(
                1 for line in stream_response.iter_lines() if line.startswith("event: ")
            )
        if event_count == 0:
            raise RuntimeError("The streaming response contained no SSE events")
        print(f"Streaming events: {event_count}")


# ---------------------------------------------------------------------------
# Run Response-Aware AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run both HTTP clients against a server listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)
