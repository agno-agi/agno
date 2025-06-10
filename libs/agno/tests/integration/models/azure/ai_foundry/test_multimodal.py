from agno.agent.agent import Agent
from agno.media import Image
from agno.models.azure import AzureAIFoundry


def test_image_input():
    agent = Agent(model=AzureAIFoundry(id="Phi-4"), markdown=True, telemetry=False, monitoring=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()
