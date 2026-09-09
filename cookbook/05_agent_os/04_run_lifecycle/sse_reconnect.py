"""
Reconnect to background AgentOS SSE streams
===========================================

Use raw ``httpx`` to track ``event_index``, deliberately disconnect, and POST
to the nested ``/resume`` route. The ``run`` demo resumes a new background
stream. The ``continue`` demo first pauses on a confirmation tool, continues
the run in the background, disconnects, and resumes that continued stream.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/sse_reconnect.py
Try: Run this file with --demo run or --demo continue in another terminal
"""

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Resumable AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "resumable-stream-agent"
RUN_SESSION_ID = "sse-reconnect-run-session"
CONTINUE_SESSION_ID = "sse-reconnect-continue-session"
EVENTS_BEFORE_DISCONNECT = 2


@tool(requires_confirmation=True)
def reserve_trip(destination: str) -> str:
    """Return a deterministic reservation result after user confirmation."""
    return f"Reserved a demonstration trip to {destination}."


db = SqliteDb(
    id="resumable-stream-db",
    db_file="tmp/agent_os_sse_reconnect.db",
)

resumable_agent = Agent(
    id=AGENT_ID,
    name="Resumable Stream Agent",
    model=OpenAIResponses(id="gpt-5.5", max_output_tokens=200),
    db=db,
    tools=[reserve_trip],
    instructions=(
        "Use reserve_trip only when explicitly asked to reserve a trip. "
        "For other requests, answer directly."
    ),
)

agent_os = AgentOS(
    id="resumable-stream-os",
    agents=[resumable_agent],
)
app = agent_os.get_app()


async def iter_sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON payloads from an SSE response."""
    event_name: str | None = None
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if data_lines:
                raw_data = "\n".join(data_lines)
                data_lines = []
                if raw_data != "[DONE]":
                    payload = json.loads(raw_data)
                    if event_name and "event" not in payload:
                        payload["event"] = event_name
                    yield payload
            event_name = None


def show_event(label: str, event: dict[str, Any]) -> None:
    """Print the event fields needed to verify reconnect behavior."""
    if event.get("event") == "RunContent":
        return

    preview = str(event.get("content") or "")[:60].replace("\n", " ")
    print(
        f"{label} event={event.get('event')} "
        f"event_index={event.get('event_index')} content={preview!r}"
    )


async def disconnect_after_events(
    response: httpx.Response,
    event_limit: int = EVENTS_BEFORE_DISCONNECT,
) -> dict[str, Any]:
    """Read a prefix of an SSE stream, then return the reconnect coordinates."""
    response.raise_for_status()
    if "text/event-stream" not in response.headers.get("content-type", ""):
        raise RuntimeError("Expected an SSE response")

    state: dict[str, Any] = {
        "run_id": None,
        "session_id": None,
        "last_event_index": None,
        "events": [],
    }
    async for event in iter_sse(response):
        show_event("BEFORE DISCONNECT", event)
        state["events"].append(event)
        state["run_id"] = event.get("run_id") or state["run_id"]
        state["session_id"] = event.get("session_id") or state["session_id"]
        if event.get("event_index") is not None:
            state["last_event_index"] = event["event_index"]
        if len(state["events"]) >= event_limit:
            break

    if not state["run_id"] or not state["session_id"]:
        raise RuntimeError("The SSE prefix did not contain run_id and session_id")
    return state


async def resume_stream(
    client: httpx.AsyncClient,
    run_id: str,
    session_id: str,
    last_event_index: int | None,
) -> list[dict[str, Any]]:
    """Reconnect to a run and consume the missed and remaining SSE events."""
    data = {"session_id": session_id}
    if last_event_index is not None:
        data["last_event_index"] = str(last_event_index)

    resumed_events: list[dict[str, Any]] = []
    async with client.stream(
        "POST",
        f"/agents/{AGENT_ID}/runs/{run_id}/resume",
        data=data,
    ) as response:
        response.raise_for_status()
        async for event in iter_sse(response):
            show_event("AFTER RECONNECT", event)
            resumed_events.append(event)

    if not resumed_events:
        raise RuntimeError("The resume endpoint returned no events")
    indexed_events = [
        event["event_index"]
        for event in resumed_events
        if event.get("event_index") is not None
    ]
    if indexed_events:
        print(
            f"Resumed event_index range: {min(indexed_events)}..{max(indexed_events)}"
        )
    return resumed_events


async def run_reconnect_demo() -> None:
    """Disconnect from a new background stream and resume it."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": (
                    "In exactly two sentences and no more than 35 words, explain why "
                    "SSE clients must reconnect. Do not call reserve_trip."
                ),
                "session_id": RUN_SESSION_ID,
                "background": "true",
                "stream": "true",
            },
        ) as response:
            state = await disconnect_after_events(response)

        print(
            f"Disconnected from run {state['run_id']} "
            f"after event_index={state['last_event_index']}"
        )
        await asyncio.sleep(1)
        await resume_stream(
            client,
            run_id=state["run_id"],
            session_id=state["session_id"],
            last_event_index=state["last_event_index"],
        )


async def start_paused_run(client: httpx.AsyncClient) -> dict[str, Any]:
    """Start a run that pauses at the confirmation-gated reservation tool."""
    paused_event: dict[str, Any] | None = None

    async with client.stream(
        "POST",
        f"/agents/{AGENT_ID}/runs",
        data={
            "message": "Reserve a demonstration trip to Kyoto.",
            "session_id": CONTINUE_SESSION_ID,
            "stream": "true",
        },
    ) as response:
        response.raise_for_status()
        async for event in iter_sse(response):
            show_event("INITIAL RUN", event)
            if event.get("event") == "RunPaused":
                paused_event = event
                break

    if paused_event is None:
        raise RuntimeError("The initial run did not pause for confirmation")
    if not paused_event.get("run_id") or not paused_event.get("session_id"):
        raise RuntimeError("The RunPaused event did not include run and session IDs")
    if not paused_event.get("tools"):
        raise RuntimeError("The RunPaused event did not include the pending tool")
    return paused_event


async def continue_reconnect_demo() -> None:
    """Continue a paused run in the background, disconnect, and resume it."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        paused = await start_paused_run(client)
        approved_tools = paused["tools"]
        for pending_tool in approved_tools:
            if pending_tool.get("requires_confirmation"):
                pending_tool["confirmed"] = True

        run_id = paused["run_id"]
        session_id = paused["session_id"]
        async with client.stream(
            "POST",
            f"/agents/{AGENT_ID}/runs/{run_id}/continue",
            data={
                "tools": json.dumps(approved_tools),
                "session_id": session_id,
                "background": "true",
                "stream": "true",
            },
        ) as response:
            state = await disconnect_after_events(response)

        print(
            f"Disconnected from continued run {state['run_id']} "
            f"after event_index={state['last_event_index']}"
        )
        await asyncio.sleep(1)
        await resume_stream(
            client,
            run_id=state["run_id"],
            session_id=state["session_id"],
            last_event_index=state["last_event_index"],
        )


# ---------------------------------------------------------------------------
# Run SSE Reconnection Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        choices=("run", "continue"),
        help="Run a reconnect client against the AgentOS server.",
    )
    args = parser.parse_args()

    if args.demo == "run":
        asyncio.run(run_reconnect_demo())
    elif args.demo == "continue":
        asyncio.run(continue_reconnect_demo())
    else:
        agent_os.serve(app=app)
