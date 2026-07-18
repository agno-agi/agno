"""
Workflow SSE Reconnection
=========================

Tests SSE stream reconnection for workflow runs using background=True, stream=True.
When background=True, the workflow runs in a detached task that survives client
disconnections. Events are buffered so the client can reconnect via /resume.

Steps:
1. Start a streaming workflow run with background=true
2. Disconnect after a few events
3. Reconnect via /resume and catch up on missed events

Prerequisites:
1. Start the AgentOS server: python cookbook/05_agent_os/basic.py
2. Run this script: python cookbook/05_agent_os/client/13_workflow_sse_reconnect.py
"""

import asyncio
import json
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:7777"
# Number of events to receive before simulating a disconnect
EVENTS_BEFORE_DISCONNECT = 6
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


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
async def test_workflow_sse_reconnection():
    print("=" * 70)
    print("Workflow SSE Reconnection Test")
    print("=" * 70)

    # Step 1: Discover a workflow
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        resp = await client.get("/workflows")
        resp.raise_for_status()
        workflows = resp.json()
        if not workflows:
            print("[ERROR] No workflows available on the server")
            return
        workflow_id = workflows[0]["id"]
        print(f"Using workflow: {workflow_id} ({workflows[0].get('name', 'unnamed')})")

    # Step 2: Start a streaming run and disconnect after a few events
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    last_event_index: Optional[int] = None
    events_phase1: list[dict] = []

    print(
        f"\nPhase 1: Starting SSE stream, will disconnect after {EVENTS_BEFORE_DISCONNECT} events..."
    )

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        form_data = {
            "message": "Tell me a detailed story about a brave knight who goes on a quest. Make it at least 5 paragraphs long.",
            "stream": "true",
            "background": "true",
        }
        async with client.stream(
            "POST", f"/workflows/{workflow_id}/runs", data=form_data
        ) as response:
            event_count = 0
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                # SSE events are delimited by double newlines
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    for line in event_str.strip().split("\n"):
                        data = parse_sse_line(line)
                        if data is None:
                            continue

                        event_type = data.get("event", "unknown")
                        ev_idx = data.get("event_index")
                        ev_run_id = data.get("run_id") or data.get("workflow_run_id")
                        ev_session_id = data.get("session_id")

                        # Track run_id and session_id
                        if ev_run_id and not run_id:
                            run_id = ev_run_id
                        if ev_session_id and not session_id:
                            session_id = ev_session_id
                        if ev_idx is not None:
                            last_event_index = ev_idx

                        events_phase1.append(data)
                        event_count += 1
                        content_preview = str(data.get("content", ""))[:60]
                        print(
                            f"  [{event_count}] event={event_type} index={ev_idx} content={content_preview!r}"
                        )

                        if event_count >= EVENTS_BEFORE_DISCONNECT:
                            break
                    if event_count >= EVENTS_BEFORE_DISCONNECT:
                        break
                if event_count >= EVENTS_BEFORE_DISCONNECT:
                    break

    print(
        f"\n[DISCONNECT] Received {event_count} events. run_id={run_id}, last_event_index={last_event_index}"
    )

    if not run_id:
        print("[ERROR] Could not determine run_id from events")
        return

    # Step 3: Wait (simulate user being away)
    print(f"\nSimulating disconnect for {DISCONNECT_DURATION} seconds...")
    await asyncio.sleep(DISCONNECT_DURATION)

    # Step 4: Resume via /resume endpoint
    print("\nPhase 2: Reconnecting via /resume endpoint...")
    events_phase2: list[dict] = []

    form_data_resume: dict = {}
    if last_event_index is not None:
        form_data_resume["last_event_index"] = str(last_event_index)
    if session_id:
        form_data_resume["session_id"] = session_id

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        async with client.stream(
            "POST",
            f"/workflows/{workflow_id}/runs/{run_id}/resume",
            data=form_data_resume,
        ) as response:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    for line in event_str.strip().split("\n"):
                        data = parse_sse_line(line)
                        if data is None:
                            continue

                        event_type = data.get("event", "unknown")
                        ev_idx = data.get("event_index")
                        events_phase2.append(data)

                        if event_type in ("catch_up", "replay", "subscribed"):
                            print(
                                f"  [META] event={event_type} | {json.dumps(data, indent=2)}"
                            )
                        else:
                            content_preview = str(data.get("content", ""))[:60]
                            print(
                                f"  [RESUME] event={event_type} index={ev_idx} content={content_preview!r}"
                            )

    # Step 5: Print summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Phase 1 events received: {len(events_phase1)}")
    print(f"Phase 2 events received: {len(events_phase2)}")

    # Check for meta events
    meta_events = [
        e
        for e in events_phase2
        if e.get("event") in ("catch_up", "replay", "subscribed")
    ]
    data_events = [
        e
        for e in events_phase2
        if e.get("event") not in ("catch_up", "replay", "subscribed", "error")
    ]
    print(f"  Meta events (catch_up/replay/subscribed): {len(meta_events)}")
    print(f"  Data events (actual workflow events): {len(data_events)}")

    # Validate event_index continuity
    phase1_indices = [
        e.get("event_index") for e in events_phase1 if e.get("event_index") is not None
    ]
    phase2_indices = [
        e.get("event_index") for e in data_events if e.get("event_index") is not None
    ]

    if phase1_indices and phase2_indices:
        last_p1 = max(phase1_indices)
        first_p2 = min(phase2_indices)
        last_p2 = max(phase2_indices)
        print(f"\n  Phase 1 event_index range: 0 -> {last_p1}")
        print(f"  Phase 2 event_index range: {first_p2} -> {last_p2}")
        if first_p2 == last_p1 + 1:
            print("  [PASS] Event indices are contiguous - no events were lost")
        elif first_p2 > last_p1:
            print(f"  [WARN] Gap in event indices: {last_p1} -> {first_p2}")
        else:
            print("  [INFO] Overlapping indices detected (dedup may have occurred)")
    elif not phase2_indices:
        print(
            "\n  [INFO] No data events in phase 2 (run may have completed before resume)"
        )
    else:
        print("\n  [INFO] No event indices in phase 1 to compare")

    total_events = len(events_phase1) + len(data_events)
    print(f"\n  Total unique events across both phases: {total_events}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_workflow_sse_reconnection())
