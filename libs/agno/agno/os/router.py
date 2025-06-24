from typing import List
from fastapi import APIRouter

from agno.os.schema import (
    ConfigResponse,
    AgentResponse,
    InterfaceResponse,
    ConnectorResponse,
    TeamResponse,
    WorkflowResponse
)

def get_base_router(
    os: "AgentOS",
) -> APIRouter:
    router = APIRouter(tags=["Built-In"])

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.get("/config", response_model=ConfigResponse)
    async def config() -> ConfigResponse:
        return ConfigResponse(
            os_id=os.os_id,
            name=os.name,
            description=os.description,
            interfaces=[InterfaceResponse(type=interface.type, version=interface.version, route=interface.router_prefix) for interface in os.interfaces],
            connectors=[ConnectorResponse(type=connector.type, id=connector.connector_id, version=connector.version, route=connector.router_prefix) for connector in os.connectors],
        )

    @router.get("/agents", response_model=List[AgentResponse])
    async def get_agents():
        if os.agents is None:
            return []

        return [
            AgentResponse.from_agent(agent)
            for agent in os.agents
        ]

    @router.get("/teams", response_model=List[TeamResponse])
    async def get_teams():
        if os.teams is None:
            return []

        return [
            TeamResponse.from_team(team)
            for team in os.teams
        ]

    @router.get("/workflows", response_model=List[WorkflowResponse])
    async def get_workflows():
        if os.workflows is None:
            return []

        return [
            WorkflowResponse(
                workflow_id=str(workflow.workflow_id),
                name=workflow.name,
                description=workflow.description,
            )
            for workflow in os.workflows
        ]

    return router


