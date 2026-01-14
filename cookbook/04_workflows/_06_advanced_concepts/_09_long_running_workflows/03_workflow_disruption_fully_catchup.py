"""
Test full catch-up functionality - reconnecting to a RUNNING workflow
and requesting ALL events from the start.

This test verifies:
1. Workflow starts running
2. Client disconnects early (after receiving only a few events)
3. Client reconnects with last_event_index=null (or omitted)
4. ALL events from the beginning are sent (not just missed ones)
5. Client continues receiving new events

Usage:
    1. Start server: python cookbook/agent_os/workflow/basic_workflow.py
    2. Run this test: python cookbook/workflows/_06_advanced_concepts/_07_long_running_workflows/01_workflow_disruption_fully_catchup.py
"""

import asyncio
import json
from typing import Optional

try:
    import websockets
except ImportError:
    print("websockets library not installed. Install with: pip install websockets")
    exit(1)


def parse_sse_message(message: str) -> dict:
    """Parse SSE-formatted message"""
    lines = message.strip().split("\n")
    for line in lines:
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(message)


async def test_full_catchup():
    """Test full catch-up for running workflows"""
    print("\n" + "=" * 80)
    print(" Full Catch-Up Test - Getting ALL Events from Running Workflow")
    print("=" * 80)

    ws_url = "ws://localhost:7777/workflows/ws"
    run_id: Optional[str] = None

    # Phase 1: Start workflow, receive a FEW events, then disconnect
    print("\n Phase 1: Starting workflow and receiving initial events...")

    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"✓ Connected to {ws_url}")

            # Wait for connection
            response = await websocket.recv()
            data = parse_sse_message(response)
            print(f"✓ {data.get('message', 'Connected')}")

            # Start workflow
            print("\n Starting workflow...")
            await websocket.send(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "content-creation-workflow",
                        "message": "Test full catch-up",
                        "session_id": "full-catchup-test",
                    }
                )
            )

            # Receive only a FEW events then disconnect
            print("\n Receiving initial events:")
            event_count = 0
            max_events = 3  # Receive only 3 events

            async for message in websocket:
                data = parse_sse_message(message)
                event_type = data.get("event")
                event_index = data.get("event_index", "N/A")

                if data.get("run_id") and not run_id:
                    run_id = data["run_id"]

                event_count += 1
                print(
                    f"  [{event_count}] event_index={event_index}, event={event_type}"
                )

                if event_count >= max_events:
                    print(f"\n Disconnecting after {event_count} events...")
                    break

    except Exception as e:
        print(f" Error in Phase 1: {e}")
        raise

    if not run_id:
        print(" No run_id captured")
        return

    # Phase 2: Wait for workflow to generate more events
    print("\n Waiting 3 seconds for workflow to generate more events...")
    await asyncio.sleep(3)

    # Phase 3: Reconnect with last_event_index=null to get FULL history
    print("\n Phase 3: Reconnecting with last_event_index=null...")
    print("   (Requesting ALL events from the start)")

    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"✓ Reconnected to {ws_url}")

            # Wait for connection
            response = await websocket.recv()
            parse_sse_message(response)

            # Reconnect with last_event_index=null (omit or set to null)
            await websocket.send(
                json.dumps(
                    {
                        "action": "reconnect",
                        "run_id": run_id,
                        "last_event_index": None,  # Request ALL events from start!
                        "workflow_id": "content-creation-workflow",
                        "session_id": "full-catchup-test",
                    }
                )
            )

            # Receive catch-up
            print("\n Receiving catch-up events:")
            catchup_events = []
            new_events = []
            got_catch_up = False
            got_subscribed = False

            async for message in websocket:
                data = parse_sse_message(message)
                event_type = data.get("event")
                event_index = data.get("event_index")

                if event_type == "catch_up":
                    got_catch_up = True
                    print("\n CATCH_UP notification:")
                    print(f"     missed_events: {data.get('missed_events')}")
                    print(
                        f"     current_event_count: {data.get('current_event_count')}"
                    )
                    print(f"     status: {data.get('status')}")
                    continue

                if event_type == "subscribed":
                    got_subscribed = True
                    print("\n SUBSCRIBED - now listening for new events")
                    print(
                        f"     current_event_count: {data.get('current_event_count')}"
                    )
                    continue

                # Track catch-up vs new events
                if event_index is not None:
                    if not got_subscribed:
                        catchup_events.append(data)
                        if len(catchup_events) <= 10:  # Show first 10
                            print(f" event_index={event_index}, event={event_type}")
                        elif len(catchup_events) == 11:
                            print("  ... (more catch-up events)")
                    else:
                        new_events.append(data)
                        if len(new_events) <= 5:  # Show first 5 new
                            print(f" event_index={event_index}, event={event_type}")

                # Stop after getting some new events
                if len(new_events) >= 5:
                    print(
                        f"\n Stopping (received {len(catchup_events)} catch-up + {len(new_events)} new events)"
                    )
                    break

                # Or stop if workflow completes
                if event_type == "WorkflowCompleted":
                    print("\n Workflow completed")
                    break

            # Verification
            print("\n Verification:")

            if not got_catch_up:
                print(" Did not receive 'catch_up' notification")
            else:
                print(" Received 'catch_up' notification")

            if catchup_events:
                first_index = catchup_events[0].get("event_index")
                last_catchup_index = catchup_events[-1].get("event_index")

                print("\n  Catch-up events:")
                print(f"    First event_index: {first_index}")
                print(f"    Last event_index: {last_catchup_index}")
                print(f"    Total received: {len(catchup_events)}")

                if first_index == 0:
                    print(" Catch-up started from event 0 (got FULL history)")
                else:
                    print(f" Catch-up started from event {first_index} (should be 0)")

                # Check for gaps
                event_indices = [e.get("event_index") for e in catchup_events]
                expected = set(range(min(event_indices), max(event_indices) + 1))
                actual = set(event_indices)
                gaps = expected - actual

                if gaps:
                    print(f" Gaps in event sequence: {sorted(gaps)}")
                else:
                    print(" No gaps in event sequence")
            else:
                print(" No catch-up events received")

            if new_events:
                print("\n  New events (after subscription):")
                print(f"    Total received: {len(new_events)}")
                print(" Workflow continued streaming after catch-up")
            else:
                print("\n No new events received (workflow may have completed)")

    except Exception as e:
        print(f" Error in Phase 3: {e}")
        raise

    print("\n" + "=" * 80)
    print(" Full Catch-Up Test Completed!")
    print("=" * 80)
    print("\n Key Takeaway:")
    print("   Send last_event_index=null to get ALL events from start,")
    print("   even when reconnecting to a RUNNING workflow!")
    print("=" * 80)


async def main():
    """Run the full catch-up test"""
    print("\n Starting Full Catch-Up Test")
    print(" Prerequisites:")
    print("   1. AgentOS server should be running at http://localhost:7777")
    print("   2. Run: python cookbook/agent_os/workflow/basic_workflow.py")
    print("\n Starting test in 2 seconds...")
    await asyncio.sleep(2)

    try:
        await test_full_catchup()
    except ConnectionRefusedError:
        print("\n Connection refused. Is the AgentOS server running?")
        print("   Start it with: python cookbook/agent_os/workflow/basic_workflow.py")
    except Exception as e:
        print(f"\n Test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
