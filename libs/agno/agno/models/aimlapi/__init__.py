from typing import TYPE_CHECKING

from agno.models.aimlapi.constants import AIMLAPI_HEADERS

if TYPE_CHECKING:
    from agno.models.aimlapi.aimlapi import AIMLAPI

__all__ = [
    "AIMLAPI",
    "AIMLAPI_HEADERS",
]


def __getattr__(name: str):
    """Lazy import of the chat model so the attribution constants can be read without `openai` installed."""
    if name == "AIMLAPI":
        from agno.models.aimlapi.aimlapi import AIMLAPI

        return AIMLAPI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
