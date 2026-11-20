"""Rizamo: publish, schedule and measure social posts.

Set RIZAMO_API_KEY (Rizamo web app, Developers) and your agent model's
credentials. The agent saves a draft, which never goes out. publish_post and
reply_to_thread reach the networks at once, so they are off unless enabled.
"""

from agno.agent import Agent

from agno.tools.rizamo import RizamoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Social Media Agent",
    tools=[RizamoTools()],
    instructions="Work with the team's social accounts through Rizamo. Save drafts unless asked to schedule.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("List my Instagram accounts, then save a draft for the first one: 'Doors open at 10.'")
    agent.print_response("How did my accounts do over the last 7 days?")
