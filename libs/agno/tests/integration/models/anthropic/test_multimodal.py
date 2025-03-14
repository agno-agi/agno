from agno.agent.agent import Agent
from agno.media import File, Image
from agno.models.anthropic import Claude


def test_image_input():
    agent = Agent(model=Claude(id="claude-3-5-sonnet-20241022"), markdown=True, telemetry=False, monitoring=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


def test_file_upload():
    agent = Agent(
        model=Claude(id="claude-3-5-sonnet-20241022"),
        markdown=True,
    )

    response = agent.run(
        "Summarize the contents of the attached file.",
        files=[
            File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"),
        ],
    )
    assert response.content is not None
    assert response.citations is not None
