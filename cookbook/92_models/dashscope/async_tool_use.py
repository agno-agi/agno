import asyncio

from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=DashScope(id="qwen-plus"),
    tools=[WebSearchTools()],
    markdown=True,
)


async def main():
    await agent.aprint_response(
        "What's the latest news about artificial intelligence?", stream=True
    )


if __name__ == "__main__":
    asyncio.run(main())
