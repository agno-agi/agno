"""
OSOP Workflow Example — Research Agent (Agno implementation)
=============================================================

This file is the RUNNABLE Agno equivalent of ``research_workflow.osop``.

It shows how an OSOP workflow (a portable YAML description) maps onto Agno
agent patterns:

* every OSOP ``agent`` node  -> an ``agno.agent.Agent``
* every OSOP ``sequential`` edge -> an ordered ``agno.workflow.Step``
* the whole graph            -> an ``agno.workflow.Workflow`` served by ``AgentOS``

Prerequisites
-------------
    export OPENAI_API_KEY=sk-...

Run
---
    python cookbook/05_agent_os/26_osop_workflow/research_workflow.py

Then open the AgentOS UI at http://localhost:7777 and type your research
question — that is the OSOP ``human`` node (user-request).
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Database — persists session history for the workflow
# ---------------------------------------------------------------------------
db = SqliteDb(
    id="osop-research-db",
    db_file="tmp/osop_research.db",
)

# ---------------------------------------------------------------------------
# Agents — one per OSOP `agent` node
# ---------------------------------------------------------------------------
web_search_agent = Agent(
    id="web-search-agent",
    name="Web Search Agent",
    model=OpenAIResponses(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=(
        "You are a web research agent. Given a research topic, search the web "
        "and return the most relevant, up-to-date facts together with their sources."
    ),
    markdown=True,
)

analysis_agent = Agent(
    id="analysis-agent",
    name="Analysis Agent",
    model=OpenAIResponses(id="gpt-4o"),
    instructions=(
        "You are an analysis agent. Given raw search results, extract the key "
        "insights, note agreements and disagreements, and summarize what matters."
    ),
    markdown=True,
)

report_agent = Agent(
    id="report-agent",
    name="Report Generator",
    model=OpenAIResponses(id="gpt-4o"),
    instructions=(
        "You are a report writer. Given the analyzed insights, produce a clear, "
        "structured research report with a heading and a few short sections."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Workflow — OSOP `sequential` edges become ordered Steps
# ---------------------------------------------------------------------------
research_workflow = Workflow(
    id="osop-research-workflow",
    name="Research Agent Workflow",
    description="Web search -> analysis -> report generation.",
    db=db,
    steps=[
        Step(name="Web Search", agent=web_search_agent),
        Step(name="Analysis", agent=analysis_agent),
        Step(name="Generate Report", agent=report_agent),
    ],
)

# ---------------------------------------------------------------------------
# AgentOS — serves the workflow over HTTP (discovery, streaming, UI)
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="osop-research-os",
    description="AgentOS serving the OSOP research workflow.",
    db=db,
    workflows=[research_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    # The `human` node (user-request) is simply the message you type in the UI/API.
    agent_os.serve(app=app)
