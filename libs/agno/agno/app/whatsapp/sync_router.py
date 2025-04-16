from typing import Optional, cast

from fastapi import APIRouter, Request

from agno.agent.agent import Agent, RunResponse
from agno.team.team import Team


def get_sync_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.post("/webhook")
    async def webhook(request: Request):
        if agent:
            run_response = cast(
                RunResponse,
                agent.run(...),
            )
        elif team:
            run_response = await team.arun(...)
        return run_response.to_dict()

    return router
