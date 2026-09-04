"""
Agent Protocol Client Example
==============================

Demonstrates using the Agno AgentProtocolClient to interact with an
AgentOS server running the Agent Protocol interface.

Prerequisites:
1. Install the ap_client SDK:
   pip install "git+https://github.com/langchain-ai/agent-protocol.git#subdirectory=client-python"

2. Start the Agent Protocol server:
   python server.py

   The server will run on http://localhost:7778
"""

import asyncio

from agno.client.agent_protocol import AgentProtocolClient

BASE_URL = "http://localhost:7778/ap"


async def main():
    client = AgentProtocolClient(base_url=BASE_URL)

    # ---- List available agents ----
    print("Listing agents...")
    agents = await client.alist_agents()
    for agent in agents:
        print(f"  - {agent.agent_id}: {agent.name} ({agent.description})")

    # ---- Stateless run (wait for result) ----
    print("\nRunning stateless query...")
    result = await client.acreate_run_wait(
        agent_id="research_agent",
        input={
            "messages": [
                {
                    "role": "user",
                    "content": "What are the main benefits of quantum computing?",
                }
            ]
        },
    )
    print(f"  Status: {result.run.status}")
    messages = result.values.get("messages", []) if result.values else []
    for msg in messages:
        if msg.get("type") == "ai":
            print(f"  Response: {msg['content'][:200]}...")

    # ---- Thread-based conversation ----
    print("\nCreating thread for multi-turn conversation...")
    thread = await client.acreate_thread(metadata={"topic": "quantum"})
    print(f"  Thread ID: {thread.thread_id}")

    # Get thread state
    fetched = await client.aget_thread(thread.thread_id)
    print(f"  Thread status: {fetched.status}")

    # ---- Store operations ----
    print("\nStoring data...")
    await client.aput_item(
        namespace=["demo", "notes"],
        key="quantum_summary",
        value={"topic": "quantum computing", "status": "researched"},
    )
    item = await client.aget_item(namespace=["demo", "notes"], key="quantum_summary")
    print(f"  Stored: {item.value}")

    # ---- Cleanup ----
    await client.adelete_item(namespace=["demo", "notes"], key="quantum_summary")
    await client.adelete_thread(thread.thread_id)
    print("\nDone. Cleaned up thread and store items.")


if __name__ == "__main__":
    asyncio.run(main())
