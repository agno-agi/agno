import pytest

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.utils.tokens import (
    _format_type,
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


def test_format_type_numeric_enum_unquoted():
    """Numeric enums must become numeric literal unions, not quoted strings."""
    assert _format_type({"type": "integer", "enum": [1, 2, 3]}, 0) == "1 | 2 | 3"
    assert _format_type({"type": "number", "enum": [1.5, 2.5]}, 0) == "1.5 | 2.5"
    # String enums are unchanged (still quoted literals).
    assert _format_type({"type": "string", "enum": ["low", "high"]}, 0) == '"low" | "high"'


def test_format_type_untyped_enum_renders_union():
    """Untyped enums (e.g. mixed-type Literals) must become a literal union, not 'any'."""
    assert _format_type({"enum": [1, "auto"]}, 0) == '1 | "auto"'
    assert _format_type({"enum": [1, 2]}, 0) == "1 | 2"
    # An unknown type with no enum still falls back to "any".
    assert _format_type({"type": "weird"}, 0) == "any"


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


# =============================================================================
# Tokenizer selection
# =============================================================================
# count_text_tokens() falls back to OpenAI's encoding for any model id it does not
# recognise. That fallback is an estimate, and token-based thresholds such as
# CompressionManager's compress_token_limit are evaluated against it, so which
# tokenizer a model resolves to is asserted here rather than left implicit.

# Provider defaults whose token counts are estimates because no tokenizer for the family
# can be loaded locally. Each entry is a deliberate choice, not an oversight: a newly added
# provider fails test_provider_default_ids_have_a_known_tokenizer until it is mapped in
# HF_TOKENIZER_PATTERNS or listed here.
ESTIMATED_PROVIDER_DEFAULTS = {
    # Anthropic and Google families. Claude, Gemini and Bedrock override Model.count_tokens()
    # with a provider API call, so their real counts do not come from this path.
    "claude-sonnet-4-5-20250929": "no offline Anthropic tokenizer",
    "claude-sonnet-4-5": "no offline Anthropic tokenizer",
    "claude-sonnet-4@20250514": "no offline Anthropic tokenizer",
    "claude-opus-5": "no offline Anthropic tokenizer",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0": "no offline Anthropic tokenizer",
    "gemini-3.7-flash": "no offline Gemini tokenizer",
    # Families with no publicly downloadable tokenizer
    "mistral-large-latest": "no offline Mistral tokenizer",
    "mistral.mistral-small-2402-v1:0": "no offline Mistral tokenizer",
    "deepseek-v4-flash": "no offline DeepSeek tokenizer",
    "qwen-plus": "no offline Qwen tokenizer",
    "qwen2.5-7b-instruct-1m": "no offline Qwen tokenizer",
    "qwen3:0.6b-q4_K_M": "no offline Qwen tokenizer",
    "Qwen/QwQ-32B": "no offline Qwen tokenizer",
    "grok-4-1-fast-non-reasoning-latest": "no offline xAI tokenizer",
    "grok-4.1-fast-non-reasoning": "no offline xAI tokenizer",
    "kimi-k3": "no offline Moonshot tokenizer",
    "MiniMax-M3": "no offline MiniMax tokenizer",
    "MiniMaxAI/MiniMax-M2.7": "no offline MiniMax tokenizer",
    "internlm2.5-latest": "no offline InternLM tokenizer",
    "mimo-v2.5-pro": "no offline Xiaomi tokenizer",
    "mercury-2": "no offline Inception tokenizer",
    "sonar": "no offline Perplexity tokenizer",
    "v0-1.0-md": "no offline Vercel tokenizer",
    "ibm/granite-20b-code-instruct": "no offline Granite tokenizer",
    "Llama-4-Maverick-17B-128E-Instruct-FP8": "no offline Llama-4 tokenizer",
    "gpt-oss:20b": "Ollama tag syntax is not a tiktoken model id",
    # Placeholders: the real model id is supplied at runtime
    "not-provided": "placeholder id",
    "not-set": "placeholder id",
    "trustedrouter/zdr": "router alias, resolved upstream",
}


def _provider_default_model_ids():
    """Default `id` of every Model subclass under agno/models, read statically.

    Parsed rather than imported so the check does not require every provider SDK. Returns
    (defaults, unresolved): `unresolved` holds `id` declarations whose default this parser
    could not reduce to a string, so an unreadable declaration fails the coverage test
    instead of quietly dropping out of it.
    """
    import ast
    from pathlib import Path

    import agno.models

    root = Path(agno.models.__file__).parent
    defaults = {}
    unresolved = {}
    for path in sorted(root.rglob("*.py")):
        # Providers live in subpackages; agno/models/*.py holds Model, Message and friends.
        if path.name == "__init__.py" or path.parent == root:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a provider module that cannot be parsed
            continue

        # Module-level string constants, so `id: str = DEFAULT_GATEWAY_MODEL` resolves.
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = node.value.value

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                is_id = (isinstance(stmt, ast.AnnAssign) and getattr(stmt.target, "id", None) == "id") or (
                    isinstance(stmt, ast.Assign) and any(getattr(t, "id", None) == "id" for t in stmt.targets)
                )
                if not is_id or stmt.value is None:
                    continue

                where = f"{path.relative_to(root)}::{node.name}"
                if isinstance(stmt.value, ast.Constant):
                    if isinstance(stmt.value.value, str):
                        defaults[stmt.value.value] = where
                    # `id: Optional[str] = None` means the provider has no default id
                    continue
                if isinstance(stmt.value, ast.Name) and stmt.value.id in constants:
                    defaults[constants[stmt.value.id]] = where
                    continue
                unresolved[where] = ast.unparse(stmt.value)
    return defaults, unresolved


def _tiktoken_installed() -> bool:
    try:
        import tiktoken  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _tiktoken_installed(), reason="tiktoken is not installed")
def test_every_provider_default_id_is_readable():
    """A default `id` this parser cannot read would drop out of the coverage check below."""
    _, unresolved = _provider_default_model_ids()
    assert not unresolved, (
        "These providers declare a default id this check cannot resolve, so they are not "
        f"covered by test_provider_default_ids_have_a_known_tokenizer: {unresolved}"
    )


@pytest.mark.skipif(not _tiktoken_installed(), reason="tiktoken is not installed")
def test_provider_default_ids_have_a_known_tokenizer():
    """Every provider's default model id belongs to a mapped family, or is a listed estimate.

    Asks whether the mapping has a gap, via is_family_mapped(), rather than what this machine
    resolves to -- otherwise a machine without the optional tokenizers package would report
    every mapped family as a gap, or worse, pass while silently counting with the estimate.
    """
    from agno.utils.tokens import is_family_mapped

    defaults, _ = _provider_default_model_ids()
    unlisted = {
        model_id: where
        for model_id, where in defaults.items()
        if not is_family_mapped(model_id) and model_id not in ESTIMATED_PROVIDER_DEFAULTS
    }
    assert not unlisted, (
        "These provider defaults silently fall back to OpenAI's encoding. Map the family in "
        f"HF_TOKENIZER_PATTERNS, or add it to ESTIMATED_PROVIDER_DEFAULTS with a reason: {unlisted}"
    )


@pytest.mark.skipif(not _tiktoken_installed(), reason="tiktoken is not installed")
def test_estimated_provider_defaults_has_no_stale_entries():
    """The estimate list does not outlive the ids it excuses."""
    from agno.utils.tokens import is_family_mapped

    defaults, _ = _provider_default_model_ids()
    stale = {
        model_id: ("no longer a provider default" if model_id not in defaults else "now has a real tokenizer")
        for model_id in ESTIMATED_PROVIDER_DEFAULTS
        if model_id not in defaults or is_family_mapped(model_id)
    }
    assert not stale, f"Remove these from ESTIMATED_PROVIDER_DEFAULTS: {stale}"


def test_cohere_default_model_maps_to_the_cohere_tokenizer():
    """Cohere's own default id is command-a-*, which the command-r-only pattern used to miss."""
    from agno.utils.tokens import _match_hf_tokenizer_repo

    assert _match_hf_tokenizer_repo("command-a-03-2025") == "Xenova/c4ai-command-r-v01-tokenizer"
    assert _match_hf_tokenizer_repo("command-r-plus") == "Xenova/c4ai-command-r-v01-tokenizer"


def test_unknown_family_matches_no_hf_tokenizer():
    from agno.utils.tokens import _match_hf_tokenizer_repo

    assert _match_hf_tokenizer_repo("mistral-large-latest") is None


@pytest.mark.skipif(not _tiktoken_installed(), reason="tiktoken is not installed")
@pytest.mark.parametrize(
    "model_id, expected_encoding",
    [
        ("openai/gpt-4", "cl100k_base"),
        ("openai/gpt-4.1", "o200k_base"),
        ("openai/gpt-oss-120b", "o200k_harmony"),
        ("accounts/fireworks/models/gpt-oss-120b", "o200k_harmony"),
    ],
)
def test_namespaced_model_ids_resolve_to_the_real_encoding(model_id, expected_encoding):
    """Provider-namespaced ids are tried without their namespace before falling back."""
    from agno.utils.tokens import TOKENIZER_SOURCE_TIKTOKEN_EXACT, _get_tiktoken_encoding, resolve_tokenizer_source

    assert resolve_tokenizer_source(model_id) == TOKENIZER_SOURCE_TIKTOKEN_EXACT
    assert _get_tiktoken_encoding(model_id).name == expected_encoding


@pytest.mark.skipif(not _tiktoken_installed(), reason="tiktoken is not installed")
def test_estimated_count_warns_once_per_model_id(monkeypatch):
    """An estimated count is announced, and not repeated for the same model."""
    from agno.utils import tokens as tokens_module

    warnings = []
    monkeypatch.setattr(tokens_module, "log_warning", lambda message: warnings.append(message))
    tokens_module._warn_estimated_token_count.cache_clear()
    tokens_module._get_tiktoken_encoding.cache_clear()

    tokens_module._select_tokenizer("some-unmapped-model-v1")
    tokens_module._select_tokenizer("some-unmapped-model-v1")

    assert len(warnings) == 1
    assert "some-unmapped-model-v1" in warnings[0]

    tokens_module._select_tokenizer("gpt-4o")
    assert len(warnings) == 1, "an exactly matched model must not be reported as an estimate"


@pytest.mark.skipif(not _tiktoken_installed(), reason="tiktoken is not installed")
def test_mapped_family_reports_the_estimate_when_tokenizers_is_missing(monkeypatch):
    """tokenizers is optional: a mapped family must not be reported as exact without it.

    Setting sys.modules["tokenizers"] to None makes `import tokenizers` raise ImportError,
    so this exercises the real resolution path rather than a stubbed one.
    """
    import sys

    from agno.utils import tokens as tokens_module

    monkeypatch.setitem(sys.modules, "tokenizers", None)
    tokens_module._tokenizers_available.cache_clear()
    tokens_module._get_hf_tokenizer.cache_clear()
    try:
        model_id = "command-a-03-2025"

        # The family is still mapped; only this machine cannot act on it.
        assert tokens_module.is_family_mapped(model_id)
        assert tokens_module.resolve_tokenizer_source(model_id) == (
            tokens_module.TOKENIZER_SOURCE_HUGGINGFACE_UNAVAILABLE
        )

        # And the reported source matches what counting actually does.
        source, _ = tokens_module._select_tokenizer(model_id)
        assert source == tokens_module.TOKENIZER_SOURCE_TIKTOKEN
    finally:
        tokens_module._tokenizers_available.cache_clear()
        tokens_module._get_hf_tokenizer.cache_clear()
