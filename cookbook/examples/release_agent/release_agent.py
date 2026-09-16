"""Runnable companion to the release agent guide."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

release_agent = Agent(
    id="release-agent",
    name="Release Agent",
    model=OpenAIResponses(id="gpt-5.6"),
    db=SqliteDb(db_file="release-agent.db"),
    add_history_to_context=True,
    instructions=[
        "Write release notes from the changes the user provides.",
        "Group changes by what they help users do.",
        "Do not invent features, dates, or availability claims.",
    ],
)
