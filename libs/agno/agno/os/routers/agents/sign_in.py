"""Routes that sign a Codex agent in to a ChatGPT subscription with a device code. Admin only."""

from typing import TYPE_CHECKING, Any, Dict

from fastapi import APIRouter, HTTPException, Request

from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.utils import get_agent_by_id
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.app import AgentOS

# The scope every one of these routes needs. A sign-in bills a person's subscription to the agent.
SIGN_IN_SCOPE = "agent_os:admin"


def _codex_agent(os: "AgentOS", agent_id: str, request: Request) -> Any:
    from agno.agents.codex import CodexAgent

    agent = get_agent_by_id(
        agent_id=agent_id,
        agents=os.agents,
        db=os.db,
        registry=os.registry,
        user_id=get_scoped_user_id(request),
        published_only=False,
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not isinstance(agent, CodexAgent):
        raise HTTPException(status_code=400, detail=f"{agent_id} is not a Codex agent; only a Codex agent signs in")
    return agent


async def _answer(agent_id: str, call: Any) -> Dict[str, Any]:
    try:
        return await call()
    except (ValueError, ImportError) as error:
        # The agent cannot be signed in as it is configured; the message says what to change.
        raise HTTPException(status_code=409, detail=str(error))
    except RuntimeError as error:
        log_error(f"ChatGPT sign-in for {agent_id} failed: {type(error).__name__}")
        raise HTTPException(status_code=502, detail=str(error))


def add_sign_in_routes(router: APIRouter, os: "AgentOS") -> None:
    @router.post(
        "/agents/{agent_id}/sign-in",
        tags=["Agents"],
        operation_id="start_agent_sign_in",
        summary="Start a ChatGPT sign-in for a Codex agent",
        description=(
            "Starts a device-code sign-in and returns `verification_url` and `user_code`. A person opens the "
            "link in their own browser and enters the code. The sign-in itself is never returned. Admin only."
        ),
    )
    async def start_agent_sign_in(agent_id: str, request: Request) -> Dict[str, Any]:
        agent = _codex_agent(os, agent_id, request)
        return await _answer(agent_id, agent.asign_in)

    @router.get(
        "/agents/{agent_id}/sign-in",
        tags=["Agents"],
        operation_id="get_agent_sign_in",
        summary="Read where a Codex agent's ChatGPT sign-in stands",
        description="`status` is `waiting`, `signed_in`, `failed` or `not_signed_in`. Admin only.",
    )
    async def get_agent_sign_in(agent_id: str, request: Request) -> Dict[str, Any]:
        agent = _codex_agent(os, agent_id, request)
        return await _answer(agent_id, agent.asign_in_status)

    @router.delete(
        "/agents/{agent_id}/sign-in",
        tags=["Agents"],
        operation_id="cancel_agent_sign_in",
        summary="Give up a ChatGPT sign-in that is waiting for its code",
        description="A stored sign-in is left as it is. Admin only.",
    )
    async def cancel_agent_sign_in(agent_id: str, request: Request) -> Dict[str, Any]:
        agent = _codex_agent(os, agent_id, request)
        return await _answer(agent_id, agent.acancel_sign_in)
