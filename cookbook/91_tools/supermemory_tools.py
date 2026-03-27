"""
This example demonstrates how to use the Supermemory toolkit with Agno agents.

Supermemory provides long-term memory infrastructure for AI agents with automatic
fact extraction, user profiles, and semantic search.

To get started, export your Supermemory API key:

export SUPERMEMORY_API_KEY=<your-supermemory-api-key>

You can get your API key from https://console.supermemory.ai
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.supermemory import SupermemoryTools

USER_ID = "agno_user"
SESSION_ID = "agno_session"
MODEL = OpenAIChat(id="gpt-5")

# Example 1: Enable all Supermemory functions
agent_all = Agent(
    model=MODEL,
    tools=[
        SupermemoryTools(
            all=True,
        )
    ],
    user_id=USER_ID,
    session_id=SESSION_ID,
    markdown=True,
    instructions=dedent(
        """
        You have full access to memory operations. You can store memories, search them,
        view the user profile, and forget memories. Proactively store important facts
        about the user for future reference.
        """
    ),
)

# Example 2: Enable specific functions only (add + search)
agent_specific = Agent(
    model=MODEL,
    tools=[
        SupermemoryTools(
            enable_add_memory=True,
            enable_search_memory=True,
            enable_get_user_profile=False,
            enable_forget_memory=False,
        )
    ],
    user_id=USER_ID,
    session_id=SESSION_ID,
    markdown=True,
    instructions=dedent(
        """
        You can add new memories and search existing ones.
        Focus on learning and recalling information about the user.
        """
    ),
)

# Example 3: Full-featured agent with custom search settings
agent = Agent(
    model=MODEL,
    tools=[
        SupermemoryTools(
            enable_add_memory=True,
            enable_search_memory=True,
            enable_get_user_profile=True,
            enable_forget_memory=True,
            search_limit=10,
            threshold=0.6,
        )
    ],
    user_id=USER_ID,
    session_id=SESSION_ID,
    markdown=True,
    instructions=dedent(
        """
        You have an evolving memory of this user. Proactively capture new personal details,
        preferences, plans, and relevant context the user shares, and naturally bring them up
        in later conversation. Before answering questions about past details, search your memory
        and check the user profile for context. Keep your memory concise: store only meaningful
        information that enhances long-term dialogue.
        """
    ),
)

# Example usage with all functions enabled
print("=== Example 1: Using all Supermemory functions ===")
agent_all.print_response("I live in NYC and work as a software engineer")
agent_all.print_response("What do you know about me?")

# Example usage with specific functions only
print("\n=== Example 2: Using specific functions (add + search only) ===")
agent_specific.print_response("I love Italian food, especially pasta")
agent_specific.print_response("What do you remember about my food preferences?")

# Example usage with full configuration
print("\n=== Example 3: Full-featured agent ===")
agent.print_response("I live in NYC")
agent.print_response("I'm planning a trip to Tokyo next month")
agent.print_response("What's my profile look like?")
