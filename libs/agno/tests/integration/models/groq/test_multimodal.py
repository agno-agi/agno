import pytest

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.groq import Groq


@pytest.mark.skip(reason="Error on Groq API")
def test_image_input():
    agent = Agent(model=Groq(id="meta-llama/llama-4-scout-17b-16e-instruct"), telemetry=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()
