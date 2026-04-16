"""Run: pip install openai slack-sdk

Requires canvases:read and canvases:write bot scopes in your Slack app.
Set the SLACK_TOKEN environment variable before running.
"""

from agno.agent import Agent
from agno.tools.slack import SlackTools

# Agent with Canvas tools enabled alongside default messaging tools
agent = Agent(
    tools=[SlackTools(enable_canvas=True)],
    markdown=True,
)

if __name__ == "__main__":
    # Create a standalone canvas
    agent.print_response(
        "Create a canvas titled 'Sprint Planning' with a markdown checklist: "
        "## Tasks\n- [ ] Review PRs\n- [ ] Update docs\n- [ ] Deploy to staging",
        stream=True,
    )

    # Create a canvas in a channel
    agent.print_response(
        "Create a canvas in channel #engineering titled 'Onboarding Guide' "
        "with an intro paragraph and three H2 sections: Setup, Tools, Contacts",
        stream=True,
    )
