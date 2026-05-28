"""
WebSocket Reconnect
===================

Tests reconnect behavior for a running workflow: initial subscription, disconnection, reconnect, and missed-event catch-up.
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
    print("websockets library not installed. Install with: uv pip install websockets")
    exit(1)


# ---------------------------------------------------------------------------
# Define Helpers
# ---------------------------------------------------------------------------
def parse_sse_message(message: str) -> dict:
    lines = message.strip().split("\n")
    data_line = None

    for line in lines:
        if line.startswith("data: "):
            data_line = line[6:]
            break

    if data_line:
        return json.loads(data_line)
    return json.loads(message)


# ---------------------------------------------------------------------------
# Create WebSocket Tester
# ---------------------------------------------------------------------------
class WorkflowWebSocketTester:
    def __init__(self, ws_url: str = "ws://localhost:7777/workflows/ws"):
        self.ws_url = ws_url
        self.run_id: Optional[str] = None
        self.last_event_index: Optional[int] = None
        self.received_events = []

    async def test_workflow_execution_with_reconnection(self) -> None:
        print("\n" + "=" * 80)
        print("WebSocket Reconnection Test")
        print("=" * 80)

        print("\nPhase 1: Starting workflow and receiving initial events...")
        await self._phase1_start_workflow()

        print("\nSimulating user leaving page for 3 seconds...")
        await asyncio.sleep(3)

        print("\nPhase 2: Reconnecting to workflow...")
        await self._phase2_reconnect()

        print("\nTest completed")
        self._print_summary()

    async def _phase1_start_workflow(self) -> None:
        try:
            async with websockets.connect(self.ws_url) as websocket:
                print(f"[OK] Connected to {self.ws_url}")

                response = await websocket.recv()
                data = parse_sse_message(response)
                print(f"[OK] Server: {data.get('message', 'Connected')}")

                print("\nSending: start-workflow action")
                await websocket.send(
                    json.dumps(
                        {
                            "action": "start-workflow",
                            "workflow_id": "content-creation-workflow",
                            "message": "Research and create content plan for AI agents",
                            "session_id": "test-session-123",
                        }
                    )
                )

                event_count = 0
                max_initial_events = 20

                print("\nReceiving initial events:")
                async for message in websocket:
                    data = parse_sse_message(message)
                    event_type = data.get("event")

                    if "run_id" in data and not self.run_id:
                        self.run_id = data["run_id"]
                    if "event_index" in data:
                        self.last_event_index = data["event_index"]

                    self.received_events.append(data)
                    event_count += 1

                    event_index = data.get("event_index", "N/A")
                    print(
                        f"  [{event_count}] event_index={event_index}, event={event_type}"
                    )

                    if event_type in ["WorkflowCompleted", "WorkflowError"]:
                        print(
                            f"\nWorkflow finished during initial connection: {event_type}"
                        )
                        break

                    if event_count >= max_initial_events:
                        print(
                            f"\nSimulating disconnect after {event_count} events "
                            f"(last_event_index={self.last_event_index})"
                        )
                        break

        except Exception as e:
            print(f"Error in Phase 1: {e}")
            raise

    async def _phase2_reconnect(self) -> None:
        if not self.run_id:
            print("No run_id found, cannot reconnect")
            return

        try:
            async with websockets.connect(self.ws_url) as websocket:
                print(f"[OK] Reconnected to {self.ws_url}")

                response = await websocket.recv()
                data = parse_sse_message(response)
                print(f"[OK] Server: {data.get('message', 'Connected')}")

                print(
                    f"\nSending: reconnect action (run_id={self.run_id}, "
                    f"last_event_index={self.last_event_index})"
                )
                await websocket.send(
                    json.dumps(
                        {
                            "action": "reconnect",
                            "run_id": self.run_id,
                            "last_event_index": self.last_event_index,
                            "workflow_id": "content-creation-workflow",
                            "session_id": "test-session-123",
                        }
                    )
                )

                print("\nReceiving events after reconnection:")
                event_count = 0
                missed_events_count = 0

                async for message in websocket:
                    data = parse_sse_message(message)
                    event_type = data.get("event")

                    if "event_index" in data:
                        self.last_event_index = data["event_index"]

                    self.received_events.append(data)
                    event_count += 1

                    if event_type == "catch_up":
                        missed_events_count = data.get("missed_events", 0)
                        print(f"catch_up: {missed_events_count} missed events")
                        print(
                            f"status={data.get('status')}, current_event_count={data.get('current_event_count')}"
                        )
                        continue
                    if event_type == "replay":
                        print(
                            f"replay: status={data.get('status')}, total_events={data.get('total_events')}"
                        )
                        print(f"message={data.get('message')}")
                        continue
                    if event_type == "subscribed":
                        print(f"subscribed: status={data.get('status')}")
                        print(f"current_event_count={data.get('current_event_count')}")
                        print("\nNow listening for NEW events as workflow continues...")
                        continue
                    if event_type == "error":
                        print(f"ERROR: {data.get('error', 'Unknown error')}")
                        print(f"Full data: {data}")
                        continue

                    event_index = data.get("event_index", "N/A")
                    is_missed = event_count <= missed_events_count
                    marker = "MISSED" if is_missed else "NEW"
                    print(
                        f"  [{event_count}] {marker} event_index={event_index}, event={event_type}"
                    )

                    if event_type in ["WorkflowCompleted", "WorkflowError"]:
                        print(f"\nWorkflow finished: {event_type}")
                        break

                print("\nWebSocket connection closed (workflow may have completed)")

        except asyncio.TimeoutError:
            print("\nTimeout waiting for events (30s). Workflow may still be running.")
        except Exception as e:
            print(f"Error in Phase 2: {e}")
            raise

    def _print_summary(self) -> None:
        print("\n" + "=" * 80)
        print("Test Summary")
        print("=" * 80)
        print(f"Run ID: {self.run_id}")
        print(f"Last Event Index: {self.last_event_index}")
        print(f"Total Events Received: {len(self.received_events)}")

        event_types = {}
        for event in self.received_events:
            event_type = event.get("event", "unknown")
            event_types[event_type] = event_types.get(event_type, 0) + 1

        print("\nEvent Type Breakdown:")
        for event_type, count in sorted(event_types.items()):
            print(f"  {event_type}: {count}")

        print("\nEvent Index Validation:")
        event_indices = [
            e.get("event_index") for e in self.received_events if "event_index" in e
        ]
        if event_indices:
            print(f"  First event_index: {min(event_indices)}")
            print(f"  Last event_index: {max(event_indices)}")
            print(f"  Total with event_index: {len(event_indices)}")

            expected = set(range(min(event_indices), max(event_indices) + 1))
            actual = set(event_indices)
            gaps = expected - actual
            if gaps:
                print(f"Gaps in event_index: {sorted(gaps)}")
            else:
                print("No gaps in event_index (all events received)")
        else:
            print("No events with event_index found")

        print("=" * 80)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
async def main() -> None:
    print("\nStarting WebSocket Reconnection Test")
    print("Prerequisites:")
    print("  1. AgentOS server should be running at http://localhost:7777")
    print("  2. Run: python cookbook/agent_os/workflow/basic_workflow.py")
    print("\nStarting test in 2 seconds...")
    await asyncio.sleep(2)

    tester = WorkflowWebSocketTester()
    try:
        await tester.test_workflow_execution_with_reconnection()
    except ConnectionRefusedError:
        print("\nConnection refused. Is the AgentOS server running?")
        print("  Start it with: python cookbook/agent_os/workflow/basic_workflow.py")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
