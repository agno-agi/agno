"""Runnable companion to the routing agent guide."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------


class MessageRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["billing", "technical", "order", "other"]
    priority: Literal["normal", "urgent"]
    order_ids: list[str] = Field(
        description="Order IDs explicitly present in the message; empty if absent."
    )
    needs_review: bool = Field(
        description="True when the request is ambiguous or spans multiple categories."
    )
    reason: str = Field(description="A short explanation grounded in the message.")
