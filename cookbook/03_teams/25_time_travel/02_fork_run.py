"""Fork a team run at a specific message.

``fork=True`` + ``continue_from="last_user"`` creates a new team run by
truncating the source's messages at the last user boundary. Same primitive
that powers regenerate, but with explicit control over where to rewind to.

Use when you want to explore an alternative path from a specific point —
e.g. an eval that varies the prompt after the first round of delegation.
The source team and its member rows stay durable; only the team's own
state (messages, tools, requirements) is forked.
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

DB_FILE = f"tmp/team_fork_{int(time.time())}.db"


def get_weather(city: str) -> str:
    data = {"Paris": "Cloudy, 14°C", "Tokyo": "Sunny, 22°C", "Lagos": "Hot, 31°C"}
    return data.get(city, "unknown")


async def main() -> None:
    weather_agent = Agent(
        name="weather-agent",
        role="Answers weather questions.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[get_weather],
        db=SqliteDb(session_table="team_fork", db_file=DB_FILE),
    )
    team = Team(
        name="weather-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[weather_agent],
        db=SqliteDb(session_table="team_fork", db_file=DB_FILE),
        instructions="Delegate weather questions to weather-agent. Summarize.",
    )

    original = await team.arun(
        input="What's the weather in Paris?",
        session_id="team-sess-fork",
    )
    print(f"Original: {original.run_id}  msgs={len(original.messages or [])}")
    print(f"  content: {original.content}")
    print()

    # Fork from the last user message. The fork drops everything after the
    # user's question and replays from there with a different framing.
    forked = await team.acontinue_run(
        run_id=original.run_id,
        session_id="team-sess-fork",
        fork=True,
        continue_from="last_user",
        input="Actually, give me a one-word answer.",
    )
    print(f"Forked: {forked.run_id}  (new)")
    print(f"  forked_from_run_id: {forked.forked_from_run_id}")
    print(f"  forked_from_message_index: {forked.forked_from_message_index}")
    print(f"  content: {forked.content}")


if __name__ == "__main__":
    asyncio.run(main())
