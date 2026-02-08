"""
File Analyst
============

Demonstrates file analyst.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/file_analyst.db")

file_analyst = Agent(
    name="File Analyst",
    model=Claude(id="claude-sonnet-4-20250514"),
    db=agent_db,
    tools=[
        SlackTools(
            enable_download_file=True,
            enable_get_channel_history=True,
            enable_upload_file=True,
            output_directory="/tmp/slack_analysis",
        )
    ],
    instructions=[
        "You are a file analysis assistant.",
        "When users share files or mention file IDs (F12345...), download and analyze them.",
        "For CSV/data files: identify patterns, outliers, and key statistics.",
        "For code files: explain what the code does, suggest improvements.",
        "For text/docs: summarize key points.",
        "You can upload analysis results back to Slack as new files.",
        "Always explain your analysis in plain language.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

agent_os = AgentOS(
    agents=[file_analyst],
    interfaces=[
        Slack(
            agent=file_analyst,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="file_analyst:app", reload=True)
