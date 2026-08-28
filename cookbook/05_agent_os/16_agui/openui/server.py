"""
Render an Agno Agent with OpenUI
================================

Serve OpenUI Lang from an Agno Agent over AG-UI. The companion React client
parses the stream into charts, follow-up actions, and validated forms.

Prerequisites: OPENAI_API_KEY and a generated OpenUI system prompt
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/openui/server.py
Try: Open http://localhost:5173 after starting the companion frontend
"""

from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool

EXAMPLE_ROOT = Path(__file__).resolve().parent
OPENUI_PROMPT_PATH = (
    EXAMPLE_ROOT / "frontend" / "src" / "generated" / "system-prompt.txt"
)

if not OPENUI_PROMPT_PATH.is_file():
    raise RuntimeError(
        "OpenUI system prompt is missing. Run `npm install` and "
        "`npm run generate:prompt` in "
        "cookbook/05_agent_os/16_agui/openui/frontend before starting the server."
    )

openui_system_prompt = OPENUI_PROMPT_PATH.read_text(encoding="utf-8")


@tool
def get_quarterly_revenue() -> dict:
    """Return the company's quarterly revenue in thousands of US dollars."""
    return {
        "currency": "USD",
        "unit": "thousands",
        "quarters": [
            {"quarter": "Q1", "revenue": 120},
            {"quarter": "Q2", "revenue": 180},
            {"quarter": "Q3", "revenue": 150},
            {"quarter": "Q4", "revenue": 240},
        ],
    }


# ---------------------------------------------------------------------------
# Create OpenUI AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-openui-db",
    db_file="tmp/agui_openui.db",
)

assistant = Agent(
    id="agui-openui-assistant",
    name="OpenUI Assistant",
    model=OpenAIResponses(id=getenv("OPENAI_MODEL", "gpt-5.5")),
    db=db,
    tools=[get_quarterly_revenue],
    instructions=[
        "Use get_quarterly_revenue when the user asks for the company's stored revenue data.",
        (
            "Treat the OpenUI instructions below as the required response format for every turn. "
            "Return only OpenUI Lang, without Markdown fences or syntax explanations. When "
            "acknowledging a form submission, mention the project name and at least one other "
            "submitted value in visible OpenUI content."
        ),
        openui_system_prompt,
    ],
    add_history_to_context=True,
    num_history_runs=10,
)

agent_os = AgentOS(
    id="agui-openui-os",
    description="An Agno AgentOS serving OpenUI Lang over AG-UI.",
    agents=[assistant],
    interfaces=[AGUI(agent=assistant)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run OpenUI AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
