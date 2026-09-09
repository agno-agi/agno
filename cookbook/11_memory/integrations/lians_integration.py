"""
Lians Integration
=================

Demonstrates current and point-in-time memory for an Agno agent using Lians.
The example runs Lians locally with SQLite, so no Lians account or API key is
required.

Prerequisites:
    uv pip install "lians-sdk[local]"

Usage:
    python cookbook/11_memory/integrations/lians_integration.py
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.utils.pprint import pprint_run_response

try:
    from lians import LocalLiansClient
except ImportError:
    raise ImportError(
        'lians-sdk is not installed. Install it using `uv pip install "lians-sdk[local]"`.'
    )


AGENT_ID = "agno-lians-demo"


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, including the common trailing-Z form."""
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value)


def build_memory_tools(client: Any, agent_id: str) -> list[Callable[..., str]]:
    """Build Agno-callable tools around a local or hosted Lians client."""

    def remember(content: str, event_time: str, entity: str, field: str) -> str:
        """Store a fact with the time it became true.

        Args:
            content: The fact to remember.
            event_time: ISO 8601 timestamp for when the fact became true.
            entity: Stable subject key, such as a company or customer ID.
            field: Attribute being recorded, such as guidance or preference.
        """
        result = client.add(
            agent_id=agent_id,
            content=content,
            event_time=_parse_datetime(event_time),
            metadata={"entity": entity, "field": field},
            source="agno",
        )
        return json.dumps(result, default=str)

    def recall(query: str, limit: int = 5) -> str:
        """Recall the current, non-superseded facts relevant to a query."""
        result = client.recall(agent_id=agent_id, query=query, k=limit)
        return json.dumps(result, default=str)

    def recall_at(query: str, as_of: str, limit: int = 5) -> str:
        """Recall facts that were valid at a specific point in time.

        Args:
            query: Natural-language description of the facts to retrieve.
            as_of: ISO 8601 timestamp for the historical knowledge boundary.
            limit: Maximum number of memories to return.
        """
        result = client.recall_at(
            agent_id=agent_id,
            query=query,
            as_of=_parse_datetime(as_of),
            k=limit,
        )
        return json.dumps(result, default=str)

    return [remember, recall, recall_at]


def seed_out_of_order_history(client: Any) -> None:
    """Insert one revision chain newest-first to test temporal ordering."""
    revisions = [
        ("NVDA FY2026 guidance is $40B", "2026-07-01T00:00:00Z"),
        ("NVDA FY2026 guidance is $36B", "2026-04-01T00:00:00Z"),
        ("NVDA FY2026 guidance is $32B", "2026-01-01T00:00:00Z"),
    ]
    for content, event_time in revisions:
        client.add(
            agent_id=AGENT_ID,
            content=content,
            event_time=_parse_datetime(event_time),
            metadata={"entity": "NVDA", "field": "FY2026 guidance"},
            source="agno-demo",
        )


if __name__ == "__main__":
    with LocalLiansClient() as memory:
        seed_out_of_order_history(memory)

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            tools=build_memory_tools(memory, AGENT_ID),
            instructions=[
                "Use recall for questions about the current state.",
                "Use recall_at when the user asks what was known at a past time.",
                "Do not replace a historical answer with a newer correction.",
            ],
        )

        current = agent.run("What is the current NVDA FY2026 guidance?")
        pprint_run_response(current)

        historical = agent.run("What was the NVDA FY2026 guidance on January 15, 2026?")
        pprint_run_response(historical)
