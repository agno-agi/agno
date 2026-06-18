"""
Dependencies Merge Demo — PR #8201
===================================

Demonstrates how agent-configured dependencies merge with UI-sent context.

The agent has backend dependencies (api_version, feature_flags) set at creation.
The UI sends frontend context (user_name, current_page) via useAgentContext.
The SDK merges both automatically — UI values win on key conflicts.

Run:
    ngrok http 9003
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/dependencies_merge.py

Test via Dojo (https://dojo.ag-ui.com):
    1. Set endpoint to <ngrok-url>/agui
    2. Ask: "What dependencies do you see?"
    3. Should see BOTH backend deps AND UI context merged together
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

agent = Agent(
    name="deps_merge_demo",
    model=OpenAIResponses(id="gpt-5.4"),
    # Backend dependencies — set at agent creation
    dependencies={
        "api_version": "v2.1",
        "feature_flags": {"dark_mode": True, "beta_features": False},
        "server_region": "us-east-1",
    },
    add_dependencies_to_context=True,
    instructions="""You help users understand what context is available to you.

When asked about dependencies or context, list everything you see in <additional context> tags:
- Backend dependencies (api_version, feature_flags, server_region)
- Frontend context (user_name, current_page, etc. from the UI)

Format your response as a clear list showing the source of each value.""",
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[AGUI(agent=agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    print("Dependencies Merge Demo")
    print("=" * 50)
    print()
    print("Backend dependencies configured:")
    print("  api_version: v2.1")
    print("  feature_flags: {dark_mode: True, beta_features: False}")
    print("  server_region: us-east-1")
    print()
    print("UI will add (via useAgentContext):")
    print("  user_name, current_page, cart_data, etc.")
    print()
    print("The SDK merges both automatically.")
    print()
    agent_os.serve(app="dependencies_merge:app", reload=True, port=9003)
