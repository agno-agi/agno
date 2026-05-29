"""
Channel Summarizer
==================

An agent that reads channel history and produces structured summaries.
Supports follow-up questions in the same thread via session history.

Key concepts:
  - ``SlackTools`` with ``enable_get_thread`` and ``enable_search_messages``
    lets the agent read Slack data as tool calls.
  - ``add_history_to_context=True`` + ``db`` enables follow-up questions
    within the same Slack thread — the agent remembers previous exchanges.
  - ``num_history_runs=5`` includes the last 5 exchanges for context.

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history,
             channels:history, channels:read, search:read, users:read
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
        "Your context includes the Slack channel_id and thread_ts you are responding in.",
        "When asked to summarize 'this channel', use the channel_id from your context.",
        "When asked about a channel:",
        "1. Use get_channel_history with the channel_id to fetch recent messages",
        "2. Look for messages with thread_ts and reply_count > 0 — these have threaded replies",
        "3. Use get_thread with the channel_id and thread_ts to expand important threads",
        "4. Group messages by topic/theme",
        "5. Highlight decisions, action items, and blockers",
        "Format summaries with clear sections:",
        "- Key Discussions (include expanded thread context)",
        "- Decisions Made",
        "- Action Items",
        "- Questions/Blockers",
        "Use bullet points and keep summaries concise.",
    ],
    # Session history — enables follow-up questions in the same Slack thread
    add_history_to_context=True,
    num_history_runs=5,
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
