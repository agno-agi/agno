"""
Async generator tools with Pydantic BaseModel arguments
=======================================================

Demonstrates that async generator tools (`async def` + `yield`) correctly
receive Pydantic BaseModel instances when the LLM passes a JSON object for a
model-typed parameter. Previously (pre-fix for #8711), the parameter arrived
as a raw dict on the async path only, producing
`AttributeError: 'dict' object has no attribute '...'` on the first attribute
access. Sync generator tools already worked.

This cookbook shows three tools on the same `Toolkit`:

  1. `sync_search`  - `def` + `yield` (sync generator)
  2. `async_search` - `async def` + `yield` (async generator, the fixed path)
  3. `async_search_no_yield` - `async def` returning a value (coroutine)

All three declare a Pydantic model as their `params` argument. The agent is
prompted to invoke each; every tool observes `params` as a real `SearchParams`
instance and can access `.query`, `.time_range`, and `.num_results`
attribute-style. Custom events yielded from the generator tools stream out.
"""

import asyncio
from dataclasses import dataclass
from typing import Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import CustomEvent
from agno.tools import Toolkit
from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    """Parameters for the search tools. Deserialization of this model from a
    JSON object supplied by the LLM is what #8711 was about."""

    query: str
    time_range: Literal["OneDay", "OneWeek", "OneMonth", "OneYear", "NoLimit"] = (
        "NoLimit"
    )
    num_results: int = Field(default=10, ge=1, le=50)


@dataclass
class SearchProgressEvent(CustomEvent):
    """CustomEvent emitted by the streaming tools as they make progress."""

    tool_name: Optional[str] = None
    query: Optional[str] = None
    stage: Optional[str] = None


class SearchToolkit(Toolkit):
    """Toolkit demonstrating sync-gen, async-gen, and async-coroutine tools
    that all take a Pydantic BaseModel as an argument."""

    def __init__(self):
        super().__init__(
            name="search_toolkit",
            tools=[self.sync_search, self.async_search, self.async_search_no_yield],
        )

    def sync_search(self, params: SearchParams):
        """Sync generator: yields progress events, then a final result payload.

        Args:
            params: Search parameters (query, time range, num results).
        """
        # Attribute access proves `params` is a SearchParams, not a dict.
        yield SearchProgressEvent(
            tool_name="sync_search", query=params.query, stage="starting"
        )
        yield SearchProgressEvent(
            tool_name="sync_search", query=params.query, stage="completed"
        )
        yield {
            "tool": "sync_search",
            "query": params.query,
            "time_range": params.time_range,
            "num_results": params.num_results,
            "results": [f"sync-result-{i}" for i in range(params.num_results)],
        }

    async def async_search(self, params: SearchParams):
        """Async generator: previously broken by #8711 - `params` used to
        arrive as a raw dict on this path. After the fix, it is a real
        SearchParams instance, matching the sync generator path.

        Args:
            params: Search parameters (query, time range, num results).
        """
        yield SearchProgressEvent(
            tool_name="async_search", query=params.query, stage="starting"
        )
        # A real await between yields, to make sure this is exercised as a
        # true async generator rather than a sync path in disguise.
        await asyncio.sleep(0)
        yield SearchProgressEvent(
            tool_name="async_search", query=params.query, stage="completed"
        )
        yield {
            "tool": "async_search",
            "query": params.query,
            "time_range": params.time_range,
            "num_results": params.num_results,
            "results": [f"async-result-{i}" for i in range(params.num_results)],
        }

    async def async_search_no_yield(self, params: SearchParams) -> dict:
        """Async coroutine (no yield) with a Pydantic argument. This path
        already worked pre-fix; included as a control.

        Args:
            params: Search parameters (query, time range, num results).
        """
        await asyncio.sleep(0)
        return {
            "tool": "async_search_no_yield",
            "query": params.query,
            "time_range": params.time_range,
            "num_results": params.num_results,
        }


agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[SearchToolkit()],
    instructions=[
        "You have three search tools: sync_search, async_search, and async_search_no_yield.",
        "When the user asks you to run the demonstration, call all three tools in order.",
        "Use query='machine learning', time_range='OneWeek', num_results=3 for every call.",
        "After all three calls complete, summarise which tools returned progress events.",
    ],
    markdown=True,
)


async def main():
    print("Running async generator tool demonstration")
    print("=" * 70)

    seen_progress_events = []

    async for event in agent.arun(
        "Run the demonstration: call all three search tools with the parameters "
        "from your instructions, then summarise the results.",
        stream=True,
    ):
        if isinstance(event, SearchProgressEvent):
            seen_progress_events.append(event)
            print(
                "  progress:",
                event.tool_name,
                "-",
                event.query,
                "-",
                event.stage,
            )

    print()
    print("Progress events observed:", len(seen_progress_events))
    tools_that_streamed = {e.tool_name for e in seen_progress_events}
    print("Tools that streamed progress:", sorted(tools_that_streamed))
    assert "sync_search" in tools_that_streamed, "sync_search should stream progress"
    assert "async_search" in tools_that_streamed, (
        "async_search should stream progress. If missing, #8711 has regressed "
        "and the async generator tool is not being dispatched correctly."
    )
    print("OK: sync_search and async_search both streamed progress events.")


if __name__ == "__main__":
    asyncio.run(main())
