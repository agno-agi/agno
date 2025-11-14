"""
Async example of tool call compression with streaming responses.

This demonstrates how compression works seamlessly with async streaming - tool results
are compressed between iterations and the next model call receives compressed content.

Run: `python cookbook/agents/context_compression/basic_compress_async_stream.py`
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.log import log_info


async def main():
    """Main async function to demonstrate compression with async streaming."""

    # Create agent with compression and streaming enabled
    agent = Agent(
        name="Async Streaming Compression Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools()],
        compress_tool_calls=True,  # Enable compression (default threshold=3)
        stream=True,  # Enable streaming
        markdown=True,
        db=SqliteDb(db_file="tmp/dbs/async_streaming_compression_test.db"),
        session_id="async_streaming_compression_test",
        add_history_to_context=True,
        instructions="Use the search tools for the latest information.",
        debug_mode=True,
    )

    log_info("=" * 80)
    log_info("Query 1: Research AI companies (will trigger tool calls)")
    log_info("=" * 80)

    # First query - will execute tools and potentially compress results
    await agent.aprint_response(
        """
        Search for recent news about:
        1. OpenAI - latest announcements
        2. Anthropic - recent developments
        3. Google AI - new releases
        4. Meta AI - research updates
        
        For each company, provide specific dates and key facts.
        """,
        show_full_reasoning=True,
    )

    print("\n\n" + "=" * 80)
    log_info("Query 2: Follow-up question (will use compressed history)")
    log_info("=" * 80)

    # Second query - will load compressed history from first query
    await agent.aprint_response(
        "What were the most significant announcements?",
        show_full_reasoning=True,
    )

    print("\n\n" + "=" * 80)
    log_info("Query 3: Another follow-up")
    log_info("=" * 80)

    # Third query - more compressed history
    await agent.aprint_response(
        "Which company had the most activity?",
        show_full_reasoning=True,
    )

    await agent.aprint_response(
        "What is the latest news about OpenAI? WHat about Meta AI? What about AGNO?",
        show_full_reasoning=True,
    )

    await agent.aprint_response(
        "What is the latest news about Anthropic?",
        show_full_reasoning=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
