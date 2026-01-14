import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
    instructions="Use the search tools and always use the latest information and data.",
    db=SqliteDb(db_file="tmp/dbs/async_tool_call_compression.db"),
    compress_tool_results=True,  # Enable tool call compression
)


async def main():
    await agent.aprint_response(
        """
        Use the search tools and always for the latest information and data.
        Research recent activities (last 3 months) for these AI companies:

        1. OpenAI - product launches, partnerships, pricing
        2. Anthropic - new features, enterprise deals, funding
        3. Google DeepMind - research breakthroughs, product releases
        4. Meta AI - open source releases, research papers
        
        For each, find specific actions with dates and numbers.""",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
