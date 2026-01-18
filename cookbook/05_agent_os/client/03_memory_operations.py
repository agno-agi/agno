"""
Memory Operations with AgentOSClient

This example demonstrates how to manage user memories using
AgentOSClient.

Prerequisites:
1. Start an AgentOS server with an agent that has enable_user_memories=True
2. Run this script: python 03_memory_operations.py
"""

import asyncio

from agno.client import AgentOSClient


async def main():
    client = AgentOSClient(base_url="http://localhost:7777")
    user_id = "example-user"

    print("=" * 60)
    print("Memory Operations")
    print("=" * 60)

    # Create a memory
    print("\n1. Creating a memory...")
    memory = await client.create_memory(
        memory="User prefers dark mode for all applications",
        user_id=user_id,
        topics=["preferences", "ui"],
    )
    print(f"   Created memory: {memory.memory_id}")
    print(f"   Content: {memory.memory}")
    print(f"   Topics: {memory.topics}")

    # List memories for the user
    print("\n2. Listing memories...")
    memories = await client.list_memories(user_id=user_id)
    print(f"   Found {len(memories.data)} memories for user {user_id}")
    for mem in memories.data:
        print(f"   - {mem.memory_id}: {mem.memory[:50]}...")

    # Get a specific memory
    print(f"\n3. Getting memory {memory.memory_id}...")
    retrieved = await client.get_memory(memory.memory_id, user_id=user_id)
    print(f"   Memory: {retrieved.memory}")

    # Update the memory
    print("\n4. Updating memory...")
    updated = await client.update_memory(
        memory_id=memory.memory_id,
        memory="User strongly prefers dark mode for all applications and websites",
        user_id=user_id,
        topics=["preferences", "ui", "accessibility"],
    )
    print(f"   Updated memory: {updated.memory}")
    print(f"   Updated topics: {updated.topics}")

    # Get memory topics (optional - may fail if not supported)
    print("\n5. Getting all memory topics...")
    try:
        topics = await client.get_memory_topics()
        print(f"   Topics: {topics}")
    except Exception as e:
        print(f"   Skipped (endpoint may not be available): {type(e).__name__}")

    # Get user memory stats (optional - may fail if not supported)
    print("\n6. Getting user memory stats...")
    try:
        stats = await client.get_user_memory_stats()
        print(f"   Stats: {len(stats.data)} entries")
    except Exception as e:
        print(f"   Skipped (endpoint may not be available): {type(e).__name__}")

    # Delete the memory
    print(f"\n7. Deleting memory {memory.memory_id}...")
    await client.delete_memory(memory.memory_id, user_id=user_id)
    print("   Memory deleted")

    # Verify deletion
    print("\n8. Verifying deletion...")
    memories_after = await client.list_memories(user_id=user_id)
    print(f"   Remaining memories: {len(memories_after.data)}")


if __name__ == "__main__":
    asyncio.run(main())
