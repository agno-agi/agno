from io import BytesIO

import requests
from PIL import Image as PILImage

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.models.google import Gemini


def test_image_input():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-exp"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "Tell me about this image.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()


def test_audio_input_bytes():
    # Fetch the audio file and convert it to a base64 encoded string
    url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
    response = requests.get(url)
    response.raise_for_status()
    wav_data = response.content

    # Provide the agent with the audio file and get result as text
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-exp"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )
    response = agent.run("What is in this audio?", audio=[Audio(content=wav_data, format="wav")])

    assert response.content is not None


def test_audio_input_url():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-exp"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "What is in this audio?",
        audio=[Audio(url="https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav")],
    )

    assert response.content is not None


def test_video_input_bytes():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-exp"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
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
            id="gemini-2.0-flash-exp-image-generation",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
        create_default_system_message=False,
        system_message=None,
    )

    agent.run("Make me an image of a cat in a tree.")

    images = agent.get_images()
    assert images is not None
    assert len(images) > 0
    assert images[0].content is not None

    image = PILImage.open(BytesIO(images[0].content))
    assert image.format in ["JPEG", "PNG"]


def test_image_generation_streaming():
    """Test streaming image generation"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.0-flash-exp-image-generation",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
        create_default_system_message=False,
        system_message=None,
    )

    response = agent.run("Make me an image of a cat in a tree.", stream=True)

    image_received = False
    for chunk in response:
        if chunk.images:
            image_received = True
            assert len(chunk.images) > 0
            assert chunk.images[0].content is not None

            image = PILImage.open(BytesIO(chunk.images[0].content))
            assert image.format in ["JPEG", "PNG"]

    assert image_received, "No image was received in the stream"


def test_image_editing():
    """Test image editing with a sample image"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.0-flash-exp-image-generation",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
        create_default_system_message=False,
        system_message=None,
    )

    sample_image_url = "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"

    agent.run("Can you add a rainbow over this bridge?", images=[Image(url=sample_image_url)])

    images = agent.get_images()
    assert images is not None
    assert len(images) > 0
    assert images[0].content is not None

    image = PILImage.open(BytesIO(images[0].content))
    assert image.format in ["JPEG", "PNG"]


def test_image_generation_with_detailed_prompt():
    """Test image generation with a detailed prompt"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.0-flash-exp-image-generation",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
        create_default_system_message=False,
        system_message=None,
    )

    detailed_prompt = """
    Create an image of a peaceful garden scene with:
    - A small wooden bench under a blooming cherry tree
    - Some butterflies flying around
    - A small stone path leading to the bench
    - Soft sunlight filtering through the branches
    """

    agent.run(detailed_prompt)

    images = agent.get_images()
    assert images is not None
    assert len(images) > 0
    assert images[0].content is not None

    image = PILImage.open(BytesIO(images[0].content))
    assert image.format in ["JPEG", "PNG"]


def test_combined_text_and_image_generation():
    """Test generating both text description and image"""
    agent = Agent(
        model=Gemini(
            id="gemini-2.0-flash-exp-image-generation",
            response_modalities=["Text", "Image"],
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
        create_default_system_message=False,
        system_message=None,
    )

    response = agent.run("Create an image of a sunset over mountains and describe what you generated.")

    # Check text response
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0

    # Check image response
    images = agent.get_images()
    assert images is not None
    assert len(images) > 0
    assert images[0].content is not None
