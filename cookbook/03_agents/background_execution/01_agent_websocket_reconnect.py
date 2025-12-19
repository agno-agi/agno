"""
Test script for Agent WebSocket reconnection functionality.

This script tests:
1. Starting an agent via WebSocket (start-agent action)
2. Receiving events with event_index
3. Simulating disconnection
4. Reconnecting (reconnect action) and catching up on missed events

Usage:
    1. Start the AgentOS server with an agent with id 'basic-agent'
    2. Run this test: python cookbook/agents/background_execution/01_agent_websocket_reconnect.py
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
    """Parse SSE-formatted message to extract JSON data.

    SSE format:
        event: <event_type>
        data: <json_data>

    """
    lines = message.strip().split("\n")
    data_line = None

    for line in lines:
        if line.startswith("data: "):
            data_line = line[6:]  # Remove 'data: ' prefix
            break

    if data_line:
        return json.loads(data_line)
    else:
        # Fallback: try parsing entire message as JSON
        return json.loads(message)


class AgentWebSocketTester:
    """Test client for agent WebSocket reconnection"""

    def __init__(self, ws_url: str = "ws://localhost:7777/agents/ws"):
        self.ws_url = ws_url
        self.run_id: Optional[str] = None
        self.last_event_index: Optional[int] = None
        self.received_events = []

    async def test_agent_execution_with_reconnection(self):
        """Test complete agent execution with simulated reconnection"""
        print("\n" + "=" * 80)
        print("Agent WebSocket Reconnection Test")
        print("=" * 80)

        # Phase 1: Start agent and receive initial events
        print("\n Phase 1: Starting agent and receiving initial events...")
        await self._phase1_start_agent()

        # Wait a bit for agent to generate more events
        print("\n Simulating user leaving page for 3 seconds...")
        await asyncio.sleep(3)

        # Phase 2: Reconnect and catch up on missed events
        print("\n Phase 2: Reconnecting to agent run...")
        await self._phase2_reconnect()

        # Print summary
        print("\n Test completed!")
        self._print_summary()

    async def _phase1_start_agent(self):
        """Phase 1: Connect, start agent, receive some events, then disconnect"""
        try:
            async with websockets.connect(self.ws_url) as websocket:
                print(f"Connected to {self.ws_url}")

                # Wait for connection confirmation
                response = await websocket.recv()
                data = parse_sse_message(response)
                print(f"Server: {data.get('message', 'Connected')}")

                # Start agent
                print("\n Sending: start-agent action")
                await websocket.send(
                    json.dumps(
                        {
                            "action": "start-agent",
                            "agent_id": "basic-agent",
                            "message": "Tell me about France in detail",
                            "session_id": "test-session-123",
                        }
                    )
                )

                # Receive initial events (simulate user receiving only first few events)
                event_count = 0
                max_initial_events = 20  # Receive only 20 events before "disconnecting"

                print("\n Receiving initial events:")
                async for message in websocket:
                    data = parse_sse_message(message)
                    event_type = data.get("event")

                    # Track run_id and event_index
                    if "run_id" in data:
                        self.run_id = data["run_id"]
                    if "event_index" in data:
                        self.last_event_index = data["event_index"]

                    self.received_events.append(data)
                    event_count += 1

                    # Print event info
                    event_index = data.get("event_index", "N/A")
                    print(
                        f"  [{event_count}] event_index={event_index}, event={event_type}"
                    )

                    # Check for agent completion during phase 1 (shouldn't happen with fast disconnect)
                    if event_type in ["RunCompleted", "RunError"]:
                        print(
                            f"\n Agent finished during initial connection: {event_type}"
                        )
                        break

                    # "Disconnect" after receiving a few events
                    if event_count >= max_initial_events:
                        print(
                            f"\n Simulating disconnect after {event_count} events "
                            f"(last_event_index={self.last_event_index})"
                        )
                        break

        except Exception as e:
            print(f" Error in Phase 1: {e}")
            raise

    async def _phase2_reconnect(self):
        """Phase 2: Reconnect to the agent run and catch up on missed events"""
        if not self.run_id:
            print(" No run_id found, cannot reconnect")
            return

        try:
            async with websockets.connect(self.ws_url) as websocket:
                print(f"Reconnected to {self.ws_url}")

                # Wait for connection confirmation
                response = await websocket.recv()
                data = parse_sse_message(response)
                print(f"Server: {data.get('message', 'Connected')}")

                # Reconnect to existing agent run
                print(
                    f"\n Sending: reconnect action (run_id={self.run_id}, "
                    f"last_event_index={self.last_event_index})"
                )
                await websocket.send(
                    json.dumps(
                        {
                            "action": "reconnect",
                            "run_id": self.run_id,
                            "last_event_index": self.last_event_index,
                            "agent_id": "basic-agent",
                            "session_id": "test-session-123",
                        }
                    )
                )

                # Receive reconnection response and remaining events
                print("\n Receiving events after reconnection:")
                event_count = 0
                missed_events_count = 0

                async for message in websocket:
                    data = parse_sse_message(message)
                    event_type = data.get("event")

                    # Track event_index
                    if "event_index" in data:
                        self.last_event_index = data["event_index"]

                    self.received_events.append(data)
                    event_count += 1

                    # Special handling for reconnection events
                    if event_type == "subscription_confirmed":
                        missed_events_count = data.get("events_to_send", 0)
                        print(
                            f" subscription_confirmed: {missed_events_count} missed events"
                        )
                        print(
                            f" source={data.get('source')}, total_events={data.get('total_events')}"
                        )
                        continue
                    elif event_type == "catch_up_completed":
                        print(
                            f" catch_up_completed: events_sent={data.get('events_sent')}"
                        )
                        print(f" is_running={data.get('is_running')}")
                        if data.get("is_running"):
                            print(
                                "\n Now listening for NEW events as agent continues..."
                            )
                        else:
                            print("\n Agent already completed")
                            break
                        continue
                    elif event_type == "replay_completed":
                        print(
                            f" replay_completed: total_events={data.get('total_events')}"
                        )
                        print(f" message={data.get('message')}")
                        break
                    elif event_type == "error":
                        print(f" ERROR: {data.get('error', 'Unknown error')}")
                        print(f"     Full data: {data}")
                        break

                    # Print regular event info
                    event_index = data.get("event_index", "N/A")
                    is_missed = event_count <= missed_events_count
                    marker = "MISSED" if is_missed else "NEW"
                    print(
                        f"  [{event_count}] {marker} event_index={event_index}, event={event_type}"
                    )

                    # Check for agent completion
                    if event_type in ["RunCompleted", "RunError"]:
                        print(f"\n Agent finished: {event_type}")
                        break

                # If we exit the loop without completion, the connection closed
                print("\n WebSocket connection closed (agent may have completed)")

        except asyncio.TimeoutError:
            print("\n Timeout waiting for events (30s). Agent may still be running.")
        except Exception as e:
            print(f" Error in Phase 2: {e}")
            raise

    def _print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 80)
        print(" Test Summary")
        print("=" * 80)
        print(f"Run ID: {self.run_id}")
        print(f"Last Event Index: {self.last_event_index}")
        print(f"Total Events Received: {len(self.received_events)}")

        # Count event types
        event_types = {}
        for event in self.received_events:
            event_type = event.get("event", "unknown")
            event_types[event_type] = event_types.get(event_type, 0) + 1

        print("\nEvent Type Breakdown:")
        for event_type, count in sorted(event_types.items()):
            print(f"  {event_type}: {count}")

        # Check for event_index continuity
        print("\nEvent Index Validation:")
        event_indices = [
            e.get("event_index") for e in self.received_events if "event_index" in e
        ]
        if event_indices:
            print(f"  First event_index: {min(event_indices)}")
            print(f"  Last event_index: {max(event_indices)}")
            print(f"  Total with event_index: {len(event_indices)}")

            # Check for gaps (missed events that weren't replayed)
            expected = set(range(min(event_indices), max(event_indices) + 1))
            actual = set(event_indices)
            gaps = expected - actual
            if gaps:
                print(f" Gaps in event_index: {sorted(gaps)}")
            else:
                print(" No gaps in event_index (all events received)")
        else:
            print(" No events with event_index found")

        print("=" * 80)


async def main():
    """Run the Agent WebSocket reconnection test"""
    print("\n Starting Agent WebSocket Reconnection Test")
    print(" Prerequisites:")
    print("   1. AgentOS server should be running at http://localhost:7777")
    print("   2. An agent with id 'basic-agent' should be registered")
    print("\n Starting test in 2 seconds...")
    await asyncio.sleep(2)

    tester = AgentWebSocketTester()
    try:
        await tester.test_agent_execution_with_reconnection()
    except ConnectionRefusedError:
        print("\n Connection refused. Is the AgentOS server running?")
    except Exception as e:
        print(f"\n Test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
