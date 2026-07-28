"""
Read Trace Trees Through AgentOS
================================

Generate one synchronous and one asynchronous agent run, list their traces
through GET /traces, then fetch GET /traces/{trace_id} and print each nested
span tree.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/read_traces.py
Try: Compare the .run and .arun roots and their nested model spans
"""

import asyncio
from typing import Any

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Trace Readback App
# ---------------------------------------------------------------------------

AGENT_ID = "trace-readback-agent"
DB_ID = "trace-readback-db"

db = SqliteDb(
    id=DB_ID,
    db_file="tmp/observability_read_traces.db",
)

trace_agent = Agent(
    id=AGENT_ID,
    name="Trace Readback Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="trace-readback-os",
    description="Generate and read complete trace trees.",
    db=db,
    agents=[trace_agent],
    tracing=True,
)
app = agent_os.get_app()


def print_span_tree(nodes: list[dict[str, Any]], depth: int = 0) -> None:
    """Print the recursive span tree returned by GET /traces/{trace_id}."""
    for node in nodes:
        print(
            f"{'  ' * depth}- {node['name']} "
            f"[{node['type']}] {node['status']} ({node['duration']})"
        )
        print_span_tree(node.get("spans", []), depth + 1)


# ---------------------------------------------------------------------------
# Run Trace Readback
# ---------------------------------------------------------------------------


async def run_trace_readback() -> None:
    """Run both Agent APIs and read their stored traces through AgentOS."""
    sync_run = trace_agent.run(
        "Reply with a short greeting for the synchronous trace.",
        session_id="trace-readback-sync",
        user_id="observability-user",
    )
    async_run = await trace_agent.arun(
        "Reply with a short greeting for the asynchronous trace.",
        session_id="trace-readback-async",
        user_id="observability-user",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://agent-os",
    ) as client:
        response = await client.get(
            "/traces",
            params={"agent_id": AGENT_ID, "db_id": DB_ID, "limit": 20},
        )
        response.raise_for_status()
        trace_page = response.json()

        traces_by_run = {
            trace["run_id"]: trace for trace in trace_page["data"] if trace["run_id"]
        }
        run_ids = [sync_run.run_id, async_run.run_id]
        missing_run_ids = [run_id for run_id in run_ids if run_id not in traces_by_run]
        if missing_run_ids:
            raise RuntimeError(f"GET /traces omitted run IDs: {missing_run_ids}")

        print(f"GET /traces returned {trace_page['meta']['total_count']} trace(s)")
        for label, run_id in (("sync", sync_run.run_id), ("async", async_run.run_id)):
            trace_id = traces_by_run[run_id]["trace_id"]
            detail_response = await client.get(
                f"/traces/{trace_id}",
                params={"db_id": DB_ID},
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            if not detail["tree"]:
                raise RuntimeError(f"Trace {trace_id} has no span tree")

            print(
                f"\n{label} run {run_id}: trace={trace_id}, "
                f"spans={detail['total_spans']}"
            )
            print_span_tree(detail["tree"])


if __name__ == "__main__":
    asyncio.run(run_trace_readback())
