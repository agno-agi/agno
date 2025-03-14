from agno.agent.agent import Agent
from agno.media import Image
from agno.models.aws.claude import Claude


def test_image_input():
    agent = Agent(
        model=Claude(id="anthropic.claude-3-5-sonnet-20240620-v1:0"), markdown=True, telemetry=False, monitoring=False
    )

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()
