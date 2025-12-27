"""
Session Management with AgentOSClient

This example demonstrates how to manage sessions using AgentOSClient.

Prerequisites:
1. Start an AgentOS server with an agent
2. Run this script: python 04_session_management.py
"""

import asyncio

from agno.client import AgentOSClient


async def main():
    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available agents
    config = await client.aget_config()
    if not config.agents:
        print("No agents available")
        return

    agent_id = config.agents[0].id
    user_id = "example-user"

    print("=" * 60)
    print("Session Management")
    print("=" * 60)

    # Create a session
    print("\n1. Creating a session...")
    session = await client.create_session(
        agent_id=agent_id,
        user_id=user_id,
        session_name="My Test Session",
    )
    print(f"   Session ID: {session.session_id}")
    print(f"   Session Name: {session.session_name}")

    # List sessions
    print("\n2. Listing sessions...")
    sessions = await client.get_sessions(user_id=user_id)
    print(f"   Found {len(sessions.data)} sessions")
    for sess in sessions.data[:5]:  # Show first 5
        print(f"   - {sess.session_id}: {sess.session_name or 'Unnamed'}")

    # Get session details
    print(f"\n3. Getting session {session.session_id}...")
    details = await client.get_session(session.session_id)
    print(f"   Agent ID: {details.agent_id}")
    print(f"   User ID: {details.user_id}")
    print(
        f"   Runs: {len(details.runs) if hasattr(details, 'runs') and details.runs else 0}"
    )

    # Run some messages in the session
    print("\n4. Running messages in session...")
    await client.run_agent(
        agent_id=agent_id,
        message="Hello!",
        session_id=session.session_id,
    )
    await client.run_agent(
        agent_id=agent_id,
        message="How are you?",
        session_id=session.session_id,
    )

    # Get session runs
    print("\n5. Getting session runs...")
    runs = await client.get_session_runs(session_id=session.session_id)
    print(f"   Found {len(runs)} runs in session")
    for run in runs:
        content_preview = (
            (run.content[:50] + "...")
            if run.content and len(str(run.content)) > 50
            else run.content
        )
        print(f"   - {run.run_id}: {content_preview}")

    # Rename session
    print("\n6. Renaming session...")
    renamed = await client.rename_session(
        session_id=session.session_id,
        session_name="Renamed Test Session",
    )
    print(f"   New name: {renamed.session_name}")

    # Delete session
    print(f"\n7. Deleting session {session.session_id}...")
    await client.delete_session(session.session_id)
    print("   Session deleted")


if __name__ == "__main__":
    asyncio.run(main())
