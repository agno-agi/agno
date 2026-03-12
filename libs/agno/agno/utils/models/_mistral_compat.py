"""
Compatibility layer for mistralai v1 (<2.0.0) and v2 (>=2.0.0).

Centralizes version detection and conditional imports so consumer modules
can simply do:
    from agno.utils.models._mistral_compat import MistralClient, AssistantMessage, ...
"""

import importlib.metadata

from agno.utils.log import log_debug, log_error

try:
    _mistral_version = int(importlib.metadata.version("mistralai").split(".")[0])
except importlib.metadata.PackageNotFoundError:
    log_error("`mistralai` not installed. Please install using `pip install mistralai`")
    raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")


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
