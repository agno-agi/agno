"""
Warp Tools AgentOS
==================

Serve one agent with every WarpTools function enabled. ``run_commands`` opens
a generated temporary Tab Config directly in a new tab, while saved
configurations and Oz agents require confirmation.

Prerequisites: OPENAI_API_KEY, Warp desktop, and an authenticated Oz CLI
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_warp_tools/warp_tools_agent.py
Try: connect at https://os.agno.com and select the Warp Tools Agent
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.warp import WarpTools

TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Create Warp Tools Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="warp-tools-db",
    db_file=str(TMP_DIR / "warp_tools.db"),
)

warp_tools = WarpTools(
    all=True,
    requires_confirmation_tools=[
        "open_launch_config",
        "open_tab_config",
        "run_agent",
    ],
)

warp_agent = Agent(
    id="warp-tools-agent",
    name="Warp Tools Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[warp_tools],
    instructions=[
        "Control Warp only through the requested WarpTools function.",
        "When the user names a function, call that exact function once with the supplied arguments.",
        "Do not ask for confirmation in chat; AgentOS enforces it where configured.",
        "Treat window, tab, and launch actions as fire-and-forget.",
        "Never claim a GUI command completed because Warp terminal output is not returned.",
        "For run_agent, return the output produced by the Oz CLI.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="warp-tools-os",
    name="Warp Tools AgentOS",
    description="AgentOS cookbook exposing every WarpTools function.",
    db=db,
    agents=[warp_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
