"""
Continue Run SSE Reconnection
==============================

Tests SSE stream reconnection for agent continue-run (HITL) scenarios.
When an agent run pauses (e.g., tool requires approval), the client calls
/continue with background=True to resume in a detached task that survives
client disconnections. Events are buffered for reconnection via /resume.

Steps:
1. Start a streaming run that will pause for tool approval
2. Wait for the run to pause
3. Continue the paused run with background=true, stream=true
4. Disconnect after a few events
5. Reconnect via /resume and catch up on missed events

Prerequisites:
1. Start the AgentOS server with: python cookbook/05_agent_os/human_in_the_loop/agent_tool_requires_confirmation.py
2. Run this script: python cookbook/05_agent_os/client/12_continue_run_sse_reconnect.py

Note: This script requires an agent with tools that pause for approval.
If the agent completes without pausing, the continue-run path won't be exercised.
"""

import asyncio
import json
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:7777"
# Number of events to receive from continue-run before simulating a disconnect
EVENTS_BEFORE_DISCONNECT = 4
# How long to "stay disconnected" (seconds)
DISCONNECT_DURATION = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_sse_line(line: str) -> Optional[dict]:
    """Parse a single SSE data line into a dict."""
    if line.startswith("data: "):
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            return None
    return None


def parse_sse_events(buffer: str) -> tuple[list[dict], str]:
    """Parse all complete SSE events from a buffer. Returns (events, remaining_buffer)."""
    events = []
    while "\n\n" in buffer:
        event_str, buffer = buffer.split("\n\n", 1)
        for line in event_str.strip().split("\n"):
            data = parse_sse_line(line)
            if data is not None:
                events.append(data)
    return events, buffer


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
async def test_continue_run_sse_reconnection():
    print("=" * 70)
    print("Continue Run SSE Reconnection Test (HITL)")
    print("=" * 70)

    # Step 1: Discover an agent
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        resp = await client.get("/agents")
        resp.raise_for_status()
        agents = resp.json()
        if not agents:
            print("[ERROR] No agents available on the server")
            return
        agent_id = agents[0]["id"]
        print(f"Using agent: {agent_id} ({agents[0].get('name', 'unnamed')})")

    # Step 2: Start a streaming run and collect events until it pauses
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    is_paused = False
    events_initial: list[dict] = []

    print("\nPhase 1: Starting agent run, waiting for tool pause...")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        form_data = {
            "message": "Search for the latest news about AI and summarize it for me.",
            "stream": "true",
        }
        async with client.stream(
            "POST", f"/agents/{agent_id}/runs", data=form_data
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                events, buffer = parse_sse_events(buffer)
                for data in events:
                    event_type = data.get("event", "unknown")
                    ev_run_id = data.get("run_id")
                    ev_session_id = data.get("session_id")

                    if ev_run_id and not run_id:
                        run_id = ev_run_id
                    if ev_session_id and not session_id:
                        session_id = ev_session_id

                    events_initial.append(data)
                    content_preview = str(data.get("content", ""))[:60]
                    print(f"  [INIT] event={event_type} content={content_preview!r}")

                    # Check if the run paused (tool approval needed)
                    if data.get("is_paused") or event_type == "RunPaused":
                        is_paused = True
                        print(
                            f"\n  [PAUSED] Run paused for tool approval. run_id={run_id}"
                        )
                        break
                if is_paused:
                    break

    if not run_id:
        print("[ERROR] Could not determine run_id from events")
        return

    if not is_paused:
        print(
            "\n[INFO] Run completed without pausing. Continue-run path not exercised."
        )
        print("  To test this, use an agent with tools that require approval.")
        return

    # Step 3: Continue the paused run with background=True
    print("\nPhase 2: Continuing paused run with background=true, stream=true...")
    print(f"  Will disconnect after {EVENTS_BEFORE_DISCONNECT} events...")

    last_event_index: Optional[int] = None
    events_continue: list[dict] = []

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        form_data = {
            "tools": "[]",  # Empty tools = approve all pending
            "session_id": session_id or "",
            "stream": "true",
            "background": "true",
        }
        async with client.stream(
            "POST", f"/agents/{agent_id}/runs/{run_id}/continue", data=form_data
        ) as response:
            event_count = 0
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                events, buffer = parse_sse_events(buffer)
                for data in events:
                    event_type = data.get("event", "unknown")
                    ev_idx = data.get("event_index")

                    if ev_idx is not None:
                        last_event_index = ev_idx

                    events_continue.append(data)
                    event_count += 1
                    content_preview = str(data.get("content", ""))[:60]
                    print(
                        f"  [{event_count}] event={event_type} index={ev_idx} content={content_preview!r}"
                    )

                    if event_count >= EVENTS_BEFORE_DISCONNECT:
                        break
                if event_count >= EVENTS_BEFORE_DISCONNECT:
                    break

    print(
        f"\n[DISCONNECT] Received {len(events_continue)} events. "
        f"run_id={run_id}, last_event_index={last_event_index}"
    )

    # Step 4: Wait (simulate user being away)
    print(f"\nSimulating disconnect for {DISCONNECT_DURATION} seconds...")
    await asyncio.sleep(DISCONNECT_DURATION)

    # Step 5: Resume via /resume endpoint
    print("\nPhase 3: Reconnecting via /resume endpoint...")
    events_resume: list[dict] = []

    form_data_resume: dict = {}
    if last_event_index is not None:
        form_data_resume["last_event_index"] = str(last_event_index)
    if session_id:
        form_data_resume["session_id"] = session_id

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        async with client.stream(
            "POST", f"/agents/{agent_id}/runs/{run_id}/resume", data=form_data_resume
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                events, buffer = parse_sse_events(buffer)
                for data in events:
                    event_type = data.get("event", "unknown")
                    ev_idx = data.get("event_index")
                    events_resume.append(data)

                    if event_type in ("catch_up", "replay", "subscribed"):
                        print(
                            f"  [META] event={event_type} | {json.dumps(data, indent=2)}"
                        )
                    else:
                        content_preview = str(data.get("content", ""))[:60]
                        print(
                            f"  [RESUME] event={event_type} index={ev_idx} content={content_preview!r}"
                        )

    # Step 6: Print summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Initial run events: {len(events_initial)}")
    print(f"Continue run events (before disconnect): {len(events_continue)}")
    print(f"Resume events: {len(events_resume)}")

    # Check for meta events in resume
    meta_events = [
        e
        for e in events_resume
        if e.get("event") in ("catch_up", "replay", "subscribed")
    ]
    data_events = [
        e
        for e in events_resume
        if e.get("event") not in ("catch_up", "replay", "subscribed", "error")
    ]
    print(f"  Meta events (catch_up/replay/subscribed): {len(meta_events)}")
    print(f"  Data events (actual agent events): {len(data_events)}")

    # Validate event_index continuity between continue and resume
    continue_indices = [
        e.get("event_index")
        for e in events_continue
        if e.get("event_index") is not None
    ]
    resume_indices = [
        e.get("event_index") for e in data_events if e.get("event_index") is not None
    ]

    if continue_indices and resume_indices:
        last_cont = max(continue_indices)
        first_res = min(resume_indices)
        last_res = max(resume_indices)
        print(f"\n  Continue event_index range: {min(continue_indices)} -> {last_cont}")
        print(f"  Resume event_index range: {first_res} -> {last_res}")
        if first_res == last_cont + 1:
            print("  [PASS] Event indices are contiguous - no events were lost")
        elif first_res > last_cont:
            print(f"  [WARN] Gap in event indices: {last_cont} -> {first_res}")
        else:
            print("  [INFO] Overlapping indices detected (dedup may have occurred)")
    elif not resume_indices:
        print(
            "\n  [INFO] No data events in resume (run may have completed before resume)"
        )
    else:
        print("\n  [INFO] No event indices in continue phase to compare")

    total_events = len(events_continue) + len(data_events)
    print(f"\n  Total unique events across continue + resume: {total_events}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_continue_run_sse_reconnection())
