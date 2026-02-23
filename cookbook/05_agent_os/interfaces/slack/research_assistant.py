"""
Research Assistant
==================

Demonstrates research assistant.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/research_assistant.db")

research_assistant = Agent(
    name="Research Assistant",
    model=Claude(id="claude-sonnet-4-5"),
    debug_mode=True,debug_level=2,
    db=agent_db,
    tools=[
        SlackTools(
            enable_search_messages=True,
            enable_get_thread=True,
            enable_list_users=True,
            enable_get_user_info=True,
        ),
        WebSearchTools(),
    ],
    instructions=[
        "You are a research assistant that helps find information.",
        "You can search Slack messages using: from:@user, in:#channel, has:link, before:/after:date",
        "You can also search the web for current information.",
        "When asked to research something:",
        "1. Search Slack for internal discussions",
        "2. Search the web for external context",
        "3. Synthesize findings into a clear summary",
        "Identify relevant experts by looking at who contributed to discussions.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[research_assistant],
    interfaces=[
        Slack(
            agent=research_assistant,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="research_assistant:app", reload=True)
