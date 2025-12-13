"""Long-Running Session with Context Compression

This example demonstrates how to use context compression for long-running
conversational sessions. As users interact with an agent over many turns,
the conversation history can exceed token limits. Context compression
automatically summarizes older interactions while preserving key facts.

Key features:
- Works with persistent database storage (SQLite or PostgreSQL)
- Compresses when loading large history from previous sessions
- Preserves user preferences and important context across compressions
- Enables unlimited conversation length within token constraints

When to use this pattern:
- Chatbots with long conversation histories
- Personal assistants that remember user preferences
- Multi-session interactions that build on previous context
- Any agent where users return over multiple sessions

Dependencies: `pip install openai agno`
"""

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# Create a compression manager for session history
# This triggers when the accumulated history exceeds the token limit
compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=8000,  # Lower limit for conversational agents
)

# Database for persistent session storage
db = SqliteDb(db_file="tmp/dbs/session_compression.db")

# Create the agent with compression enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools(verify_ssl=False)],
    instructions=[
        "You are a helpful personal assistant.",
        "Remember user preferences and past conversations.",
        "When asked about previous interactions, refer to the context.",
        "Be friendly and conversational.",
    ],
    db=db,
    # Enable compression for managing session history
    compression_manager=compression_manager,
    # Load history from previous sessions
    add_history_to_context=True,
    # Load more history runs - compression will manage the size
    num_history_runs=10,
    markdown=True,
    debug_mode=True,
)

if __name__ == "__main__":
    # Simulate a multi-turn conversation that builds context

    print("=" * 60)
    print("Turn 1: User introduction")
    print("=" * 60)
    agent.print_response(
        "Hi! My name is Alex and I work as a software engineer at a startup. I'm interested in AI and machine learning.",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Turn 2: Preference sharing")
    print("=" * 60)
    agent.print_response(
        "I prefer Python for most of my projects, and I use PyTorch for ML work. Can you remember this?",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Turn 3: Research request with tools")
    print("=" * 60)
    agent.print_response(
        "Search for the latest developments in transformer architectures for 2024.",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Turn 4: Follow-up question")
    print("=" * 60)
    agent.print_response(
        "Based on what you found, which of these developments would be most relevant for someone with my background?",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Turn 5: Another research request")
    print("=" * 60)
    agent.print_response(
        "Now search for PyTorch tutorials on implementing these new architectures.",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Turn 6: Memory test")
    print("=" * 60)
    agent.print_response(
        "What do you remember about me and my preferences?",
        stream=True,
    )

    # Show compression statistics
    if compression_manager.stats:
        print("\n" + "=" * 60)
        print("Compression Statistics:")
        print("=" * 60)
        for key, value in compression_manager.stats.items():
            print(f"  {key}: {value}")
