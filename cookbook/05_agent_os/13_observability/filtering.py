"""
Filter Traces Through AgentOS
=============================

Build a composable FilterExpr, apply it directly to the tracing database, and
send the same expression to POST /traces/search. GET /traces/filter-schema
provides the fields and operators a client can expose.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/filtering.py
Try: Change the agent IDs in the OR expression and compare both result counts
"""

import asyncio
import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.filters import AND, EQ, OR
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Filterable Traces
# ---------------------------------------------------------------------------

DB_ID = "trace-filtering-db"
NEWS_AGENT_ID = "filter-news-agent"
RELEASE_AGENT_ID = "filter-release-agent"

db = SqliteDb(
    id=DB_ID,
    db_file="tmp/observability_filtering.db",
)

news_agent = Agent(
    id=NEWS_AGENT_ID,
    name="News Summary Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Reply in one short sentence.",
)

release_agent = Agent(
    id=RELEASE_AGENT_ID,
    name="Release Summary Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="trace-filtering-os",
    description="Search traces with the FilterExpr DSL.",
    db=db,
    agents=[news_agent, release_agent],
    tracing=True,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Filtered Trace Search
# ---------------------------------------------------------------------------


async def run_filtering_demo() -> None:
    """Generate traces and query them through both Python and AgentOS."""
    await news_agent.arun(
        "Summarize this headline: AgentOS exposes trace search.",
        session_id="filter-news-session",
        user_id="observability-user",
    )
    await release_agent.arun(
        "Summarize this release note: trace filters are composable.",
        session_id="filter-release-session",
        user_id="observability-user",
    )

    filter_expr = AND(
        EQ("status", "OK"),
        OR(
            EQ("agent_id", NEWS_AGENT_ID),
            EQ("agent_id", RELEASE_AGENT_ID),
        ),
    )
    filter_dict = filter_expr.to_dict()

    python_traces, python_count = db.get_traces(filter_expr=filter_dict)
    if python_count < 2:
        raise RuntimeError("The Python FilterExpr query did not find both traces")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://agent-os",
    ) as client:
        schema_response = await client.get("/traces/filter-schema")
        schema_response.raise_for_status()
        schema = schema_response.json()

        schema_fields = {field["key"] for field in schema["fields"]}
        if not {"status", "agent_id"}.issubset(schema_fields):
            raise RuntimeError("The trace filter schema omitted required fields")
        if schema["logical_operators"] != ["AND", "OR"]:
            raise RuntimeError("Unexpected logical operators in filter schema")

        search_response = await client.post(
            "/traces/search",
            params={"db_id": DB_ID},
            json={
                "filter": filter_dict,
                "group_by": "run",
                "page": 1,
                "limit": 20,
            },
        )
        search_response.raise_for_status()
        search_page = search_response.json()

    returned_agent_ids = {
        trace["agent_id"] for trace in search_page["data"] if trace["agent_id"]
    }
    expected_agent_ids = {NEWS_AGENT_ID, RELEASE_AGENT_ID}
    if not expected_agent_ids.issubset(returned_agent_ids):
        raise RuntimeError("POST /traces/search omitted an expected agent")

    print("FilterExpr:")
    print(json.dumps(filter_dict, indent=2))
    print(f"Python filter count: {python_count}")
    print(f"API filter fields: {len(schema['fields'])}")
    print(f"API search count: {search_page['meta']['total_count']}")
    for trace in python_traces:
        print(f"- {trace.agent_id}: {trace.name} [{trace.status}]")


if __name__ == "__main__":
    asyncio.run(run_filtering_demo())
