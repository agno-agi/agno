"""Regenerate a team's last response — `regenerate=True`.

Team checkpointing is direct parity with the agent surface. Members are
out of scope: they're treated like tools the team delegated to. From the
team's perspective the member's output is just a tool-role message in the
team's conversation.

What `regenerate=True` does on a team:
- Auto-picks the truncation index just after the last user message
- Forks: produces a new ``run_id`` with fresh ``RunMetrics``
- The forked team's ``forked_from_run_id`` / ``regenerated_from`` point at
  the source team
- The source team's ``run_id``, member runs, and metrics stay untouched
- The forked team's ``member_responses`` field references the same member
  data (deep-copied so the fork can't corrupt the source), but no new
  member rows are written to the session

That last bit is the important parity statement: just like agent fork
doesn't clone "tool execution rows," team fork doesn't clone member rows.
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

DB_FILE = f"tmp/team_regenerate_{int(time.time())}.db"


def get_weather(city: str) -> str:
    """Mock weather lookup."""
    data = {"Paris": "Cloudy, 14°C", "Tokyo": "Sunny, 22°C", "Lagos": "Hot, 31°C"}
    return data.get(city, "unknown")


def get_population(city: str) -> str:
    """Mock population lookup."""
    data = {"Paris": "2.1M", "Tokyo": "13.9M", "Lagos": "15.3M"}
    return data.get(city, "unknown")


async def main() -> None:
    weather_agent = Agent(
        name="weather-agent",
        role="Answers weather questions.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[get_weather],
        db=SqliteDb(session_table="team_demo", db_file=DB_FILE),
    )
    population_agent = Agent(
        name="population-agent",
        role="Answers population questions.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[get_population],
        db=SqliteDb(session_table="team_demo", db_file=DB_FILE),
    )

    team = Team(
        name="travel-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[weather_agent, population_agent],
        db=SqliteDb(session_table="team_demo", db_file=DB_FILE),
        instructions=(
            "Delegate weather questions to weather-agent and population "
            "questions to population-agent. Summarize in one sentence."
        ),
    )

    print("=" * 70)
    print("STEP 1: Original team run")
    print("=" * 70)
    original = await team.arun(
        input="What's the weather and population of Paris?",
        session_id="team-sess-1",
    )
    print(f"  run_id: {original.run_id}")
    print(f"  content: {original.content}")
    print()

    print("=" * 70)
    print("STEP 2: regenerate=True with steering")
    print("=" * 70)
    forked = await team.acontinue_run(
        run_id=original.run_id,
        session_id="team-sess-1",
        regenerate=True,
        additional_instructions="This time, only mention weather. Skip population.",
    )
    print(f"  run_id: {forked.run_id}  (new)")
    print(f"  forked_from_run_id: {forked.forked_from_run_id}")
    print(f"  regenerated_from: {forked.regenerated_from}")
    print(f"  content: {forked.content}")
    print()

    print("=" * 70)
    print("STEP 3: Session inspection")
    print("=" * 70)
    session = team.db.get_session(session_id="team-sess-1", session_type="team")
    team_runs = [r for r in (session.runs or []) if hasattr(r, "member_responses")]
    agent_runs = [r for r in (session.runs or []) if not hasattr(r, "member_responses")]
    print(f"  Team rows: {len(team_runs)} (original + fork — both durable)")
    for r in team_runs:
        marker = (
            f" forked_from={r.forked_from_run_id[:8]}…"
            if getattr(r, "forked_from_run_id", None)
            else ""
        )
        print(f"    - {r.run_id} [{r.status}]{marker}")
    print(
        f"  Member rows: {len(agent_runs)} (NOT cloned; stay attached to original team)"
    )
    for r in agent_runs:
        parent = (r.parent_run_id[:8] + "…") if r.parent_run_id else "(no parent)"
        print(f"    - {r.run_id} [{r.status}] parent={parent}")


if __name__ == "__main__":
    asyncio.run(main())
