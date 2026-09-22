"""Deterministic approval flow for a side-effecting tool.

This example uses a local mock model, so it runs without provider credentials.
The same boundary applies to email, payments, database writes, and other
side-effecting tools: the tool body must not run until the requirement is
confirmed.
"""

import json
from typing import Any, AsyncIterator, Iterator

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools import tool

published_reports: list[str] = []


@tool(requires_confirmation=True)
def publish_report(title: str) -> str:
    """Publish a report after the user approves the side effect."""
    published_reports.append(title)
    return f"Published {title!r}."


class DeterministicModel(Model):
    """Return one tool call, then a final response, without network access."""

    def __init__(self) -> None:
        super().__init__(id="deterministic-approval-demo", provider="local")
        self._calls = 0

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._calls += 1
        if self._calls == 1:
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "publish-1",
                        "type": "function",
                        "function": {
                            "name": "publish_report",
                            "arguments": json.dumps({"title": "Weekly status"}),
                        },
                    }
                ]
            )
        return ModelResponse(content="The approval flow is complete.")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[ModelResponse]:
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def run_case(approve: bool) -> None:
    agent = Agent(
        model=DeterministicModel(),
        tools=[publish_report],
        db=InMemoryDb(),
    )
    response = agent.run("Publish the weekly status report.")
    assert response.is_paused, "The side-effecting tool should require approval."

    for requirement in response.active_requirements:
        if requirement.needs_confirmation:
            if approve:
                requirement.confirm()
            else:
                requirement.reject("The report is not ready to publish.")

    response = agent.continue_run(
        run_id=response.run_id,
        requirements=response.requirements,
    )
    assert not response.is_paused


if __name__ == "__main__":
    published_reports.clear()
    run_case(approve=False)
    assert published_reports == [], "Rejected calls must not execute the tool."

    run_case(approve=True)
    assert published_reports == ["Weekly status"]
    print("Rejected call skipped the side effect; approved call published once.")
