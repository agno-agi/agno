"""
Let an Agent Generate its Own Interface over AG-UI
==================================================

Serve an agent that can answer with a rendered surface instead of prose. A
client that renders A2UI asks for generation per run and forwards the catalog of
components it knows how to draw; a render subagent designs a surface from that
catalog, and the client paints it as the design streams in.

Nothing below turns generation on. The agent has one ordinary tool and no A2UI
setup of its own: the AG-UI interface adds the generation tool for any run whose
`forwardedProps` carry `injectA2UITool`, and adds nothing to a run that does
not ask. The instructions below do talk about surfaces, intents, and surface
ids, because knowing when a surface is the better answer is the agent's job.
They say it conditionally, because a run that did not ask has no generation tool
for the model to call.

The one A2UI setting made here is the render subagent's tool choice, which is a
reliability measure rather than wiring: with the render call forced, a subagent
that would have replied in prose cannot spend one of its three attempts doing
so. Nothing is forced by default because the forced shape is provider specific,
and this file has picked its provider.

The model here is OpenAIChat rather than OpenAIResponses because the Responses
API hands over tool arguments in one piece. Generation works either way, but on
Responses the surface appears all at once instead of building as it is written.
Chat completions asks for something back: this model takes function tools there
only with its reasoning turned off, so the model below sets that explicitly.

Prerequisites: OPENAI_API_KEY, .venvs/demo/bin/pip install -U ag-ui-a2ui-toolkit
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/a2ui_generated_ui.py
Try: POST with forwardedProps.injectA2UITool at http://localhost:7777/generated-ui/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat  # deliberate: see the model below
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui.a2ui import OPENAI_RENDER_TOOL_CHOICE
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Generating Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-a2ui-db",
    db_file="tmp/agui_a2ui.db",
)


@tool
def quarterly_sales() -> dict:
    """Return sales figures for the last four quarters."""
    return {
        "currency": "USD",
        "quarters": [
            {"quarter": "Q1", "revenue": 1_240_000, "growth": 0.04},
            {"quarter": "Q2", "revenue": 1_385_000, "growth": 0.12},
            {"quarter": "Q3", "revenue": 1_301_000, "growth": -0.06},
            {"quarter": "Q4", "revenue": 1_702_000, "growth": 0.31},
        ],
    }


sales_agent = Agent(
    id="agui-a2ui-agent",
    name="AG-UI Sales Agent",
    # OpenAIChat rather than the OpenAIResponses the cookbook otherwise calls
    # for, and the exception is the lesson: Responses hands tool arguments over in one
    # piece, which leaves a generated surface appearing whole instead of painting
    # as it is written, and progressive painting is what this file exists to show.
    # The reasoning effort is off because chat completions refuses function tools
    # for this model otherwise, which is the price of painting progressively.
    model=OpenAIChat(id="gpt-5.6-luna", reasoning_effort="none"),
    db=db,
    # The AG-UI interface passes only the latest user message as input, so this
    # is what gives the agent its earlier turns. Finding a surface to edit does
    # not depend on it: that search reads the message history the client
    # forwards with every request.
    add_history_to_context=True,
    tools=[quarterly_sales],
    instructions=[
        "Answer questions about sales using the quarterly_sales tool.",
        (
            "When you have a tool for generating a surface and the user asks to "
            "see, show, compare, or lay something out, generate a surface for "
            "it instead of describing it in prose. Without that tool, answer in "
            "prose."
        ),
        (
            "To change a surface you already rendered, generate again with "
            "intent set to update and the surface id you used, so the client "
            "reconciles what is on screen instead of replacing it."
        ),
        "Keep any prose alongside a surface to a single sentence.",
    ],
)

agent_os = AgentOS(
    id="agui-a2ui-os",
    description="AgentOS whose agent renders its own interface over AG-UI.",
    agents=[sales_agent],
    # Generation itself needs no configuration here: the client asks per run.
    # The tool choice is the OpenAI forced-function shape, which the model above
    # accepts and Gemini would reject, so it is set per file rather than as a
    # default. Also available: a2ui={"inject_a2ui_tool": True} to generate for
    # clients that do not ask, or a2ui={"default_catalog_id": ...} to pin the
    # catalog yourself.
    interfaces=[
        AGUI(
            agent=sales_agent,
            prefix="/generated-ui",
            a2ui={"tool_choice": OPENAI_RENDER_TOOL_CHOICE},
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Generated-UI Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
