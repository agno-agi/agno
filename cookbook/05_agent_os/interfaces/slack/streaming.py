"""
Streaming
=========

Demonstrates streaming responses in Slack using the chat_startStream/appendStream/stopStream API.
Tokens are delivered in real-time as the agent generates them, and tool
calls are shown as progress updates in Slack's plan display.

Requirements:
  - Your Slack app must have the ``assistant:write`` scope enabled.
  - Event Subscriptions must be configured for ``app_mention``, ``message.im``,
    and ``assistant_thread_started`` (for suggested prompts).
  - The ``assistant_thread_started`` event enables suggested prompts when a
    user opens a new thread with the bot.
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/streaming.db")

streaming_agent = Agent(
    name="Streaming Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS — streaming enabled
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[streaming_agent],
    interfaces=[
        Slack(
            agent=streaming_agent,
            streaming=True,
            reply_to_mentions_only=True,
            initial_buffer_size=1,
            loading_messages=[
                "Thinking...",
                "Searching the web...",
                "Working on it...",
            ],
            suggested_prompts=[
                {"title": "Help", "message": "What can you help me with?"},
                {"title": "Search", "message": "Search the web for the latest news"},
            ],
        )
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="streaming:app", reload=True)
