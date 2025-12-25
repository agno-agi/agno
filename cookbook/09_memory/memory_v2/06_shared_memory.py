"""
Memory V2 Shared - Multiple Agents Share User Memory
=====================================================
This example shows how multiple agents can share the same user memory.
Information learned by one agent is available to all agents.

Different from single-agent examples, this shows how memory portability
enables consistent user experience across specialized agents.

Key concepts:
- Shared database: Multiple agents use the same SqliteDb instance
- Memory portability: User context transfers between specialized agents
- Consistent experience: User doesn't need to repeat themselves

Example prompts to try:
- Tell chat agent about yourself
- Ask research agent for recommendations
- Both agents know your preferences
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/shared_memory.db")

# ============================================================================
# User Configuration
# ============================================================================
user_id = "john_doe"

# ============================================================================
# Create the Agents
# ============================================================================
# Agent 1: Chat agent that learns about the user
chat_agent = Agent(
    name="Chat Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="You are a helpful assistant that chats with users",
    db=agent_db,
    update_memory_on_run=True,
    markdown=True,
)

# Agent 2: Research agent that uses user context for personalized research
research_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="You are a research assistant that helps users find information",
    tools=[DuckDuckGoTools(cache_results=True)],
    db=agent_db,
    update_memory_on_run=True,
    markdown=True,
)

# ============================================================================
# Run the Agents
# ============================================================================
if __name__ == "__main__":
    # Chat agent learns about the user
    chat_agent.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends.",
        user_id=user_id,
        stream=True,
    )

    chat_agent.print_response(
        "What are my hobbies?",
        user_id=user_id,
        stream=True,
    )

    # Research agent has access to the same memory
    research_agent.print_response(
        "I love quantum computing. What is the latest news on quantum computing?",
        user_id=user_id,
        stream=True,
    )

    # View shared memory
    print("\n" + "=" * 60)
    print("Shared User Memory")
    print("=" * 60)

    user = chat_agent.get_user_memory_v2(user_id)
    if user:
        print_json(json.dumps(user.to_dict()))

    # Verify both agents see the same memory
    user_from_research = research_agent.get_user_memory_v2(user_id)
    if user_from_research:
        print(
            "\nResearch agent sees same memory:", user_from_research.user_id == user_id
        )

# ============================================================================
# More Examples
# ============================================================================
"""
Use cases for shared memory:

1. Specialized agents:
   - Chat agent: casual conversation, learns preferences
   - Research agent: uses preferences for personalized search
   - Support agent: knows user history and context

2. Onboarding flow:
   - Onboarding agent: collects user info
   - All other agents: benefit from that info

3. Multi-channel:
   - Web agent, mobile agent, voice agent
   - All share the same user memory

The key is using the same database instance across agents.
"""
