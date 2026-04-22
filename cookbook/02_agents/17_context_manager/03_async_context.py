"""Use context items with async agents and variable substitution."""

import asyncio

from agno.agent import Agent
from agno.context.manager import ContextManager
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat


async def main():
    db = AsyncSqliteDb(db_file="tmp/context_async.db", context_table="context_items")
    context_manager = ContextManager(db=db)

    # Create context with variables
    async_template = """You are {role} specializing in {specialty}.\nProvide {style} responses with practical examples.\nAsk in the end if the user has any more questions."""

    await context_manager.acreate(
        name="async_template",
        content=async_template,
        description="Async context template",
    )

    # Use with async agent
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        system_message=await context_manager.aget(
            name="async_template",
            role="an async programming expert",
            specialty="Python asyncio",
            style="clear and practical",
        ),
    )
    print(agent.system_message)
    await agent.aprint_response(
        "Explain async/await in Python",
        markdown=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
