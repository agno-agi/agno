"""Manage AgentOS sessions and user memories with the Python client.

The example creates a named agent session, runs in it, inspects its history,
and exercises create/read/update/delete memory calls.

Prerequisites: start ``_server.py`` and set OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/03_sessions_and_memory.py
Try: inspect the named session before the example cleans it up.
"""

import asyncio

from agno.client import AgentOSClient
from agno.db.base import SessionType

BASE_URL = "http://localhost:7778"
AGENT_ID = "assistant"
USER_ID = "python-client-user"


# ---------------------------------------------------------------------------
# Create the Client
# ---------------------------------------------------------------------------


async def manage_session_and_memory() -> None:
    """Exercise the session lifecycle and memory CRUD APIs."""
    client = AgentOSClient(base_url=BASE_URL)
    session_id: str | None = None
    memory_id: str | None = None

    try:
        session = await client.create_session(
            session_type=SessionType.AGENT,
            user_id=USER_ID,
            session_name="Python client session",
            agent_id=AGENT_ID,
        )
        session_id = session.session_id
        print(f"Created session: {session_id}")

        run = await client.run_agent(
            agent_id=AGENT_ID,
            message="Remember that this request belongs to our SDK tutorial.",
            session_id=session_id,
            user_id=USER_ID,
        )
        print(f"Created run: {run.run_id}")

        sessions = await client.get_sessions(
            session_type=SessionType.AGENT,
            component_id=AGENT_ID,
            user_id=USER_ID,
        )
        print(f"Sessions for user: {len(sessions.data)}")

        details = await client.get_session(
            session_id=session_id,
            session_type=SessionType.AGENT,
            user_id=USER_ID,
        )
        print(f"Session name: {details.session_name}")

        runs = await client.get_session_runs(
            session_id=session_id,
            session_type=SessionType.AGENT,
            user_id=USER_ID,
        )
        print(f"Runs in session: {len(runs)}")

        renamed = await client.rename_session(
            session_id=session_id,
            session_name="Renamed Python client session",
            session_type=SessionType.AGENT,
            user_id=USER_ID,
        )
        print(f"Renamed session: {renamed.session_name}")

        memory = await client.create_memory(
            memory="The user prefers concise SDK examples.",
            user_id=USER_ID,
            topics=["preferences", "sdk"],
        )
        memory_id = memory.memory_id
        print(f"Created memory: {memory_id}")

        memories = await client.list_memories(user_id=USER_ID)
        print(f"Memories for user: {len(memories.data)}")

        retrieved = await client.get_memory(memory_id, user_id=USER_ID)
        print(f"Retrieved memory: {retrieved.memory}")

        updated = await client.update_memory(
            memory_id=memory_id,
            memory="The user prefers concise, typed SDK examples.",
            user_id=USER_ID,
            topics=["preferences", "sdk", "typing"],
        )
        print(f"Updated memory: {updated.memory}")
    finally:
        if memory_id is not None:
            await client.delete_memory(memory_id, user_id=USER_ID)
            print(f"Deleted memory: {memory_id}")
        if session_id is not None:
            await client.delete_session(session_id, user_id=USER_ID)
            print(f"Deleted session: {session_id}")


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(manage_session_and_memory())
