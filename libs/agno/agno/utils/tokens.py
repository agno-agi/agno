import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, Union

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_warning

# Default image dimensions used as fallback when actual dimensions cannot be determined.
# These values provide a more conservative estimate for high-detail image token counting.
DEFAULT_IMAGE_WIDTH = 1024
DEFAULT_IMAGE_HEIGHT = 1024


# Different models use different encodings
@lru_cache(maxsize=16)
def _get_tiktoken_encoding(model_id: str):
    model_id = model_id.lower()
    try:
        import tiktoken

        try:
            # Use model-specific encoding
            return tiktoken.encoding_for_model(model_id)
        except KeyError:
            return tiktoken.get_encoding("o200k_base")
    except ImportError:
        log_warning("tiktoken not installed. Please install it using `pip install tiktoken`.")
        return None


@lru_cache(maxsize=16)
def _get_hf_tokenizer(model_id: str):
    try:
        from tokenizers import Tokenizer

        model_id = model_id.lower()

        # Llama-3 models use a different tokenizer than Llama-2
        if "llama-3" in model_id or "llama3" in model_id:
            return Tokenizer.from_pretrained("Xenova/llama-3-tokenizer")

        # Llama-2 models and Replicate models (LiteLLM uses llama tokenizer for replicate)
        if "llama-2" in model_id or "llama2" in model_id or "replicate" in model_id:
            return Tokenizer.from_pretrained("hf-internal-testing/llama-tokenizer")

        # Cohere command-r models have their own tokenizer
        if "command-r" in model_id:
            return Tokenizer.from_pretrained("Xenova/c4ai-command-r-v01-tokenizer")

        return None
    except ImportError:
        log_warning("tokenizers not installed. Please install it using `pip install tokenizers`.")
        return None
    except Exception:
        return None


def _select_tokenizer(model_id: str) -> Tuple[str, Any]:
    # Priority 1: HuggingFace tokenizers for models with specific tokenizers
    hf_tokenizer = _get_hf_tokenizer(model_id)
    if hf_tokenizer is not None:
        return ("huggingface", hf_tokenizer)

    # Priority 2: tiktoken for OpenAI models
    tiktoken_enc = _get_tiktoken_encoding(model_id)
    if tiktoken_enc is not None:
        return ("tiktoken", tiktoken_enc)

    # Fallback: No tokenizer available, will use character-based estimation
    return ("none", None)


# =============================================================================
# Tool Token Counting
# =============================================================================
# OpenAI counts tool/function tokens by converting them to a TypeScript-like
# namespace format. This approach was reverse-engineered and documented from:
# https://github.com/forestwanglin/openai-java/blob/main/jtokkit/src/main/java/xyz/felh/openai/jtokkit/utils/TikTokenUtils.java
#
# The formatted output looks like:
#   namespace functions {
#   // {description}
#   type {name} = (_: {
#     // {param_description}
#     {param_name}{?}: {type},
#   }) => any;
#   } // namespace functions
# =============================================================================


# OpenAI internally represents function/tool definitions in a TypeScript-like format for tokenization
def _format_function_definitions(tools: List[Dict[str, Any]]) -> str:
    """
    Formats tool definitions as a TypeScript namespace.

    Returns:
        A TypeScript namespace string representation of all tools.

    Example:
        Input tool: {"function": {"name": "get_weather", "parameters": {...}}}
        Output: "namespace functions {\ntype get_weather = (_: {...}) => any;\n}"
    """
    lines = []
    lines.append("namespace functions {")
    lines.append("")

    for tool in tools:
        # Handle both {"function": {...}} and direct function dict formats
        function = tool.get("function", tool)
        if function_description := function.get("description"):
            lines.append(f"// {function_description}")

        function_name = function.get("name", "")
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})

        if properties:
            lines.append(f"type {function_name} = (_: {{")
            lines.append(_format_object_parameters(parameters, 0))
            lines.append("}) => any;")
        else:
            # Functions with no parameters
            lines.append(f"type {function_name} = () => any;")
        lines.append("")

    lines.append("} // namespace functions")
    return "\n".join(lines)


def _format_object_parameters(parameters: Dict[str, Any], indent: int) -> str:
    """
    Format JSON Schema object properties as TypeScript object properties.

    Args:
        parameters: A JSON Schema object with 'properties' and optional 'required' keys.
        indent: Number of spaces for indentation.

    Returns:
        TypeScript property definitions, one per line.

    Example:
        Input: {"properties": {"name": {"type": "string"}}, "required": ["name"]}
        Output: "name: string,"
    """
    properties = parameters.get("properties", {})
    if not properties:
        return ""

    required_params = parameters.get("required", [])
    lines = []

    for key, props in properties.items():
        # Add property description as a comment
        description = props.get("description")
        if description:
            lines.append(f"// {description}")

        # Required params have no "?", optional params have "?"
        question = "" if required_params and key in required_params else "?"
        lines.append(f"{key}{question}: {_format_type(props, indent)},")

    return "\n".join([" " * max(0, indent) + line for line in lines])


def _format_type(props: Dict[str, Any], indent: int) -> str:
    """
    Convert a JSON Schema type to its TypeScript equivalent.

    Recursively handles nested types including arrays and objects.

    Args:
        props: A JSON Schema property definition containing 'type' and optionally
            'enum', 'items' (for arrays), or 'properties' (for objects).
        indent: The current indentation level for nested object formatting.

    Returns:
        A TypeScript type string.

    Example:
        - {"type": "string"} -> "string"
        - {"type": "string", "enum": ["low", "high"]} -> '"low" | "high"'
        - {"type": "array", "items": {"type": "number"}} -> "number[]"
    """
    type_name = props.get("type", "any")

    if type_name == "string":
        if "enum" in props:
            # Convert enum to TypeScript union of string literals
            return " | ".join([f'"{item}"' for item in props["enum"]])
        return "string"
    elif type_name == "array":
        # Recursively format the array item type
        items = props.get("items", {})
        return f"{_format_type(items, indent)}[]"
    elif type_name == "object":
        # Recursively format nested object properties
        return f"{{\n{_format_object_parameters(props, indent + 2)}\n}}"
    elif type_name in ["integer", "number"]:
        if "enum" in props:
            return " | ".join([f'"{item}"' for item in props["enum"]])
        return "number"
    elif type_name == "boolean":
        return "boolean"
    elif type_name == "null":
        return "null"
    else:
        # Default to "any" for unknown types
        return "any"


# =============================================================================
# Multi-modal Token Counting
# =============================================================================
# Image dimension parsing uses magic byte detection to identify file formats
# without relying on external libraries. This allows efficient header-only reads.
# =============================================================================


def _get_image_type(data: bytes) -> Optional[str]:
    """Returns the image format from magic bytes in the file header."""
    if len(data) < 12:
        return None
    # PNG: 8-byte signature
    if data[0:8] == b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a":
        return "png"
    # GIF: "GIF8" followed by "9a" or "7a" (we check for 'a')
    if data[0:4] == b"GIF8" and data[5:6] == b"a":
        return "gif"
    # JPEG: SOI marker (Start of Image)
    if data[0:3] == b"\xff\xd8\xff":
        return "jpeg"
    # HEIC/HEIF: ftyp box at offset 4
    if data[4:8] == b"ftyp":
        return "heic"
    # WebP: RIFF container with WEBP identifier
    if data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _parse_image_dimensions_from_bytes(data: bytes, img_type: Optional[str] = None) -> Tuple[int, int]:
    """Returns the image dimensions (width, height) from raw image bytes."""
    import io
    import struct

    if img_type is None:
        img_type = _get_image_type(data)

    if img_type == "png":
        # PNG IHDR chunk: width at offset 16, height at offset 20 (big-endian)
        return struct.unpack(">LL", data[16:24])
    elif img_type == "gif":
        # GIF logical screen descriptor: width/height at offset 6 (little-endian)
        return struct.unpack("<HH", data[6:10])
    elif img_type == "jpeg":
        # JPEG requires scanning for SOF (Start of Frame) markers
        # SOF markers are 0xC0-0xCF, excluding 0xC4 (DHT), 0xC8 (JPG), 0xCC (DAC)
        with io.BytesIO(data) as f:
            f.seek(0)
            size = 2
            ftype = 0
            while not 0xC0 <= ftype <= 0xCF or ftype in (0xC4, 0xC8, 0xCC):
                f.seek(size, 1)
                byte = f.read(1)
                # Skip any padding 0xFF bytes
                while ord(byte) == 0xFF:
                    byte = f.read(1)
                ftype = ord(byte)
                size = struct.unpack(">H", f.read(2))[0] - 2
            f.seek(1, 1)  # Skip precision byte
            h, w = struct.unpack(">HH", f.read(4))
        return w, h
    elif img_type == "webp":
        # WebP has three encoding formats with different dimension locations
        if data[12:16] == b"VP8X":
            # Extended format: 24-bit dimensions stored in 3 bytes each
            w = struct.unpack("<I", data[24:27] + b"\x00")[0] + 1
            h = struct.unpack("<I", data[27:30] + b"\x00")[0] + 1
            return w, h
        elif data[12:16] == b"VP8 ":
            # Lossy format: dimensions in first frame header, 14-bit masked
            w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
            return w, h
        elif data[12:16] == b"VP8L":
            # Lossless format: dimensions bit-packed in 4 bytes
            bits = struct.unpack("<I", data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return w, h

    return DEFAULT_IMAGE_WIDTH, DEFAULT_IMAGE_HEIGHT


def _get_image_dimensions(image: Image) -> Tuple[int, int]:
    """Returns the image dimensions (width, height) from an Image object."""
    try:
        # Try to get format hint from metadata to skip magic byte detection
        img_format = image.format
        if not img_format and image.mime_type:
            img_format = image.mime_type.split("/")[-1] if "/" in image.mime_type else None

        # Get raw bytes from the appropriate source
        if image.content:
            data = image.content
        elif image.filepath:
            with open(image.filepath, "rb") as f:
                data = f.read(100)  # Only need header bytes for dimension parsing
        elif image.url:
            import httpx

            response = httpx.get(image.url, timeout=5)
            data = response.content
        else:
            return DEFAULT_IMAGE_WIDTH, DEFAULT_IMAGE_HEIGHT

        return _parse_image_dimensions_from_bytes(data, img_format)
    except Exception:
        return DEFAULT_IMAGE_WIDTH, DEFAULT_IMAGE_HEIGHT


def count_file_tokens(file: File) -> int:
    """Estimate the number of tokens in a file based on its size and type."""
    # Determine file size from available source
    size = 0
    if file.content and isinstance(file.content, (str, bytes)):
        size = len(file.content)
    elif file.filepath:
        try:
            path = Path(file.filepath) if isinstance(file.filepath, str) else file.filepath
            if path.exists():
                size = path.stat().st_size
        except Exception:
            pass
    elif file.url:
        # Use HEAD request to get Content-Length without downloading
        try:
            import urllib.request

            req = urllib.request.Request(file.url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    size = int(content_length)
        except Exception:
            pass

    if size == 0:
        return 0

    # Determine file extension for type-based estimation
    ext = None
    if file.format:
        ext = file.format.lower().lstrip(".")
    elif file.filepath:
        path = Path(file.filepath) if isinstance(file.filepath, str) else file.filepath
        ext = path.suffix.lower().lstrip(".") if path.suffix else None
    elif file.url:
        url_path = file.url.split("?")[0]
        if "." in url_path:
            ext = url_path.rsplit(".", 1)[-1].lower()

    # Text files: ~4 characters per token (based on typical tiktoken ratios)
    if ext in {"txt", "csv", "md", "json", "xml", "html"}:
        return size // 4
    # Binary/other files: ~40 bytes per token (rough estimate)
    return size // 40


def count_tool_tokens(
    tools: Sequence[Union[Function, Dict[str, Any]]],
    model_id: str = "gpt-4o",
) -> int:
    """Count tokens consumed by tool/function definitions"""
    if not tools:
        return 0

    # Convert Function objects to dict format for formatting
    tool_dicts = []
    for tool in tools:
        if isinstance(tool, Function):
            tool_dicts.append(tool.to_dict())
        else:
            tool_dicts.append(tool)

    # Format tools in TypeScript namespace format and count tokens
    formatted = _format_function_definitions(tool_dicts)
    tokens = count_text_tokens(formatted, model_id)
    return tokens


def count_schema_tokens(
    output_schema: Optional[Union[Dict, Type["BaseModel"]]],
    model_id: str = "gpt-4o",
) -> int:
    """Estimate tokens for output_schema/output_schema."""
    if output_schema is None:
        return 0

    try:
        from pydantic import BaseModel

        if isinstance(output_schema, type) and issubclass(output_schema, BaseModel):
            # Convert Pydantic model to JSON schema
            schema = output_schema.model_json_schema()
        elif isinstance(output_schema, dict):
            schema = output_schema
        else:
            return 0

        schema_json = json.dumps(schema)
        return count_text_tokens(schema_json, model_id)
    except Exception:
        return 0


def count_text_tokens(text: str, model_id: str = "gpt-4o") -> int:
    if not text:
        return 0
    tokenizer_type, tokenizer = _select_tokenizer(model_id)
    if tokenizer_type == "huggingface":
        return len(tokenizer.encode(text).ids)
    elif tokenizer_type == "tiktoken":
        # disallowed_special=() allows all special tokens to be encoded
        return len(tokenizer.encode(text, disallowed_special=()))
    else:
        # Fallback: ~4 characters per token (typical for English text)
        return len(text) // 4


# =============================================================================
# Image Token Counting
# =============================================================================
# OpenAI's vision models process images by dividing them into 512x512 tiles.
#     The token count depends on the image dimensions and detail level.
#     OpenAI's image token formula:
#         1. If max(width, height) > 2000: scale to fit in 2000px on longest side
#         2. If min(width, height) > 768: scale so shortest side is 768px
#         3. tiles = ceil(width/512) * ceil(height/512)
#         4. tokens = 85 + (170 * tiles)

#     Token constants:
#         - 85: Base tokens for any image (covers metadata, low-detail representation)
#         - 170: Additional tokens per 512x512 tile (high-detail tile encoding)

#     Detail modes:
#         - "low": Fixed 85 tokens (thumbnail/overview only)
#         - "high"/"auto": Full tile-based calculation


#     Example:
#         1024x1024 image with high detail:
#         - No scaling needed (within limits)
#         - tiles = ceil(1024/512) * ceil(1024/512) = 2 * 2 = 4
#         - tokens = 85 + (170 * 4) = 765
# =============================================================================
def count_image_tokens(image: Image) -> int:
    width, height = _get_image_dimensions(image)
    detail = image.detail or "auto"

    if width <= 0 or height <= 0:
        return 0

    # Low detail: fixed 85 tokens regardless of dimensions
    if detail == "low":
        return 85

    # For auto/high detail, calculate based on dimensions
    # Step 1: Scale down if longest side exceeds 2000px
    if max(width, height) > 2000:
        scale = 2000 / max(width, height)
        width, height = int(width * scale), int(height * scale)

    # Step 2: Scale down if shortest side exceeds 768px
    if min(width, height) > 768:
        scale = 768 / min(width, height)
        width, height = int(width * scale), int(height * scale)

    # Step 3: Calculate tiles (512x512 each)
    tiles = math.ceil(width / 512) * math.ceil(height / 512)

    # Step 4: 85 base tokens + 170 tokens per tile
    return 85 + (170 * tiles)


# =============================================================================
# Audio Token Counting
# =============================================================================
# This is an Agno-specific implementation using a conservative estimate of 25 tokens per second of audio.
# OpenAI's Whisper model actually uses ~50 tokens/second (20ms per token), but this estimate is more conservative for context window planning.
# Example:
#     10 seconds of audio: 10 * 25 = 250 tokens


def count_audio_tokens(audio: Audio) -> int:
    """Estimate the number of tokens for an audio clip based on duration."""
    duration = audio.duration or 0
    if duration <= 0:
        return 0
    return int(duration * 25)


# =============================================================================
# Video Token Counting
# =============================================================================
# This is an Agno-specific implementation that treats video as a sequence of
# images, applying the OpenAI image token formula to each frame.
# Example:
#     5 second video at 1 fps with 512x512 resolution:
#     - tiles = 1 (512/512 = 1)
#     - tokens_per_frame = 85 + 170 = 255
#     - num_frames = 5
#     - total = 255 * 5 = 1275 tokens
# =============================================================================


def count_video_tokens(video: Video) -> int:
    duration = video.duration or 0
    if duration <= 0:
        return 0

    # Use defaults if dimensions/fps not specified
    width = video.width or 512
    height = video.height or 512
    fps = video.fps or 1.0

    # Calculate tokens per frame using the same formula as images (high detail)
    w, h = width, height
    # Scale down if longest side exceeds 2000px
    if max(w, h) > 2000:
        scale = 2000 / max(w, h)
        w, h = int(w * scale), int(h * scale)
    # Scale down if shortest side exceeds 768px
    if min(w, h) > 768:
        scale = 768 / min(w, h)
        w, h = int(w * scale), int(h * scale)
    tiles = math.ceil(w / 512) * math.ceil(h / 512)
    tokens_per_frame = 85 + (170 * tiles)

    # Calculate total tokens for all frames
    num_frames = max(int(duration * fps), 1)
    return num_frames * tokens_per_frame


def _count_media_tokens(message: Message) -> int:
    tokens = 0

    if message.images:
        for image in message.images:
            tokens += count_image_tokens(image)

    if message.audio:
        for audio in message.audio:
            tokens += count_audio_tokens(audio)

    if message.videos:
        for video in message.videos:
            tokens += count_video_tokens(video)

    if message.files:
        for file in message.files:
            tokens += count_file_tokens(file)

    return tokens


def _count_message_tokens(message: Message, model_id: str = "gpt-4o") -> int:
    tokens = 0
    text_parts: List[str] = []

    # Collect content text
    content = message.get_content(use_compressed_content=True)
    if content:
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            # Handle multimodal content blocks
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict):
                    item_type = item.get("type", "")
                    if item_type == "text":
                        text_parts.append(item.get("text", ""))
                    elif item_type == "image_url":
                        # Handle OpenAI-style content lists without populating message.images
                        image_url_data = item.get("image_url", {})
                        url = image_url_data.get("url") if isinstance(image_url_data, dict) else None
                        detail = image_url_data.get("detail", "auto") if isinstance(image_url_data, dict) else "auto"

                        temp_image = Image(url=url, detail=detail)
                        tokens += count_image_tokens(temp_image)
                    else:
                        text_parts.append(json.dumps(item))
        else:
            text_parts.append(str(content))

    # Collect tool call arguments
    if message.tool_calls:
        for tool_call in message.tool_calls:
            if isinstance(tool_call, dict) and "function" in tool_call:
                args = tool_call["function"].get("arguments", "")
                text_parts.append(str(args))

    # Collect tool response id
    if message.tool_call_id:
        text_parts.append(message.tool_call_id)

    # Collect reasoning content
    if message.reasoning_content:
        text_parts.append(message.reasoning_content)
    if message.redacted_reasoning_content:
        text_parts.append(message.redacted_reasoning_content)

    # Collect name field
    if message.name:
        text_parts.append(message.name)

    # Count all text tokens in a single call
    if text_parts:
        tokens += count_text_tokens(" ".join(text_parts), model_id)

    # Count all media attachments
    tokens += _count_media_tokens(message)

    return tokens


def count_tokens(
    messages: List[Message],
    tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
    model_id: str = "gpt-4o",
    output_schema: Optional[Union[Dict, Type["BaseModel"]]] = None,
) -> int:
    total = 0
    model_id = model_id.lower()

    # Count message tokens
    if messages:
        for msg in messages:
            total += _count_message_tokens(msg, model_id)

    # Add tool tokens
    if tools:
        total += count_tool_tokens(tools, model_id)

    # Add output_schema/output_schema tokens
    if output_schema is not None:
        total += count_schema_tokens(output_schema, model_id)

    return total
