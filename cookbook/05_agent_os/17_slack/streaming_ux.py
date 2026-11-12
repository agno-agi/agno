"""
Configure Slack Streaming UX
=============================

Stream a reply into Slack with loading messages, suggested prompts, plan-mode
task cards for tool calls, and the Stop button.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/streaming_ux.py
Try in Slack: Ask "Write a detailed report on what changed in Python packaging this year, with sources", then press Stop while it streams
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Streaming Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-streaming-db",
    db_file="tmp/slack_streaming.db",
)

researcher = Agent(
    id="slack-streaming-researcher",
    name="Slack Streaming Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    instructions=[
        "Research current questions with web search.",
        "Use more than one source when the answer benefits from comparison.",
        "When asked for a detailed report, write one section per topic with source links.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-streaming-os",
    description="AgentOS demonstrating Slack streaming presentation controls.",
    agents=[researcher],
    interfaces=[
        Slack(
            agent=researcher,
            streaming=True,
            task_display_mode="plan",
            loading_text="Researching...",
            loading_messages=[
                "Searching current sources...",
                "Comparing the evidence...",
                "Preparing a concise answer...",
            ],
            suggested_prompts=[
                {
                    "title": "Technology brief",
                    "message": "Summarize today's most important AI infrastructure news.",
                },
                {
                    "title": "Detailed report",
                    "message": "Write a detailed report on what changed in Python packaging this year, with sources.",
                },
            ],
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Streaming Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
