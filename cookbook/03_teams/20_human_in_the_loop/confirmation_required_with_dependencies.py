"""Team HITL: dependencies/session_state survive across continue_run.

Reproduces and demonstrates the fix for
https://github.com/agno-agi/agno/issues/8135

A member tool that requires confirmation also depends on a value the caller
threaded through `dependencies` (e.g. an auth header). Before the fix, when the
team paused at the member tool and the caller resumed via `team.acontinue_run`,
the member tool received `dependencies=None`. After the fix, the team forwards
its `dependencies` (and `metadata` / `knowledge_filters`) when calling
`member.acontinue_run`, so the tool sees the same values it would have during
the initial run.

Run:
    .venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/confirmation_required_with_dependencies.py
"""

import asyncio
from typing import Any, Dict

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.team.team import Team
from agno.tools import tool


@tool(requires_confirmation=True)
def group_del_stock(
    group_id: str, stock_list: list, run_context: RunContext
) -> Dict[str, Any]:
    """Delete stocks from a watch group. Requires an auth token from dependencies.

    Args:
        group_id: ID of the watch group.
        stock_list: List of stock codes to remove.
    """
    token = (run_context.dependencies or {}).get("user_token")
    if not token:
        return {"ok": False, "error": "missing user_token in dependencies"}
    return {
        "ok": True,
        "group_id": group_id,
        "removed": stock_list,
        "auth_header_used": token,
    }


stock_agent = Agent(
    name="Stock Agent",
    role="Manages user stock watch groups. Uses group_del_stock to remove stocks.",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[group_del_stock],
)

stock_team = Team(
    name="Stock Team",
    members=[stock_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Delegate every stock-group request to the Stock Agent.",
    ],
)


async def main() -> None:
    # The caller threads their auth token through `dependencies`.
    dependencies = {"user_token": "Bearer demo-token-123"}

    response = await stock_team.arun(
        "Remove MAOTAI from the 'premium' watch group",
        dependencies=dependencies,
    )

    if not response.is_paused:
        print(f"Result: {response.content}")
        return

    print("Team paused - requires confirmation")
    for req in response.active_requirements:
        if req.needs_confirmation:
            print(f"  Tool: {req.tool_execution.tool_name}")
            print(f"  Args: {req.tool_execution.tool_args}")
            req.confirm()

    # Re-pass dependencies on resume. With the fix, the team forwards them to
    # the member's acontinue_run, so group_del_stock sees the same token.
    final = await stock_team.acontinue_run(response, dependencies=dependencies)
    print(f"Result: {final.content}")


if __name__ == "__main__":
    asyncio.run(main())
