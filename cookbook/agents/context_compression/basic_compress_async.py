"""
Async example of tool call compression without streaming.

This demonstrates how compression works seamlessly with async agent methods.
Tool results are compressed and stored with both original and compressed content.

Run: `python cookbook/agents/context_compression/basic_compress_async.py`
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.log import log_info


async def main():
    """Main async function to demonstrate compression with async agent."""

    # Create agent with compression enabled
    agent = Agent(
        name="Async Compression Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools()],
        compress_tool_calls=True,  # Enable compression (default threshold=3)
        markdown=True,
        db=SqliteDb(db_file="tmp/dbs/async_compression_test.db"),
        session_id="async_compression_test",
        add_history_to_context=True,
        instructions="Use the search tools for the latest information.",
        debug_mode=True,
    )

    log_info("=" * 80)
    log_info("Query 1: Research AI companies (will trigger tool calls)")
    log_info("=" * 80)

    # First query - will execute tools and potentially compress results
    response1 = await agent.arun(
        """
        Search for recent news about:
        1. OpenAI - latest announcements
        2. Anthropic - recent developments
        3. Google AI - new releases
        4. Meta AI - research updates
        
        For each company, provide specific dates and key facts.
        """
    )

    print("\n" + "=" * 80)
    log_info("Query 2: Follow-up question (will use compressed history)")
    log_info("=" * 80)

    # Second query - will load compressed history from first query
    response2 = await agent.arun("What were the most significant announcements?")

    print("\n" + "=" * 80)
    log_info("Query 3: Another follow-up")
    log_info("=" * 80)

    # Third query - more compressed history
    response3 = await agent.arun("Which company had the most activity?")

    print("\n\n" + "=" * 80)
    log_info("✅ Async compression test complete!")
    log_info("Check debug logs above to see:")
    log_info("  - Tool results being compressed")
    log_info("  - Compressed content sent to API")
    log_info("  - Space savings from compression")
    log_info("  - Both original and compressed content stored")
    log_info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
