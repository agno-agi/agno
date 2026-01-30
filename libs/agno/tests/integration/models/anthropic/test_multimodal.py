from agno.agent.agent import Agent
from agno.media import File, Image
from agno.models.anthropic import Claude


def test_image_input(image_path):
    agent = Agent(model=Claude(id="claude-sonnet-4-20250514"), markdown=True, telemetry=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(filepath=image_path)],
    )

    assert response.content is not None
    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


def test_file_upload():
    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),
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
