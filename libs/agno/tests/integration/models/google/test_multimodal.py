from io import BytesIO

import pytest
import requests
from PIL import Image as PILImage

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.media import Audio, File, Image, Video
from agno.models.google import Gemini


def test_image_input(image_path):
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
    )

    response = agent.run(
        "Tell me about this image.",
        images=[Image(filepath=image_path)],
    )

    assert response.content is not None
    assert "golden" in response.content.lower()


def test_audio_input_bytes():
    # Fetch the audio file and convert it to a base64 encoded string
    url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
    response = requests.get(url)
    response.raise_for_status()
    wav_data = response.content

    # Provide the agent with the audio file and get result as text
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
    )
    response = agent.run("What is in this audio?", audio=[Audio(content=wav_data, format="wav")])

    assert response.content is not None


def test_audio_input_url():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
    )

    response = agent.run(
        "What is in this audio?",
        audio=[Audio(url="https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav")],
    )

    assert response.content is not None


def test_video_input_bytes():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
    )

    url = "https://videos.pexels.com/video-files/5752729/5752729-uhd_2560_1440_30fps.mp4"

    # Download the video file from the URL as bytes
    response = requests.get(url)
    video_content = response.content

    response = agent.run(
        "Tell me about this video",
        videos=[Video(content=video_content)],
    )

    assert response.content is not None


def test_image_generation():
    """Test basic image generation capability"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.5-flash-image",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        build_context=False,
        system_message=None,
        db=InMemoryDb(),
    )

    response = agent.run("Make me an image of a cat in a tree.")

    # Check images directly from the response
    assert response.images is not None
    assert len(response.images) > 0

    image = PILImage.open(BytesIO(response.images[0].content))
    assert image.format in ["JPEG", "PNG"]


def test_image_generation_streaming():
    """Test streaming image generation"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.5-flash-image",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        build_context=False,
        system_message=None,
        db=InMemoryDb(),
    )

    response = agent.run("Make me an image of a cat in a tree.", stream=True)

    image_received = False
    for chunk in response:
        if hasattr(chunk, "image") and chunk.image:  # type: ignore
            image_received = True
            assert chunk.image is not None  # type: ignore

            image = PILImage.open(BytesIO(chunk.image.content))  # type: ignore
            assert image.format in ["JPEG", "PNG"]
            break

    assert image_received, "No image was received in the stream"


@pytest.mark.skip(reason="This test fails often on CI for Gemini")
def test_image_editing(image_path):
    """Test image editing with a sample image"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.5-flash-image",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        build_context=False,
        system_message=None,
        db=InMemoryDb(),
    )

    response = agent.run("Can you add a rainbow over this bridge?", images=[Image(filepath=image_path)])

    # Check images directly from the response
    assert response.images is not None
    assert len(response.images) > 0
    assert response.images[0].content is not None

    image = PILImage.open(BytesIO(response.images[0].content))
    assert image.format in ["JPEG", "PNG"]


def test_image_generation_with_detailed_prompt():
    """Test image generation with a detailed prompt"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.5-flash-image",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        build_context=False,
        system_message=None,
        db=InMemoryDb(),
    )

    detailed_prompt = """
    Create an image of a peaceful garden scene with:
    - A small wooden bench under a blooming cherry tree
    - Some butterflies flying around
    - A small stone path leading to the bench
    - Soft sunlight filtering through the branches
    """

    agent.run(detailed_prompt)

    # Use get_last_run_output instead of get_images
    run_response = agent.get_last_run_output()
    assert run_response is not None
    assert run_response.images is not None
    assert len(run_response.images) > 0
    assert run_response.images[0].content is not None

    # Handle base64 encoded image data
    image_content = run_response.images[0].content
    if isinstance(image_content, bytes):
        # Check if it's base64 encoded by trying to decode as UTF-8
        try:
            decoded_string = image_content.decode("utf-8")
            if decoded_string.startswith("iVBORw0KGgo") or decoded_string.startswith("/9j/"):
                import base64

                image_content = base64.b64decode(decoded_string)
        except (UnicodeDecodeError, ValueError):
            pass

    image = PILImage.open(BytesIO(image_content))
    assert image.format in ["JPEG", "PNG"]


def test_combined_text_and_image_generation():
    """Test generating both text description and image"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.5-flash-image",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        build_context=False,
        system_message=None,
        db=InMemoryDb(),
    )

    response = agent.run("Create an image of a sunset over mountains and describe what you generated.")

    # Check text response
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0

    # Check image response using get_last_run_output
    run_response = agent.get_last_run_output()
    assert run_response is not None
    assert run_response.images is not None
    assert len(run_response.images) > 0
    assert run_response.images[0].content is not None


def test_file_input_bytes():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
    )

    # Create a small text file as bytes
    file_content = b"This is a test document.\nIt contains some text for the model to analyze."

    response = agent.run(
        "What does this document say?",
        files=[File(content=file_content, mime_type="text/plain")],
    )

    assert response.content is not None
    assert "test document" in response.content.lower() or "text" in response.content.lower()


def test_file_input_with_text_prompt():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-001"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
    )

    # Create a PDF-like content (simple text for testing)
    file_content = b"Project Report\n\nQ1 Revenue: $100,000\nQ2 Revenue: $150,000\nGrowth: 50%"

    response = agent.run(
        "Summarize the revenue data from this file",
        files=[File(content=file_content, mime_type="text/plain")],
    )

    assert response.content is not None
    # Should be able to read and process the file content
    assert any(keyword in response.content.lower() for keyword in ["revenue", "100", "150", "growth"])
