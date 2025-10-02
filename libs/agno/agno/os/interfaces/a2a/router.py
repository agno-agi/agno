"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

from typing import Optional

from fastapi import HTTPException, Request
from fastapi.routing import APIRouter
from typing_extensions import List

try:
    from a2a.types import SendMessageSuccessResponse
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a`") from e

from agno.agent import Agent
from agno.os.interfaces.a2a.utils import map_a2a_request_to_run_input, map_run_output_to_a2a_task
from agno.os.router import _get_request_kwargs
from agno.os.utils import get_agent_by_id, get_team_by_id
from agno.team import Team


def attach_routes(
    router: APIRouter, agents: Optional[List[Agent]] = None, teams: Optional[List[Team]] = None
) -> APIRouter:
    if agents is None and teams is None:
        raise ValueError("Agents or Teams are required to setup the A2A interface.")

    @router.post(
        "/a2a/agents/{id}",
        tags=["A2A"],
        operation_id="run_a2a",
        summary="Run Agent via A2A",
        description="Run an Agno Agent using the A2A protocol.",
        response_model_exclude_none=True,
        responses={
            200: {
                "jsonrpc": "2.0",
                "id": "id",
                "result": {
                    "task": {
                        "id": "id",
                        "context_id": "id",
                        "status": "status",
                        "history": [
                            {
                                "message_id": "id",
                                "role": "user",
                                "parts": [
                                    {
                                        "kind": "text",
                                        "text": "This is the user question",
                                    }
                                ],
                            },
                            {
                                "message_id": "id",
                                "role": "agent",
                                "parts": [
                                    {
                                        "kind": "text",
                                        "text": "This is the agent answer",
                                    }
                                ],
                            },
                        ],
                    }
                },
            },
            400: {"description": "A2A run failed"},
            404: {"description": "Agent not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_agent(id: str, request: Request):
        request_body = await request.json()
        kwargs = await _get_request_kwargs(request, a2a_agent)

        agent = get_agent_by_id(id, agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        run_input = await map_a2a_request_to_run_input(request_body)

        response = await agent.arun(
            input=run_input.input_content,
            images=run_input.images,
            videos=run_input.videos,
            audio=run_input.audios,
            files=run_input.files,
            **kwargs,
        )

        a2a_task = map_run_output_to_a2a_task(response)

        # Send A2A-valid JSON-RPC response
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=a2a_task,
        )

    @router.post(
        "/a2a/teams/{id}",
        tags=["A2A"],
        operation_id="run_a2a",
        summary="Run Team via A2A",
        description="Run an Agno Team using the A2A protocol.",
        response_model_exclude_none=True,
        responses={
            200: {
                "jsonrpc": "2.0",
                "id": "id",
                "result": {
                    "task": {
                        "id": "id",
                        "context_id": "id",
                        "status": "status",
                        "history": [
                            {
                                "message_id": "id",
                                "role": "user",
                                "parts": [
                                    {
                                        "kind": "text",
                                        "text": "This is the user question",
                                    }
                                ],
                            },
                            {
                                "message_id": "id",
                                "role": "agent",
                                "parts": [
                                    {
                                        "kind": "text",
                                        "text": "This is the team answer",
                                    }
                                ],
                            },
                        ],
                    }
                },
            },
            400: {"description": "A2A run failed"},
            404: {"description": "Team not found"},
        },
        response_model=SendMessageSuccessResponse,
    )
    async def a2a_team(id: str, request: Request):
        request_body = await request.json()
        kwargs = await _get_request_kwargs(request, a2a_team)

        team = get_team_by_id(id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        run_input = await map_a2a_request_to_run_input(request_body)

        response = await team.arun(
            input=run_input.input_content,
            images=run_input.images,
            videos=run_input.videos,
            audio=run_input.audios,
            files=run_input.files,
            **kwargs,
        )

        # TODO: Team specific? can we carry members content?
        a2a_task = map_run_output_to_a2a_task(response)

        # Send A2A-valid JSON-RPC response
        return SendMessageSuccessResponse(
            id=request_body.get("id", "unknown"),
            result=a2a_task,
        )

    return router
