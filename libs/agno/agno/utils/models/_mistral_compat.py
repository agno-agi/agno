"""
Compatibility layer for mistralai v1 (<2.0.0) and v2 (>=2.0.0).

Centralizes version detection and conditional imports so consumer modules
can simply do:
    from agno.utils.models._mistral_compat import MistralClient, AssistantMessage, ...

The module uses lazy loading: the ``mistralai`` package is NOT imported (and its
absence is NOT logged as an error) until the symbols defined here are actually
accessed.  This means that apps which do **not** use Mistral will start without
any error or warning even if ``mistralai`` is not installed.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

# ---------------------------------------------------------------------------
# Availability check (no error/log here — just a flag)
# ---------------------------------------------------------------------------

_MISTRAL_AVAILABLE: bool = True
_MISTRAL_VERSION: int | None = None

try:
    _MISTRAL_VERSION = int(importlib.metadata.version("mistralai").split(".")[0])
except importlib.metadata.PackageNotFoundError:
    _MISTRAL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ERR_MSG = "`mistralai` not installed. Please install using `pip install mistralai`"


def _require_mistral() -> None:
    if not _MISTRAL_AVAILABLE:
        from agno.utils.log import log_error

        log_error(_ERR_MSG)
        raise ImportError(_ERR_MSG)


def _load_symbols() -> dict[str, Any]:
    """Import and return all exported symbols from mistralai."""
    _require_mistral()

    assert _MISTRAL_VERSION is not None

    if _MISTRAL_VERSION >= 2:
        # v2: mistralai >= 2.0.0
        from mistralai.client import Mistral as MistralClient  # type: ignore[attr-defined]
        from mistralai.client.errors import HTTPValidationError, SDKError  # type: ignore[attr-defined]
        from mistralai.client.models import (  # type: ignore[attr-defined]
            AssistantMessage,
            ChatCompletionResponse,
            CompletionEvent,
            DeltaMessage,
            EmbeddingResponse,
            ImageURLChunk,
            SystemMessage,
            TextChunk,
            ToolMessage,
            UserMessage,
        )
        from mistralai.client.types.basemodel import Unset  # type: ignore[attr-defined]
    else:
        # v1: mistralai < 2.0.0
        from agno.utils.log import log_debug

        log_debug(
            f"mistralai v{_MISTRAL_VERSION} detected. v1 support will be deprecated, "
            "please consider upgrading: `pip install -U mistralai`"
        )
        from mistralai import CompletionEvent  # type: ignore[attr-defined,no-redef]
        from mistralai import Mistral as MistralClient  # type: ignore[attr-defined,no-redef]
        from mistralai.models import (  # type: ignore[no-redef]
            AssistantMessage,
            HTTPValidationError,
            ImageURLChunk,
            SDKError,
            SystemMessage,
            TextChunk,
            ToolMessage,
            UserMessage,
        )
        from mistralai.models.chatcompletionresponse import ChatCompletionResponse  # type: ignore[no-redef]
        from mistralai.models.deltamessage import DeltaMessage  # type: ignore[no-redef]
        from mistralai.models.embeddingresponse import EmbeddingResponse  # type: ignore[no-redef]
        from mistralai.types.basemodel import Unset  # type: ignore[no-redef]

    # These paths are the same in both v1 and v2
    from mistralai.extra import response_format_from_pydantic_model
    from mistralai.extra.struct_chat import ParsedChatCompletionResponse

    return {
        "AssistantMessage": AssistantMessage,
        "ChatCompletionResponse": ChatCompletionResponse,
        "CompletionEvent": CompletionEvent,
        "DeltaMessage": DeltaMessage,
        "EmbeddingResponse": EmbeddingResponse,
        "HTTPValidationError": HTTPValidationError,
        "ImageURLChunk": ImageURLChunk,
        "MistralClient": MistralClient,
        "ParsedChatCompletionResponse": ParsedChatCompletionResponse,
        "SDKError": SDKError,
        "SystemMessage": SystemMessage,
        "TextChunk": TextChunk,
        "ToolMessage": ToolMessage,
        "Unset": Unset,
        "UserMessage": UserMessage,
        "response_format_from_pydantic_model": response_format_from_pydantic_model,
        "MISTRAL_SDK_VERSION": _MISTRAL_VERSION,
    }


# ---------------------------------------------------------------------------
# Module-level __getattr__ for lazy loading
# ---------------------------------------------------------------------------

_cache: dict[str, Any] | None = None

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


def __getattr__(name: str) -> Any:
    global _cache
    if name in __all__:
        if _cache is None:
            _cache = _load_symbols()
        if name in _cache:
            return _cache[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
