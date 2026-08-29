"""
Serve agents as MCP tools
=========================

Turn the default MCP surface off and serve agents directly as tools. A bare
agent in MCPConfig(tools=[...]) becomes a tool named after its id with the
agent's own description; agent.as_tool(name=..., description=...) publishes
it under a model-facing name and pitch of your choosing instead. An MCP
client sees chief and deep_research -- not run_agent(agent_id=...) -- and
each call runs through the same machinery as the default run tools (fresh
session minting, scope checks, progress). continue_run and cancel_run ride
along automatically so paused (human-in-the-loop) runs stay resumable; set
lifecycle_tools=False to serve exactly the configured tools.

as_tool also carries the presentation a client and a marketplace reviewer
read: title= is the display name, and annotations= are the behaviour hints
(readOnlyHint, destructiveHint, idempotentHint, openWorldHint) merged over
the defaults a published component asserts about itself.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/agents_as_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call chief or deep_research
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig

# ---------------------------------------------------------------------------
# Create the agents to expose
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-agents-as-tools-db",
    db_file="tmp/mcp_agents_as_tools.db",
)

chief = Agent(
    id="chief",
    name="Chief",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    description="Answers executive questions and delegates follow-ups.",
    instructions="Answer briefly and decisively.",
    # Every exposed tool tells the client "pass session_id back to continue the
    # conversation" -- history in context is what makes that promise real.
    add_history_to_context=True,
)

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    description="Digs into a topic and returns sourced findings.",
    instructions="Be thorough and cite what you rely on.",
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Serve the agents as the only MCP tools
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-agents-as-tools-os",
    description="AgentOS serving its agents directly as MCP tools.",
    db=db,
    agents=[chief, researcher],
    mcp=MCPConfig(
        default_tools=False,
        tools=[
            chief,
            researcher.as_tool(
                name="deep_research",
                title="Deep Research",
                description="Thorough, sourced research. Send one clear question.",
                # Hints are published to the client and read by assistant marketplaces
                # during a listing review, which test them against what the tool really
                # does -- so a wrong hint is worse than a missing one. The researcher
                # holds no tools and only appends to its own session, so it refines the
                # default rather than contradicting it: still not read-only (every run
                # writes a session and a run row), but nothing it writes destroys
                # anything, and running it twice is not the same as running it once.
                annotations={"destructiveHint": False, "idempotentHint": False},
            ),
        ],
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Agents-as-Tools AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
