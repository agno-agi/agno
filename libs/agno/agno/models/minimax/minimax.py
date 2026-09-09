from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse


@dataclass
class MiniMax(OpenAILike):
    """
    A class for interacting with MiniMax models.

    MiniMax provides an OpenAI-compatible API for its large language models.
    For more information, see: https://platform.minimax.io/docs/api-reference/text-openai-api

    Attributes:
        id (str): The model id. Defaults to "MiniMax-M3".
        name (str): The model name. Defaults to "MiniMax".
        provider (str): The provider name. Defaults to "MiniMax".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.minimax.io/v1".
    """

    id: str = "MiniMax-M3"
    name: str = "MiniMax"
    provider: str = "MiniMax"

    api_key: Optional[str] = field(default_factory=lambda: getenv("MINIMAX_API_KEY"))
    base_url: str = "https://api.minimax.io/v1"

    # MiniMax does not support native structured outputs
    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("MINIMAX_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="MINIMAX_API_KEY not set. Please set the MINIMAX_API_KEY environment variable.",
                    model_name=self.name,
                )

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    # MiniMax-M2.x and MiniMax-M3 stream thinking via BOTH the structured
    # ``reasoning_content`` field (auto-handled by
    # ``OpenAIChat._parse_provider_response_delta``) AND inline
    # ``<think>...</think>`` tags in the content stream. The structured field
    # already drives the Thinking panel; the inline tags would otherwise leak
    # into the Response panel. Strip them here, statefully (tags can split
    # across chunks).
    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:  # type: ignore[override]
        state: Dict[str, Any] = {"in_think": False, "pending": ""}
        for model_response in super().invoke_stream(*args, **kwargs):
            _strip_inline_think_tags(model_response, state)
            yield model_response
        tail = _flush_think_filter(state)
        if tail is not None:
            yield tail

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:  # type: ignore[override]
        state: Dict[str, Any] = {"in_think": False, "pending": ""}
        async for model_response in super().ainvoke_stream(*args, **kwargs):
            _strip_inline_think_tags(model_response, state)
            yield model_response
        tail = _flush_think_filter(state)
        if tail is not None:
            yield tail


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _strip_inline_think_tags(model_response: ModelResponse, state: Dict[str, Any]) -> None:
    """Strip ``<think>...</think>`` blocks from a streamed content delta in place."""
    if not model_response.content:
        return
    buf = state["pending"] + model_response.content
    state["pending"] = ""
    out: List[str] = []
    while buf:
        if state["in_think"]:
            idx = buf.find(_THINK_CLOSE)
            if idx == -1:
                keep = _trailing_tag_prefix(buf, _THINK_CLOSE)
                if keep:
                    state["pending"] = buf[-keep:]
                buf = ""
            else:
                buf = buf[idx + len(_THINK_CLOSE) :]
                state["in_think"] = False
        else:
            idx = buf.find(_THINK_OPEN)
            if idx == -1:
                keep = _trailing_tag_prefix(buf, _THINK_OPEN)
                if keep:
                    out.append(buf[:-keep])
                    state["pending"] = buf[-keep:]
                else:
                    out.append(buf)
                buf = ""
            else:
                out.append(buf[:idx])
                buf = buf[idx + len(_THINK_OPEN) :]
                state["in_think"] = True
    cleaned = "".join(out)
    model_response.content = cleaned if cleaned else None


def _flush_think_filter(state: Dict[str, Any]) -> Optional[ModelResponse]:
    """Emit any held-back partial-tag text at end of stream as plain content."""
    pending = state["pending"]
    state["pending"] = ""
    if not pending or state["in_think"]:
        return None
    tail = ModelResponse()
    tail.content = pending
    return tail


def _trailing_tag_prefix(s: str, tag: str) -> int:
    """Length of the longest non-empty proper prefix of ``tag`` that ``s`` ends with."""
    max_n = min(len(s), len(tag) - 1)
    for n in range(max_n, 0, -1):
        if s.endswith(tag[:n]):
            return n
    return 0
