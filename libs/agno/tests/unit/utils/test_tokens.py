import pytest

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.utils.tokens import (
    count_audio_tokens,
    count_file_tokens,
    count_image_tokens,
    count_schema_tokens,
    count_text_tokens,
    count_tokens,
    count_video_tokens,
)


def test_count_text_tokens_basic():
    result = count_text_tokens("Hello world")
    assert isinstance(result, int)
    assert result > 0
    assert result == 2


def test_count_text_tokens_empty_string():
    result = count_text_tokens("")
    assert result == 0


def test_count_text_tokens_multiple_words():
    text = "The quick brown fox jumps over the lazy dog"
    result = count_text_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_text_tokens_long_text():
    text = " ".join(["word"] * 100)
    result = count_text_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_text_tokens_special_characters():
    text = "Hello! How are you? I'm fine, thanks."
    result = count_text_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_text_tokens_unicode():
    text = "Hello 世界"
    result = count_text_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_text_tokens_different_lengths():
    short_text = "Hello"
    long_text = "Hello " * 10

    short_count = count_text_tokens(short_text)
    long_count = count_text_tokens(long_text)

    assert long_count >= short_count


def test_count_image_tokens_low_detail():
    image = Image(url="https://example.com/image.jpg", detail="low")
    result = count_image_tokens(image)
    assert result == 85  # Low detail is always 85 tokens


def test_count_image_tokens_high_detail_default():
    image = Image(url="https://example.com/image.jpg", detail="high")
    result = count_image_tokens(image)
    # Default 1024x1024 = 2x2 tiles = 4 tiles
    # 85 + (170 * 4) = 765
    assert result == 765


def test_count_image_tokens_auto_detail():
    image = Image(url="https://example.com/image.jpg", detail="auto")
    result = count_image_tokens(image)
    assert result == 765  # Same as high detail with default dimensions


def test_count_image_tokens_no_detail():
    image = Image(url="https://example.com/image.jpg")
    result = count_image_tokens(image)
    assert result == 765


def test_count_audio_tokens_basic():
    audio = Audio(url="https://example.com/audio.mp3", duration=10.0)
    result = count_audio_tokens(audio)
    # 10 seconds * 25 tokens/second = 250 tokens
    assert result == 250


def test_count_audio_tokens_zero_duration():
    audio = Audio(url="https://example.com/audio.mp3", duration=0)
    result = count_audio_tokens(audio)
    assert result == 0


def test_count_audio_tokens_long_audio():
    audio = Audio(url="https://example.com/audio.mp3", duration=60.0)
    result = count_audio_tokens(audio)
    # 60 seconds * 25 tokens/second = 1500 tokens
    assert result == 1500


# --- Video Token Tests ---


def test_count_video_tokens_basic():
    video = Video(url="https://example.com/video.mp4", duration=5.0, fps=1.0)
    result = count_video_tokens(video)
    # Default 512x512 = 1x1 tile = 1 tile per frame
    # tokens_per_frame = 85 + (170 * 1) = 255
    # 5 frames * 255 = 1275 tokens
    assert result == 1275


def test_count_video_tokens_no_duration():
    video = Video(url="https://example.com/video.mp4")
    result = count_video_tokens(video)
    assert result == 0


def test_count_video_tokens_with_dimensions():
    video = Video(
        url="https://example.com/video.mp4",
        duration=2.0,
        fps=1.0,
        width=1024,
        height=1024,
    )
    result = count_video_tokens(video)
    assert result == 1530


# --- File Token Tests ---
def test_count_file_tokens_text_file():
    file = File(content="Hello world! " * 100, format="txt")
    result = count_file_tokens(file)
    content_size = len("Hello world! " * 100)
    expected = content_size // 4
    assert result == expected


def test_count_file_tokens_binary_file():
    file = File(content=b"binary content " * 100, format="pdf")
    result = count_file_tokens(file)
    content_size = len(b"binary content " * 100)
    expected = content_size // 40
    assert result == expected


def test_count_file_tokens_url_without_size():
    file = File(url="https://example.com/nonexistent.txt", format="txt")
    result = count_file_tokens(file)
    assert result == 0


def test_count_tokens_simple_message():
    messages = [Message(role="user", content="Hello world")]
    result = count_tokens(messages)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_with_images():
    image = Image(url="https://example.com/image.jpg", detail="low")
    messages = [Message(role="user", content="What is in this image?", images=[image])]
    result = count_tokens(messages)
    # Should include text tokens + 85 for low detail image
    assert result > 85


def test_count_tokens_with_content_list_image_url_low():
    messages = [
        Message(
            role="user",
            content=[
                {"type": "text", "text": "What is in this image?"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg", "detail": "low"}},
            ],
        )
    ]
    result = count_tokens(messages)
    assert result >= 85
    # Ensure image tokens are counted in addition to text
    assert result > count_tokens([Message(role="user", content="What is in this image?")])


def test_count_tokens_with_audio():
    audio = Audio(url="https://example.com/audio.mp3", duration=10.0)
    messages = [Message(role="user", content="Transcribe this audio", audio=[audio])]
    result = count_tokens(messages)
    # Should include text tokens + 250 for 10s audio
    assert result > 250


def test_count_tokens_with_content_list_image_url_high_detail_default_dims():
    messages = [
        Message(
            role="user",
            content=[
                {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
            ],
        )
    ]
    result = count_tokens(messages)
    # Default dimensions (1024x1024) with auto/high detail -> 765 tokens for the image
    assert result >= 765


def test_count_tokens_multiple_messages():
    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi there! How can I help you?"),
        Message(role="user", content="What is 2 + 2?"),
    ]
    result = count_tokens(messages)
    assert isinstance(result, int)
    assert result > 10  # Multiple messages should have meaningful token count


def test_count_tokens_multimodal_message():
    image1 = Image(url="https://example.com/img1.jpg", detail="low")
    image2 = Image(url="https://example.com/img2.jpg", detail="low")
    audio = Audio(url="https://example.com/audio.mp3", duration=10.0)
    video = Video(url="https://example.com/video.mp4", duration=2.0, fps=1.0)
    file = File(content="x" * 400, format="txt")

    # Long text content
    long_text = "This is a detailed description. " * 50

    messages = [
        Message(
            role="user",
            content=long_text,
            images=[image1, image2],
            audio=[audio],
            videos=[video],
            files=[file],
        )
    ]

    result = count_tokens(messages)

    expected_media_tokens = 170 + 250 + 510 + 100

    assert result > expected_media_tokens
    assert result > 1000


def test_count_tokens_conversation_with_media():
    image = Image(url="https://example.com/photo.jpg", detail="low")
    audio = Audio(url="https://example.com/voice.mp3", duration=5.0)

    messages = [
        Message(role="system", content="You are a helpful assistant that can analyze images and audio."),
        Message(role="user", content="What do you see in this image?", images=[image]),
        Message(role="assistant", content="I can see a beautiful landscape with mountains."),
        Message(role="user", content="Now listen to this audio and describe it.", audio=[audio]),
        Message(role="assistant", content="The audio contains background music with nature sounds."),
    ]

    result = count_tokens(messages)

    assert result > 210
    assert result > 250


@pytest.mark.asyncio
async def test_model_acount_tokens():
    """Test async token counting on Model base class."""
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="Hello world")]

    sync_count = model.count_tokens(messages)
    async_count = await model.acount_tokens(messages)

    assert sync_count == async_count
    assert sync_count > 0


@pytest.mark.asyncio
async def test_model_acount_tokens_with_tools():
    """Test async token counting with tools."""
    from agno.models.openai import OpenAIChat
    from agno.tools.function import Function

    model = OpenAIChat(id="gpt-4o")
    messages = [Message(role="user", content="What is the weather?")]

    def get_weather(location: str) -> str:
        """Get weather for a location."""
        return f"Weather in {location}"

    tools = [Function.from_callable(get_weather)]

    sync_count = model.count_tokens(messages, tools)
    async_count = await model.acount_tokens(messages, tools)

    assert sync_count == async_count
    assert sync_count > 0


def test_count_schema_tokens_pydantic():
    """Test schema token counting with Pydantic model."""
    from pydantic import BaseModel

    class SimpleSchema(BaseModel):
        answer: str
        score: float

    tokens = count_schema_tokens(SimpleSchema, "gpt-4o-mini")
    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens < 100  # Reasonable range for simple schema


def test_count_schema_tokens_complex():
    """Test schema token counting with more complex schema."""
    from typing import List

    from pydantic import BaseModel, Field

    class ComplexSchema(BaseModel):
        title: str = Field(..., description="Title of the item")
        description: str = Field(..., description="Detailed description")
        score: int = Field(..., description="Score from 1-10")
        tags: List[str] = Field(default_factory=list, description="List of tags")

    tokens = count_schema_tokens(ComplexSchema, "gpt-4o-mini")
    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens > 50  # Complex schema should have more tokens


def test_count_schema_tokens_dict():
    """Test schema token counting with dict schema."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name", "age"],
    }

    tokens = count_schema_tokens(schema, "gpt-4o-mini")
    assert isinstance(tokens, int)
    assert tokens > 0


def test_count_schema_tokens_none():
    """Test schema token counting with None."""
    tokens = count_schema_tokens(None, "gpt-4o-mini")
    assert tokens == 0


def test_count_tokens_with_schema():
    """Test count_tokens includes schema tokens."""
    from pydantic import BaseModel

    class SimpleSchema(BaseModel):
        answer: str

    messages = [Message(role="user", content="Hello")]

    # Count without schema
    tokens_no_schema = count_tokens(messages, model_id="gpt-4o-mini")

    # Count with schema
    tokens_with_schema = count_tokens(messages, model_id="gpt-4o-mini", output_schema=SimpleSchema)

    # Schema should add tokens
    assert tokens_with_schema > tokens_no_schema


def test_model_count_tokens_with_schema():
    """Test model.count_tokens includes schema tokens."""
    from pydantic import BaseModel

    from agno.models.openai import OpenAIChat

    class SimpleSchema(BaseModel):
        answer: str

    model = OpenAIChat(id="gpt-4o-mini")
    messages = [Message(role="user", content="Hello")]

    # Count without schema
    tokens_no_schema = model.count_tokens(messages)

    # Count with schema
    tokens_with_schema = model.count_tokens(messages, output_schema=SimpleSchema)

    # Schema should add tokens
    assert tokens_with_schema > tokens_no_schema


@pytest.mark.asyncio
async def test_model_acount_tokens_with_schema():
    """Test model.acount_tokens includes schema tokens."""
    from pydantic import BaseModel

    from agno.models.openai import OpenAIChat

    class SimpleSchema(BaseModel):
        answer: str

    model = OpenAIChat(id="gpt-4o-mini")
    messages = [Message(role="user", content="Hello")]

    # Count without schema
    tokens_no_schema = await model.acount_tokens(messages)

    # Count with schema
    tokens_with_schema = await model.acount_tokens(messages, output_schema=SimpleSchema)

    # Schema should add tokens
    assert tokens_with_schema > tokens_no_schema
