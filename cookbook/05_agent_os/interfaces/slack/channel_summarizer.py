"""
Channel Summarizer
==================

Demonstrates channel summarizer.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/summarizer.db")

summarizer = Agent(
    name="Channel Summarizer",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    tools=[
        SlackTools(
            enable_get_thread=True,
            enable_search_messages=True,
            enable_list_users=True,
        )
    ],
    instructions=[
        "You summarize Slack channel activity.",
        "When asked about a channel:",
        "1. Get recent message history",
        "2. Identify active threads and expand them",
        "3. Group messages by topic/theme",
        "4. Highlight decisions, action items, and blockers",
        "Format summaries with clear sections:",
        "- Key Discussions",
        "- Decisions Made",
        "- Action Items",
        "- Questions/Blockers",
        "Use bullet points and keep summaries concise.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[summarizer],
    interfaces=[
        Slack(
            agent=summarizer,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="channel_summarizer:app", reload=True)
