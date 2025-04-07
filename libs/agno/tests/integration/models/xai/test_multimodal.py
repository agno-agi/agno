from agno.agent import Agent
from agno.media import Image
from agno.models.xai import xAI
from agno.tools.duckduckgo import DuckDuckGoTools


def test_image_input():
    agent = Agent(
        model=xAI(id="grok-2-vision-latest"),
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
