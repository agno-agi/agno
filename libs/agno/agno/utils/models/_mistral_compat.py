"""
Compatibility layer for mistralai v1 (<2.0.0) and v2 (>=2.0.0).

Centralizes version detection and conditional imports so consumer modules
can simply do:
    from agno.utils.models._mistral_compat import MistralClient, AssistantMessage, ...

If mistralai is not installed, this module can still be imported without error.
Actual ImportError is raised only when the exported symbols are accessed.
"""

import importlib.metadata

from agno.utils.log import log_debug

_mistral_available = False
_mistral_version = 0

try:
    _mistral_version = int(importlib.metadata.version("mistralai").split(".")[0])
    _mistral_available = True
except importlib.metadata.PackageNotFoundError:
    pass


if _mistral_available:
    if _mistral_version >= 2:
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
        log_debug(
            f"mistralai v{_mistral_version} detected. v1 support will be deprecated, please consider upgrading: `pip install -U mistralai`"
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

MISTRAL_SDK_VERSION = _mistral_version

if not _mistral_available:

    def __getattr__(name: str):  # noqa: ANN001, ANN202
        raise ImportError(
            f"`mistralai` not installed. Cannot import '{name}'. Please install using `pip install mistralai`"
        )


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
