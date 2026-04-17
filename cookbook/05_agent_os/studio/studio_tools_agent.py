"""Agent with StudioTool -- let the agent compose new agents, teams, and workflows.

The StudioTool uses the AgentOS Registry (tools, models, dbs) and the core
component APIs (Agent, Team, Workflow, Step) to dynamically build new
components described by the user in natural language.

Ask the studio agent things like:
    - "What models and tools do we have available?"
    - "Create an agent named 'news' using claude-sonnet-4-5 with DuckDuckGoTools
       that summarizes news headlines in 2-3 sentences."
    - "Create a team called 'research' with the news agent and the Greeter agent."
    - "Create a workflow called 'daily-briefing' that runs the news agent then the
       Reporter agent."
    - "Run the news agent with message 'Top AI story today?'"

Usage:
    # Start the AgentOS server
    .venvs/demo/bin/python cookbook/05_agent_os/studio/studio_tools_agent.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.studio import StudioTool

db = SqliteDb(id="studio-demo2-db", db_file="tmp/studio_demo2.db")

registry = Registry(
    name="Studio Registry",
    tools=[DuckDuckGoTools(), HackerNewsTools(), CalculatorTools()],
    models=[
        OpenAIChat(id="gpt-4o-mini"),
        OpenAIChat(id="gpt-5.4"),
        Claude(id="claude-sonnet-4-5"),
    ],
    dbs=[db],
)

greeter = Agent(
    id="greeter",
    name="Greeter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["You are a friendly greeter."],
    db=db,
)

reporter = Agent(
    id="reporter",
    name="Reporter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["You summarize news headlines in 2-3 sentences."],
    db=db,
)




studio_agent = Agent(
    id="studio-agent",
    name="Studio Agent",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        StudioTool(
            registry=registry,
            db=db,
            agents_list=[ greeter, reporter],
            default_model_id="gpt-4o-mini",
        ),
    ],
    instructions=[
        "You are an AgentOS studio. You help users compose new agents, teams, and workflows.",
        "Always start by listing the available models, tools, and existing agents so the user knows what primitives are on hand.",
        "Before calling create_agent, restate the exact tool names you plan to pass and confirm they match what the user requested. If the user named a tool (e.g. 'calculator'), you MUST include that exact name in tool_names.",
        "After creating a component, confirm what was created (including the full tool_names list) and how to invoke it.",
    ],
    db=db,
    markdown=True,
)


agent_os = AgentOS(
    id="studio-agent-os",
    agents=[greeter, reporter, studio_agent],
    registry=registry,
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="studio_tools_agent:app", port=7777, reload=True)
