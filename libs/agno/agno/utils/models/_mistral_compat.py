"""
Compatibility layer for mistralai v1 (<2.0.0) and v2 (>=2.0.0).

Centralizes version detection and conditional imports so consumer modules
can simply do:
    from agno.utils.models._mistral_compat import MistralClient, AssistantMessage, ...

All imports from ``mistralai`` are deferred until first access so that
applications which do not use Mistral never pay the cost of (or see errors
about) the optional ``mistralai`` dependency.
"""

import importlib.metadata
from typing import Any, Dict, Optional

from agno.utils.log import log_debug, log_error

# ---------------------------------------------------------------------------
# Lazy-loading machinery
# ---------------------------------------------------------------------------

_MISTRAL_SDK_VERSION: Optional[int] = None
_resolved: Dict[str, Any] = {}


def _resolve() -> None:
    """Run the version check and conditional imports exactly once."""
    global _MISTRAL_SDK_VERSION

    if _MISTRAL_SDK_VERSION is not None:
        return  # already resolved

    try:
        _MISTRAL_SDK_VERSION = int(importlib.metadata.version("mistralai").split(".")[0])
    except importlib.metadata.PackageNotFoundError:
        log_error("`mistralai` not installed. Please install using `pip install mistralai`")
        raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")

    if _MISTRAL_SDK_VERSION >= 2:
        # v2: mistralai >= 2.0.0
        from mistralai.client import Mistral as _MistralClient  # type: ignore[attr-defined]
        from mistralai.client.errors import HTTPValidationError as _HTTPValidationError, SDKError as _SDKError  # type: ignore[attr-defined]
        from mistralai.client.models import (  # type: ignore[attr-defined]
            AssistantMessage as _AssistantMessage,
            ChatCompletionResponse as _ChatCompletionResponse,
            CompletionEvent as _CompletionEvent,
            DeltaMessage as _DeltaMessage,
            EmbeddingResponse as _EmbeddingResponse,
            ImageURLChunk as _ImageURLChunk,
            SystemMessage as _SystemMessage,
            TextChunk as _TextChunk,
            ToolMessage as _ToolMessage,
            UserMessage as _UserMessage,
        )
        from mistralai.client.types.basemodel import Unset as _Unset  # type: ignore[attr-defined]
    else:
        # v1: mistralai < 2.0.0
        log_debug(
            f"mistralai v{_MISTRAL_SDK_VERSION} detected. v1 support will be deprecated, please consider upgrading: `pip install -U mistralai`"
        )
        from mistralai import CompletionEvent as _CompletionEvent  # type: ignore[attr-defined,no-redef]
        from mistralai import Mistral as _MistralClient  # type: ignore[attr-defined,no-redef]
        from mistralai.models import (  # type: ignore[no-redef]
            AssistantMessage as _AssistantMessage,
            HTTPValidationError as _HTTPValidationError,
            ImageURLChunk as _ImageURLChunk,
            SDKError as _SDKError,
            SystemMessage as _SystemMessage,
            TextChunk as _TextChunk,
            ToolMessage as _ToolMessage,
            UserMessage as _UserMessage,
        )
        from mistralai.models.chatcompletionresponse import ChatCompletionResponse as _ChatCompletionResponse  # type: ignore[no-redef]
        from mistralai.models.deltamessage import DeltaMessage as _DeltaMessage  # type: ignore[no-redef]
        from mistralai.models.embeddingresponse import EmbeddingResponse as _EmbeddingResponse  # type: ignore[no-redef]
        from mistralai.types.basemodel import Unset as _Unset  # type: ignore[no-redef]

    # These paths are the same in both v1 and v2
    from mistralai.extra import response_format_from_pydantic_model as _response_format_from_pydantic_model
    from mistralai.extra.struct_chat import ParsedChatCompletionResponse as _ParsedChatCompletionResponse

    _resolved.update(
        {
            "AssistantMessage": _AssistantMessage,
            "ChatCompletionResponse": _ChatCompletionResponse,
            "CompletionEvent": _CompletionEvent,
            "DeltaMessage": _DeltaMessage,
            "EmbeddingResponse": _EmbeddingResponse,
            "HTTPValidationError": _HTTPValidationError,
            "ImageURLChunk": _ImageURLChunk,
            "MistralClient": _MistralClient,
            "ParsedChatCompletionResponse": _ParsedChatCompletionResponse,
            "SDKError": _SDKError,
            "SystemMessage": _SystemMessage,
            "TextChunk": _TextChunk,
            "ToolMessage": _ToolMessage,
            "Unset": _Unset,
            "UserMessage": _UserMessage,
            "response_format_from_pydantic_model": _response_format_from_pydantic_model,
            "MISTRAL_SDK_VERSION": _MISTRAL_SDK_VERSION,
        }
    )


def __getattr__(name: str) -> Any:
    """Lazy module-level attribute access — triggers import on first use."""
    if name in _resolved:
        return _resolved[name]

    if name in __all__:
        _resolve()
        if name in _resolved:
            return _resolved[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AssistantMessage",
    "ChatCompletionResponse",
    "CompletionEvent",
    "DeltaMessage",
    "EmbeddingResponse",
    "HTTPValidationError",
    "ImageURLChunk",
    "MistralClient",
    "ParsedChatCompletionResponse",
    "SDKError",
    "SystemMessage",
    "TextChunk",
    "ToolMessage",
    "Unset",
    "UserMessage",
    "response_format_from_pydantic_model",
    "MISTRAL_SDK_VERSION",
]
