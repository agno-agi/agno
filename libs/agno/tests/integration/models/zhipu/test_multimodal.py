import pytest

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.zhipu import Zhipu


def test_image_input_url(image_path):
    """Test URL-like workflow: load image from file and send as bytes"""
    agent = Agent(model=Zhipu(id="glm-4.6v"), markdown=True, telemetry=False)

    # Read image as bytes (simulating downloaded URL image)
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = agent.run(
        "Tell me about this image.",
        images=[Image(content=image_bytes, format="png")],
    )

    assert response.content is not None
    assert response.status.value != "ERROR", f"API call failed: {response.content}"
    # The response should contain information about the image
    assert len(response.content) > 50


def test_image_input_bytes(image_path):
    agent = Agent(model=Zhipu(id="glm-4.6v"), telemetry=False)

    response = agent.run(
        "Tell me about this image.",
        images=[Image(filepath=image_path)],
    )

    assert response.content is not None
    assert "golden" in response.content.lower()
    assert "bridge" in response.content.lower()


@pytest.mark.asyncio
async def test_async_image_input_stream(image_path):
    agent = Agent(model=Zhipu(id="glm-4.6v"), markdown=True, telemetry=False)

    response_stream = agent.arun("Describe this image in detail.", images=[Image(filepath=image_path)], stream=True)

    responses = []
    async for chunk in response_stream:
        responses.append(chunk)
        # Note: Some chunks may have None content (control messages)
        # Only validate non-None content chunks

    assert len(responses) > 0

    # Collect all non-None content
    full_content = ""
    content_chunks = 0
    for r in responses:
        if r.content is not None:
            full_content += r.content
            content_chunks += 1

    # Verify we received actual content
    assert content_chunks > 0, "Should have at least some chunks with content"
    assert len(full_content) > 10, f"Full content should be substantial, got: {full_content}"


def test_image_with_text_context(image_path):
    """Test image with additional text context"""
    agent = Agent(model=Zhipu(id="glm-4.6v"), markdown=True, telemetry=False)

    response = agent.run(
        "I'm planning a trip to see this landmark. What should I know before visiting?",
        images=[Image(filepath=image_path)],
    )

    assert response.content is not None
    assert response.status.value != "ERROR", f"API call failed: {response.content}"
    # The response should contain travel advice related to the landmark
    assert len(response.content) > 50


def test_image_analysis_with_structured_output(image_path):
    """Test image analysis with structured output using glm-4.6v"""
    from pydantic import BaseModel, Field

    class ImageAnalysis(BaseModel):
        description: str = Field(..., description="Brief description of the image")
        main_objects: list = Field(..., description="List of main objects in the image")
        setting: str = Field(..., description="Setting of the image")

    agent = Agent(
        model=Zhipu(id="glm-4.6v"),  # Use glm-4.6v which supports structured outputs better
        output_schema=ImageAnalysis,
        use_json_mode=True,
        telemetry=False,
    )

    response = agent.run(
        "Analyze this image and provide: 1) a brief description, 2) list of main objects, 3) the setting.",
        images=[Image(filepath=image_path)],
    )

    assert response.content is not None
    assert response.status.value != "ERROR", f"API call failed: {response.content}"

    # Check if structured output worked, otherwise just verify we got content

    assert response.content.description is not None
    assert response.content.main_objects is not None
    assert response.content.setting is not None
