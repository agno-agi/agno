"""Pydantic models and conversion helpers for the Anthropic Messages API interface."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from agno.media import Image

# ---------------------------------------------------------------------------
# Input content blocks (Anthropic -> Agno)
# ---------------------------------------------------------------------------


class TextBlockParam(BaseModel):
    type: Literal["text"]
    text: str
    cache_control: Optional[Dict[str, Any]] = None


class ImageSourceBase64(BaseModel):
    type: Literal["base64"]
    media_type: str
    data: str


class ImageSourceUrl(BaseModel):
    type: Literal["url"]
    url: str


class ImageBlockParam(BaseModel):
    type: Literal["image"]
    source: Union[ImageSourceBase64, ImageSourceUrl]
    cache_control: Optional[Dict[str, Any]] = None


class ToolUseBlockParam(BaseModel):
    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)
    cache_control: Optional[Dict[str, Any]] = None


class ToolResultBlockParam(BaseModel):
    type: Literal["tool_result"]
    tool_use_id: str
    content: Union[str, List[Dict[str, Any]]] = ""
    is_error: Optional[bool] = None
    cache_control: Optional[Dict[str, Any]] = None


class ThinkingBlockParam(BaseModel):
    type: Literal["thinking"]
    thinking: str
    signature: Optional[str] = None


InputContentBlock = Union[
    TextBlockParam,
    ImageBlockParam,
    ToolUseBlockParam,
    ToolResultBlockParam,
    ThinkingBlockParam,
]


class MessageParam(BaseModel):
    role: Literal["user", "assistant"]
    content: Union[str, List[InputContentBlock]]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ToolDefinition(BaseModel):
    """Anthropic tool schema. Accepted but not forwarded to Agno in v1."""

    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    cache_control: Optional[Dict[str, Any]] = None


class MessagesRequest(BaseModel):
    model: str
    messages: List[MessageParam]
    max_tokens: int = 1024
    system: Optional[Union[str, List[TextBlockParam]]] = None
    metadata: Optional[Dict[str, Any]] = None
    stop_sequences: Optional[List[str]] = None
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    thinking: Optional[Dict[str, Any]] = None


class CountTokensRequest(BaseModel):
    model: str
    messages: List[MessageParam]
    system: Optional[Union[str, List[TextBlockParam]]] = None
    tools: Optional[List[ToolDefinition]] = None


# ---------------------------------------------------------------------------
# Response models (non-streaming)
# ---------------------------------------------------------------------------


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)


class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: Optional[str] = None


OutputContentBlock = Union[TextBlock, ToolUseBlock, ThinkingBlock]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None


class MessagesResponse(BaseModel):
    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    model: str
    content: List[OutputContentBlock] = Field(default_factory=list)
    stop_reason: Optional[str] = "end_turn"
    stop_sequence: Optional[str] = None
    usage: Usage = Field(default_factory=Usage)


class CountTokensResponse(BaseModel):
    input_tokens: int


# ---------------------------------------------------------------------------
# /v1/models
# ---------------------------------------------------------------------------


class ModelInfo(BaseModel):
    id: str
    type: Literal["model"] = "model"
    display_name: str
    created_at: str


class ModelsListResponse(BaseModel):
    data: List[ModelInfo]
    has_more: bool = False
    first_id: Optional[str] = None
    last_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


class AnthropicErrorBody(BaseModel):
    type: str
    message: str


class AnthropicErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    error: AnthropicErrorBody


def error_response(error_type: str, message: str) -> Dict[str, Any]:
    return AnthropicErrorResponse(error=AnthropicErrorBody(type=error_type, message=message)).model_dump()


# ---------------------------------------------------------------------------
# Input translation (Anthropic -> Agno)
# ---------------------------------------------------------------------------


def _coerce_content(content: Union[str, List[InputContentBlock], List[Dict[str, Any]]]) -> List[InputContentBlock]:
    """Normalize the `content` field into a list of typed blocks."""
    if isinstance(content, str):
        return [TextBlockParam(type="text", text=content)]
    blocks: List[InputContentBlock] = []
    for item in content:
        if isinstance(item, BaseModel):
            blocks.append(item)  # type: ignore[arg-type]
            continue
        if not isinstance(item, dict):
            continue
        block_type = item.get("type")
        if block_type == "text":
            blocks.append(TextBlockParam(**item))
        elif block_type == "image":
            blocks.append(ImageBlockParam(**item))
        elif block_type == "tool_use":
            blocks.append(ToolUseBlockParam(**item))
        elif block_type == "tool_result":
            blocks.append(ToolResultBlockParam(**item))
        elif block_type == "thinking":
            blocks.append(ThinkingBlockParam(**item))
    return blocks


def _image_from_block(block: ImageBlockParam) -> Image:
    source = block.source
    if isinstance(source, ImageSourceBase64):
        return Image.from_base64(base64_content=source.data, mime_type=source.media_type)
    return Image(url=source.url)


def _system_to_text(system: Optional[Union[str, List[TextBlockParam]]]) -> Optional[str]:
    if system is None:
        return None
    if isinstance(system, str):
        return system
    parts = []
    for block in system:
        if isinstance(block, BaseModel):
            parts.append(block.text)  # type: ignore[attr-defined]
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n\n".join(p for p in parts if p) or None


def extract_agno_input(request: MessagesRequest) -> Dict[str, Any]:
    """Translate an Anthropic MessagesRequest into kwargs for Agent.arun / Team.arun.

    Strategy: Anthropic clients (including Claude Code) send full history each turn. Agno
    manages history via session DB, so we feed only the latest user turn into `input`,
    relying on `session_id` for continuity. The system prompt is injected via
    `dependencies` so the agent's instructions remain authoritative — but it's still
    available to the agent through its context.
    """
    text_parts: List[str] = []
    images: List[Image] = []

    # Find the last user message and use its content as input.
    last_user_msg: Optional[MessageParam] = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            last_user_msg = msg
            break

    if last_user_msg is None:
        return {"input": "", "images": []}

    for block in _coerce_content(last_user_msg.content):
        if isinstance(block, TextBlockParam):
            text_parts.append(block.text)
        elif isinstance(block, ImageBlockParam):
            images.append(_image_from_block(block))
        elif isinstance(block, ToolResultBlockParam):
            # Surface tool result text so the agent can react to it.
            if isinstance(block.content, str):
                text_parts.append(block.content)
            else:
                for sub in block.content:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        text_parts.append(sub.get("text", ""))

    return {
        "input": "\n\n".join(p for p in text_parts if p),
        "images": images or None,
        "system_override": _system_to_text(request.system),
    }


# ---------------------------------------------------------------------------
# Output translation (Agno RunOutput -> Anthropic response)
# ---------------------------------------------------------------------------


def _stop_reason_from_status(status: Any) -> str:
    status_str = getattr(status, "value", str(status)).lower()
    if "cancel" in status_str:
        return "stop_sequence"
    if "error" in status_str:
        return "error"
    return "end_turn"


def build_messages_response(run_output: Any, model: str) -> MessagesResponse:
    """Convert an Agno RunOutput (or TeamRunOutput) into an Anthropic MessagesResponse."""
    blocks: List[OutputContentBlock] = []

    reasoning = getattr(run_output, "reasoning_content", None)
    if reasoning:
        blocks.append(ThinkingBlock(thinking=str(reasoning)))

    tools = getattr(run_output, "tools", None) or []
    for tool in tools:
        blocks.append(
            ToolUseBlock(
                id=tool.tool_call_id or f"toolu_{uuid.uuid4().hex[:24]}",
                name=tool.tool_name or "tool",
                input=tool.tool_args or {},
            )
        )

    content = getattr(run_output, "content", None)
    if content is not None:
        blocks.append(TextBlock(text=str(content)))

    if not blocks:
        blocks.append(TextBlock(text=""))

    metrics = getattr(run_output, "metrics", None)
    usage = Usage(
        input_tokens=int(getattr(metrics, "input_tokens", 0) or 0),
        output_tokens=int(getattr(metrics, "output_tokens", 0) or 0),
        cache_read_input_tokens=getattr(metrics, "cache_read_tokens", None) or None,
        cache_creation_input_tokens=getattr(metrics, "cache_write_tokens", None) or None,
    )

    return MessagesResponse(
        id=f"msg_{uuid.uuid4().hex[:24]}",
        model=model,
        content=blocks,
        stop_reason=_stop_reason_from_status(getattr(run_output, "status", "completed")),
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def generate_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def generate_tool_use_id() -> str:
    return f"toolu_{uuid.uuid4().hex[:24]}"
