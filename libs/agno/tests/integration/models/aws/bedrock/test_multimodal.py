import tempfile
from pathlib import Path

import pytest

from agno.agent.agent import Agent
from agno.media import File, Image
from agno.models.aws import AwsBedrock
from agno.utils.media import download_file


@pytest.mark.asyncio
async def test_async_image_input_bytes():
    """Test async image input using bytes with Amazon Nova Pro model.

    Only bytes input is supported for multimodal models.
    """
    agent = Agent(model=AwsBedrock(id="amazon.nova-pro-v1:0"), markdown=True, telemetry=False)

    image_path = Path(__file__).parent.parent.parent.joinpath("resources/sample_image.jpg")

    image_bytes = image_path.read_bytes()

    response = await agent.arun(
        "Tell me about this image.",
        images=[Image(content=image_bytes, format="jpeg")],
    )

    assert "bridge" in response.content.lower()


@pytest.mark.asyncio
async def test_async_image_input_stream():
    """Test async image input with streaming using Amazon Nova Pro model."""
    agent = Agent(model=AwsBedrock(id="amazon.nova-pro-v1:0"), markdown=True, telemetry=False)

    image_path = Path(__file__).parent.parent.parent.joinpath("resources/sample_image.jpg")
    image_bytes = image_path.read_bytes()

    full_response_content = ""
    async for response in agent.arun(
        "Describe this image in detail.", images=[Image(content=image_bytes, format="jpeg")], stream=True
    ):
        full_response_content += response.content or ""

    assert len(full_response_content) > 0
    assert "bridge" in full_response_content.lower()


@pytest.mark.asyncio
async def test_async_multiple_images():
    """Test async processing of multiple images."""
    agent = Agent(model=AwsBedrock(id="amazon.nova-pro-v1:0"), markdown=True, telemetry=False)

    image_path = Path(__file__).parent.parent.parent.joinpath("resources/sample_image.jpg")
    image_bytes = image_path.read_bytes()

    response = await agent.arun(
        "Compare these two images and tell me what you see.",
        images=[Image(content=image_bytes, format="jpeg"), Image(content=image_bytes, format="jpeg")],
    )

    assert response.content is not None
    assert len(response.content) > 0


def test_pdf_file_input_from_url():
    """
    Test PDF file input by downloading from URL
    """
    agent = Agent(model=AwsBedrock(id="amazon.nova-pro-v1:0"), markdown=True, telemetry=False)

    # Download PDF from URL to temporary file
    with tempfile.NamedTemporaryFile(suffix=".pdf") as temp_file:
        download_file("https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", temp_file.name)

        # Read as bytes (required for AWS Bedrock)
        pdf_bytes = Path(temp_file.name).read_bytes()

        response = agent.run(
            "What type of document is this? Give me a brief summary.",
            files=[File(content=pdf_bytes, format="pdf", name="Thai Recipes")],
        )

        assert response.content is not None
        assert len(response.content) > 0
        # Should mention recipes or Thai food
        content_lower = response.content.lower()
        assert any(keyword in content_lower for keyword in ["recipe", "thai", "food", "cooking", "ingredient"])
