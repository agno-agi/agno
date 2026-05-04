"""Factory with HITL (Human-in-the-Loop) tool confirmation.

Demonstrates a factory agent with a tool that requires human confirmation
before executing. The agent pauses when the tool is called, and the user
must approve or reject it via the /continue endpoint.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/agent/05_hitl_factory.py

Test flow:
    # 1. Start a run that triggers the tool (non-streaming to get full response)
    curl -X POST http://localhost:7777/agents/hitl-agent/runs \
        -F 'message=Get the top 3 hacker news stories' \
        -F 'user_id=user_1' \
        -F 'stream=false'

    # Response will include:
    #   - "status": "PAUSED"
    #   - "tools": [{"tool_call_id": "...", "tool_name": "...", "tool_args": {...},
    #                "requires_confirmation": true, ...}]
    # Note the run_id, session_id, and the full tools array from the response.

    # 2. Confirm: echo the full tools array back with `confirmed: true` set on each entry.
    # (The /continue endpoint replaces stored tool state with what you send, so the
    # payload must include tool_name and tool_args — not just tool_call_id.)
    curl -X POST http://localhost:7777/agents/hitl-agent/runs/RUN_ID/continue \
        -F 'session_id=SESSION_ID' \
        -F 'tools=<TOOLS_ARRAY_FROM_STEP_1_WITH_CONFIRMED_TRUE>' \
        -F 'stream=false'

    # 3. Or reject: same pattern, set `confirmed: false` (and optional confirmation_note).
    curl -X POST http://localhost:7777/agents/hitl-agent/runs/RUN_ID/continue \
        -F 'session_id=SESSION_ID' \
        -F 'tools=<TOOLS_ARRAY_FROM_STEP_1_WITH_CONFIRMED_FALSE>' \
        -F 'stream=false'

    # 4. Check run status
    curl "http://localhost:7777/agents/hitl-agent/runs/RUN_ID?session_id=SESSION_ID"

    # 5. Cancel a run
    curl -X POST http://localhost:7777/agents/hitl-agent/runs/RUN_ID/cancel
"""

import json

import httpx
from agno.agent import Agent, AgentFactory
from agno.db.postgres import PostgresDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="hitl-factory-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Tool that requires human confirmation
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories: Number of stories to retrieve.

    Returns:
        JSON string of story details.
    """
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()
    stories = []
    for story_id in story_ids[:num_stories]:
        story = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        ).json()
        story.pop("text", None)
        stories.append(story)
    return json.dumps(stories)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_hitl_agent(ctx: RequestContext) -> Agent:
    """Build an agent with a HITL tool for the calling tenant."""
    user_id = ctx.user_id or "anonymous"

    return Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        db=db,
        tools=[get_top_hackernews_stories],
        instructions=(
            f"You are a news assistant for {user_id}. "
            "Use the get_top_hackernews_stories tool to fetch stories when asked."
        ),
        markdown=True,
    )


hitl_factory = AgentFactory(
    db=db,
    id="hitl-agent",
    name="HITL Agent",
    description="Factory agent with a tool requiring human confirmation before execution",
    factory=build_hitl_agent,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-factory-demo",
    description="Demo: factory agent with human-in-the-loop tool confirmation",
    agents=[hitl_factory],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="05_hitl_factory:app", port=7777, reload=True)
