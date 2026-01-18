import asyncio

from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=DashScope(id="qwen-vl-plus"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)


async def main():
    await agent.aprint_response(
        "What do you see in this image? Provide a detailed description and search for related information.",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1200px-Cat03.jpg"
            )
        ],
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
