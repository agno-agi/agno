"""
Stream a served Workflow over WebSocket
=======================================

Connect to the workflow-only /workflows/ws surface, send start-workflow, and
consume indexed workflow events until the served workflow completes.

Prerequisites: basic.py running on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/ws_stream.py
Try: Compare this full-duplex stream with the SSE stream in run_over_api.py
"""

import asyncio
import json
import os
from typing import Any

import websockets

# ---------------------------------------------------------------------------
# Create WebSocket Workflow Client
# ---------------------------------------------------------------------------

WS_URL = os.getenv("AGENT_OS_WS_URL", "ws://localhost:7777/workflows/ws")
WORKFLOW_ID = "release-notes-workflow"
SESSION_ID = "workflow-websocket-session"
TERMINAL_EVENTS = {"WorkflowCancelled", "WorkflowCompleted", "WorkflowError"}


def parse_message(message: str) -> dict[str, Any]:
    """Parse either plain JSON control messages or SSE-framed workflow events."""
    for line in message.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(message)


async def stream_workflow() -> None:
    """Start a workflow and receive its events over a genuine WebSocket."""
    event_types: list[str] = []
    run_id: str | None = None
    last_event_index: int | None = None

    async with websockets.connect(WS_URL, open_timeout=30.0) as websocket:
        connected = parse_message(await asyncio.wait_for(websocket.recv(), 30.0))
        if connected.get("event") != "connected":
            raise RuntimeError(f"Unexpected WebSocket greeting: {connected}")
        if connected.get("requires_auth"):
            raise RuntimeError(
                "This local WebSocket unexpectedly requires authentication"
            )

        await websocket.send(
            json.dumps(
                {
                    "action": "start-workflow",
                    "workflow_id": WORKFLOW_ID,
                    "message": (
                        "Document a more reliable WebSocket workflow stream "
                        "with concise event handling."
                    ),
                    "session_id": SESSION_ID,
                }
            )
        )

        while True:
            message = await asyncio.wait_for(websocket.recv(), timeout=180.0)
            event = parse_message(message)
            event_type = event.get("event", "message")
            event_types.append(event_type)
            run_id = run_id or event.get("run_id")

            if event.get("event_index") is not None:
                last_event_index = event["event_index"]

            if event_type in TERMINAL_EVENTS:
                if event_type != "WorkflowCompleted":
                    raise RuntimeError(f"Workflow ended with {event_type}: {event}")
                break

    if not run_id:
        raise RuntimeError("The WebSocket stream did not include a run_id")
    if last_event_index is None:
        raise RuntimeError("The WebSocket stream did not include indexed events")

    print(f"Connected: {connected['message']}")
    print(f"Workflow run: {run_id}")
    print(f"Indexed through: {last_event_index}")
    print(f"Event count: {len(event_types)}")
    print(f"Event types: {list(dict.fromkeys(event_types))}")


# ---------------------------------------------------------------------------
# Run WebSocket Stream
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(stream_workflow())
