"""
Validate Factory Input
======================

Attach a Pydantic schema to an AgentFactory, send typed factory_input through
the run API, and observe invalid input fail with HTTP 400 before construction.

Prerequisites: none beyond OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_factories/02_with_input_schema.py
Try: In another terminal, rerun this file with --demo
"""

import json
import os
import sys
from typing import Literal, cast

import httpx
from agno.agent import Agent, AgentFactory
from agno.db.sqlite import SqliteDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create and Register a Typed Factory
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
db = SqliteDb(
    id="input-schema-factory-db",
    db_file="tmp/21_factories_input_schema.db",
)


class ResearchInput(BaseModel):
    """Untrusted, client-controlled configuration for one produced Agent."""

    persona: Literal["analyst", "advisor", "skeptic"] = "analyst"
    depth: int = Field(default=2, ge=1, le=5)


def build_research_agent(ctx: RequestContext) -> Agent:
    """Build an Agent from already validated factory input."""
    config = cast(ResearchInput, ctx.input)
    return Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        instructions=(
            f"Act as a {config.persona}. "
            f"Give exactly {config.depth} numbered points and no preamble."
        ),
    )


research_factory = AgentFactory(
    id="research-assistant",
    name="Configurable Research Assistant",
    description="Validates persona and depth before constructing an Agent.",
    db=db,
    factory=build_research_agent,
    input_schema=ResearchInput,
)

agent_os = AgentOS(
    id="input-schema-factory-os",
    description="AgentOS validating factory_input with Pydantic.",
    agents=[research_factory],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Run valid input, then prove invalid input returns HTTP 400."""
    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        health = client.get("/health")
        health.raise_for_status()

        agents_response = client.get("/agents")
        agents_response.raise_for_status()
        factory = next(
            agent
            for agent in agents_response.json()
            if agent["id"] == research_factory.id
        )
        schema = factory["factory_input_schema"]
        if set(schema["properties"]) != {"persona", "depth"}:
            raise RuntimeError("Factory discovery returned the wrong input schema")

        valid_response = client.post(
            f"/agents/{research_factory.id}/runs",
            data={
                "message": "Explain why API input validation matters.",
                "factory_input": json.dumps({"persona": "skeptic", "depth": 2}),
                "stream": "false",
            },
        )
        valid_response.raise_for_status()
        valid_run = valid_response.json()
        if valid_run["status"] != "COMPLETED":
            raise RuntimeError("Valid factory input did not complete")

        invalid_response = client.post(
            f"/agents/{research_factory.id}/runs",
            data={
                "message": "This request must not reach a model.",
                "factory_input": json.dumps({"persona": "skeptic", "depth": 99}),
                "stream": "false",
            },
        )
        if invalid_response.status_code != 400:
            raise RuntimeError(
                f"Invalid factory input returned {invalid_response.status_code}"
            )
        detail = invalid_response.json()["detail"]
        if "factory_input validation failed" not in detail:
            raise RuntimeError("HTTP 400 did not explain factory validation")

    print(f"Health: {health.json()['status']}")
    print(f"Schema fields: {sorted(schema['properties'])}")
    print(f"Valid run: {valid_run['run_id']} -> {valid_run['status']}")
    print(f"Invalid input: {invalid_response.status_code}")
    print(f"Validation detail: {detail}")


# ---------------------------------------------------------------------------
# Run Factory AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
