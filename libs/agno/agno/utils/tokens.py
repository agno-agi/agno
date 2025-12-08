import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_warning

DEFAULT_IMAGE_WIDTH = 1024
DEFAULT_IMAGE_HEIGHT = 1024


@lru_cache(maxsize=16)
def _get_tiktoken_encoding(model_id: str):
    try:
        import tiktoken

        # Use o200k_base for gpt-4o models
        if "gpt-4o" in model_id.lower():
            return tiktoken.get_encoding("o200k_base")

        try:
            return tiktoken.encoding_for_model(model_id)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        log_warning("tiktoken not installed. Please install it using `pip install tiktoken`.")
        return None


@lru_cache(maxsize=16)
def _get_hf_tokenizer(model_id: str):
    try:
        from tokenizers import Tokenizer

        model_id = model_id.lower()

        # Llama-3 models
        if "llama-3" in model_id or "llama3" in model_id:
            return Tokenizer.from_pretrained("Xenova/llama-3-tokenizer")

        # Llama-2 models and Replicate models (LiteLLM uses llama tokenizer for replicate)
        if "llama-2" in model_id or "llama2" in model_id or "replicate" in model_id:
            return Tokenizer.from_pretrained("hf-internal-testing/llama-tokenizer")

        # Cohere command-r models
        if "command-r" in model_id:
            return Tokenizer.from_pretrained("Xenova/c4ai-command-r-v01-tokenizer")

        return None
    except ImportError:
        log_warning("tokenizers not installed. Please install it using `pip install tokenizers`.")
        return None
    except Exception:
        return None


def _select_tokenizer(model_id: str) -> Tuple[str, Any]:
    hf_tokenizer = _get_hf_tokenizer(model_id)
    if hf_tokenizer is not None:
        return ("huggingface", hf_tokenizer)

    tiktoken_enc = _get_tiktoken_encoding(model_id)
    if tiktoken_enc is not None:
        return ("tiktoken", tiktoken_enc)

    return ("none", None)


# Tool token counting


def _format_function_definitions(tools: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append("namespace functions {")
    lines.append("")

    for tool in tools:
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
            lines.append(f"type {function_name} = () => any;")
        lines.append("")

    lines.append("} // namespace functions")
    return "\n".join(lines)


def _format_object_parameters(parameters: Dict[str, Any], indent: int) -> str:
    properties = parameters.get("properties", {})
    if not properties:
        return ""

    required_params = parameters.get("required", [])
    lines = []

    for key, props in properties.items():
        description = props.get("description")
        if description:
            lines.append(f"// {description}")

        question = "" if required_params and key in required_params else "?"
        lines.append(f"{key}{question}: {_format_type(props, indent)},")

    return "\n".join([" " * max(0, indent) + line for line in lines])


def _format_type(props: Dict[str, Any], indent: int) -> str:
    type_name = props.get("type", "any")

    if type_name == "string":
        if "enum" in props:
            return " | ".join([f'"{item}"' for item in props["enum"]])
        return "string"
    elif type_name == "array":
        items = props.get("items", {})
        return f"{_format_type(items, indent)}[]"
    elif type_name == "object":
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
        return "any"


# Multi-modal token counting
def _get_image_type(data: bytes) -> Optional[str]:
    if len(data) < 12:
        return None
    if data[0:8] == b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a":
        return "png"
    if data[0:4] == b"GIF8" and data[5:6] == b"a":
        return "gif"
    if data[0:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[4:8] == b"ftyp":
        return "heic"
    if data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _parse_image_dimensions_from_bytes(data: bytes, img_type: Optional[str] = None) -> Tuple[int, int]:
    import io
    import struct

    if img_type is None:
        img_type = _get_image_type(data)

    if img_type == "png":
        return struct.unpack(">LL", data[16:24])
    elif img_type == "gif":
        return struct.unpack("<HH", data[6:10])
    elif img_type == "jpeg":
        with io.BytesIO(data) as f:
            f.seek(0)
            size = 2
            ftype = 0
            while not 0xC0 <= ftype <= 0xCF or ftype in (0xC4, 0xC8, 0xCC):
                f.seek(size, 1)
                byte = f.read(1)
                while ord(byte) == 0xFF:
                    byte = f.read(1)
                ftype = ord(byte)
                size = struct.unpack(">H", f.read(2))[0] - 2
            f.seek(1, 1)
            h, w = struct.unpack(">HH", f.read(4))
        return w, h
    elif img_type == "webp":
        if data[12:16] == b"VP8X":
            w = struct.unpack("<I", data[24:27] + b"\x00")[0] + 1
            h = struct.unpack("<I", data[27:30] + b"\x00")[0] + 1
            return w, h
        elif data[12:16] == b"VP8 ":
            w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
            return w, h
        elif data[12:16] == b"VP8L":
            bits = struct.unpack("<I", data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return w, h

    return DEFAULT_IMAGE_WIDTH, DEFAULT_IMAGE_HEIGHT


def _get_image_dimensions(image: Image) -> Tuple[int, int]:
    try:
        # Get format from metadata if available
        img_format = image.format
        if not img_format and image.mime_type:
            img_format = image.mime_type.split("/")[-1] if "/" in image.mime_type else None

        # Get raw bytes
        if image.content:
            data = image.content
        elif image.filepath:
            with open(image.filepath, "rb") as f:
                data = f.read(100)  # Only need header
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
    # Get file size
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

    # Check if text file
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

    if ext in {"txt", "csv", "md", "json", "xml", "html"}:
        return size // 4
    return size // 40


def _count_tool_tokens(
    tools: Sequence[Union[Function, Dict[str, Any]]],
    model_id: str = "gpt-4o",
    includes_system_message: bool = False,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
) -> int:
    if not tools:
        return 0

    # Convert tools to dict format
    tool_dicts = []
    for tool in tools:
        if hasattr(tool, "to_dict"):
            tool_dicts.append(tool.to_dict())
        else:
            tool_dicts.append(tool)

    # Format tools in TypeScript namespace format and count
    formatted = _format_function_definitions(tool_dicts)
    tokens = count_text_tokens(formatted, model_id) + 9

    if includes_system_message:
        tokens -= 4

    # Handle tool_choice tokens
    if tool_choice == "none":
        tokens += 1
    elif isinstance(tool_choice, dict):
        tokens += 7
        func_name = tool_choice.get("function", {}).get("name", "")
        if func_name:
            tokens += count_text_tokens(func_name, model_id)

    return tokens


def count_text_tokens(text: str, model_id: str = "gpt-4o") -> int:
    if not text:
        return 0
    tokenizer_type, tokenizer = _select_tokenizer(model_id)
    if tokenizer_type == "huggingface":
        return len(tokenizer.encode(text).ids)
    elif tokenizer_type == "tiktoken":
        return len(tokenizer.encode(text, disallowed_special=()))
    else:
        return len(text) // 4


def count_image_tokens(image: Image) -> int:
    width, height = _get_image_dimensions(image)
    detail = image.detail or "auto"

    if width <= 0 or height <= 0:
        return 0

    if detail == "low":
        return 85

    # For auto/high, calculate based on dimensions
    if max(width, height) > 2000:
        scale = 2000 / max(width, height)
        width, height = int(width * scale), int(height * scale)

    if min(width, height) > 768:
        scale = 768 / min(width, height)
        width, height = int(width * scale), int(height * scale)

    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    return 85 + (170 * tiles)


def count_audio_tokens(audio: Audio) -> int:
    duration = audio.duration or 0
    if duration <= 0:
        return 0
    return int(duration * 25)


def count_video_tokens(video: Video) -> int:
    duration = video.duration or 0
    if duration <= 0:
        return 0

    width = video.width or 512
    height = video.height or 512
    fps = video.fps or 1.0

    # Calculate tokens per frame (high detail)
    w, h = width, height
    if max(w, h) > 2000:
        scale = 2000 / max(w, h)
        w, h = int(w * scale), int(h * scale)
    if min(w, h) > 768:
        scale = 768 / min(w, h)
        w, h = int(w * scale), int(h * scale)
    tiles = math.ceil(w / 512) * math.ceil(h / 512)
    tokens_per_frame = 85 + (170 * tiles)

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


def _count_message_tokens(
    message: Message,
    model_id: str = "gpt-4o",
    tokens_per_message: int = 3,
    tokens_per_name: int = 1,
) -> int:
    tokens = tokens_per_message

    if message.role:
        tokens += count_text_tokens(message.role, model_id)

    content = message.get_content(use_compressed_content=True)
    if content:
        if isinstance(content, str):
            tokens += count_text_tokens(content, model_id)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    tokens += count_text_tokens(item, model_id)
                elif isinstance(item, dict):
                    item_type = item.get("type", "")
                    if item_type == "text":
                        tokens += count_text_tokens(item.get("text", ""), model_id)
                    elif item_type == "image_url":
                        image_url_data = item.get("image_url", {})
                        detail = image_url_data.get("detail", "auto") if isinstance(image_url_data, dict) else "auto"
                        tokens += 85 if detail == "low" else 765
                    else:
                        tokens += count_text_tokens(json.dumps(item), model_id)
        else:
            tokens += count_text_tokens(str(content), model_id)

    if message.tool_calls:
        for tool_call in message.tool_calls:
            if isinstance(tool_call, dict) and "function" in tool_call:
                args = tool_call["function"].get("arguments", "")
                tokens += count_text_tokens(str(args), model_id)

    if message.tool_call_id:
        tokens += count_text_tokens(message.tool_call_id, model_id)

    if message.reasoning_content:
        tokens += count_text_tokens(message.reasoning_content, model_id)

    if message.redacted_reasoning_content:
        tokens += count_text_tokens(message.redacted_reasoning_content, model_id)

    if message.name:
        tokens += count_text_tokens(message.name, model_id)
        tokens += tokens_per_name

    tokens += _count_media_tokens(message)

    return tokens


def count_tokens(
    messages: List[Message],
    tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
    model_id: str = "gpt-4o",
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
) -> int:
    total = 0

    # Count message tokens
    if messages:
        model_id_lower = model_id.lower()
        if "gpt-3.5-turbo-0301" in model_id_lower:
            tokens_per_message, tokens_per_name = 4, -1
        else:
            tokens_per_message, tokens_per_name = 3, 1

        for msg in messages:
            total += _count_message_tokens(msg, model_id, tokens_per_message, tokens_per_name)

    # Add 3 tokens for reply priming
    total += 3

    # Count tool tokens
    if tools:
        includes_system = any(msg.role == "system" for msg in messages)
        total += _count_tool_tokens(tools, model_id, includes_system, tool_choice)

    return total
