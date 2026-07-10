"""
E2E test for nested team AGUI message boundaries (issue #6141).

Tests that when a nested team runs (ParentTeam → SubTeam → Agent),
each source gets its own TEXT_MESSAGE_START with distinct messageId and name.
"""

import asyncio
import json
import time
from threading import Thread

import httpx
import uvicorn
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team

model = OpenAIResponses(id="gpt-4.1-mini")

# Nested team structure: ParentTeam → SubTeam → Agent
inner_agent = Agent(
    name="NumberPicker",
    role="Number picker",
    instructions="Pick a random number between 1-100 and respond with just the number.",
    model=model,
)

sub_team = Team(
    name="SubTeam",
    role="Sub team",
    members=[inner_agent],
    instructions="When asked for a number, delegate to NumberPicker and report their result.",
    model=model,
    stream_member_events=True,
)

parent_team = Team(
    name="ParentTeam",
    role="Parent team coordinator",
    members=[sub_team],
    instructions="When asked for a number, delegate to SubTeam and summarize.",
    model=model,
    stream_member_events=True,
)

agent_os = AgentOS(
    teams=[parent_team],
    interfaces=[
        AGUI(team=parent_team, prefix="/team"),
    ],
)

app = agent_os.get_app()


async def test_nested_team_boundaries():
    """Test that nested team responses have separate message boundaries."""

    # Start server in background
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    thread = Thread(target=server.run)
    thread.daemon = True
    thread.start()

    # Wait for server to start
    time.sleep(2)

    request_body = {
        "threadId": "test-thread-1",
        "runId": "test-run-1",
        "state": {},
        "messages": [
            {
                "id": "msg-1",
                "role": "user",
                "content": "Pick a number for me",
            }
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    events = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "http://127.0.0.1:8765/team/agui",
            json=request_body,
            headers={"Accept": "text/event-stream"},
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        event = json.loads(line[6:])
                        events.append(event)
                    except json.JSONDecodeError:
                        pass

    # Analyze events
    print("\n" + "=" * 60)
    print("EVENT ANALYSIS")
    print("=" * 60)

    starts = [e for e in events if e.get("type") == "TEXT_MESSAGE_START"]
    ends = [e for e in events if e.get("type") == "TEXT_MESSAGE_END"]
    contents = [e for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"]

    print(f"\nTEXT_MESSAGE_START events: {len(starts)}")
    print(f"TEXT_MESSAGE_END events: {len(ends)}")
    print(f"TEXT_MESSAGE_CONTENT events: {len(contents)}")

    print("\n--- TEXT_MESSAGE_START details ---")
    message_ids = set()
    names = []
    for i, start in enumerate(starts):
        msg_id = start.get("messageId", "")[:8]
        name = start.get("name", "<none>")
        message_ids.add(start.get("messageId"))
        names.append(name)
        print(f"  [{i + 1}] messageId={msg_id}... name={name}")

    print(f"\nUnique messageIds: {len(message_ids)}")
    print(f"Names found: {names}")

    # Verify the fix
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # We should have multiple message starts (one per source)
    if len(starts) > 1:
        print("✓ Multiple TEXT_MESSAGE_START events emitted")
    else:
        print("✗ Only 1 TEXT_MESSAGE_START (bug not fixed)")

    # Each should have a unique messageId
    if len(message_ids) == len(starts):
        print("✓ Each message has a unique messageId")
    else:
        print("✗ Some messages share messageId (bug not fixed)")

    # At least some should have the name field populated
    named_starts = [n for n in names if n != "<none>"]
    if named_starts:
        print(f"✓ Messages have source names: {named_starts}")
    else:
        print("✗ No name fields populated")

    # Balanced START/END
    if len(starts) == len(ends):
        print(f"✓ Balanced {len(starts)} STARTs and {len(ends)} ENDs")
    else:
        print(f"✗ Unbalanced: {len(starts)} STARTs vs {len(ends)} ENDs")

    print("\n" + "=" * 60)

    # Request server shutdown
    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(test_nested_team_boundaries())
