"""
Async full context compression example.

This example demonstrates async full context compression, which is useful for
web applications and other async environments where you need to maintain
conversation continuity while staying within token limits.

The compression happens asynchronously, making it efficient for high-throughput
applications.
"""

import asyncio

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# Create a compression manager with a token limit
compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=4000,  # Compress when context exceeds 4000 tokens
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    description="A research assistant that can search the web for information",
    instructions="Use the search tools to find the latest information. Be thorough and cite sources.",
    db=SqliteDb(db_file="tmp/dbs/async_full_compression.db"),
    compression_manager=compression_manager,
    add_history_to_context=True,
    num_history_runs=5,
)


async def main():
    # First research task
    await agent.aprint_response(
        "Research the latest developments in AI model reasoning capabilities. Focus on o1, Claude, and Gemini.",
        stream=True,
    )

    print("\n" + "=" * 50 + "\n")

    # Second research task - context may be compressed here
    await agent.aprint_response(
        "Now compare the pricing of these models for enterprise use.",
        stream=True,
    )

    print("\n" + "=" * 50 + "\n")

    # Third task - builds on previous context
    await agent.aprint_response(
        "Based on your research, which model would you recommend for a startup building a coding assistant?",
        stream=True,
    )

    # Show compression stats
    if compression_manager.stats:
        print("\nCompression Statistics:")
        for key, value in compression_manager.stats.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
