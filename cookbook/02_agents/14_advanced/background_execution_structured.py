"""
Example demonstrating background execution with structured output.

Combines background execution (non-blocking, async) with Pydantic output_schema
so the completed run returns typed, structured data.

Requirements:
- PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
- OPENAI_API_KEY set

Usage:
    .venvs/demo/bin/python cookbook/02_agents/other/background_execution_structured.py
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.run.base import RunStatus
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------


class CityFact(BaseModel):
    city: str = Field(..., description="Name of the city")
    country: str = Field(..., description="Country the city is in")
    population: str = Field(..., description="Approximate population")
    fun_fact: str = Field(..., description="An interesting fact about the city")


class CityFactsResponse(BaseModel):
    cities: List[CityFact] = Field(..., description="List of city facts")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    session_table="bg_structured_sessions",
)


# ---------------------------------------------------------------------------
# Create and Run Background Examples
# ---------------------------------------------------------------------------


async def example_structured_background_run():
    """Background run that returns structured data via output_schema."""
    print("=" * 60)
    print("Background Execution with Structured Output")
    print("=" * 60)

    agent = Agent(
        name="CityFactsAgent",
        model=OpenAIResponses(id="gpt-5-mini"),
        description="An agent that provides structured facts about cities.",
        db=db,
    )

    # Start a background run with structured output
    run_output = await agent.arun(
        "Give me facts about Tokyo, Paris, and New York.",
        output_schema=CityFactsResponse,
        background=True,
    )

    print(f"Run ID: {run_output.run_id}")
    print(f"Status: {run_output.status}")
    assert run_output.status == RunStatus.pending

    # Poll for completion
    print("\nPolling for completion...")
    for i in range(30):
        await asyncio.sleep(1)
        result = await agent.aget_run_output(
            run_id=run_output.run_id,
            session_id=run_output.session_id,
        )
        if result is None:
            print(f"  [{i + 1}s] Not in DB yet")
            continue

        print(f"  [{i + 1}s] Status: {result.status}")

        if result.status == RunStatus.completed:
            print("\nCompleted! Structured output:")

            # Parse the JSON content into our Pydantic model
            try:
                content = result.content
                if isinstance(content, str):
                    import json

                    content = json.loads(content)
                parsed = CityFactsResponse.model_validate(content)
                for city_fact in parsed.cities:
                    print(f"\n  {city_fact.city}, {city_fact.country}")
                    print(f"    Population: {city_fact.population}")
                    print(f"    Fun fact: {city_fact.fun_fact}")
            except Exception:
                print(f"  Raw content: {result.content}")
            break
        elif result.status == RunStatus.error:
            print(f"\nFailed: {result.content}")
            break
    else:
        print("\nTimed out waiting for completion")


async def example_multiple_background_runs():
    """Launch multiple background runs concurrently and collect results."""
    from uuid import uuid4

    print()
    print("=" * 60)
    print("Multiple Concurrent Background Runs")
    print("=" * 60)

    agent = Agent(
        name="QuizAgent",
        model=OpenAIResponses(id="gpt-5-mini"),
        description="An agent that answers trivia questions.",
        db=db,
    )

    questions = [
        "What is the tallest mountain in the world? Answer in one sentence.",
        "What is the deepest ocean trench? Answer in one sentence.",
        "What is the longest river in the world? Answer in one sentence.",
    ]

    # Launch all runs concurrently, each with its own session to avoid conflicts
    runs = []
    for question in questions:
        session_id = str(uuid4())
        run_output = await agent.arun(question, background=True, session_id=session_id)
        runs.append(run_output)
        print(f"Launched: {run_output.run_id} - {question[:50]}...")

    # Poll all runs until all complete
    print("\nWaiting for all runs to complete...")
    results = {}
    for attempt in range(30):
        await asyncio.sleep(1)
        all_done = True
        for run in runs:
            if run.run_id in results:
                continue
            result = await agent.aget_run_output(
                run_id=run.run_id,
                session_id=run.session_id,
            )
            if result and result.status in (RunStatus.completed, RunStatus.error):
                results[run.run_id] = result
            else:
                all_done = False

        if all_done:
            break

    # Print results
    print(f"\nCompleted {len(results)}/{len(runs)} runs:")
    for i, run in enumerate(runs):
        result = results.get(run.run_id)
        if result:
            print(f"\n  Q: {questions[i]}")
            print(f"  A: {result.content}")
            print(f"  Status: {result.status}")
        else:
            print(f"\n  Q: {questions[i]}")
            print("  Status: Still running or not found")


async def main():
    await example_structured_background_run()
    await example_multiple_background_runs()
    print("\nAll examples completed!")


if __name__ == "__main__":
    asyncio.run(main())
