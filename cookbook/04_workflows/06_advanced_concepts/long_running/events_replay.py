"""
Events Replay
=============

Tests replay behavior when reconnecting to a completed workflow run.
"""

import asyncio
import json
from typing import Optional

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
try:
    import websockets
except ImportError:
    print(
        "[ERROR] websockets library not installed. Install with: uv pip install websockets"
    )
    exit(1)


# ---------------------------------------------------------------------------
# Define Helpers
# ---------------------------------------------------------------------------
def parse_sse_message(message: str) -> dict:
    lines = message.strip().split("\n")
    for line in lines:
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(message)


# ---------------------------------------------------------------------------
# Create Replay Test
# ---------------------------------------------------------------------------
async def test_replay() -> None:
    print("\n" + "=" * 80)
    print("Replay Test - Reconnecting to Completed Workflow")
    print("=" * 80)

    ws_url = "ws://localhost:7777/workflows/ws"
    run_id: Optional[str] = None
    total_events = 0

    print("\nPhase 1: Starting workflow and letting it complete...")

    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"[OK] Connected to {ws_url}")

            response = await websocket.recv()
            data = parse_sse_message(response)
            print(f"[OK] {data.get('message', 'Connected')}")

            print("\nStarting workflow...")
            await websocket.send(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "content-creation-workflow",
                        "message": "Quick test workflow",
                        "session_id": "replay-test-session",
                    }
                )
            )

            print("\nWaiting for workflow to complete...")
            async for message in websocket:
                data = parse_sse_message(message)
                event_type = data.get("event")

                if data.get("run_id") and not run_id:
                    run_id = data["run_id"]

                if data.get("event_index") is not None:
                    total_events = max(total_events, data["event_index"] + 1)

                if event_type == "WorkflowStarted":
                    print(f"  Workflow started (run_id: {run_id})")

                if event_type == "WorkflowCompleted":
                    print(f"  Workflow completed ({total_events} events)")
                    break

    except Exception as e:
        print(f"[ERROR] Phase 1: {e}")
        raise

    if not run_id:
        print("[ERROR] No run_id captured")
        return

    print("\nWaiting 2 seconds before reconnection...")
    await asyncio.sleep(2)

    print("\nPhase 2: Reconnecting to COMPLETED workflow...")
    print("  Sending last_event_index=10 (should be IGNORED)")

    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"[OK] Reconnected to {ws_url}")

            response = await websocket.recv()
            parse_sse_message(response)

            await websocket.send(
                json.dumps(
                    {
                        "action": "reconnect",
                        "run_id": run_id,
                        "last_event_index": 10,
                        "workflow_id": "content-creation-workflow",
                        "session_id": "replay-test-session",
                    }
                )
            )

            print("\nReceiving replay...")
            replay_events = []
            got_replay_notification = False

            async for message in websocket:
                data = parse_sse_message(message)
                event_type = data.get("event")

                if event_type == "replay":
                    got_replay_notification = True
                    print("\nREPLAY notification:")
                    print(f"  status: {data.get('status')}")
                    print(f"  total_events: {data.get('total_events')}")
                    print(f"  message: {data.get('message')}")
                    continue

                if data.get("event_index") is not None:
                    replay_events.append(data)

                if len(replay_events) > 0 and event_type == "WorkflowCompleted":
                    break

            print(f"\nReceived {len(replay_events)} events")

            print("\nVerification:")
            if not got_replay_notification:
                print("[ERROR] Did not receive 'replay' notification")
            else:
                print("[OK] Received 'replay' notification")

            if replay_events:
                first_index = replay_events[0].get("event_index")
                last_index = replay_events[-1].get("event_index")

                print(f"  First event_index: {first_index}")
                print(f"  Last event_index: {last_index}")

                if first_index == 0:
                    print("[OK] Replay started from event 0 (correct)")
                else:
                    print(
                        f"[ERROR] Replay started from event {first_index} (should be 0)"
                    )

                if len(replay_events) == total_events:
                    print(
                        f"[OK] Received all {total_events} events (last_event_index was ignored)"
                    )
                else:
                    print(
                        f"[ERROR] Received {len(replay_events)} events, expected {total_events}"
                    )

                event_indices = [e.get("event_index") for e in replay_events]
                expected = set(range(min(event_indices), max(event_indices) + 1))
                actual = set(event_indices)
                gaps = expected - actual

                if gaps:
                    print(f"[ERROR] Gaps in event sequence: {sorted(gaps)}")
                else:
                    print("[OK] No gaps in event sequence")
            else:
                print("[ERROR] No events received during replay")

    except Exception as e:
        print(f"[ERROR] Phase 2: {e}")
        raise

    print("\n" + "=" * 80)
    print("Replay Test Completed")
    print("=" * 80)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
async def main() -> None:
    print("\nStarting Replay Test")
    print("Prerequisites:")
    print("  1. AgentOS server should be running at http://localhost:7777")
    print("  2. Run: python cookbook/agent_os/workflow/basic_workflow.py")
    print("\nStarting test in 2 seconds...")
    await asyncio.sleep(2)

    try:
        await test_replay()
    except ConnectionRefusedError:
        print("\n[ERROR] Connection refused. Is the AgentOS server running?")
        print("  Start it with: python cookbook/agent_os/workflow/basic_workflow.py")
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
