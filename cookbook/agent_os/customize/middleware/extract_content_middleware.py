"""Example for AgentOS to show how to extract content from a response and send it to a notification service.

This example middleware can extract content from both streaming and non-streaming responses.
"""

import json

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.os import AgentOS
from fastapi import Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
)
from starlette.middleware.base import (
    _StreamingResponse as StreamingResponse,
)


# Setup Middleware
class ContentExtractionMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts content from the response body for /runs endpoints
    and captures the response body for notifications.
    Only processes POST requests to paths ending with /runs.

    It also extracts X-APP-UUID from the request headers for notifications.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only extract content for POST requests to /runs endpoints
        is_runs_endpoint = request.method == "POST" and request.url.path.endswith(
            "/runs"
        )

        # Extract X-APP-UUID from request headers
        app_uuid = request.headers.get("X-APP-UUID")

        if app_uuid:
            print(f"✨ Extracted X-APP-UUID from headers: {app_uuid}")

        # Process request
        response = await call_next(request)

        # Capture response body for notification
        if app_uuid and is_runs_endpoint:
            # Check if it's a streaming response
            if isinstance(response, StreamingResponse):
                # Handle streaming SSE response
                async def capture_streaming_response():
                    response_chunks = []
                    content_parts = []

                    async for chunk in response.body_iterator:
                        response_chunks.append(chunk)

                        # Parse SSE format to extract content
                        chunk_text = (
                            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                        )

                        # SSE format: "event: EventName\ndata: {...}\n\n"
                        for line in chunk_text.split("\n"):
                            if line.startswith("data: "):
                                try:
                                    # Extract JSON from data line
                                    json_str = line[6:]  # Remove "data: " prefix
                                    data = json.loads(json_str)

                                    # Extract content if present
                                    if (
                                        "content" in data
                                        and data["content"]
                                        and data["event"] == "RunContent"
                                    ):
                                        content_parts.append(data["content"])
                                except json.JSONDecodeError:
                                    pass  # Skip malformed JSON

                        yield chunk

                    # After streaming completes, send notification with assembled content
                    full_content = "".join(content_parts)
                    self._send_notification(app_uuid, full_content, is_streaming=True)

                return StreamingResponse(
                    capture_streaming_response(),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            else:
                # Handle non-streaming response
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk

                # Send notification with response body
                response_text = response_body.decode("utf-8")
                self._send_notification(app_uuid, response_text, is_streaming=False)

                # Reconstruct response with captured body
                return Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        return response

    def _send_notification(
        self, app_uuid: str, response_body: str, is_streaming: bool = False
    ):
        """Send notification with the response body."""
        print(f"\n{'=' * 60}")
        print(f"📲 Sending notification for app: {app_uuid}")
        print(f"{'=' * 60}")

        if is_streaming:
            # For streaming, response_body is already the assembled content
            print(f"Assembled Content from Stream:\n{response_body}")
        else:
            # For non-streaming, parse JSON and extract content
            try:
                if response_body.strip().startswith("{"):
                    response_json = json.loads(response_body)
                    if "content" in response_json:
                        print(f"Response Content:\n{response_json['content']}")
                    else:
                        print(f"Response Body:\n{json.dumps(response_json, indent=2)}")
                else:
                    preview = response_body[:500]
                    print(f"Response Preview:\n{preview}...")
            except Exception as _:
                # If parsing fails, just show the raw response preview
                preview = response_body[:500]
                print(f"Response Preview:\n{preview}...")

        print(f"{'=' * 60}\n")


# Setup the database
db = SqliteDb(id="basic-db", db_file="tmp/agent_os.db")

# Setup basic agents, teams and workflows
user_request_bot = Agent(
    id="user-agent",
    name="User Agent",
    description="Answer queries about the user.",
    db=db,
    markdown=True,
    enable_user_memories=True,
    instructions="You are a user agent. You are asked to answer queries about the user.",
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example AgentOS to show how to extract content from a response",
    agents=[user_request_bot],
)
app = agent_os.get_app()

# Add the metadata extraction middleware
app.add_middleware(ContentExtractionMiddleware)


if __name__ == "__main__":
    """Run your AgentOS.
    
    This shows how to pass UUIDs via headers to the agent. It also shows how to pass metadata to the agent.

    Test passing UUIDs via headers (non-streaming):
    curl --location 'http://localhost:7777/agents/user-agent/runs' \
        --header 'X-APP-UUID: app-12345' \
        --form 'message=What do you know about the app?' \
        --form 'stream=false' \
        --form 'metadata={"app_uuid": "app-12345", "user_tier": "premium", "source": "mobile_app"}'
    
    Test with streaming (notification sent after stream completes):
    curl --location 'http://localhost:7777/agents/user-agent/runs' \
        --header 'X-APP-UUID: app-67890' \
        --form 'message=Tell me something about myself?' \
        --form 'stream=true'
    
    The X-APP-UUID header will be extracted, and after the agent responds,
    a notification will be sent with the response body.
    """
    agent_os.serve(app="extract_content_middleware:app", reload=True)
